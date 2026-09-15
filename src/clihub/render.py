from __future__ import annotations

import json
import sys


def render_rows(rows: list[tuple[str, str]]) -> None:
    if not rows:
        return
    width = max(len(left) for left, _ in rows)
    for left, right in rows:
        if right:
            sys.stdout.write(f"{left.ljust(width)}  {right}\n")
        else:
            sys.stdout.write(f"{left}\n")


def render_json(payload: object) -> None:
    json.dump(payload, sys.stdout, separators=(",", ":"))
    sys.stdout.write("\n")


def render_text(text: str) -> None:
    sys.stdout.write(text)
    if not text.endswith("\n"):
        sys.stdout.write("\n")
