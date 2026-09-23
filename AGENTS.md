# Working on clihub

clihub routes `ch <name> [args...]` to a command recorded in `~/.clihub/registry.toml`.
It never parses a tool's arguments and never knows what a tool does.

Read `docs/design.md` before changing behaviour. It is the specification; this file is
how to work in the repo.

## Setup

```sh
pip install -e .
python3 -m unittest discover -s tests -t .   # no dependencies required
python3 -m pytest tests/                     # nicer output, if installed
```

There is no lint or type-check step. Do not add one without asking.

## Rules

**Never let a test touch the real `$HOME` or `~/.clihub`.** `tests/fixture.py` sets
`HOME`, `CLIHUB_HOME` and `PATH` to temporary directories and clears `XDG_*` and
`ZDOTDIR`. Use `ClihubFixture`; do not build environments by hand. A test that writes
to the real home is not a failing test, it is damage.

**The same goes for anything you run to check your work.** Set `CLIHUB_HOME` inline on
every command — `CLIHUB_HOME=$(mktemp -d) ch rg add ...` — not exported once for a
shell. An exported variable that does not reach a subshell writes to the real registry.

**Keep the dispatch path light.** `ch <tool>` costs ~48ms, and ~22ms of that is Python
starting. Every import reachable from `cli.py` → `dispatch.py` is paid by every
command. Import anything heavier inside the function that needs it — `shutil`,
`tomlkit` and `subprocess` are all deferred this way. Measure with
`python3 -X importtime -m clihub --version`; read the *marginal* column, not the
cumulative one.

**One rule, one function.** Where `add` and `doctor` both judge something, they call
the same function — `registry.is_shell_construct`, `registry.syntax_problem`,
`registry.issues_for`. Two copies of a rule drift, and the drift is silent.

**Ask the shell, do not model it.** Whether a command line parses is answered by
`sh -n`, not by matching keywords. Two attempts to guess which endings are safe to
append `"$@"` to were both wrong.

## Tests

Seven files by area, sharing one fixture. Put a test where its subject lives:

| file | subject |
| --- | --- |
| `test_dispatch.py` | running a command, exit codes, signals, PATH resolution |
| `test_registry.py` | add, edit, remove, show, export, import |
| `test_doctor.py` | doctor and `registry validate` findings |
| `test_discovery.py` | list, find, help, `--version` |
| `test_setup.py` | init, completion, config |
| `test_journal.py` | the invocation log and `tools stats` |
| `test_suite_integrity.py` | the suite's own failure modes |

**A test must fail when the behaviour breaks.** Before trusting a new test, break the
code it guards and confirm it goes red. Asserting "exit 0 and some output" does not
distinguish a builtin answering `--help` from one ignoring it and running — that exact
test shipped green for weeks.

**Do not assert on wording** unless the wording is the behaviour. Assert on exit codes,
on files written, on what actually ran.

## Committing

Subject line says what changed and why, in the imperative, no prefix tags. The body
explains what was wrong — that is where history belongs, not in comments.

A comment says **why** the code is the way it is, where that is not evident from
reading it. It does not narrate what the code used to be, restate what the code says,
or carry benchmark numbers.

## Releasing

The version lives in `src/clihub/__init__.py` and pyproject reads it. On PyPI the
distribution is `clihub-cli`, because `clihub` there belongs to an unrelated
project; the import package and both commands are unaffected.

Tagging is the whole release. Everything after it is the workflow's.

1. Bump `__version__`, commit, and push to `main`. Wait for the matrix: it is the
   only thing that runs the suite on Linux and on 3.13 and 3.14.
2. `git tag -a vX.Y.Z -m "clihub X.Y.Z" && git push origin --tags`.

`release.yml` then runs the tests, refuses a tag that disagrees with
`__version__`, publishes to PyPI, and points `nitkrar/homebrew-tap` at the sdist
PyPI is serving. The formula names that sdist rather than a GitHub tag archive,
so brew can only ever offer a version pip already has, and a release that failed
to publish leaves the tap alone.

Two credentials, both configured once and neither stored in the repository:

- PyPI trusted publishing, set up on pypi.org for project `clihub-cli`: owner
  `nitkrar`, repository `clihub`, workflow `release.yml`. There is no API token.
- `TAP_TOKEN`, an Actions secret on this repository holding a fine-grained PAT
  with `contents: write` on `nitkrar/homebrew-tap` alone. `GITHUB_TOKEN` cannot
  reach another repository, which is the only reason this exists.

## Things that will bite you

- **zsh does not word-split unquoted parameters.** `for c in "a b"; do ch $c; done`
  passes one argument, not two. Use arrays or write the commands out.
- **`$?` after a pipe is the last command's**, so `ch foo | head` reports `head`'s
  exit code. Redirect to a file instead when you are measuring exit codes.
- **`git checkout -- <file>` discards uncommitted work.** Restoring after a mutation
  test has silently reverted real fixes; copy the file aside instead.
- **`sed -i` edits succeed while being wrong.** A rename applied to two call sites
  produced a `NameError` in the one whose variable had a different name. Prefer
  editing in place and reading the result.
