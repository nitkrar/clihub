"""What a registry is made of: entries, the groups holding them, and the whole.

These types carry no file and no I/O. Reading builds them, writing edits the
document they came from, and doctor asks them questions.
"""
from __future__ import annotations

from dataclasses import dataclass
import shlex

from ..errors import RegistryEntryError


@dataclass(frozen=True)
class Entry:
    """One addressable name. `llm.llama`, or `jq`, or `llm` itself via `.command`."""

    name: str
    namespace: str
    tool: str | None
    command: str
    description: str | None

    @property
    def script(self) -> str:
        """What gets handed to the shell: the command as written.

        A list is joined with `shlex.join`, since the shell needs argv quoted back
        into a command line.
        """
        if isinstance(self.command, (list, tuple)):
            parts = [str(item) for item in self.command]
            if not parts:
                raise RegistryEntryError(
                    f"invalid registry entry for {self.name}: empty command"
                )
            return shlex.join(parts)
        if not isinstance(self.command, str):
            raise RegistryEntryError(
                f"invalid registry entry for {self.name}: command must be a string "
                f"or a list, got {type(self.command).__name__}"
            )
        if not self.command.strip():
            raise RegistryEntryError(
                f"invalid registry entry for {self.name}: empty command"
            )
        return self.command

    @property
    def prefix(self) -> tuple[str, ...]:
        """Parsed on access, never at load, so one malformed entry stays its own
        problem: it is still listed, and only running it fails."""
        return _split_prefix(self.name, self.command)


@dataclass(frozen=True)
class Namespace:
    name: str
    description: str | None
    entries: tuple[Entry, ...]      # tools only, never the .command entry
    command: Entry | None


@dataclass(frozen=True)
class Registry:
    namespaces: tuple[Namespace, ...]

    def by_name(self) -> dict[str, Entry]:
        return {entry.name: entry for entry in self.entries()}

    def entries(self) -> list[Entry]:
        """Every addressable name, sorted — what `ch list` renders flat."""
        found: list[Entry] = []
        for namespace in self.namespaces:
            if namespace.command is not None:
                found.append(namespace.command)
            found.extend(namespace.entries)
        return sorted(found, key=lambda entry: entry.name.casefold())

    def namespace(self, name: str) -> Namespace | None:
        for namespace in self.namespaces:
            if namespace.name == name:
                return namespace
        return None


def _split_prefix(name: str, raw) -> tuple[str, ...]:
    """A command is either a line to split, or an argv vector taken as written.

    A list is already argv and must not be re-split, which is what lets it carry a
    path with spaces unquoted. clihub only ever writes the string form.
    """
    if isinstance(raw, (list, tuple)):
        parts = [str(item) for item in raw]
        if any(not isinstance(item, str) for item in raw):
            raise RegistryEntryError(
                f"invalid registry entry for {name}: command list must hold strings"
            )
    elif isinstance(raw, str):
        try:
            parts = shlex.split(raw, comments=False)
        except ValueError as exc:
            raise RegistryEntryError(f"invalid registry entry for {name}: {exc}") from exc
    else:
        raise RegistryEntryError(
            f"invalid registry entry for {name}: command must be a string or a list, "
            f"got {type(raw).__name__}"
        )
    if not parts or not all(part.strip() for part in parts[:1]):
        raise RegistryEntryError(f"invalid registry entry for {name}: empty command")
    return tuple(parts)
