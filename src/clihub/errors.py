from __future__ import annotations


class ClihubError(Exception):
    exit_code = 1


class BuiltinError(ClihubError):
    pass


class UsageError(BuiltinError):
    exit_code = 2


class UnknownCommandError(ClihubError):
    """Nothing by that name, at any level.

    Everything a user types is a command -- `git`, `brew`, `ch llm.llama`. Namespace
    and tool describe how the registry is *shaped*; they are not words to report a
    typo with. 127 is the shell's "command not found", so a caller that already
    handles it needs no new vocabulary.
    """

    exit_code = 127

    def __init__(self, name: str, message: str | None = None) -> None:
        super().__init__(message or f"unknown command: {name}")
        self.name = name


class RegistryEntryError(ClihubError):
    exit_code = 126


class DispatchError(ClihubError):
    exit_code = 126
