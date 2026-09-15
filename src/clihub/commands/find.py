"""`ch find <words>` — reach a command without already knowing its name.

Three layers, each covering what the others cannot:

    substring   `sql` finds `sqlite3`; BM25 tokenises, so `sql` is not a token
    BM25        ranks multi-word queries against whole descriptions
    difflib     `dokcer` finds `docker`. Names only — against descriptions it
                matches a short query to a long sentence on shared letters

Ordered tiers rather than one blended score: summing a BM25 score, a substring hit
and a similarity ratio needs weights nobody can defend, and tiers are explainable —
a name you almost typed, then relevance, then possible misspellings.
"""
from __future__ import annotations

import argparse
import difflib
import math
import re
import sys

from .. import describe, dispatch, registry
from ..config import load as load_settings
from ..paths import Paths
from ..render import render_json, render_rows

# What `ch --help` prints for this command. Separate from __doc__, which is
# about the module: different readers, different words.
SUMMARY = "a command by what it does, not its name"
ARGS = "<what you want to do>"

# The fallback when nobody passes one: `rank` is pure and callable without a config,
# and this is the value defaults.toml ships. Both are stated in one place --
# defaults.toml is authoritative and a test holds them equal.
DEFAULT_TYPO_CUTOFF = 0.7

_K1 = 1.5      # term-frequency saturation
_B = 0.75      # length normalisation
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def run(argv: list[str], paths: Paths) -> int:
    parser = argparse.ArgumentParser(prog="ch find")
    parser.add_argument("term", nargs="+")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv[2:])
    term = " ".join(args.term)

    loaded = registry.load(paths)
    for name in registry.shadowed_names(loaded):
        dispatch.write_shadowed_builtin_notice(name)
    entries = registry.visible_entries(loaded)

    rows, notices = describe.entry_rows(paths, entries)
    for notice in notices:
        sys.stderr.write(f"{notice}\n")

    matches = rank(
        term,
        [(row.namespace, row.description or row.status or "") for row in rows],
        typo_cutoff=load_settings(paths.config_file).find_typo_cutoff,
    )
    if not matches:
        sys.stderr.write("nothing matched\n")

    if args.json:
        render_json([{"name": name, "description": text} for name, text in matches])
        return 0
    render_rows(matches)
    return 0


def rank(term: str, rows: list[tuple[str, str]],
         typo_cutoff: float = DEFAULT_TYPO_CUTOFF) -> list[tuple[str, str]]:
    """Ordered matches. Pure, so it is testable without a registry."""
    lowered = term.strip().lower()
    if not lowered:
        return []
    query = _tokens(lowered)
    scores = _bm25(query, rows)

    names = [name for name, _ in rows]
    typos = set()
    if len(query) <= 1:
        # Only a single word can be a typo of a name. A phrase that happens to
        # resemble one is a coincidence, not a misspelling.
        typos = set(difflib.get_close_matches(lowered, names, n=len(names), cutoff=typo_cutoff))

    tiered: list[tuple[int, float, str, tuple[str, str]]] = []
    for name, text in rows:
        if lowered in name.lower():
            tier = 0
        elif scores.get(name, 0.0) > 0:
            tier = 1
        elif lowered in text.lower():
            tier = 1        # substring of the description, but no token matched
        elif name in typos:
            tier = 2
        else:
            continue
        tiered.append((tier, -scores.get(name, 0.0), name.casefold(), (name, text)))
    tiered.sort()
    return [row for _, _, _, row in tiered]


def _tokens(text: str) -> list[str]:
    return [
        token for token in _TOKEN_RE.findall(text.lower())
        if token not in describe._STOPWORDS
    ]


def _bm25(query: list[str], rows: list[tuple[str, str]]) -> dict[str, float]:
    """Okapi BM25 over name-plus-description. Hand-rolled: the corpus is ~20 rows.

    IDF is the standard +1 form, which keeps a term appearing in every document at a
    small positive weight instead of going negative and pushing good matches below
    unrelated ones.
    """
    if not query:
        return {}
    documents = {name: _tokens(f"{name} {text}") for name, text in rows}
    if not documents:
        return {}
    total = len(documents)
    average = sum(len(tokens) for tokens in documents.values()) / total

    frequencies = {
        token: sum(1 for tokens in documents.values() if token in tokens)
        for token in set(query)
    }
    scores: dict[str, float] = {}
    for name, tokens in documents.items():
        score = 0.0
        length = len(tokens) or 1
        for token in query:
            occurrences = tokens.count(token)
            if not occurrences:
                continue
            idf = math.log((total - frequencies[token] + 0.5) / (frequencies[token] + 0.5) + 1)
            score += idf * (occurrences * (_K1 + 1)) / (
                occurrences + _K1 * (1 - _B + _B * length / average)
            )
        if score > 0:
            scores[name] = score
    return scores
