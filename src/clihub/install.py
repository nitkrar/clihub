"""Where clihub itself is installed, as opposed to where it keeps its data.

`ch` and `clihub` are two console scripts in one directory, put there by pip,
pipx, uv or Homebrew. Whether that directory is on PATH is what `init` acts on
and `doctor` reports, and both have to decide it the same way.
"""
from __future__ import annotations

import sys
from pathlib import Path


def console_script() -> Path | None:
    """The `ch` beside the interpreter running us, or None if none was installed.

    Deliberately NOT resolved: a venv's bin/python is a symlink back to the base
    interpreter, so resolving it lands in the Homebrew Cellar and leaves the venv
    entirely — where no `ch` exists. The opposite of dispatch, which must resolve to
    find a tool's real path.
    """
    here = Path(sys.executable).parent
    for directory in (_outlives_upgrades(here), here):
        script = directory / "ch"
        if script.is_file():
            return script
    return None


def on_path() -> Path | None:
    """The `ch` that PATH reaches, whoever installed it."""
    import shutil

    found = shutil.which("ch")
    return Path(found) if found else None


def same_install(one: Path, other: Path) -> bool:
    """Whether two console scripts came from the same installation.

    By directory, not by file: `ch` and `clihub` are two files in one bin.
    """
    return one.resolve().parent == other.resolve().parent


def _outlives_upgrades(bin_dir: Path) -> Path:
    """The same directory named so that a Homebrew upgrade cannot invalidate it.

    Homebrew installs a formula under `Cellar/<formula>/<version>` and points
    `opt/<formula>` at whichever version is current, deleting the tree it
    replaced. A link into Cellar dangles one upgrade later; the opt path does
    not. Any other layout is returned unchanged.
    """
    parts = bin_dir.parts
    if "Cellar" not in parts:
        return bin_dir
    cellar = parts.index("Cellar")
    if len(parts) <= cellar + 2:
        return bin_dir
    return Path(*parts[:cellar], "opt", parts[cellar + 1], *parts[cellar + 3:])
