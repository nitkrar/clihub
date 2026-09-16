# clihub

One entry point for the tools you already have.

```console
$ ch find reshape json
jq    filter and reshape JSON text

$ echo '{"name":"clihub"}' | ch jq -r .name
clihub
```

`ch` does not wrap your tools or reimplement them. It keeps a registry of names you
chose and what each one runs, so a tool you set up months ago stays reachable by
description instead of by memory.

## Install

```sh
brew install nitkrar/tap/clihub    # or: pipx install clihub-cli
ch init
```

The distribution is `clihub-cli`; the commands it installs are `ch` and
`clihub`. Either installer puts both on PATH and keeps them there across
upgrades, so `ch init` does not touch PATH — it writes `config.toml` with every
setting present and commented out, which is where the tunables are documented.

Installing into a virtualenv instead leaves `ch` in that virtualenv's `bin/`,
where it only resolves while the virtualenv is active:

```sh
pip install -e .   # creates `ch`, inside that virtualenv only
ch init            # symlinks it into ~/.local/bin as well
```

That is the case `ch init`'s symlink is for. It tells you if `~/.local/bin` is
not on your PATH.

Add `--completions` to install shell completion at the same time, or run
`ch tools completion` later.

Python 3.12+, no dependencies. It also runs straight from a checkout:

```sh
PYTHONPATH=src python3 -m clihub list
```

## Commands

```sh
ch <name> [args...]         # run a registered command
ch <group>.<name> [args...] # one inside a group

ch list [<group>]           # everything registered
ch find <what you want>     # by description, not by name
ch help <name>              # that tool's own --help
ch doctor                   # is any of this going to work
ch --version
```

Editing the registry:

```sh
ch registry add jq --describe "filter and reshape JSON text" -- /usr/bin/jq
ch rg add llm.llama -- ~/bin/llmctl llama      # a tool inside a group
ch rg edit jq --describe "..."                 # change one field
ch rg remove jq
ch rg {show,validate,export,import}
```

Everything after `--` is the command and its fixed arguments. Anything you type at
run time is appended to that, untouched.

## The registry

`~/.clihub/registry.toml`. A table is a group; a table inside it is a command in
that group. Hand-editing is expected — comments you write survive clihub rewriting
the file.

```toml
[jq]
description = "filter and reshape JSON text"
command = "/usr/bin/jq"

[llm]
description = "local model servers"

  [llm.llama]
  description = "start, stop and inspect the local model servers"
  command = "/Users/me/bin/llmctl llama"
```

### How a target is stored

Three ways to name one, each meaning something different:

| you write | stored as | resolved |
| --- | --- | --- |
| `jq` | `jq`, as written | at run time, by PATH — picks up a project's venv |
| `/usr/bin/jq` | as written | that exact file |
| `./bin/jq` | absolutised when added | — you will not be in that directory later |

A relative path is the only one rewritten, and `add` says so when it does.

`add` refuses only what can never come right — a command the shell cannot parse.
A target that is simply not here is reported and still recorded: a bare name
resolves at dispatch, and a file can be installed after the fact. `ch doctor`
counts that as broken and exits non-zero, so it is not lost.

Fixed arguments containing spaces are quoted for you.

### Where your arguments go

`command` is a shell command line, run as `sh -ec`, so pipes, `&&`, redirects and
`VAR=x cmd` mean what they say. Your arguments bind to `"$@"` and are never
re-parsed — a pipe in the registry is syntax, a pipe in an argument is data.

Multi-line commands work, and are written by hand rather than through `add`
(argv cannot carry a script). Two rules:

1. **Contains `$@` anywhere → used exactly as written.** This is how you put
   arguments in the middle, or into a loop, or into one stage of a pipeline.
2. **Otherwise `"$@"` is appended — but only to a single simple command.** For
   anything else (a pipeline, `&&`, a loop, several lines, a trailing comment,
   a here-doc) the end of the text is not an argument position, so nothing is
   appended. Such a command runs fine with no arguments; give it some and it
   stops with exit 126 rather than dropping them. `ch doctor` lists it as
   *takes no arguments* beforehand.

```toml
[stack.up]
description = "bring the local model stack up"
command = """
export LLM_PROFILE=dev
ch llm.vm start
ch llm.llama serve --port 8080 "$@"
"""
```

A trailing `\` inside a `"""` block is TOML's own line continuation: it joins the
lines before clihub sees them, so splitting one long command across lines for
readability is still a single-line command and none of the above applies.

## Configuration

`~/.clihub/config.toml`, written by `ch init` with every key present, commented
out, with its default and what it does. Uncomment what you want. Anything not in
that file is structural, not tunable.

A config that will not parse is ignored rather than fatal — dispatch carries on
with the shipped defaults, and `ch doctor` tells you the whole file is inert.

`CLIHUB_HOME` moves the directory; it is the only path variable clihub reads.

## For agents

An agent has been trained on `git` and `docker`. It has not been trained on the
tools you wrote, and cannot guess they exist. That is what the registry is for, and
the integration is one paragraph — put this in your `AGENTS.md` or `CLAUDE.md`:

> Local tools are registered with `ch`. Run `ch list --json` to see what is
> available, or `ch find <what you want to do> --json` to search by intent. Run one
> with `ch <name> [args...]`; arguments are passed through untouched. Check this
> before concluding a capability is missing.

`ch list`, `ch find` and `ch tools stats` take `--json`; `ch rg show <name>` emits
TOML. There is no MCP server and no per-agent install step: an agent already has a
shell, and `ch` is a command.

## When something is wrong

`ch doctor` checks the registry (parsing, commands, syntax, quoting, targets,
permissions, shadowing, duplicates, portability, names) and clihub's own setup
(`ch` on PATH, config readable, completion current).

It never runs your tools. The one command it spawns is `sh -n`, which parses a
stored command and exits without executing it — that is the `syntax` check, and
it runs on the line clihub would actually run, `"$@"` included.

It exits non-zero only when something is *broken* — an entry that cannot run, a
registry that will not parse, a config discarded whole. Advisories exit 0.

| exit | meaning |
| --- | --- |
| child's own | dispatch propagated it verbatim |
| 1 | a builtin failed, or (under bash as `sh`) a path target the shell could not run |
| 2 | usage error, or a syntax error in a stored command |
| 126 | the entry cannot take your arguments — empty, not text, or it does not say where they go |
| 127 | unknown name, or a **bare** target the shell could not find |
| 130 | interrupted |

Codes above 0 come from the shell once dispatch starts, and the two common `sh`
implementations differ for a target written as a path. Under bash as `sh` (macOS)
`-e` collapses both "missing" and "not executable" to 1; under dash (most Linux)
they stay 127 and 126. Bare names give 127 either way. clihub passes through
whatever it gets, and `ch doctor` names both conditions before you ever run them.

## Development

```sh
python3 -m unittest discover -s tests -t .   # no dependencies needed
python3 -m pytest tests/                     # if you have it
```

`AGENTS.md` is how to work in this repo. `docs/design.md` is the specification,
`docs/findings.md` what testing showed about descriptions and discovery,
`docs/backlog.md` the open questions.

## License

MIT.
