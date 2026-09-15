"""Turning the TOML file into a Registry, and finding things in the result.

`tomllib`, so the dispatch path stays stdlib. Nothing here writes.
"""
from __future__ import annotations

from pathlib import Path
import tomllib

from ..errors import RegistryEntryError, UnknownCommandError
from ..paths import Paths
from .model import Entry, Namespace, Registry
from .names import is_shadowed


def load(paths: Paths) -> Registry:
    return read_file(paths.registry_file, missing_ok=True)


def read_file(path: Path, *, missing_ok: bool = False) -> Registry:
    """Any registry file, not only the live one.

    `import` has to judge a file before adopting it, and judging it with a second
    parser is how the two would come to disagree about what is legal.
    """
    if not path.is_file():
        if missing_ok:
            return _build({})
        raise RegistryEntryError(f"no such file: {path}")
    try:
        with path.open("rb") as handle:
            document = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise RegistryEntryError(
            f"cannot parse {path}: {exc}\n"
            f"  edit it by hand, or run: ch doctor"
        ) from exc
    return _build(document)


def _build(document: dict) -> Registry:
    """A TOML table is a group; a table inside it is a command in that group."""
    namespaces: list[Namespace] = []
    for section, body in document.items():
        if not isinstance(body, dict):
            raise RegistryEntryError(
                f"invalid registry entry for {section}: expected a table, got a value"
            )
        description = _clean(body.get("description"))
        command_raw = body.get("command")

        entries = tuple(
            Entry(
                name=f"{section}.{tool}",
                namespace=section,
                tool=tool,
                command=inner.get("command"),
                description=_clean(inner.get("description")),
            )
            for tool, inner in sorted(body.items())
            if isinstance(inner, dict)
        )
        command = (
            Entry(
                name=section,
                namespace=section,
                tool=None,
                command=command_raw,
                description=description,
            )
            if command_raw is not None
            else None
        )
        namespaces.append(
            Namespace(
                name=section,
                description=description,
                entries=entries,
                command=command,
            )
        )
    return Registry(namespaces=tuple(sorted(namespaces, key=lambda n: n.name.casefold())))


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def resolve(registry: Registry, argv: list[str]) -> tuple[Entry, list[str]]:
    """`ch <command> [args…]` -> the entry to run and the arguments to pass it.

    The first word is the whole command name; everything after it is an argument,
    so a line's meaning never depends on what else is registered.
    """
    head, tail = argv[0], argv[1:]
    by_name = registry.by_name()
    if head in by_name:
        return by_name[head], tail
    raise UnknownCommandError(head)


def shadowed_names(registry: Registry) -> list[str]:
    """Registered namespaces a builtin makes unreachable — what to warn about."""
    return [namespace.name for namespace in registry.namespaces if is_shadowed(namespace.name)]


def visible_entries(registry: Registry) -> list[Entry]:
    """Entries a user can actually reach. Shadowed namespaces are not among them."""
    return [entry for entry in registry.entries() if not is_shadowed(entry.namespace)]


def is_grouping_namespace(registry: Registry, name: str) -> bool:
    """A namespace that lists but does not run: `ch <name>` should show its tools."""
    namespace = registry.namespace(name)
    return namespace is not None and namespace.command is None
