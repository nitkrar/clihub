from __future__ import annotations

import argparse

from .. import dispatch, registry
from ..errors import UnknownCommandError
from ..paths import Paths
from ..render import render_text
from . import list as list_command

# What `ch --help` prints for this command. Separate from __doc__, which is
# about the module: different readers, different words.
SUMMARY = "that command's own --help"
ARGS = "<name>"

# Written out rather than generated: argparse cannot produce this, because every
# builtin builds its own parser and none of them knows the others exist. A test
# asserts each registered builtin appears here, so the two cannot drift.
TITLE = "ch - one entry point for your tools"
NUDGE = "To reach a command: ch list, or ch find <what you want to do>"
DISPATCH = (
    ("ch <command> [args...]", "run a registered command"),
    ("ch <group>.<command> [args...]", "one inside a group"),
)
TAIL = "Arguments after the command are passed through untouched."


def usage() -> str:
    """Assembled from the commands themselves, not written out.

    Each command module carries its own SUMMARY and ARGS, so adding one cannot
    leave the help behind -- which is how `show`, `edit` and `export` stayed
    missing for three commits. A group's verbs are read off the parser that
    accepts them, so the help cannot advertise a verb that would be rejected.
    """
    from importlib import import_module

    from ..cli import BUILTIN_COMMANDS

    # Two names for one module is an alias: `registry|rg`, printed once.
    names: dict[str, list[str]] = {}
    for name, module in BUILTIN_COMMANDS.items():
        names.setdefault(module, []).append(name)

    rows, groups = [], []
    for module, spelling in sorted(names.items(), key=_rank):
        loaded = import_module(f".commands.{module}", "clihub")
        shown = "|".join(sorted(spelling, key=len, reverse=True))
        args = getattr(loaded, "ARGS", "")
        rows.append((f"ch {shown}{' ' + args if args else ''}", getattr(loaded, "SUMMARY", "")))
        verbs = getattr(loaded, "subcommands", None)
        if verbs is not None:
            shortest = min(spelling, key=len)
            listed = list(verbs())
            # A long group would push the line past anything readable, and the
            # group's own --help is one command away.
            more = "|..." if len(listed) > MAX_VERBS else ""
            joined = "|".join(listed[:MAX_VERBS])
            groups.append((shown, f"ch {shortest} {{{joined}{more}}}"))

    body = [*DISPATCH, ("", "")]
    for row in rows:
        body.append(row)
        for shown, line in groups:
            if row[0].startswith(f"ch {shown}"):
                body.append((line, ""))
    body += [("", ""), ("ch --version", "which clihub this is")]
    width = max(len(left) for left, right in body if right)
    lines = [TITLE, NUDGE, ""]
    for left, right in body:
        lines.append(f"  {left.ljust(width)}  {right}".rstrip() if left or right else "")
    return "\n".join([*lines, "", TAIL])


MAX_VERBS = 10

# The order they are worth reading in, which is not alphabetical. A preference,
# not a registry: anything missing sorts to the end rather than raising, so adding
# a command cannot break `ch --help` by forgetting to mention it here.
_ORDER = ["list", "find", "help", "doctor", "init", "registry", "tools"]


def _rank(item) -> tuple:
    module = item[0]
    return (_ORDER.index(module) if module in _ORDER else len(_ORDER), module)


def run(argv: list[str], paths: Paths) -> int:
    # `ch help` with nothing after it asks for clihub's own help, not a usage error.
    # `ch`, `ch -h` and `ch --help` route here too.
    if len(argv) < 3 or argv[2] in ("-h", "--help"):
        render_text(usage())
        return 0

    parser = argparse.ArgumentParser(add_help=False, prog="ch help")
    parser.add_argument("name")
    args = parser.parse_args(argv[2:])

    # A builtin has help of its own; asking for it is not an error. The reserved-word
    # message belongs to a *registered entry* that a builtin makes unreachable, which
    # is a different situation and is reported by `doctor` and at dispatch.
    if registry.is_shadowed(args.name):
        from ..cli import run_builtin

        return run_builtin(args.name, ["ch", args.name, "--help"], paths)

    loaded = registry.load(paths)

    # A namespace that only groups has no command to ask for help, so the useful
    # answer is what it contains.
    if registry.is_grouping_namespace(loaded, args.name):
        return list_command.run(["ch", "list", args.name], paths)

    entry = loaded.by_name().get(args.name)
    if entry is None:
        raise UnknownCommandError(args.name)
    return dispatch.dispatch(paths, entry.name, entry.script, ["--help"])
