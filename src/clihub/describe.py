"""Descriptions, which come from the registry and nowhere else.

clihub never asks a tool what it is for. The only thing it probes for is `--help`,
and only to warn when a description you wrote looks copied from it.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from . import dispatch

_STOPWORDS = frozenset(
    "a an and are as at be by for from in is it its of on or that the this to use used "
    "using with you your".split()
)


@dataclass(frozen=True)
class NamespaceDescription:
    namespace: str
    description: str | None
    status: str | None = None


def entry_rows(paths, entries: list) -> tuple[list[NamespaceDescription], list[str]]:
    """What `list` and `find` render: each entry's name and its description.

    Runs nothing and cannot fail, so a malformed entry does not stop the listing.
    """
    rows = [
        NamespaceDescription(namespace=entry.name, description=entry.description)
        for entry in entries
    ]
    notices = []
    if any(row.description is None for row in rows):
        notices.append(
            "some commands have no description - write one with "
            "'ch registry edit <name> --describe \"...\"'"
        )
    return rows, notices


def tool_help_text(script: str, settings) -> str:
    """Best-effort help output. Tools disagree on how to ask, so try each form."""
    for form in settings.help_forms:
        try:
            completed = dispatch.capture(
                script, list(form), timeout=settings.describe_timeout_seconds
            )
        except Exception:
            continue
        # Help goes to stdout or stderr depending on the tool and whether it treats
        # the request as an error, so take both and judge by volume, not exit code.
        text = f"{completed.stdout or ''}\n{completed.stderr or ''}".strip()
        if len(text) >= 40:
            return text
    return ""


def _content_words(text: str) -> set:
    return {
        word
        for word in re.findall(r"[a-z][a-z0-9-]+", text.lower())
        if word not in _STOPWORDS
    }


def description_overlap(description: str, help_text: str) -> float:
    """Fraction of the description's content words that also appear in the help.

    Lexical, not semantic — a paraphrased verb list scores low and still reads badly.
    """
    words = _content_words(description)
    if not words or not help_text:
        return 0.0
    return len(words & _content_words(help_text)) / len(words)
