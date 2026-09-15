from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable


class ClihubFixture(unittest.TestCase):
    """Setup and helpers only. Holds no tests of its own, so the suites that
    subclass it do not each re-run a shared set."""

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.base = Path(self.tempdir.name)
        self.tools_root = self.base / "tools"
        self.tools_root.mkdir()
        self.clihub_home = self.base / "clihub-home"
        self.env = os.environ.copy()
        self.env["PYTHONPATH"] = str(ROOT / "src")
        self.env["PYTHONUNBUFFERED"] = "1"
        self.env["CLIHUB_HOME"] = str(self.clihub_home)
        # Completion appends to a shell rc, and init migrates out of ~/.config and
        # ~/.local, so HOME must never be the real one. Asserted, not just set:
        # a test that writes to the real home is not a failing test, it is damage.
        self.env["HOME"] = str(self.base / "home")
        (self.base / "home").mkdir()
        for leaked in ("XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME", "XDG_CONFIG_HOME",
                       "ZDOTDIR"):
            self.env.pop(leaked, None)
        self.env["SHELL"] = "/bin/zsh"
        # `ch on PATH` is one of doctor's checks, so whether it passes has to come
        # from the fixture. Left to the ambient PATH it passes on a machine with
        # clihub installed and fails everywhere else, including CI.
        shim = self.base / "shim"
        shim.mkdir()
        (shim / "ch").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        (shim / "ch").chmod(0o755)
        self.env["PATH"] = f"{shim}{os.pathsep}{self.env.get('PATH', '')}"

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def run_cli(self, *args: str, timeout: float = 5.0) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [PYTHON, "-m", "clihub", *args],
            cwd=ROOT,
            env=self.env,
            text=True,
            capture_output=True,
            timeout=timeout,
        )

    def start_cli(self, *args: str) -> subprocess.Popen[str]:
        return subprocess.Popen(
            [PYTHON, "-m", "clihub", *args],
            cwd=ROOT,
            env=self.env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )

    def write_tool(self, name: str, body: str, directory: Path | None = None) -> Path:
        target_dir = self.tools_root if directory is None else directory
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / name
        script = f"#!{PYTHON}\n" + textwrap.dedent(body).lstrip()
        path.write_text(script, encoding="utf-8")
        path.chmod(0o755)
        return path

    def write_router_tool(
        self,
        name: str,
        namespace: str,
        directory: Path | None = None,
        behavior: str = 'print(json.dumps(args))',
        help_text: str | None = None,
    ) -> Path:
        help_value = help_text or f"help for {namespace}"
        indented_behavior = textwrap.indent(textwrap.dedent(behavior).strip(), "        ")
        body = f"""
        import json
        import sys

        args = sys.argv[1:]
        if args == ["--describe"]:
            print({namespace!r} + ": manage {namespace}")
            raise SystemExit(0)
        if args == ["--help"]:
            print({help_value!r})
            raise SystemExit(0)
{indented_behavior}
        """
        return self.write_tool(name, body, directory=directory)

    @property
    def registry_file(self) -> Path:
        return self.clihub_home / "registry.toml"

    @property
    def config_file(self) -> Path:
        path = self.clihub_home / "config.toml"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def write_entry(self, name: str, command: str) -> Path:
        """Append a raw section, bypassing `tools add`, to exercise bad input."""
        path = self.registry_file
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            # A TOML basic string, so a Windows-style path or a quote in the command
            # survives being written into a fixture.
            handle.write(f"\n[{name}]\ncommand = {json.dumps(command)}\n")
        return path
