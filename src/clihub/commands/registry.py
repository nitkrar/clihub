"""`ch registry add|remove|edit|show|validate|export|import` — editing `registry.toml`.

Named for what they change rather than for what the entries are: `registry add llm`
creates a namespace's `.command`, not only a tool, so `tools` was too narrow a word
for the group. These do what you would otherwise do by hand in that file.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import sys

from pathlib import Path

from ..config import load as load_settings
from .. import describe
from .. import registry as store
from ..errors import BuiltinError, RegistryEntryError, UnknownCommandError, UsageError
from ..paths import Paths
from ..render import render_rows, render_text

# What `ch --help` prints for this command. Separate from __doc__, which is
# about the module: different readers, different words.
SUMMARY = "edit the registry"
ARGS = "<command>"

_USAGE = (
    'usage: ch registry add <name> [--describe "..."] [--force] -- <path> [fixed-args...]\n'
    "  <name> is <tool> or <namespace>.<tool>"
)


def subcommands() -> tuple:
    """The verbs this group accepts, from the parser that accepts them.

    Read off the subparsers action rather than kept as a second list, so
    `ch --help` cannot advertise a verb the parser would reject.
    """
    return tuple(_build_parser().get_default("_subcommands").choices)


def run(argv: list[str], paths: Paths) -> int:
    parser = _build_parser()
    # A group named with nothing after it is asking what is in it, not making a
    # mistake, so it prints its own help and succeeds.
    if len(argv) < 3 or argv[2] in ("-h", "--help"):
        parser.print_help()
        return 0
    args = parser.parse_args(argv[2:])
    if args.action == "add":
        return _run_add(args, paths)
    if args.action == "validate":
        return _run_validate(paths)
    if args.action == "show":
        return _run_show(args, paths)
    if args.action == "edit":
        return _run_edit(args, paths)
    if args.action == "export":
        return _run_export(args, paths)
    if args.action == "import":
        return _run_import(args, paths)
    return _run_remove(args, paths)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ch registry", description=SUMMARY)
    subparsers = parser.add_subparsers(dest="action", metavar="<command>")
    parser.set_defaults(_subcommands=subparsers)
    add_parser = subparsers.add_parser("add", prog="ch registry add", help="register a tool")
    add_parser.add_argument("name", help="<tool> or <namespace>.<tool>")
    add_parser.add_argument("--describe", metavar="TEXT", help="what this command is for")
    add_parser.add_argument("--force", action="store_true", help="replace an existing entry entirely")
    add_parser.add_argument("prefix", nargs="*", metavar="-- <path> [fixed-args...]")
    remove_parser = subparsers.add_parser("remove", prog="ch registry remove", help="drop an entry")
    remove_parser.add_argument("name")
    subparsers.add_parser("validate", prog="ch registry validate",
                          help="check the registry's integrity")
    show_parser = subparsers.add_parser("show", prog="ch registry show",
                                        help="print a command's registry entry")
    show_parser.add_argument("name", help="a command, or a group to show all of it")
    edit_parser = subparsers.add_parser("edit", prog="ch registry edit",
                                        help="change one thing about an entry")
    edit_parser.add_argument("name")
    edit_parser.add_argument("--name", dest="rename", metavar="NEW",
                             help="rename in place; never across groups")
    edit_parser.add_argument("--describe", metavar="TEXT",
                             help='new description; pass "" to clear it')
    edit_parser.add_argument("prefix", nargs="*", metavar="-- <path> [fixed-args...]")
    export_parser = subparsers.add_parser("export", prog="ch registry export",
                                          help="copy registry.toml somewhere")
    export_parser.add_argument("path", nargs="?",
                               help="a directory, or a file to write; default here")
    export_parser.add_argument("--force", action="store_true",
                               help="overwrite an existing file")
    import_parser = subparsers.add_parser("import", prog="ch registry import",
                                          help="merge another registry into this one")
    import_parser.add_argument("path", help="a registry.toml, or a directory holding one")
    import_parser.add_argument("--force", action="store_true",
                               help="let the imported file win where the two disagree")
    return parser


def _run_add(args, paths: Paths) -> int:
    """Register a command.

    Everything after `--` is the command, stored verbatim. argparse handles the
    separator natively, including a command carrying flags of its own
    (`-- /bin/echo --json`), so options may appear in any order.
    """
    name = args.name
    store.ensure_addable(name)
    if not args.prefix:
        raise UsageError(_USAGE)
    target = _validated_target(name, args.prefix)
    _warn_if_environment_specific(name, target)
    full_prefix = [target, *args.prefix[1:]]

    store.add(paths, name, full_prefix, description=args.describe or None,
              force=args.force)
    if args.describe:
        _warn_if_copied_from_help(name, args.describe, shlex.join(full_prefix), paths)
    else:
        sys.stderr.write(
            f"{name}: no description. Write one with "
            f"'ch registry edit {name} --describe \"...\"'\n"
        )
    return 0


def _warn_if_copied_from_help(name: str, description: str, script: str, paths) -> None:
    """Hint when a description looks lifted from the tool's own help.

    Descriptions that enumerate subcommands measurably mislead small models: they read
    the verbs as tool names. Advisory only — the description is stored either way.
    """
    settings = load_settings(paths.config_file)
    if not settings.overlap_check:
        # Checked before probing: off means no help spawn at all, not a silent warning.
        return
    help_text = describe.tool_help_text(script, settings)
    if not help_text:
        return
    if describe.description_overlap(description, help_text) < settings.overlap_warn:
        return
    sys.stderr.write(settings.overlap_warning.format(tool=name) + "\n")

def _run_export(args, paths: Paths) -> int:
    """Copy registry.toml out, byte for byte.

    Copied rather than regenerated through the parser, which does not preserve
    comments: an exported registry you had hand-annotated would come back stripped
    of the annotations, and an export that quietly differs from its source is worse
    than no export.

    A directory means "put registry.toml in here"; anything else is the filename to
    write; nothing at all means the current directory. An existing file is never
    replaced without --force, the same rule as `add` and `init`.
    """
    source = paths.registry_file
    if not source.is_file():
        raise BuiltinError(f"nothing to export: {source} does not exist")
    content = source.read_bytes()

    destination = Path(args.path).expanduser() if args.path else Path.cwd()
    if destination.is_dir():
        destination = destination / source.name
    if not destination.parent.is_dir():
        raise BuiltinError(f"no such directory: {destination.parent}")
    if destination.exists() and not args.force:
        raise BuiltinError(f"{destination} already exists (use --force to replace)")
    destination.write_bytes(content)
    print(f"exported {source} -> {destination}")
    return 0


def _run_import(args, paths: Paths) -> int:
    """Merge another registry.toml into this one. Three problems, three answers:

        will not parse       refused whole; nothing is written
        wrong in itself      left behind and named; the rest of the file comes in
        missing *here*       imported and reported, since it may be right elsewhere

    A key that merely disagrees is a decision, not a fault: the keys that agree go
    in and the ones that do not are listed for --force.
    """
    source = Path(args.path).expanduser().resolve()
    if source.is_dir():
        # The mirror of export, so `ch rg export ~/backup` round-trips.
        source = source / paths.registry_file.name
    if not source.is_file():
        raise BuiltinError(f"nothing to import: {source} is not a file")
    if source == paths.registry_file.resolve():
        raise BuiltinError("that is this registry; nothing to import")

    try:
        incoming = store.read_file(source)
    except RegistryEntryError as exc:
        # Reported here rather than raised, so a file this command refuses exits the
        # same way whether the parser or the checks were the one to refuse it.
        # The exception already names the file; saying it twice reads like two files.
        render_text(f"refusing it: {str(exc).splitlines()[0]}")
        return 1

    problems = store.issues_for(incoming)
    illegal = [i for i in problems
               if i.severity == store.BROKEN and i.kind == store.STRUCTURE]
    unreachable = [i for i in problems
                   if i.severity == store.BROKEN and i.kind == store.REACHABILITY]
    skip = frozenset(issue.namespace for issue in illegal)

    result = store.merge_file(paths, source, force=args.force, skip=skip)

    counts = [f"{len(result.added)} added"]
    if result.replaced:
        counts.append(f"{len(result.replaced)} replaced")
    if result.unchanged:
        counts.append(f"{len(result.unchanged)} already matched")
    kept = len(result.conflicts) - len(result.replaced)
    if kept:
        counts.append(f"{kept} kept")
    if illegal:
        counts.append(f"{len(illegal)} skipped")
    render_text(f"{source} -> {', '.join(counts)}")

    if illegal:
        render_text("\nleft behind, wrong on any machine")
        render_rows([(f"  {issue.namespace}", issue.problem) for issue in illegal])

    if result.conflicts and not args.force:
        render_text("\nkept yours; re-run with --force to take theirs")
        for label, mine, theirs in result.conflicts:
            render_text(f"  {label}\n    yours:  {mine}\n    theirs: {theirs}")

    # Imported, then reported. Not being installed here is a fact about this machine
    # rather than about the file, and doctor keeps saying it until it stops being true.
    if unreachable:
        render_text("\nimported, but not usable here yet (ch doctor repeats these)")
        render_rows([(f"  {issue.namespace}", issue.problem) for issue in unreachable])
    return 0


def _run_edit(args, paths: Paths) -> int:
    """Change one part of an entry and leave the rest alone.

    `add --force` replaces an entry whole, description included; this touches only
    what you name.

    Renaming works for groups and commands alike -- renaming a group renames the
    commands under it. Never across groups: that moves an entry rather than
    renaming it, and is a remove plus an add.
    """
    store.split_name(args.name)
    if args.rename is None and args.describe is None and not args.prefix:
        raise UsageError(
            "nothing to change: give --name, --describe, or -- <path> [fixed-args...]"
        )

    loaded = store.load(paths)
    if args.name not in loaded.by_name() and loaded.namespace(args.name) is None:
        raise UnknownCommandError(args.name)

    current = args.name
    if args.prefix:
        target = _validated_target(current, args.prefix)
        _warn_if_environment_specific(current, target)
        store.set_command(paths, current, [target, *args.prefix[1:]])
        print(f"command     {current} -> {target}")
    if args.describe is not None:
        store.set_description(paths, current, args.describe or None)
        print(f"description {current} -> {args.describe or '(cleared)'}")
    if args.rename is not None:
        store.rename(paths, current, args.rename)
        print(f"renamed     {current} -> {args.rename}")
    return 0


def _run_show(args, paths: Paths) -> int:
    """Print what the registry holds for a name, in the file's own syntax.

    Shown as TOML rather than as a prettier summary because that is what is actually
    stored: what you read here is what you would edit, and it can be pasted back.

    A bare name shows its whole group, so `show llm` answers "what is under llm"
    without having to ask twice. A dotted name shows just that command.
    """
    store.split_name(args.name)          # rejects two dots, bad characters
    loaded = store.load(paths)
    namespace, tool = store.split_name(args.name)

    group = loaded.namespace(namespace)
    if group is None:
        raise UnknownCommandError(args.name)
    if tool is not None and not any(entry.tool == tool for entry in group.entries):
        raise UnknownCommandError(args.name)

    def quoted(value: str) -> str:
        return json.dumps(value)      # TOML basic strings are JSON strings

    lines: list[str] = []
    keep = [e for e in group.entries if tool is None or e.tool == tool]
    if tool is None:
        lines.append(f"[{group.name}]")
        if group.description:
            lines.append(f"description = {quoted(group.description)}")
        if group.command is not None:
            lines.append(f"command = {quoted(group.command.command)}")
    for entry in keep:
        if lines:
            lines.append("")
        lines.append(f"[{group.name}.{entry.tool}]")
        if entry.description:
            lines.append(f"description = {quoted(entry.description)}")
        lines.append(f"command = {quoted(entry.command)}")
    render_text("\n".join(lines))

    # The entry can be present and still not runnable; say so rather than let it
    # look healthy.
    broken = [i for i in store.doctor_issues(paths)
              if i.severity == store.BROKEN and (i.namespace == args.name
                                                 or i.namespace.startswith(f"{group.name}."))]
    for issue in broken:
        sys.stderr.write(f"{issue.namespace}: {issue.problem}\n")
    return 1 if broken else 0


def _run_validate(paths: Paths) -> int:
    """The registry's own integrity checks.

    `ch doctor` calls `store.doctor_issues` too, rather than reimplementing it, and
    wraps clihub's setup checks around the same result.
    """
    issues = store.doctor_issues(paths)
    if not issues:
        render_text("ok - checked: " + ", ".join(store.CHECKS))
        return 0
    render_rows([(issue.namespace, issue.problem) for issue in issues])
    return 1 if any(i.severity == store.BROKEN for i in issues) else 0


def _run_remove(args: argparse.Namespace, paths: Paths) -> int:
    store.split_name(args.name)
    store.remove(paths, args.name)
    return 0

def _validated_target(name: str, prefix: list[str]) -> str:
    """Resolve the target, and refuse only what can never come right.

        jq              whatever PATH means, resolved at dispatch
        ./bin/foo       relative to where you are now, and you will not be here at
                        dispatch, so it is resolved now
        /opt/.../jq     that exact file, stored exactly

    Two questions are asked and only the second is fatal. Whether the target is
    there *now* is worth saying -- it is how a typo surfaces -- but a bare name is
    stored precisely so it resolves later, and a file can be installed after the
    fact, so a miss is a warning. Whether the assembled line *parses* is different:
    no change of PATH or install will ever make `done --flag "$@"` run.
    """
    path_value = prefix[0]
    target = path_value

    # A word the shell runs itself names no file, so there is nothing to look up
    # and nothing to rewrite. The same rule doctor applies, from the same function.
    if not store.is_shell_construct(path_value):
        if os.sep in path_value or path_value.startswith("~"):
            target = os.path.abspath(os.path.expanduser(path_value))
            if target != path_value:
                # The only case where what is stored is not what was typed. Said
                # out loud, because silently it reads as though your text was kept
                # -- and `./bin/tool` kept verbatim would mean a different file
                # from every directory.
                why = ("~ expanded now" if path_value.startswith("~")
                       else "relative to where you are now, and you will not be here later")
                sys.stderr.write(f"{path_value}: stored as {target} ({why})\n")
            # Said, not refused. doctor reports the same thing as broken and exits
            # non-zero, so nothing is lost by letting the entry exist.
            if not os.path.exists(target):
                sys.stderr.write(f"{name}: target missing: {target}\n")
            elif not os.access(target, os.X_OK):
                sys.stderr.write(f"{name}: target not executable: {target}\n")
        elif shutil.which(path_value) is None:
            sys.stderr.write(f"{name}: not found on PATH: {path_value}\n")

    problem = store.syntax_problem(name, shlex.join([target, *prefix[1:]]))
    if problem is not None:
        raise BuiltinError(f"{name}: {problem}")
    return target


def _warn_if_environment_specific(name: str, path_value: str) -> None:
    """A bare name resolved through something that will not be there later.

    Late resolution is the point of storing a bare name -- it is what gets you the
    venv's `black` inside the project. It is also the one case where `ch <name>`
    means different things in different shells, so say so while the choice is still
    being made. `registry validate` says it again afterwards, off the same helper.
    """
    if os.sep in path_value or path_value.startswith("~"):
        return
    found = store.environment_specific(path_value)
    if found is None:
        # Either stable, or several stable copies with a stable winner: ordinary,
        # and PATH order decides exactly as it does in a shell.
        return
    reason, winner, elsewhere = found
    if elsewhere is not None:
        sys.stderr.write(
            f"{name}: resolved through {reason}, so this one depends on where "
            f"`ch {name}` is run from.\n"
            f"  here:      {winner}\n  elsewhere: {elsewhere}\n"
        )
        return
    sys.stderr.write(
        f"{name}: only exists in {reason} ({winner}),\n"
        f"  so `ch {name}` will fail anywhere else. Register the full path to pin it.\n"
    )

