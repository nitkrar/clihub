"""Every mutation of the registry file.

`tomlkit` rather than `tomllib`, so hand-written comments and layout survive a
rewrite; it is imported inside each function, so the dispatch path never loads it.

Every mutation takes the lock and ends in a rename: renaming alone makes a write
atomic but not safe, because concurrent writers would all read the same state and
the last one would win.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator
import fcntl
import os
import shlex

from ..errors import BuiltinError, RegistryEntryError, UnknownCommandError
from ..paths import Paths
from .names import ensure_addable, split_name


def add(
    paths: Paths,
    name: str,
    prefix: list[str],
    description: str | None = None,
    force: bool = False,
) -> None:
    import tomlkit

    namespace, tool = ensure_addable(name)
    if description is not None and "\n" in description:
        raise BuiltinError("a description must be a single line")
    with _locked(paths.registry_file):
        document = _read_for_write(paths)
        group = _table(document, namespace, create=True)
        if tool is not None and tool not in group:
            group[tool] = tomlkit.table()
        target = group if tool is None else group[tool]
        if "command" in target and not force:
            raise BuiltinError(f"already registered: {name} (use --force to replace)")
        if description:
            target["description"] = description
        elif force and "description" in target:
            # A description written for the old command does not describe the new
            # one, so --force clears it rather than leaving a lie in place.
            del target["description"]
        target["command"] = shlex.join(prefix)
        _write(paths, document)


@dataclass(frozen=True)
class MergeResult:
    """What a merge did, per key, so the report is the truth rather than a summary."""

    added: list[str]
    replaced: list[str]
    conflicts: list[tuple[str, str, str]]   # label, mine, theirs
    unchanged: list[str]


def merge_file(
    paths: Paths, source: Path, *, force: bool = False, skip: frozenset[str] = frozenset()
) -> MergeResult:
    """Fold another registry into this one, key by key.

    A key is the unit: `[llm]` on both sides is not a disagreement, `llm.llama`
    pointing at two different commands is. Same key and same value is a no-op, so
    re-importing what you exported does nothing.
    """
    import tomlkit

    with _locked(paths.registry_file):
        mine = _read_for_write(paths)
        theirs = tomlkit.parse(source.read_text(encoding="utf-8"))

        added, replaced, conflicts, unchanged = [], [], [], []

        def fold(ours, incoming, entry: str) -> None:
            """Merge one table's scalar keys, then recurse into its sub-tables."""
            for key, value in incoming.items():
                if isinstance(value, dict):
                    continue
                label = entry if key == "command" else f"{entry} ({key})"
                if key not in ours:
                    ours[key] = value
                    added.append(label)
                elif ours[key] == value:
                    unchanged.append(label)
                else:
                    conflicts.append((label, ours[key], value))
                    if force:
                        ours[key] = value
                        replaced.append(label)

        for section, body in theirs.items():
            if section in skip or not isinstance(body, dict):
                continue
            if section not in mine:
                mine[section] = tomlkit.table()
            fold(mine[section], body, section)
            for tool, inner in body.items():
                if not isinstance(inner, dict) or f"{section}.{tool}" in skip:
                    continue
                if tool not in mine[section]:
                    mine[section][tool] = tomlkit.table()
                fold(mine[section][tool], inner, f"{section}.{tool}")

        # Conflicts are applied partially on purpose -- the keys that agreed are
        # wanted either way -- but as one atomic write, not a sequence of edits.
        _write(paths, mine)
    return MergeResult(added, replaced, conflicts, unchanged)


def set_description(paths: Paths, name: str, description: str | None) -> None:
    namespace, tool = split_name(name)
    with _locked(paths.registry_file):
        document = _read_for_write(paths)
        group = _table(document, namespace)
        if group is None:
            raise BuiltinError(f"unknown command: {namespace}")
        target = group if tool is None else group.get(tool)
        if target is None:
            raise UnknownCommandError(name)
        if description:
            target["description"] = description
        elif "description" in target:
            del target["description"]
        _write(paths, document)


def set_command(paths: Paths, name: str, prefix: list[str]) -> None:
    """Point an existing name somewhere else, leaving its description alone.

    `add --force` replaces the entry whole, description included. This is the other
    half: change one thing and keep the rest.
    """
    namespace, tool = split_name(name)
    with _locked(paths.registry_file):
        document = _read_for_write(paths)
        group = _table(document, namespace)
        target = None if group is None else (group if tool is None else group.get(tool))
        if target is None or "command" not in target:
            raise UnknownCommandError(name)
        target["command"] = shlex.join(prefix)
        _write(paths, document)


def rename(paths: Paths, old: str, new: str) -> None:
    """Rename in place. Never across namespaces -- that is a remove and an add.

    Renaming a group renames every command under it at once, which is the thing a
    group is for; renaming a command touches only that key. Both carry the same
    consequence, that the previous spelling stops working, so both are refused if
    the new name is already taken.
    """
    old_ns, old_tool = split_name(old)
    new_ns, new_tool = ensure_addable(new)
    if (old_tool is None) != (new_tool is None):
        raise BuiltinError(
            f"cannot rename {old} to {new}: a group and a command are different shapes"
        )
    if old_tool is not None and old_ns != new_ns:
        raise BuiltinError(
            f"cannot rename {old} to {new}: that moves it between groups; "
            f"use remove and add"
        )

    with _locked(paths.registry_file):
        document = _read_for_write(paths)
        group = _table(document, old_ns)
        if group is None:
            raise UnknownCommandError(old)

        if old_tool is None:
            if new_ns in document:
                raise BuiltinError(f"already registered: {new}")
            document[new_ns] = group
            del document[old_ns]
        else:
            if old_tool not in group:
                raise UnknownCommandError(old)
            if new_tool in group:
                raise BuiltinError(f"already registered: {new}")
            # The whole sub-table moves, so the description rides along.
            group[new_tool] = group[old_tool]
            del group[old_tool]
        _write(paths, document)


def remove(paths: Paths, name: str) -> None:
    """Remove exactly the entry named — never entries the caller did not name.

    `ch registry remove llm.llama` drops that tool. `ch registry remove llm` drops the
    namespace's own command; the namespace survives as a pure grouping if it still
    holds tools, and disappears entirely when it does not.
    """
    namespace, tool = split_name(name)
    with _locked(paths.registry_file):
        document = _read_for_write(paths)
        group = _table(document, namespace)
        if group is None:
            raise UnknownCommandError(name, f"unknown command: {name}")
        if tool is None:
            if "command" not in group:
                raise UnknownCommandError(name, f"unknown command: {name}")
            del group["command"]
            if "description" in group:
                del group["description"]
        else:
            if tool not in group:
                raise UnknownCommandError(name, f"unknown command: {name}")
            del group[tool]
        if not _remaining_tools(group) and "command" not in group:
            del document[namespace]
        _write(paths, document)


def _remaining_tools(table) -> list[str]:
    """Commands still inside a group -- its sub-tables, not its own keys."""
    return [key for key, value in table.items() if isinstance(value, dict)]


def _read_for_write(paths: Paths):
    """The document as written, with comments and layout intact."""
    import tomlkit

    if not paths.registry_file.is_file():
        return tomlkit.document()
    try:
        return tomlkit.parse(paths.registry_file.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RegistryEntryError(f"cannot parse {paths.registry_file}: {exc}") from exc


def _write(paths: Paths, document) -> None:
    """Rename into place so a write is never half-visible."""
    import tomlkit

    path = paths.registry_file
    path.parent.mkdir(parents=True, exist_ok=True)
    body = tomlkit.dumps(document)
    if not body.lstrip().startswith("#"):
        body = _HEADER + body
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(body, encoding="utf-8")
    os.replace(temporary, path)


def _table(document, namespace: str, *, create: bool = False):
    """The table a name lives in, creating it only when asked."""
    import tomlkit

    if namespace not in document:
        if not create:
            return None
        document[namespace] = tomlkit.table()
    return document[namespace]


_HEADER = (
    "# clihub registry. A table is a group; a table inside it is a command.\n"
    "# Safe to hand-edit -- comments here survive when clihub rewrites it.\n\n"
)


@contextmanager
def _locked(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(path.name + ".lock")
    with open(lock_path, "a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
