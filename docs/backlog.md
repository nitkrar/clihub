# Backlog

Open questions, and things to research before they become questions.

## 1. Should the overlap check measure shape rather than vocabulary?

`registry add` warns when a description's words mostly appear in the tool's own help. It
fires on 9 of 19 good descriptions (`findings.md` §5), because a purpose-stating
description necessarily uses the tool's domain words. What makes a bad description bad
is that it *enumerates subcommands* — structural, not lexical — and no threshold
separates the two when three false positives score a flat 1.00.

Today the answer is a switch: `overlap_check` on or off, with `overlap_warn` and
`overlap_warning` as knobs beside it.

*Research:* whether a shape-based test — counting short verb-like lines, comma-run
density, a leading `<name>:` — separates the two classes on the same 19 descriptions.
If it does, it replaces the metric and the knobs stay. If it doesn't, the switch is
the permanent answer and this closes.

## 2. Auto-discovery of tools

Deferred since the first draft, and not on principle — discovery is fine, naive
discovery is not. Everything on PATH is thousands of binaries, almost none of which
anyone would register, so a pass that proposes all of them has moved the work rather
than done it. What is missing is the selection: knowing which of those are worth a row.

*Research:* what would actually make the choice. Recency of use, being outside the
system prefixes, having a `--help` that parses, already appearing in shell history —
and whether any of those, alone or together, picks out the handful a person would
have registered by hand.
