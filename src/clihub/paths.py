"""Where clihub keeps things: one directory, `~/.clihub`.

    config.toml            yours; every key commented out with its default
    registry.toml          the registry
    completion.<shell>     generated
    log/invocations.jsonl  safe to delete

CLIHUB_HOME moves the root, and is the only path variable clihub reads.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
import os

HOME_VAR = "CLIHUB_HOME"
DEFAULT_DIRNAME = ".clihub"


@dataclass(frozen=True)
class Paths:
    root: Path

    @property
    def registry_file(self) -> Path:
        return self.root / "registry.toml"

    @property
    def config_file(self) -> Path:
        return self.root / "config.toml"

    @property
    def log_root(self) -> Path:
        return self.root / "log"

    @property
    def journal_file(self) -> Path:
        return self.log_root / "invocations.jsonl"

    @property
    def completion_root(self) -> Path:
        return self.root


def get_paths(env: Mapping[str, str] | None = None) -> Paths:
    current_env = os.environ if env is None else env
    override = current_env.get(HOME_VAR)
    if override:
        return Paths(root=Path(override).expanduser())
    home = Path(current_env.get("HOME", str(Path.home()))).expanduser()
    return Paths(root=home / DEFAULT_DIRNAME)
