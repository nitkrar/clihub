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


def ask(question: str) -> str | None:
    """Put a question to stdin when it is a terminal, or `None` otherwise.

    One home for the rule, because every caller needs the same answers:
    a non-terminal caller is never asked, and an abandoned prompt is not an
    answer. The question goes to stderr -- stdout is for what the command was
    asked to produce.
    """
    if not sys.stdin.isatty():
        return None
    # What was printed so far is the context for the question. Piped stdout is
    # block-buffered, so without this the question arrives before it.
    sys.stdout.flush()
    sys.stderr.write(question)
    sys.stderr.flush()
    try:
        return input().strip()
    except (EOFError, KeyboardInterrupt):
        sys.stderr.write("\n")
        return None


def confirm(question: str) -> bool:
    """A yes/no where silence means no."""
    return (ask(f"{question} [y/N] ") or "").lower() in ("y", "yes")
