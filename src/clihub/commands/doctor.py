"""`ch doctor` — is clihub working, and is the registry sound?

Top level because it is what you reach for when something is wrong, and where
clihub's own error messages send you.

Two kinds of check. The registry's own are `ch registry validate`, called from here
rather than reimplemented. The rest are about clihub's installation: whether `ch` is
reachable, whether it is the one you think, whether completion has fallen behind,
whether your config is being silently ignored.

It reads and stats. It does **not** run your tools: the one command it spawns is
`sh -n`, which parses a stored command and exits without executing it.

Exit code is non-zero only when something is *broken* -- a registry that will not
parse, an entry that cannot run, a config discarded whole. Advisories exit 0.

"Broken" does not mean clihub stopped: an unparseable config is broken while
dispatch carries on with the shipped defaults, because every key you wrote in it
is silently inert.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

from .. import completion, config, registry
from ..paths import Paths
from ..render import render_rows, render_text

# What `ch --help` prints for this command. Separate from __doc__, which is
# about the module: different readers, different words.
SUMMARY = "check clihub and the registry"
ARGS = ""

SETUP_CHECKS = ("ch on PATH", "config readable", "completion current")


def run(argv: list[str], paths: Paths) -> int:
    if len(argv) > 2 and argv[2] in ("-h", "--help"):
        render_text(
            "usage: ch doctor\n\nChecks the registry ("
            + ", ".join(registry.CHECKS)
            + ")\nand clihub's own setup ("
            + ", ".join(SETUP_CHECKS)
            + ")."
        )
        return 0

    issues = registry.doctor_issues(paths) + _setup_issues(paths)
    broken = [i for i in issues if i.severity == registry.BROKEN]
    advisory = [i for i in issues if i.severity == registry.ADVISORY]
    scale = _scale(paths)

    # First line of any bug report, so it is printed whatever the verdict.
    from .. import __version__

    render_text(f"clihub {__version__}")

    if not issues:
        render_text(
            f"ok - {scale}\n     checked: "
            + ", ".join([*registry.CHECKS, *SETUP_CHECKS])
        )
        return 0

    counts = []
    if broken:
        counts.append(f"{len(broken)} broken")
    if advisory:
        counts.append(f"{len(advisory)} advisory")
    render_text(f"{', '.join(counts)} - {scale}")
    for label, group in (("broken", broken), ("advisory", advisory)):
        if not group:
            continue
        render_text(f"\n{label}")
        render_rows([(f"  {i.namespace}", i.problem) for i in group])
    return 1 if broken else 0


def _setup_issues(paths: Paths) -> list:
    """Everything that is about clihub rather than about what it routes to."""
    issues = []

    problem = config.parse_problem(paths.config_file)
    if problem is not None:
        # load() ignores a broken config on purpose -- a typo in a preferences file
        # must never stop dispatch -- so nothing else would ever say this.
        #
        # Broken rather than advisory, though it does not stop anything: the file
        # is discarded whole, so *every* setting in it is silently doing nothing.
        # One unreachable entry exits 1; a config where nothing you wrote applies
        # should not be quieter than that.
        issues.append(
            registry.DoctorIssue(
                "config",
                f"ignored, will not parse: {problem}",
                registry.BROKEN,
                registry.REACHABILITY,
            )
        )

    found = shutil.which("ch")
    if found is None:
        issues.append(
            registry.DoctorIssue("ch", "not on PATH; run ch init", registry.ADVISORY)
        )
    else:
        running = Path(sys.argv[0]).resolve()
        if running.name in ("ch", "clihub") and Path(found).resolve() != running:
            issues.append(
                registry.DoctorIssue(
                    "ch",
                    f"PATH has a different install: {Path(found).resolve()}",
                    registry.ADVISORY,
                )
            )

    for shell in completion.SHELLS:
        try:
            from .tools import completion_words

            for problem in completion.problems(paths, shell, completion_words(paths)):
                issues.append(
                    registry.DoctorIssue(f"completion.{shell}", problem, registry.ADVISORY)
                )
        except Exception:
            continue
    return issues


def _scale(paths: Paths) -> str:
    """How much was looked at. "ok" alone does not say whether anything was."""
    try:
        loaded = registry.load(paths)
    except Exception:
        return "registry unreadable"
    entries, namespaces = len(loaded.entries()), len(loaded.namespaces)
    return (
        f"{entries} {'entry' if entries == 1 else 'entries'}, "
        f"{namespaces} {'namespace' if namespaces == 1 else 'namespaces'}"
    )
