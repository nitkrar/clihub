"""Values that are structural, not tunable.

The sibling `defaults.toml` holds what you may change: timeouts, thresholds, wording.
This file holds what you may not, because changing it would make two parts of clihub
disagree rather than make clihub behave differently.

Kept here, next to the tunables, so there is one place to look for "what is clihub
configured with" — and kept in Python rather than in the INI so the distinction is
visible at a glance.
"""
from __future__ import annotations

# Words that always mean the builtin, never a registered tool. `tools add` refuses
# them, and `cli` guarantees each one has a function behind it at startup.
BUILTIN_NAMES = frozenset(
    {"list", "help", "find", "tools", "init", "doctor", "registry", "rg"}
)
