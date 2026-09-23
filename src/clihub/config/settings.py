"""Tunable settings: shipped defaults, optionally overridden by the user.

Two layers, no more:

    clihub/config/defaults.toml          shipped, authoritative, never edited
    ~/.clihub/config.toml                optional, only the keys you set

Everything here is a *preference* — a timeout, a threshold, a rotation size. Values
that change what clihub *does* rather than how patiently it does it live in
`constants.py`.

Layering is per-section, so setting one key in `[describe]` does not discard the
rest of that section's defaults.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib

DEFAULTS_NAME = "defaults.toml"


@dataclass(frozen=True)
class Settings:
    describe_timeout_seconds: float
    help_forms: tuple[tuple[str, ...], ...]
    overlap_check: bool
    overlap_warn: float
    overlap_warning: str
    find_typo_cutoff: float
    completions_auto_enabled: bool
    completions_enabled: bool
    journal_enabled: bool
    journal_max_bytes: int
    journal_backup_count: int


def load(config_file: Path | None = None) -> Settings:
    """Shipped defaults, then the user's file layered on top if it exists.

    Always takes the path explicitly. An argument-less default let callers silently
    load shipped defaults only, which is how `timeout_seconds` in the user's config
    came to be ignored for two of its four call sites.
    """
    values = _default_values()
    if config_file is not None and config_file.is_file():
        try:
            with config_file.open("rb") as handle:
                _merge_user_values(values, tomllib.load(handle))
            return _settings_from_values(values)
        except Exception:
            # A malformed user config must never stop dispatch; defaults still stand.
            pass
    return _settings_from_values(_default_values())


def parse_problem(config_file: Path | None) -> str | None:
    """Why the user's config was ignored, if it was.

    `load()` swallows a broken config on purpose -- a typo in a preferences file
    must never stop dispatch -- which means nothing tells you it was ignored.
    This is how `doctor` finds out.
    """
    if config_file is None or not config_file.is_file():
        return None
    values = _default_values()
    try:
        with config_file.open("rb") as handle:
            _merge_user_values(values, tomllib.load(handle))
        _settings_from_values(values)
    except Exception as exc:
        return str(exc).splitlines()[0]
    return None


def defaults_text() -> str:
    """The shipped defaults, verbatim. `ch init` renders them commented out."""
    return (Path(__file__).resolve().parent / DEFAULTS_NAME).read_text(encoding="utf-8")


def _default_values() -> dict:
    return tomllib.loads(defaults_text())


def _merge_user_values(values: dict, incoming: dict) -> None:
    for section, body in incoming.items():
        if section in values and isinstance(values[section], dict):
            if not isinstance(body, dict):
                raise TypeError(f"{section} must be a table")
            values[section].update(body)
        elif isinstance(body, dict):
            values.setdefault(section, {}).update(body)


def _settings_from_values(values: dict) -> Settings:
    describe = _table(values, "describe")
    find = _table(values, "find")
    completions = _table(values, "completions")
    journal = _table(values, "journal")
    return Settings(
        describe_timeout_seconds=_number(describe, "timeout_seconds", "describe.timeout_seconds"),
        # Each form is a one-word argv, so a caller passes it straight to the shell.
        help_forms=tuple((form,) for form in _string_list(describe, "help_forms",
                                                          "describe.help_forms")),
        overlap_check=_boolean(describe, "overlap_check", "describe.overlap_check"),
        overlap_warn=_number(describe, "overlap_warn", "describe.overlap_warn"),
        overlap_warning=_string(describe, "overlap_warning", "describe.overlap_warning"),
        find_typo_cutoff=_number(find, "typo_cutoff", "find.typo_cutoff"),
        completions_auto_enabled=_boolean(completions, "completions_auto_enabled",
                                          "completions.completions_auto_enabled"),
        completions_enabled=_boolean(completions, "completions_enabled",
                                     "completions.completions_enabled"),
        journal_enabled=_boolean(journal, "enabled", "journal.enabled"),
        journal_max_bytes=_integer(journal, "max_bytes", "journal.max_bytes"),
        journal_backup_count=_integer(journal, "backup_count", "journal.backup_count"),
    )


def _table(values: dict, name: str) -> dict:
    table = values.get(name)
    if not isinstance(table, dict):
        raise TypeError(f"{name} must be a table")
    return table


def _number(table: dict, key: str, label: str) -> float:
    value = table[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{label} must be a number")
    return float(value)


def _integer(table: dict, key: str, label: str) -> int:
    value = table[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{label} must be an integer")
    return value


def _boolean(table: dict, key: str, label: str) -> bool:
    value = table[key]
    if not isinstance(value, bool):
        raise TypeError(f"{label} must be true or false")
    return value


def _string(table: dict, key: str, label: str) -> str:
    value = table[key]
    if not isinstance(value, str):
        raise TypeError(f"{label} must be text")
    return value


def _string_list(table: dict, key: str, label: str) -> list[str]:
    value = table[key]
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise TypeError(f"{label} must be a list of text")
    return value
