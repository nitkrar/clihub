from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

# The only copy. pyproject reads this attribute rather than restating it, so a
# release cannot ship a number that disagrees with what `ch --version` prints.
__version__ = "1.0.1"

# Vendored tomlkit, imported straight from the wheel. See _vendor/README.md.
_sys.path.insert(0, str(_Path(__file__).parent / "_vendor" /
                        "tomlkit-0.15.1-py3-none-any.whl"))

__all__ = ["main", "__version__"]

from .cli import main
