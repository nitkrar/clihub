from __future__ import annotations

from typing import Sequence
import sys

from importlib import import_module

from . import dispatch, registry
from .config import BUILTIN_NAMES
from .errors import ClihubError, UnknownCommandError
from .paths import get_paths
from .render import render_text

# Module names, not functions: importing all seven cost every command the price of
# the heaviest. Dispatch needs registry, dispatch and journal -- not describe, whose
# subprocess and tempfile imports it never touches.
BUILTIN_COMMANDS = {
    "doctor": "doctor",
    "help": "help",
    "init": "init",
    "list": "list",
    "registry": "registry",
    "rg": "registry",      # the one group typed often enough to shorten
    "find": "find",
    "tools": "tools",
}


def run_builtin(name: str, argv: list[str], paths) -> int:
    return import_module(f".commands.{BUILTIN_COMMANDS[name]}", __package__).run(argv, paths)

# The names live in the config package because `registry` needs them too. This is what
# keeps the two in step: a name with no function behind it fails here, at import,
# rather than becoming a word `tools add` refuses but nothing can run.
_missing = BUILTIN_NAMES ^ set(BUILTIN_COMMANDS)
if _missing:
    raise RuntimeError(f"builtin names and commands disagree: {sorted(_missing)}")


def main(argv: Sequence[str] | None = None) -> int:
    raw_argv = list(sys.argv if argv is None else argv)
    paths = get_paths()

    # No arguments, or a help flag where a name would go, asks about clihub itself.
    # A tool can never be named `-h` or `--help`, so intercepting here cannot shadow
    # one; `ch <tool> --help` is untouched, because the flag is not in this position.
    if len(raw_argv) < 2 or raw_argv[1] in ("-h", "--help"):
        return run_builtin("help", ["ch", "help"], paths)
    if raw_argv[1] in ("-V", "--version"):
        # Imported here, not at module scope: `clihub/__init__` imports this module,
        # so at import time the attribute may not be bound yet.
        from . import __version__

        render_text(f"clihub {__version__}")
        return 0

    command = raw_argv[1]
    try:
        # Builtins run before the registry is read at all. Self-management has to
        # work when the registry is broken -- that is when you need it most -- and
        # a shadowed entry is unreachable by this ordering anyway, so warning here
        # bought nothing and printed twice for the commands that scan it themselves.
        if command in BUILTIN_COMMANDS:
            return run_builtin(command, raw_argv, paths)

        loaded = registry.load(paths)
        # A namespace that only groups has nothing to run, so showing what is inside
        # it is the useful answer rather than an error.
        if len(raw_argv) == 2 and registry.is_grouping_namespace(loaded, command):
            return run_builtin("list", ["ch", "list", command], paths)

        try:
            entry, tail = registry.resolve(loaded, raw_argv[1:])
        except UnknownCommandError:
            raise _unknown(loaded, raw_argv[1:]) from None
        return dispatch.dispatch(paths, entry.name, entry.script, tail)
    except ClihubError as exc:
        return _handle_error(exc)


def _unknown(loaded: registry.Registry, words: list[str]) -> ClihubError:
    """A group name typed as a command is almost always a missing dot."""
    head = words[0]
    group = loaded.namespace(head)
    if group is not None and len(words) > 1:
        # Not a fuzzy match: the two words joined by a dot either are a registered
        # command or they are not. Listing what the group holds instead would grow
        # the error past the listing it is standing in for.
        wanted = f"{head}.{words[1]}"
        if any(entry.name == wanted for entry in group.entries):
            return UnknownCommandError(
                head, f"unknown command: {head} - did you mean '{wanted}'?"
            )
        return UnknownCommandError(head)
    # Nothing matched at all: name the two commands that would find it.
    return UnknownCommandError(
        head, f"unknown command: {head} - try 'ch list', or 'ch find {head}'"
    )


def _handle_error(error: ClihubError) -> int:
    sys.stderr.write(f"{error}\n")
    return error.exit_code
