# Findings

What was measured, and the design decision each result produced.

**Method.** Three local models: `granite-4.0-h-tiny` (small), `lfm2.5-8b-a1b` (small,
tool-calling), `qwen3.6-35b-a3b` (large). A 19-tool registry and 15 task descriptions
with one correct tool each. Runs were repeated to separate a result from noise.

---

## 1. A description must say what a tool is for, not list its commands

A description copied from a tool's own help — `relay: send, rooms, peers, status` —
made granite report `rooms` and `peers` as tool names. Rewritten to state purpose,
the same model picked correctly every time.

> **granite, same tasks, same registry: 0/6 with command-list descriptions, 6/6 with
> purpose-stating ones.**

The largest single effect measured, and why `registry add` warns when a description's
words mostly appear in the tool's own help.

## 2. Drill-down costs a round trip and buys nothing

A two-level listing — namespaces first, then drill in — needed **22 tool calls against
15** for the same tasks, and 3× the wall clock on qwen, because most tasks took a
second call.

Accuracy did not improve to pay for it. Score differences were 1–2 points, inside
run-to-run variance: the same model scored 13 and 11 on the *identical* condition.
Only the call count is a result.

> **Decision: namespaces exist in the data model; `ch list` renders flat.** On the
> call count, not on accuracy.

## 3. Dotted names cost nothing

Naming tools `<namespace>.<tool>` rather than bare, flat rendering either way:

| | bare | dotted |
|---|---|---|
| granite-4.0-h-tiny | 13/15 | 13/15 |
| qwen3.6-35b-a3b | 15/15 | 15/15 |
| lfm2.5-8b-a1b | 11/15 | 8–9/15 |

Identical on the two stable models. lfm2.5 scored worse dotted at its configured
sampling and *better* dotted at temperature 0 — a 4-point swing in both directions,
so not a result either way.

> **Decision: name tools dotted from the start.** It costs nothing measurable, and
> grouping later becomes a rendering default rather than a rename.

## 4. A warning's presence matters; its wording does not

Five wordings of the copied-description warning, across three models. Any warning
roughly halved how much of a rewritten description was lifted from the tool's help.
Differences between wordings were smaller than run-to-run variance.

> **Decision: the text is a config key to be worded as you like, not tuned for
> effect.**

## 5. The overlap check has a material false-positive rate

The check from finding 1, measured against 19 hand-written purpose-stating
descriptions, none of which was a command list:

> **9 of 19 tripped the warning.** Three scored a flat 1.00.

One was "reformat python source files to a standard style" — every word of which
appears in that tool's help, because that is what the tool does. The measure is
lexical; what makes a bad description bad is *structural*, that it enumerates
subcommands. No threshold separates them when three false positives sit at 1.00.

> **Decision: `overlap_check` is an on/off switch, not a threshold to raise.**
> Default on, because finding 4 shows the warning changes behaviour when it fires.
