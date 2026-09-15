"""What a legal command name is, and the three ways to ask.

`validate_name` and `split_name` raise, for input arriving from a user.
`name_problem` returns, for names already in the file, where raising would stop a
scan at the first bad one and hide the rest.
"""
from __future__ import annotations

import re

from ..config import BUILTIN_NAMES
from ..errors import BuiltinError

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def validate_name(name: str, *, what: str = "command name") -> str:
    """N4a: what a user reads says "command", never "namespace" or "tool".

    Those words describe how the registry is shaped. Someone who typed a name wrong
    is not helped by learning which level of a structure they have not read about
    rejected it.
    """
    if not name:
        raise BuiltinError(f"{what} is required")
    if not _NAME_RE.match(name):
        raise BuiltinError(
            f"invalid {what}: {name} — lowercase letters, digits, '-' and '_' only"
        )
    return name


def name_problem(name: str) -> str | None:
    """Why this name is not legal, or None. The question without the exception."""
    try:
        split_name(name)
    except BuiltinError as exc:
        return str(exc)
    return None


def split_name(name: str) -> tuple[str, str | None]:
    """`llm.llama` -> ('llm', 'llama'); `jq` -> ('jq', None)."""
    if not name:
        raise BuiltinError("a command name is required")
    parts = name.split(".")
    if len(parts) > 2:
        raise BuiltinError(
            f"invalid command name: {name} — at most one dot, as <group>.<command>"
        )
    namespace = validate_name(parts[0], what="command name")
    tool = validate_name(parts[1], what="command name") if len(parts) == 2 else None
    return namespace, tool


def ensure_addable(name: str) -> tuple[str, str | None]:
    namespace, tool = split_name(name)
    if namespace in BUILTIN_NAMES:
        raise BuiltinError(f"reserved name: {namespace} - it is a builtin")
    return namespace, tool


def is_shadowed(name: str) -> bool:
    """A builtin always wins, so a registry entry with that name is unreachable."""
    return name in BUILTIN_NAMES
