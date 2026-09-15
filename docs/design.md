# Personal umbrella CLI - design

Status: **implemented**
Name: **clihub**, binary **`ch`**

Goal: **one entry point that gives agents and the user uniform access to independent
personal tools, without the entry point knowing tool-specific semantics.**

---

## 1. Requirements

**Extensibility**
- R1. Adding a namespace requires no code change to clihub.
- R2. Adding a namespace requires no rebuild, compile, or packaging step.
- R3. A tool may be written in any language.
- R4. A tool keeps its own dependencies, runtime, and repo.
- R5. Tools remain independently executable; the umbrella is optional.
- R6. Removing the umbrella leaves every tool working.

**Consumers**
- R7. The primary consumer is an agent; the secondary consumer is the user directly.
- R8. Discovery output must be parseable by small models, not only frontier ones.
- R9. Discovery happens through `list`, `help`, and `find`.
- R10. The entry point must stay short to type.

**Behavior**
- R11. Exit codes propagate verbatim once a tool is dispatched.
- R12. Interactive tools keep working; tty is preserved.
- R13. Invocations are logged with namespace, verb, exit code, and duration.
- R14. Arguments are redacted by design; do not log plaintext secrets.
- R15. A failed log write never prevents dispatch.

**Environment**
- R16. The system must work across machines with different tools installed.
- R17. Use the CLI whenever the consumer has shell access. Add MCP only when the
  consumer does not.

---

## 2. Constraints

- C1. clihub is a router, not a tool framework.
- C2. The dispatch path resolves one registered entry and forwards the remaining argv
  unchanged. A stored command prefix may be prepended, but the user's tail is never
  rewritten.
- C3. clihub's only global flags are `--help` and `--version`, both of which answer
  about clihub itself. No flag of clihub's may change how a tool is dispatched.
- C4. clihub never parses a tool's arguments.
- C5. On dispatch, the child inherits stdin, stdout, and stderr. Builtins may capture a
  tool's output only for management work such as probing `--help`.
- C6. clihub never orchestrates dependencies between tools.
- C7. clihub never reads, writes, validates, or injects a tool's configuration or child
  environment by design.
- C8. clihub does not manage tool secrets or persistent state.
- C9. Supervisors own their own lifecycle, daemons, and dependencies.
- C10. Heavy dependencies belong in tools, not in the router.
- C11. No heavy dependency on the dispatch path. A dependency reached only by a
  command invoked deliberately is judged on its weight there; one every `ch <tool>`
  would pay for is not.
- C12. clihub preserves CLI-observable behavior: stdout, stderr, exit code, tty, and
  interactivity. It is not required to be literally invisible in the process tree.

---

## 3. Names, model, and registry

### 3.1 Naming rules

- N1. A namespace is structural, never data-derived.
- N2. Names must be lowercase, guessable, and self-describing.
- N3. A namespace and a tool name match `^[a-z0-9][a-z0-9_-]*$`: lowercase, digits,
  `-` and `_`. Neither may contain a dot — the dot separates namespace from tool and
  is the one character that is parsed.
- N4. Reserved top-level words are `list`, `help`, `find`, `init`, `doctor`,
  `registry`, `rg`, and `tools`. `rg` is a short alias for `registry` — the one
  place two spellings are deliberate, because it is a builtin rather than a
  registered entry, where aliasing is rejected (N5).
- N4a. **User-facing text says "command".** Everything a user types is one — `git`,
  `brew`, `ch llm.llama`. `namespace`, `tool` and `entry` describe how the registry is
  shaped and belong in this document and in the code, not in an error someone reads.
  `ch llm nosuch` reports `unknown command: llm.nosuch`, naming the spelling that
  would have worked rather than the level that failed.
- N5. One tool may be registered under more than one namespace when more than one
  question leads to it. The cost is drift between the copies, so `doctor`
  reports entries sharing a command prefix rather than forbidding them.

### 3.2 Dispatch model

Definitions:
- A **tool** is a name mapped to a stored command prefix.
- A **namespace** groups tools and may also define its own `command` for
  fall-through dispatch.
- Namespaces group by the question an agent or user has, not by which binary implements
  the answer.

Accepted forms:

```text
ch <namespace> <tool> [args...]
ch <namespace>.<tool> [args...]
ch <tool> [args...]
ch <namespace>
```

Resolution rules:

```text
ch <command> [args...]
  the first word is the whole command name; everything after it is an argument
  <command> is registered      -> dispatch it, argv tail untouched
  <command> is a group         -> unknown command, suggesting the dotted spelling
  otherwise                    -> unknown command

ch <ns>
  if <ns> has its own command   -> dispatch it with no arguments
  else                          -> list what the namespace holds
```

**One spelling per command.** The second word is always an argument, never a tool
name, so a line's meaning never depends on what else is registered.

Additional rules:
- At most one dot is parsed.
- A bare tool is just a namespace with a `command` and no named tools.
- A tool may appear in more than one namespace.
- Discoverable tools are curated. A namespace with a `command` may expose more surface
  than `list` shows.
- There is no catch-all namespace and no enforced budget for top-level names. Group only
  when the grouping is meaningful.
- Existing tool surfaces are not requirements. If a tool is awkward to express in this
  model, change the tool or do not expose that command.

### 3.3 Registry

The runtime registry is a single TOML file at `~/.clihub/registry.toml`.

A table is a group; a table inside it is a command in that group:

```toml
[llm]
description = "local model servers and related tooling"
command     = "/Users/me/bin/llmctl"

  [llm.llama]
  description = "run and control local language model servers"
  command     = "/Users/me/bin/llmctl llama"

[jq]
description = "filter and reshape JSON text"
command     = "/usr/bin/jq"
```

Registry rules:
- A table is a group; a table inside it is a command in that group. The nesting is
  the two-level model, so there is no reserved-key encoding: `command` and
  `description` are ordinary keys in the right table.
- TOML, because the model has two levels and the format nests. `tomllib` reads,
  keeping the dispatch path stdlib; `tomlkit` writes, so hand-written comments
  survive a rewrite.
- `command` is a **shell command line**, run as `sh -ec`. A list of strings is also
  accepted and is joined with `shlex.join` into one, which is how a path containing
  spaces arrives without quoting. clihub only ever writes the string form.
- `registry add` stores the command prefix in the form it was written, using
  `shlex.join([target, *fixed_args])`. Each form expresses something different, so
  each is kept: a bare `jq` means "whatever PATH means here" and is resolved at
  dispatch, which is what gets you the venv's `black` inside a project; an absolute
  path means *that file* and is stored exactly; a relative path is resolved to
  absolute at add time, because you will not be standing in that directory later,
  and `add` says so when it rewrites one. `shutil.which` still runs on a bare name,
  as the typo check rather than a rewrite.
- Command prefixes are parsed on access with `shlex.split(..., comments=False)`.
  A malformed entry must not prevent other entries from loading or listing.
- Registry mutations use locking plus temp-file-and-rename writes.
- The registry is machine-local state. Setup scripts may populate it per machine, but
  the tracked repository is not the runtime registry.

### 3.4 Composition

Aggregates such as "bring the stack up" are ordinary tools or scripts that call other
namespaces.

Rules:
- Composition is a tool, not an umbrella feature.
- Composition scripts register like any other tool.
- Wrappers should call `ch`, not hardcoded underlying binaries, so registry resolution
  stays central.

---

## 4. Runtime behavior

### 4.1 Process model

- Python, stdlib only.
- Dispatch uses `subprocess.Popen(...).wait()`, not `exec`, so clihub can record
  duration and write the invocation log after the child exits.
- The dispatch path does not use `subprocess.run()`. The parent must not kill a child
  that chooses to handle `SIGINT` itself.
- The child inherits stdin, stdout, and stderr unchanged.
- Dispatch is `["/bin/sh", "-ec", command + ' "$@"', f"ch {name}", *tail]`:
  - **`-c`** — a stored command is a shell command line, so pipes, redirects,
    globs and `VAR=x cmd` mean what they say.
  - **`-e`** — a multi-line command stops at the first failure.
  - **`"$@"`** — the tail binds to positional parameters, never spliced into the
    string, so arguments are not re-parsed. A pipe in the registry is syntax; a
    pipe in an argument is data. Appended only when the command does not place it
    *and* is a single simple command, since anywhere else the end of the text is
    not an argument position. A command that does not say where arguments go is
    refused a tail rather than silently losing it.
  - **`$0`** — the clihub name, so the shell's errors read `ch llm.llama: …`.
  - `/bin/sh`, not `$SHELL`. PATH is exported and inherited either way; a
    non-interactive shell reads no rc file, so aliases are unavailable to both.
- Consequences, accepted: a missing binary returns the shell's 127 rather than 126,
  and a syntax error returns 2; shell builtins (`echo`, `test`, `printf`, `pwd`)
  resolve before PATH; and metacharacters in an argument must be quoted as they
  would be in a shell.
- While waiting, clihub loops on `KeyboardInterrupt` and keeps waiting. `SIGINT` reaches
  both parent and child; the child decides how to handle it.
- Negative return codes are mapped to `128 + signal`.
- Log writes are best effort. Failures are swallowed.

### 4.2 Runtime data

One directory, with the disposable parts in subdirectories:

```text
~/.clihub/registry.toml           the registry
~/.clihub/config.toml             your overrides; written by init, all commented
~/.clihub/completion.<shell>      generated
~/.clihub/log/invocations.jsonl   rotated invocation log — safe to delete
```

`CLIHUB_HOME` moves the root; it is the only path variable clihub reads.

One dotted directory in `$HOME`, as `.ssh`, `.aws` and `.kube` use, rather than the
XDG split across four trees. The disposable parts stay separable as subdirectories.

Rules:
- Every write to `registry.toml` takes a lock and lands by rename, so a reader
  never sees a half-written file.

### 4.3 Logging

Each invocation record stores:
- `ts`
- `ns`
- `verb`
- `argc`
- `rc`
- `ms`

Logging rules:
- `verb` is the first token of the user's tail, or `null` if there is no tail.
- Arguments are never logged.
- The journal format is JSONL.
- The journal is rotated.
- `ch tools stats` reads it back: runs, failures, latency and total time per
  command. Nothing else in clihub reads it.

### 4.4 Code boundaries

- `registry/` is the only package that reads or writes `registry.toml`. Callers
  import `registry`, never its parts: `model` is the shapes, `names` is what a
  legal name is, `read` parses and looks up, `write` mutates, `checks` is what
  doctor asks.
- `dispatch.py` is the only module that runs a registered command. `registry/checks.py`
  also spawns a shell, but only `sh -n`, which parses and exits without executing.
- `render.py` is the only module that writes clihub's own structured output.
- `describe.py` renders registry descriptions and owns the overlap check.
- `registry/` also owns the rule that a builtin shadows a registered name;
  `dispatch.py` only sends the notice.
- `config/` is the one place a setting is defined: `defaults.toml` for what may be
  changed, `constants.py` for what may not. `cli.py` raises at import if a builtin
  name has no function behind it, so the two cannot drift.
- Commands import core modules; core modules do not import command modules.

---

## 5. Tool contract

A tool exposed through clihub must:

1. Return meaningful exit codes. On the clihub side, `2` remains the builtin usage
   error code.
2. Keep stdout for data and stderr for diagnostics.
3. Support `--json` wherever it emits structured data.
4. Resolve its own config repo-relative, not cwd-relative.
5. Resolve symlinks when locating itself, and not rely on `argv[0]`.

clihub does not ask a tool to describe itself. Descriptions are written in the
registry.

---

## 6. Discovery

`list` renders **flat**: one row per tool, no grouping. Namespaces are a data model,
not a rendering level — a grouped listing measured worse for tool selection than a
flat one on every model tested. Tool names are dotted regardless, which costs nothing
measured, so grouping could later become a rendering option without renaming anything.
See `findings.md` §2 and §3.

Discovery commands:
- `ch list` prints a flat list of discoverable names with descriptions when available.
- `ch list --json` returns the same surface in machine-readable form.
- `ch help <name>` runs the target tool's `--help` through the normal dispatch path. It
  has no JSON mode.
- `ch find <words>` is in v1 and is the preferred discovery entry point for agents.
  Named for the intent rather than the mechanism: you know what you want done, not
  what it is called. It cannot collide with `/usr/bin/find`, which `ch` never reaches.

`find` uses three dependency-free layers:
- exact substring matching for prefix and infix hits;
- BM25-style token ranking over names and descriptions;
- typo matching on names only, for single-word queries.

Description handling:
- A description comes from the registry and nowhere else. `registry add --describe`
  and `registry edit --describe` write it; nothing else produces one.
- `list` and `find` read it directly, so they run no tool and cannot fail. That is
  why a malformed entry no longer takes the whole listing down with it.
- `timeout_seconds` bounds the `--help` probe behind the overlap warning.
- `find` returns zero rows when nothing matches. It does not fall back to printing the
  full list.

### 6.1 Shell completion

- v1 completion covers builtins plus every registered name, including dotted
  `<namespace>.<tool>` names, since those are invocable spellings in their own
  right. Namespaces are offered too, so the two-word form completes as well.
- clihub does not complete a tool's internal verbs.
- `ch tools completion [<shell>]` **installs**: it writes
  `~/.clihub/completion.<shell>` and appends one line to the shell's rc
  that sources it. `--print` emits the script instead; `--remove` deletes the file
  and takes the rc line with it, since a `source` pointing at a deleted file errors
  on every new shell.
- The rc line is matched by a trailing `# clihub completions` marker, so reinstalling
  never duplicates it and a moved config directory still updates cleanly.
- The script is a file clihub owns and the rc gets one `source` line, so
  regenerating completions never touches the rc again. Sourcing a file costs
  +2.5 ms against `eval "$(ch ...)"` at +63.9 ms, which starts Python per shell.
- The generated script runs `compinit` itself if `compdef` is undefined, since a
  plain rc never calls it and the registration would silently fail.
- `ch init` installs completion only when asked — `--completions`, or
  `completions_auto_enabled` in config, which is **off by default**. Editing a shell
  config is not something init should do on its own initiative.
- `completions_enabled` is read by the generated script itself, with a grep of the
  config, so turning completion off takes effect on the next tab without
  reinstalling. Candidates are baked in rather than queried, because a `ch`
  invocation is 65 ms and that is too long to sit under a tab press — the cost is
  that the list goes stale when a tool is added, until completion is reinstalled.
- A later optional contract may add `--complete <partial>` passthrough for tools.

---

## 7. Self-management

Self-management is builtin, not registered, so it still works when the registry is empty
or broken.

Rules:
- `ch init` creates `~/.clihub` and its `log/` subdirectory, writes `config.toml`
  with every key commented out, and symlinks `ch` into `--link-dir`
  (default `~/.local/bin`). It is the one command run by full path, because its
  purpose is that `ch` is not yet on PATH. Idempotent; it refuses to replace a
  foreign `ch` without `--force`.
- `--` marks the start of the stored command prefix. argparse handles the separator
  natively, which is why `registry add` no longer walks its tokens by hand — and it
  is what sets `requires-python`. Below 3.12 the same command fails with
  `unrecognized arguments: -- /bin/echo`; the behaviour arrived in 3.12, not 3.11
  as this document claimed until CI ran it. `ch list` and dispatch work on older
  versions, so the floor is invisible until you register something — which is why
  the wrong floor shipped. Lowering it means hand-rolling the separator again.
- Commands are grouped by what they touch. `registry` edits `registry.toml`;
  `tools` holds setup that is not a registry edit, currently only `completion`.
  `doctor` is top level because it is what you reach for when something is
  wrong, and where clihub's own error messages send you.
- `registry` rather than `tools` for the edit verbs: `registry add llm` creates a
  namespace's own `command`, not only a tool, so `tools` was the narrower word.
- `registry add` stores the command in the form it was written with `shlex.join`,
  validates the name, rejects reserved-word collisions, and warns when a bare name
  resolves through something transient (`$VIRTUAL_ENV`, `$CONDA_PREFIX`, a relative
  PATH entry).
- It refuses only what can never come right: a line the shell cannot parse, decided
  by the same `registry.syntax_problem` doctor uses. A target that is merely absent
  is reported and still recorded — a bare name resolves at dispatch, and a file may
  be installed later — and `doctor` counts that as broken.
- `registry add --describe` is how a description gets written; there is no other source.
- `registry remove <ns>.<tool>` removes only that tool.
- `registry remove <ns>` removes the namespace's own `command`; the namespace remains if named
  tools still exist.
- `registry show <name>` prints what the registry holds, in the file's own TOML
  syntax rather than a prettier summary: what you read is what you would edit.
  A bare name shows its whole group, a dotted name one command. An unknown name
  is 127. An entry that is present but cannot run still prints, with the reason
  on stderr and exit 1.
- `registry edit <name>` changes one part of an entry and leaves the rest. It is
  the half `add --force` is not: force replaces an entry whole, description
  included. Renaming is allowed for groups and commands alike — the operation
  is the same, and renaming a group renames every command under it at once,
  since the group name is half of each one. Never across groups: that moves an
  entry rather than renaming it, and is a remove plus an add.
- `registry export [<path>]` copies `registry.toml` out byte for byte — a copy,
  not a re-render, because an export that quietly differs from its source is
  worse than none. A directory means "put
  it in here", anything else is the filename, nothing at all means the current
  directory. An existing file is never replaced without `--force`.
- `registry validate` checks the registry: malformed command values, command lines
  the shell cannot parse, missing or non-executable targets, unquoted spaces in
  paths, builtin collisions, empty namespaces, duplicate command prefixes.
- The parse check runs `sh -n` on the *assembled* body, not the stored text, because
  the failure it catches is created by assembly: `"$@"` appended after `done` is a
  syntax error the stored command does not have alone. Only commands holding a
  metacharacter or a leading keyword are asked about; anything else is a plain word
  list, which always parses.
- `doctor` calls that same check and adds clihub's own setup: is `ch` on PATH, is it
  this install, is the config parseable, has completion fallen behind. It reads and
  stats, and never runs a tool: `sh -n` parses and exits without executing.
- Issues carry a severity. **Only `broken` makes the exit code non-zero** — a
  registry that will not parse, an entry that cannot run. `advisory` exits 0, since
  a stale completion list should not fail a script.
- Resolution order is fixed: builtin first, then registry. A registry entry can never
  shadow a builtin.

---

## 8. Command surface and exit codes

Accepted command surface:

```text
ch <ns> <tool> [args...]
ch <ns>.<tool> [args...]
ch <tool> [args...]
ch <ns>
ch --version
ch list [<ns>] [--json]
ch find <terms> [--json]
ch help <name>
ch init [--link-dir DIR] [--no-link] [--force] [--completions|--no-completions]
ch registry add <name> [--describe "..."] [--force] -- <path> [fixed-args...]
ch registry remove <name>
ch registry show <name>
ch registry edit <name> [--name NEW] [--describe TEXT] [-- <path> ...]
ch registry export [<path>] [--force]
ch registry import <path> [--force]
ch registry validate
ch doctor
ch tools completion [<shell>] [--print] [--remove]
ch tools stats [--json]
```

Notes:
- `<name>` is `<tool>` or `<namespace>.<tool>`.
- `ch` itself has no global flags. `--json` belongs to builtins that do not dispatch.

Exit codes:

| code | meaning |
|---|---|
| child's own | dispatch propagated verbatim |
| 0 | builtin succeeded |
| 1 | builtin failed; or, under bash as `sh`, a path target it could not run |
| 2 | builtin usage error, or a syntax error in a stored command |
| 126 | the entry cannot take your arguments: empty, not a string or list, or it does not say where they go |
| 127 | unknown name, or a **bare** target the shell could not find |
| 130 | interrupted |

Notes:
- Everything from 1 upward once dispatch has started is the shell's, passed on
  unchanged. clihub never invents a code for a command that ran.
- **The code for a path target depends on which `sh` is installed.** Under bash
  as `sh`, `-e` collapses a missing path and a non-executable one to 1; under dash
  they are the conventional 127 and 126. Bare names keep 127 either way. CI runs
  both, and the test accepts both, because clihub passes the shell's answer through
  rather than having an answer of its own. The flag is kept because stopping a multi-line
  command at its first failure matters more than the distinction, and `ch doctor`
  reports both conditions by name before they are ever run.
- 126 therefore does not mean "found but not executable". It means the entry could
  not be turned into a command line at all, which is decided before any shell runs.
- Once a child runs, numeric collisions between tool exit codes and clihub exit codes
  are unavoidable. stderr must distinguish the source of failure, which is what
  setting `$0` to the clihub name is for.

---

## 9. Rejected alternatives

- In-process plugins: would force one runtime and dependency tree.
- RPC: not needed while tools already have working CLIs.
- Monorepo with one shared venv: would violate tool independence.
- A runtime manifest as the registry: machines differ; the runtime registry is
  per-machine state.
- Global PATH discovery: creates silent shadowing and pollutes PATH.
- Vector or embedding search: the corpus is small, and the dependency would land on
  the dispatch path (C11).
- Dependency graphs between tools: a command may be several lines run in order, but
  clihub never derives an order or a graph. Composition belongs in a script.
- Marking commands as agent-safe or human-only: blocking is the tool's own affair,
  and clihub does not parse a tool's arguments (C4).
- Catch-all namespaces such as `misc`: they add a required extra discovery hop without a
  meaningful grouping.
