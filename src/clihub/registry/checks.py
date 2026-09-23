"""What `ch doctor` asks of a registry, and the vocabulary it answers in.

Everything here reads and stats; nothing runs a tool. Severity says whether it
stops you, `kind` says whether the problem travels to another machine — doctor
treats both alike, `import` cannot, since it judges a file written elsewhere.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

from ..config import BUILTIN_NAMES
from ..errors import RegistryEntryError
from ..paths import Paths
from .model import Registry
from .names import name_problem
from .read import load

# What `issues_for` actually looks at. Named here rather than in the command, so
# the report and the checks cannot drift apart.
CHECKS = (
    "parsing",
    "commands",
    "syntax",
    "quoting",
    "targets",
    "permissions",
    "shadowing",
    "duplicates",
    "portability",
    "names",
)


BROKEN = "broken"        # the entry cannot work, or cannot be reached
ADVISORY = "advisory"    # it works; you may still want to look

STRUCTURE = "structure"        # wrong in itself, on any machine
REACHABILITY = "reachability"  # fine in itself; not satisfiable in this environment


@dataclass(frozen=True)
class DoctorIssue:
    namespace: str
    problem: str
    severity: str = BROKEN
    kind: str = STRUCTURE


def path_matches(name: str) -> list[tuple[str, str]]:
    """Every executable PATH would find for this name: (directory, full path).

    `type -a`. The directory is kept as PATH wrote it, because whether it was
    written relative is the thing that decides if the hit is cwd-dependent.
    """
    seen: set[str] = set()
    found: list[tuple[str, str]] = []
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        if not directory or directory in seen:
            continue
        seen.add(directory)
        candidate = os.path.join(directory, name)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            found.append((directory, candidate))
    return found


def _transient_reason(directory: str, resolved: str) -> str | None:
    """Why this hit will not exist in another shell, or None if it will.

    Only declared environments count. A relative PATH entry is cwd-dependent by
    construction; "under the current directory" is not, since run from $HOME it
    would call a permanent entry like /Users/x/.local/bin transient.
    """
    if not os.path.isabs(directory):
        return "a relative PATH entry"
    for var in ("VIRTUAL_ENV", "CONDA_PREFIX"):
        root = os.environ.get(var)
        if not root or not os.path.isabs(root):
            continue
        try:
            if os.path.commonpath([resolved, root]) == os.path.normpath(root):
                return f"${var}"
        except ValueError:
            continue
    return None


def environment_specific(name: str) -> tuple[str, str, str | None] | None:
    """Does this bare name resolve somewhere that will not be there later?

    Returns (why, the binary winning here, the one winning elsewhere or None).
    A missing alternative is the worse case, not the milder one: it means the
    entry is not merely different outside, it is absent.
    """
    matches = path_matches(name)
    if not matches:
        return None
    directory, winner = matches[0]
    reason = _transient_reason(directory, winner)
    if reason is None:
        return None
    stable = next(
        (path for other, path in matches[1:] if _transient_reason(other, path) is None),
        None,
    )
    return reason, winner, stable


def _unquoted_space_target(prefix: tuple[str, ...]) -> str | None:
    """A path whose space was never quoted splits into tokens that rejoin into a file.

    Checked even when the first token exists on its own: `/opt/bin with/tool` splits to
    `/opt/bin`, which may well be a real executable, and reporting it as "ok" is worse
    than the contrived risk of a file genuinely named "<target> <arg>".
    """
    for index in range(2, len(prefix) + 1):
        candidate = " ".join(prefix[:index])
        if Path(candidate).exists():
            return candidate
    return None


# Words the shell runs itself. Several are also real files -- /bin/echo, /bin/test,
# /usr/bin/time -- but the shell resolves its own before PATH, so what `which` finds
# is not what would run.
_SHELL_WORDS = frozenset("""
    ! : . [ ]] [[ { } alias bg break case cd command continue declare do done echo
    elif else esac eval exec exit export false fg fi for function getopts hash if
    jobs kill let local printf pwd read readonly return select set shift source
    test then time times trap true type typeset ulimit umask unalias unset until
    wait while
""".split())


def is_shell_construct(word: str) -> bool:
    """Is the first word something the shell interprets, rather than a file to find?

    A command line may be a script -- `export X=1` then more lines, or a leading
    `VAR=value` -- and then its first word names no executable. Looking it up
    reports a working entry as broken, which is the worse error of the two: a
    target that cannot be checked is not a target that is missing.

    Shared with `registry add` so the two cannot disagree about what is legal:
    a command doctor accepts must be one `add` would let you write.
    """
    if word in _SHELL_WORDS:
        return True
    name, assigned, _ = word.partition("=")
    return bool(assigned) and name.isidentifier()


_METACHARACTERS = frozenset(";|&(){}<>`$\n")


def _could_fail_to_parse(script: str) -> bool:
    """Is there anything here the shell could choke on?

    A plain word list always parses, so most entries need no shell at all. Two
    things take it out of that class: a metacharacter, and a leading keyword --
    `done --flag` holds no punctuation and is still a syntax error.
    """
    if _METACHARACTERS & set(script):
        return True
    words = script.split()
    return bool(words) and words[0] in _SHELL_WORDS


def syntax_problem(name: str, script: str) -> str | None:
    """Why the line clihub would actually run will not parse, or None.

    Asked of the assembled body, not the stored text, because the failure this
    catches is created by assembly: `"$@"` appended after `done` or `fi` is a
    syntax error the stored command does not have on its own.

    `sh -n` reads without executing, so this asks the shell instead of guessing
    whether the assembled body still parses.
    """
    if not _could_fail_to_parse(script):
        return None

    import subprocess

    from ..dispatch import SHELL, shell_argv

    body = shell_argv(script, f"ch {name}", [])[2]
    try:
        result = subprocess.run([SHELL, "-n", "-c", body], capture_output=True, text=True)
    except OSError:
        return None
    if result.returncode == 0:
        return None
    lines = result.stderr.strip().splitlines()
    detail = lines[0].split(": ", 2)[-1] if lines else "the shell cannot parse it"
    hint = "" if "$@" in script else '; place "$@" where arguments belong'
    return f"will not parse: {detail}{hint}"


def _locate(target: str) -> Path | None:
    """Where this target actually is, or None. A bare name is a PATH lookup.

    shutil is imported here rather than at the top because it costs 19 ms and is
    not otherwise on the dispatch path -- and the only caller is doctor, which is
    never on it.
    """
    if os.sep in target or target.startswith("~"):
        path = Path(target).expanduser()
        return path if path.exists() else None
    import shutil

    found = shutil.which(target)
    return Path(found) if found else None


def doctor_issues(paths: Paths) -> list[DoctorIssue]:
    try:
        registry = load(paths)
    except RegistryEntryError as exc:
        # Doctor is what a broken registry sends you to, so it reports the breakage
        # instead of hitting it.
        first = str(exc).splitlines()[0]
        return [DoctorIssue(paths.registry_file.name, first.split(": ", 1)[-1])]
    return issues_for(registry)


def issues_for(registry: Registry) -> list[DoctorIssue]:
    """Every check CHECKS names, against a registry from anywhere.

    Taken apart from doctor_issues so `import` can hold a candidate file to the
    same standard as the live one instead of growing its own opinion of legal.
    """
    from ..dispatch import takes_appended_arguments

    issues: list[DoctorIssue] = []
    seen_prefixes: dict[tuple[str, ...], str] = {}

    for namespace in registry.namespaces:
        if namespace.name in BUILTIN_NAMES:
            issues.append(
                DoctorIssue(namespace.name, "shadowed by a builtin; rename or remove it")
            )
        if namespace.command is None and not namespace.entries:
            issues.append(DoctorIssue(namespace.name, "nothing registered here", ADVISORY))

    for entry in registry.entries():
        # Advisory: a hand-written `[Mail]` or `ok.bad.name` dispatches perfectly
        # well, because load() builds entries from the raw section and key text and
        # never asks. That makes it the user's entry to fix rather than clihub being
        # broken -- but `add` refuses these names, so leaving them silent means the
        # rule holds only for the path that goes through `add`.
        bad_name = name_problem(entry.name)
        if bad_name is not None:
            issues.append(DoctorIssue(entry.name, bad_name, ADVISORY))

        try:
            prefix = entry.prefix
        except RegistryEntryError as exc:
            issues.append(DoctorIssue(entry.name, str(exc)))
            continue

        broken_syntax = syntax_problem(entry.name, entry.script)
        if broken_syntax is not None:
            issues.append(DoctorIssue(entry.name, broken_syntax, BROKEN, STRUCTURE))
            continue

        # Advisory, not broken: it runs, it just cannot be given arguments, and
        # `ch <name> arg` says so rather than dropping them.
        if not takes_appended_arguments(entry.script) and "$@" not in entry.script:
            issues.append(
                DoctorIssue(
                    entry.name,
                    'takes no arguments; put "$@" in the command where they belong',
                    ADVISORY,
                )
            )
        # Only a string can have got its quoting wrong; a list is already argv.
        joined = (
            None if isinstance(entry.command, (list, tuple))
            else _unquoted_space_target(prefix)
        )
        if joined is not None:
            issues.append(DoctorIssue(entry.name, f"unquoted path contains a space: {joined}"))
            continue
        # A script's first word names no file, so there is nothing to locate and
        # nothing to say. Skipped rather than reported: doctor reads and stats, and
        # where the script leads cannot be answered without running it.
        if not is_shell_construct(prefix[0]):
            target = _locate(prefix[0])
            if target is None:
                where = "on PATH" if os.sep not in prefix[0] else ""
                issues.append(
                    DoctorIssue(entry.name,
                                f"target missing{' ' + where if where else ''}: {prefix[0]}",
                                BROKEN, REACHABILITY)
                )
                continue
            if not os.access(target, os.X_OK):
                issues.append(
                    DoctorIssue(entry.name, f"target not executable: {target}",
                                BROKEN, REACHABILITY)
                )
                continue
            # Advisory, not broken: it resolves here, so it works here. What it does
            # not do is mean the same thing in the next shell, and only running from
            # that shell would otherwise tell you. Reported from wherever doctor is
            # invoked, which is the only environment it can honestly speak about.
            transient = environment_specific(prefix[0]) if os.sep not in prefix[0] else None
            if transient is not None:
                reason, winner, elsewhere = transient
                issues.append(
                    DoctorIssue(
                        entry.name,
                        f"only in {reason}: {winner}; missing in any other shell"
                        if elsewhere is None
                        else f"resolves in {reason}: {winner}; {elsewhere} elsewhere",
                        ADVISORY,
                        REACHABILITY,
                    )
                )
        first = seen_prefixes.get(prefix)
        if first is not None:
            # Deliberate multi-membership is allowed; drift between the copies is
            # the real cost, so this is news rather than a fault.
            issues.append(
                DoctorIssue(entry.name, f"same command as {first}; keep them in step", ADVISORY)
            )
        else:
            seen_prefixes[prefix] = entry.name
    return issues
