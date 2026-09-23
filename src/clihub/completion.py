"""Shell completion: generating the script, installing it, and taking it back out.

The script is a file clihub owns; the rc gets one line that sources it, so
regenerating completions never touches the rc again.

    ~/.clihub/completion.zsh    ours
    ~/.zshrc  += source "..."  # clihub completions

Candidates are baked into the script rather than queried at tab time, since a `ch`
invocation is too slow to sit under a tab press. `completions_enabled` is therefore
honoured by the *shell*, which greps the config: flipping it takes effect on the
next tab with no reinstall.
"""
from __future__ import annotations

from pathlib import Path
import os

from .paths import Paths

SHELLS = ("zsh", "bash")
MARKER = "# clihub completions"

RC_FILES = {"zsh": ".zshrc", "bash": ".bashrc"}


def detect_shell() -> str:
    name = Path(os.environ.get("SHELL", "")).name
    return name if name in SHELLS else "zsh"


def script_path(paths: Paths, shell: str) -> Path:
    return paths.completion_root / f"completion.{shell}"


def rc_path(shell: str) -> Path:
    # With ZDOTDIR set, zsh reads $ZDOTDIR/.zshrc and never looks at ~/.zshrc, so
    # installing there writes a line no shell will ever source.
    if shell == "zsh":
        zdotdir = os.environ.get("ZDOTDIR")
        if zdotdir:
            return Path(zdotdir) / ".zshrc"
    return Path.home() / RC_FILES[shell]


def source_line(paths: Paths, shell: str) -> str:
    return f'source "{script_path(paths, shell)}"  {MARKER}'


def install(paths: Paths, shell: str, words: list[str]) -> tuple[Path, Path, bool]:
    """Write the script and make sure the rc sources it.

    Returns (script, rc, rc_changed). Re-running changes nothing the second time:
    the script is overwritten with the same content and the rc line is matched by
    its marker, not by its text, so a moved config directory still updates cleanly.
    """
    target = script_path(paths, shell)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(script(shell, words), encoding="utf-8")

    rc = rc_path(shell)
    wanted = source_line(paths, shell)
    lines = rc.read_text(encoding="utf-8").splitlines() if rc.is_file() else []
    kept = [line for line in lines if MARKER not in line]
    if kept == lines and wanted in lines:
        return target, rc, False
    if kept + [wanted] == lines:
        return target, rc, False
    rc.parent.mkdir(parents=True, exist_ok=True)
    rc.write_text("\n".join([*kept, wanted]) + "\n", encoding="utf-8")
    return target, rc, True


def remove(paths: Paths, shell: str) -> tuple[bool, bool]:
    """Delete the script and drop the rc line.

    The rc line goes too: leaving a `source` pointing at a deleted file makes every
    new shell print an error, which is a worse state than never having installed.
    """
    target = script_path(paths, shell)
    had_script = target.is_file()
    if had_script:
        target.unlink()

    rc = rc_path(shell)
    had_line = False
    if rc.is_file():
        lines = rc.read_text(encoding="utf-8").splitlines()
        kept = [line for line in lines if MARKER not in line]
        had_line = len(kept) != len(lines)
        if had_line:
            rc.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
    return had_script, had_line


def is_stale(paths: Paths, shell: str, words: list[str]) -> bool:
    """Installed, but listing different names than the registry holds now.

    The word list is baked in at install time, which is what makes completion cost
    nothing at tab time; the price is that adding a tool leaves it behind.
    """
    target = script_path(paths, shell)
    if not target.is_file():
        return False
    return target.read_text(encoding="utf-8") != script(shell, words)


def problems(paths: Paths, shell: str, words: list[str]) -> list[str]:
    """Everything wrong with this shell's completion, in the order it breaks.

    Whether the script *works* cannot be answered without running the shell, so
    what is checked is the chain that must hold for it to: the file exists, the rc
    sources it, they name the same path, and only then is the word list current.
    """
    target = script_path(paths, shell)
    rc = rc_path(shell)
    sourced = [
        line for line in (rc.read_text(encoding="utf-8").splitlines() if rc.is_file() else [])
        if MARKER in line
    ]

    found: list[str] = []
    if not target.is_file():
        if sourced:
            found.append(f"{rc} sources a completion script that is not there: {target}")
        return found
    if not sourced:
        found.append(f"installed at {target}, but nothing in {rc} sources it")
    elif str(target) not in sourced[0]:
        # A moved clihub home leaves the old path behind in the rc.
        found.append(f"{rc} sources a different path than {target}")
    if is_stale(paths, shell, words):
        found.append("lists different tools than the registry; run ch tools completion")
    return found


def script(shell: str, words: list[str]) -> str:
    joined = " ".join(words)
    guard = _GUARD_ZSH if shell == "zsh" else _GUARD_BASH
    body = _ZSH if shell == "zsh" else _BASH
    return guard + body.format(words=joined)


# `${CLIHUB_HOME:-$HOME/.clihub}` rather than asking clihub, so a disabled
# completion costs a grep instead of a Python interpreter.
_GUARD_ZSH = """#compdef ch clihub

_clihub_disabled() {
  local cfg="${CLIHUB_HOME:-$HOME/.clihub}/config.toml"
  [[ -f $cfg ]] || return 1
  grep -Eiq '^[[:space:]]*completions_enabled[[:space:]]*=[[:space:]]*(false|no|0|off)' "$cfg"
}

"""

_GUARD_BASH = """_clihub_disabled() {
  local cfg="${CLIHUB_HOME:-$HOME/.clihub}/config.toml"
  [ -f "$cfg" ] || return 1
  grep -Eiq '^[[:space:]]*completions_enabled[[:space:]]*=[[:space:]]*(false|no|0|off)' "$cfg"
}

"""

_ZSH = """_clihub_complete() {{
  _clihub_disabled && return 1
  local -a _clihub_words
  _clihub_words=({words})
  _describe 'command' _clihub_words
}}

# compdef only exists once compinit has run. Load it here so completion
# registration works in a plain rc as well as under a shell framework.
if ! whence compdef >/dev/null 2>&1; then
  autoload -Uz compinit && compinit -u
fi
compdef _clihub_complete ch clihub
"""

_BASH = """_clihub_complete() {{
  _clihub_disabled && return 1
  local cur
  COMPREPLY=()
  cur="${{COMP_WORDS[COMP_CWORD]}}"
  COMPREPLY=( $(compgen -W "{words}" -- "$cur") )
}}
complete -F _clihub_complete ch
complete -F _clihub_complete clihub
"""
