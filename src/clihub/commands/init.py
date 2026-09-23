"""`ch init` — make clihub usable: create its directories and put `ch` on PATH.

This is the one command you run by full path, because the whole point of it is that
`ch` is not yet reachable by name. Everything it does is idempotent.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

from .. import completion, config, install, render
from ..config import load as load_settings
from ..errors import BuiltinError
from ..paths import Paths

# What `ch --help` prints for this command. Separate from __doc__, which is
# about the module: different readers, different words.
SUMMARY = "create the directories, put ch on PATH"
ARGS = ""

DEFAULT_LINK_DIR = Path("~/.local/bin")
DEFAULT_SKILL_DIR = Path("~/.claude/skills")


def run(argv: list[str], paths: Paths) -> int:
    parser = argparse.ArgumentParser(prog="ch init")
    parser.add_argument("--link-dir", default=str(DEFAULT_LINK_DIR))
    parser.add_argument("--no-link", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--completions", action=argparse.BooleanOptionalAction, default=None
    )
    # No default: whether it was given is the question, since being told where
    # is what replaces asking. The default is applied where it is used.
    parser.add_argument("--skill-dir")
    parser.add_argument("--no-skill", action="store_true")
    args = parser.parse_args(argv[2:])

    for directory in (paths.root, paths.log_root):
        directory.mkdir(parents=True, exist_ok=True)
    wrote_config = _write_commented_config(paths)
    print(f"home       {paths.root}")
    print(f"registry   {paths.registry_file.name}")
    print(f"config     {paths.config_file.name}"
          f"{'  (written; every key commented out)' if wrote_config else '  (kept yours)'}")
    print(f"log        {paths.log_root.name}/       safe to delete")

    _install_completions(paths, choice=args.completions)
    status = _link_command(args)
    _offer_skill(args)
    _offer_registry(paths)
    return status


def _link_command(args) -> int:
    if args.no_link:
        return 0

    source = install.console_script()
    if source is None:
        sys.stderr.write(
            "could not locate the installed `ch` script; skipping the symlink.\n"
            "  install with: pip install -e . ; then re-run ch init\n"
        )
        return 0

    # Whoever installed clihub owns that name and relinks it on upgrade; a
    # second copy here would compete with them. The link is for a checkout
    # whose venv is not active.
    reachable = install.on_path()
    if reachable is not None and not args.force and install.same_install(reachable, source):
        print(f"command    {reachable}  already on PATH")
        return 0

    link_dir = Path(args.link_dir).expanduser()
    link_dir.mkdir(parents=True, exist_ok=True)
    link = link_dir / "ch"
    _link(source, link, force=args.force)

    print(f"command    {link} -> {source}")
    if not _on_path(link_dir):
        sys.stderr.write(
            f"\n{link_dir} is not on your PATH. Add it, or pick a directory that is:\n"
            f"  export PATH=\"{link_dir}:$PATH\"\n"
        )
    return 0


def _offer_skill(args) -> None:
    """Offer the agent skill that ships with clihub, and say where it is either way.

    Declining still prints the path: the file is no use to anyone who cannot
    find it, and that is the whole reason this offer exists.
    """
    shipped = install.shipped_dir("skills")
    if shipped is None:
        return
    source = shipped / "clihub" / "SKILL.md"
    if not source.is_file():
        return
    if args.no_skill:
        print(f"skill      {source}")
        return

    told = args.skill_dir is not None
    target_dir = Path(args.skill_dir or DEFAULT_SKILL_DIR).expanduser() / "clihub"
    target = target_dir / "SKILL.md"
    if target.is_file() and target.read_bytes() == source.read_bytes():
        print(f"skill      {target}  already installed")
        return

    question = (f"\ninstall the clihub agent skill to {target_dir}?" if told
                else "\ninstall the clihub agent skill?")
    if not render.confirm(question):
        print(f"skill      {source}")
        return

    if not told:
        answer = render.ask(f"where? [{DEFAULT_SKILL_DIR}] ")
        if answer is None:
            # Abandoned rather than answered: installing somewhere they did not
            # choose is worse than not installing.
            print(f"skill      {source}")
            return
        if answer:
            target_dir = Path(answer).expanduser() / "clihub"
            target = target_dir / "SKILL.md"

    target_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    print(f"skill      {target}")


def _offer_registry(paths: Paths) -> None:
    """Offer a shipped registry, where this machine could run what is in it.

    Only the registries named for this platform: importing commands built on
    `scutil` and APFS paths onto Linux registers fifty entries that cannot run
    and leaves `doctor` failing on a machine nobody has touched yet.
    """
    shipped = install.shipped_dir("registries")
    if shipped is None:
        return
    for source in sorted(shipped.glob("*.toml")):
        if not source.stem.startswith(_platform_prefix()):
            continue
        entries = _count_commands(source)
        if not render.confirm(
            f"\nimport {entries} {source.stem} commands into your registry?"
        ):
            print(f"registry   {source}  import it with 'ch registry import'")
            continue
        from . import registry as registry_command

        registry_command.import_file(paths, source, force=False)


def _platform_prefix() -> str:
    return {"darwin": "macos", "linux": "linux"}.get(sys.platform, sys.platform)


def _count_commands(source: Path) -> int:
    """How many runnable commands the shipped registry defines."""
    import tomllib

    def walk(table: dict) -> int:
        total = 0
        for value in table.values():
            if isinstance(value, dict):
                total += ("command" in value) + walk(value)
        return total

    try:
        with source.open("rb") as handle:
            return walk(tomllib.load(handle))
    except (OSError, tomllib.TOMLDecodeError):
        return 0


def _write_commented_config(paths: Paths) -> bool:
    """Write config.toml as the shipped defaults with every key commented out.

    Generated from defaults.toml rather than copied, so the two cannot drift and a
    key added later shows up here the next time init runs. Commented rather than
    live on purpose: a user file holding real values would shadow every future
    change to a default, so raising a timeout in a release would silently not
    reach anyone who had ever run init.
    """
    if paths.config_file.exists():
        return False
    body = [
        "# clihub settings. Uncomment a line to override it; the value shown is",
        "# what clihub uses when you do not. Generated by `ch init` from the",
        "# defaults shipped in the package -- editing those is not the way.",
        "",
    ]
    lines = config.defaults_text().splitlines()
    # Drop the shipped file's own header: this file has one already, and two
    # headers explaining the same thing differently is how one goes stale.
    while lines and not lines[0].startswith("["):
        lines.pop(0)
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("["):
            body.append(line)
        else:
            body.append(f"# {line}")
    paths.config_file.parent.mkdir(parents=True, exist_ok=True)
    paths.config_file.write_text("\n".join(body).rstrip() + "\n", encoding="utf-8")
    return True


def _install_completions(paths: Paths, *, choice: bool | None) -> None:
    """Off unless asked: init should not edit a shell config on its own initiative.

    `--completions`/`--no-completions` override the config for one run.
    """
    if choice is False:
        return
    if choice is None and not load_settings(paths.config_file).completions_auto_enabled:
        return
    from .tools import install_completion

    install_completion(paths, completion.detect_shell())


def _link(source: Path, link: Path, *, force: bool) -> None:
    if link.is_symlink() or link.exists():
        # Refuse silently replacing something the user put there — same rule as
        # `tools add`: an existing entry is only replaced when asked explicitly.
        if link.is_symlink() and link.resolve() == source.resolve():
            return
        if not force:
            raise BuiltinError(
                f"{link} already exists and does not point at {source}. "
                "Re-run with --force to replace it."
            )
        link.unlink()
    link.symlink_to(source)


def _on_path(directory: Path) -> bool:
    entries = os.environ.get("PATH", "").split(os.pathsep)
    resolved = directory.expanduser().resolve()
    for entry in entries:
        if not entry:
            continue
        try:
            if Path(entry).expanduser().resolve() == resolved:
                return True
        except OSError:
            continue
    return False
