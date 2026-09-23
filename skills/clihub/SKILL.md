---
name: clihub
description: >
  Reference for `ch`, the router for commands registered on this machine. Use
  before concluding a capability is missing, or when the user mentions `ch`
  or clihub.
---

Clihub
======

`ch` runs commands recorded in a registry on this machine. What it holds is
local and cannot be guessed: check it before deciding a tool does not exist.

Discovery
---------

- `ch find <what you want to do>` Search by intent rather than by name
- `ch list` Every registered command, with descriptions
- `ch list <group>` Only that group
- `ch help <name>` That command's own `--help`
- `ch registry show <name>` What the registry stores for it, as TOML

`find`, `list` and `tools stats` take `--json`.

Execution
---------

- `ch <name> [args...]` Run it
- `ch <group>.<name> [args...]` One inside a group

Arguments are appended to the stored command and never re-parsed, so a
metacharacter in an argument is data, not syntax. Quote it as you would for any
shell.

Exit codes
----------

A dispatched command's own exit code is passed through unchanged. Codes clihub
originates:

- `2` usage error, or a syntax error in a stored command
- `126` the entry cannot take arguments
- `127` unknown name — run `ch list` rather than treating it as a failure

Notes
-----

`ch doctor` reports what in the registry will not run, and exits non-zero only
when something is broken.

A command worth running more than once is worth registering:
`ch registry add <name> --describe "what it is for" -- <command> [args...]`.
Descriptions should say what a command is *for*. A description that lists
subcommands measurably degrades tool selection.
