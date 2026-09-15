"""`ch tools` — some useful tools.

Common Module to add some useful tools without separate commands.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .. import completion, registry
from ..errors import RegistryEntryError
from ..paths import Paths
from ..render import render_json, render_text

# What `ch --help` prints for this command. Separate from __doc__, which is
# about the module: different readers, different words.
SUMMARY = "some useful tools"
ARGS = "<command>"


def subcommands() -> tuple:
    """The verbs this group accepts, from the parser that accepts them.

    Read off the subparsers action rather than kept as a second list, so
    `ch --help` cannot advertise a verb the parser would reject.
    """
    return tuple(_build_parser().get_default("_subcommands").choices)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ch tools", description=SUMMARY)
    subparsers = parser.add_subparsers(dest="action", metavar="<command>")
    parser.set_defaults(_subcommands=subparsers)
    completion_parser = subparsers.add_parser(
        "completion", prog="ch tools completion", help="install shell completion"
    )
    completion_parser.add_argument(
        "shell", nargs="?", choices=completion.SHELLS, help="defaults to $SHELL"
    )
    completion_parser.add_argument(
        "--print",
        dest="print_only",
        action="store_true",
        help="write the script to stdout and change nothing",
    )
    completion_parser.add_argument(
        "--remove", action="store_true", help="delete the script and its rc line"
    )
    stats_parser = subparsers.add_parser(
        "stats", prog="ch tools stats", help="what you run, and what it costs"
    )
    stats_parser.add_argument("--json", action="store_true")
    return parser


def run(argv: list[str], paths: Paths) -> int:
    parser = _build_parser()
    if len(argv) < 3 or argv[2] in ("-h", "--help"):
        parser.print_help()
        return 0
    args = parser.parse_args(argv[2:])
    if args.action == "stats":
        return _run_stats(args, paths)
    return _run_completion(args, paths)


def _run_stats(args: argparse.Namespace, paths: Paths) -> int:
    """Read the invocation journal back as a per-command profile.

    Sorted by total time rather than by count, which is the only ordering that says
    anything: 111 `jq` runs came to 0.7s while 26 `llama` runs came to 68s. Counting
    invocations tells you what you type; totalling them tells you where the time goes.

    Names come from the journal, not the registry, so entries you have since renamed
    or removed still appear. That is the point of a log.
    """
    rows = _profile(paths.journal_file)
    if not rows:
        render_text(f"nothing recorded yet: {paths.journal_file}")
        return 0
    if args.json:
        render_json(rows)
        return 0
    header = ("command", "runs", "fail", "p50ms", "p95ms", "total_s", "last")
    table = [header] + [
        (r["command"], str(r["runs"]), str(r["fail"]), str(r["p50_ms"]),
         str(r["p95_ms"]), f"{r['total_s']:.1f}", r["last"][:10])
        for r in rows
    ]
    widths = [max(len(row[i]) for row in table) for i in range(len(header))]
    for row in table:
        render_text("  ".join(cell.ljust(w) for cell, w in zip(row, widths)).rstrip())
    return 0


def _profile(journal: Path) -> list[dict]:
    """One row per command name seen in the journal.

    A malformed line is skipped rather than fatal: this is a log being read for
    interest, and half a profile beats a traceback.
    """
    if not journal.is_file():
        return []
    seen: dict[str, dict] = {}
    with journal.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                record = json.loads(line)
                name, milliseconds = record["ns"], int(record["ms"])
            except Exception:
                continue
            row = seen.setdefault(name, {"command": name, "ms": [], "fail": 0, "last": ""})
            row["ms"].append(milliseconds)
            row["fail"] += 1 if record.get("rc") else 0
            row["last"] = max(row["last"], str(record.get("ts", "")))

    profile = []
    for row in seen.values():
        ordered = sorted(row["ms"])
        profile.append({
            "command": row["command"],
            "runs": len(ordered),
            "fail": row["fail"],
            "p50_ms": ordered[len(ordered) // 2],
            "p95_ms": ordered[min(int(len(ordered) * 0.95), len(ordered) - 1)],
            "total_s": sum(ordered) / 1000,
            "last": row["last"],
        })
    return sorted(profile, key=lambda row: -row["total_s"])


def completion_words(paths: Paths) -> list[str]:
    """Builtins plus every invocable name: tools, their dotted spellings, namespaces.

    A registry that will not parse yields the builtins alone rather than an error,
    since installing completions must not require a working registry.
    """
    try:
        loaded = registry.load(paths)
    except RegistryEntryError:
        return sorted(registry.BUILTIN_NAMES, key=str.casefold)
    names = {entry.name for entry in loaded.entries()}
    names |= {namespace.name for namespace in loaded.namespaces}
    names = {name for name in names if not registry.is_shadowed(name)}
    return sorted([*registry.BUILTIN_NAMES, *names], key=str.casefold)


def _run_completion(args: argparse.Namespace, paths: Paths) -> int:
    shell = args.shell or completion.detect_shell()
    if args.print_only:
        render_text(completion.script(shell, completion_words(paths)))
        return 0
    if args.remove:
        had_script, had_line = completion.remove(paths, shell)
        if not (had_script or had_line):
            sys.stderr.write(f"{shell} completion was not installed\n")
            return 0
        print(f"removed    {completion.script_path(paths, shell)}")
        if had_line:
            print(f"unsourced  {completion.rc_path(shell)}")
        return 0
    return install_completion(paths, shell)


def install_completion(paths: Paths, shell: str) -> int:
    """Shared with `ch init`, so both routes install the same way."""
    target, rc, changed = completion.install(paths, shell, completion_words(paths))
    print(f"completion {target}")
    print(f"{'sourced   ' if changed else 'already in'} {rc}")
    if changed:
        sys.stderr.write(f"open a new shell, or run: source {rc}\n")
    return 0
