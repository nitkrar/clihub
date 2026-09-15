from __future__ import annotations

from time import monotonic
import subprocess
import sys

from .errors import DispatchError
from .journal import write_invocation
from .paths import Paths


SHELL = "/bin/sh"

# Anything here means the line is more than one simple command, so its end is not
# an argument position: it is inside a comment, past a pipe, after a here-doc
# terminator, beyond a compound's closing word.
_BEYOND_ONE_COMMAND = frozenset(";|&(){}<>`\\\n")


def takes_appended_arguments(script: str) -> bool:
    """Would `"$@"` appended to the end of this land where arguments go?

    Only for a single simple command. Deciding it any other way means deciding
    where a shell line ends, and every attempt to do that has been wrong in a new
    way: a trailing newline, a `done`, a here-doc terminator, a `#` comment.

    `#` counts only where a word starts, since a path may contain one and
    `/opt/we#ird/tool` is a filename, not a comment.
    """
    text = script.strip()
    if _BEYOND_ONE_COMMAND & set(text):
        return False
    return not any(word.startswith("#") for word in text.split())


def shell_body(script: str, tail: list[str]) -> str:
    """The script `sh` is given: as written, or with `"$@"` appended.

    Nothing is appended when there is nothing to bind, so a command that says
    where its arguments go -- or is never given any -- runs exactly as written.
    """
    if "$@" in script or not tail:
        return script
    if not takes_appended_arguments(script):
        raise DispatchError(
            'this command does not say where arguments go; put "$@" in it '
            "where they belong"
        )
    return f'{script.rstrip()} "$@"'


def shell_argv(script: str, name: str, tail: list[str]) -> list[str]:
    """`sh -ec <script> <$0> <args...>` — the whole dispatch model in one line.

    A stored command is a shell command line, so pipes, redirects and `VAR=x cmd`
    mean what they say. `-e` stops a multi-line command at the first failure.

    The tail binds to `$@` rather than being spliced into the script, so arguments
    are never re-parsed: a pipe in the registry is syntax, a pipe in an argument is
    data.

    `$0` is the clihub name, so the shell's errors read `ch llm.llama: ...`.
    """
    return [SHELL, "-ec", shell_body(script, tail), name, *tail]


def dispatch(paths: Paths, namespace: str, script: str, tail: list[str]) -> int:
    argv = shell_argv(script, f"ch {namespace}", tail)
    started = monotonic()
    try:
        proc = subprocess.Popen(argv)
    except OSError as exc:
        rc = 126
        write_invocation(paths, namespace, tail, rc, _duration_ms(started))
        raise DispatchError(
            f"failed to execute {namespace}: {exc.strerror or exc}"
        ) from exc

    while True:
        try:
            rc = proc.wait()
            break
        except KeyboardInterrupt:
            continue

    if rc < 0:
        rc = 128 + abs(rc)
    write_invocation(paths, namespace, tail, rc, _duration_ms(started))
    return rc


def capture(
    script: str, tail: list[str], timeout: float | None = None
) -> subprocess.CompletedProcess[str]:
    """The same shell, for management work: reading a tool's `--help`."""
    argv = shell_argv(script, "ch", tail)
    try:
        return subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except OSError as exc:
        raise DispatchError(f"failed to execute {script}: {exc.strerror or exc}") from exc


def write_shadowed_builtin_notice(namespace: str) -> None:
    sys.stderr.write(
        f"note: registry entry '{namespace}' is using a builtin name; remove it with 'ch registry remove {namespace}'\n"
    )


def _duration_ms(started: float) -> int:
    return int((monotonic() - started) * 1000)
