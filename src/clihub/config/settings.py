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
    values = tomllib.loads(defaults_text())
    if config_file is not None and config_file.is_file():
        try:
            with config_file.open("rb") as handle:
                for section, body in tomllib.load(handle).items():
                    if isinstance(body, dict):
                        values.setdefault(section, {}).update(body)
        except Exception:
            # A malformed user config must never stop dispatch; defaults still stand.
            pass

    describe, find = values["describe"], values["find"]
    completions, journal = values["completions"], values["journal"]
    return Settings(
        describe_timeout_seconds=float(describe["timeout_seconds"]),
        # Each form is a one-word argv, so a caller passes it straight to the shell.
        help_forms=tuple((form,) for form in describe["help_forms"]),
        overlap_check=bool(describe["overlap_check"]),
        overlap_warn=float(describe["overlap_warn"]),
        overlap_warning=str(describe["overlap_warning"]),
        find_typo_cutoff=float(find["typo_cutoff"]),
        completions_auto_enabled=bool(completions["completions_auto_enabled"]),
        completions_enabled=bool(completions["completions_enabled"]),
        journal_enabled=bool(journal["enabled"]),
        journal_max_bytes=int(journal["max_bytes"]),
        journal_backup_count=int(journal["backup_count"]),
    )


def parse_problem(config_file: Path | None) -> str | None:
    """Why the user's config was ignored, if it was.

    `load()` swallows a broken config on purpose -- a typo in a preferences file
    must never stop dispatch -- which means nothing tells you it was ignored.
    This is how `doctor` finds out.
    """
    if config_file is None or not config_file.is_file():
        return None
    try:
        with config_file.open("rb") as handle:
            tomllib.load(handle)
    except Exception as exc:
        return str(exc).splitlines()[0]
    return None


def defaults_text() -> str:
    """The shipped defaults, verbatim. `ch init` renders them commented out."""
    return (Path(__file__).resolve().parent / DEFAULTS_NAME).read_text(encoding="utf-8")
