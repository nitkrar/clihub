from __future__ import annotations

import argparse
import sys

from .. import describe, dispatch, registry
from ..errors import UnknownCommandError
from ..paths import Paths
from ..render import render_json, render_rows, render_text

# What `ch --help` prints for this command. Separate from __doc__, which is
# about the module: different readers, different words.
SUMMARY = "everything registered"
ARGS = "[<group>]"


def run(argv: list[str], paths: Paths) -> int:
    parser = argparse.ArgumentParser(prog="ch list")
    parser.add_argument("namespace", nargs="?")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv[2:])

    loaded = registry.load(paths)
    for name in registry.shadowed_names(loaded):
        dispatch.write_shadowed_builtin_notice(name)

    if args.namespace:
        namespace = loaded.namespace(args.namespace)
        if namespace is None:
            raise UnknownCommandError(args.namespace)
        entries = [*( [namespace.command] if namespace.command else [] ), *namespace.entries]
        if namespace.command is None and namespace.description:
            render_text(f"{namespace.name}  {namespace.description}")
    else:
        # Flat: one row per tool, and none for a group that only groups. A group
        # earns a row by being dispatchable, which makes it an entry like any other.
        entries = registry.visible_entries(loaded)

    rows, notices = describe.entry_rows(paths, entries)
    for notice in notices:
        sys.stderr.write(f"{notice}\n")

    listing = [(row.namespace, row.description or row.status or "") for row in rows]
    listing.sort(key=lambda pair: pair[0].casefold())

    # Every registered entry is always listed. A missing description empties the
    # second column; it never removes the row. `list` is the only way to learn an
    # entry exists, so a bare name is far more useful than nothing at all.
    if args.json:
        render_json([{"name": name, "description": text} for name, text in listing])
        return 0

    render_rows(listing)
    return 0
