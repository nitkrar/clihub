from __future__ import annotations

import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

from .fixture import ROOT, ClihubFixture


class SetupTests(ClihubFixture):
    """Installing clihub itself: init, completion, config."""

    def test_the_zsh_script_registers_itself_without_a_compinit_in_the_rc(self) -> None:
        """`compdef` does not exist until compinit has run, and a plain ~/.zshrc
        never calls it.

        Unregistered, zsh falls back to filename completion, which looks like
        broken completion rather than absent completion. `zsh -f` skips every rc,
        so it reproduces that state exactly.
        """
        if shutil.which("zsh") is None:
            self.skipTest("zsh not installed")
        tool = self.write_router_tool("c.py", "c")
        self.run_cli("registry", "add", "noted","--", str(tool))
        self.run_cli("tools", "completion")
        script = self.clihub_home / "completion.zsh"

        # -f skips every rc, so compinit has definitely not run.
        # The fixture env, not the ambient one: the script greps $CLIHUB_HOME/config.toml
        # and would otherwise read the real one. It happens not to write anything, but
        # a probe that reaches outside the temp setup is one edit away from doing so.
        probe = subprocess.run(
            ["zsh", "-f", "-c", f'source "{script}" 2>&1; echo "REGISTERED=${{_comps[ch]:-no}}"'],
            env=self.env, capture_output=True, text=True, timeout=30,
        )
        self.assertIn("REGISTERED=_clihub_complete", probe.stdout, probe.stdout + probe.stderr)
        self.assertNotIn("command not found", probe.stdout)

    def test_completion_installs_by_sourcing_a_file_we_own(self) -> None:
        """The rc gets one line; the script it points at is ours to rewrite."""
        tool = self.write_router_tool("done.py", "done")
        self.run_cli("registry", "add", "notes", "--", str(tool))
        script = self.clihub_home / "completion.zsh"
        rc = self.base / "home" / ".zshrc"

        with self.subTest("init does nothing unless asked"):
            self.assertEqual(self.run_cli("init", "--no-link").returncode, 0)
            self.assertFalse(script.exists())
            self.assertFalse(rc.exists())

        with self.subTest("--completions installs and creates a missing rc"):
            result = self.run_cli("init", "--no-link", "--completions")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("notes", script.read_text(encoding="utf-8"))
            self.assertEqual(
                rc.read_text(encoding="utf-8").count("clihub completions"), 1
            )

        with self.subTest("installing again does not duplicate the rc line"):
            self.run_cli("tools", "completion")
            self.run_cli("init", "--no-link", "--completions")
            self.assertEqual(
                rc.read_text(encoding="utf-8").count("clihub completions"), 1
            )

        with self.subTest("the script defers to config, so it can be switched off"):
            body = script.read_text(encoding="utf-8")
            self.assertIn("completions_enabled", body)
            self.assertIn("_clihub_disabled && return 1", body)

        with self.subTest("the guard accepts every boolean python accepts"):
            zsh = shutil.which("zsh")
            if zsh:
                for value, expected in (("false", "DISABLED"), ("False", "DISABLED"),
                                        ("OFF", "DISABLED"), ("true", "active")):
                    (self.config_file).write_text(
                        f"[completions]\ncompletions_enabled = {value}\n", encoding="utf-8")
                    probe = subprocess.run(
                        [zsh, "-c", f"source {script}; _clihub_disabled && echo DISABLED || echo active"],
                        capture_output=True, text=True, env=self.env)
                    self.assertEqual(probe.stdout.strip(), expected, value)
                (self.config_file).unlink()

        with self.subTest("--print changes nothing on disk"):
            rc_before = rc.read_text(encoding="utf-8")
            result = self.run_cli("tools", "completion", "--print", "zsh")
            self.assertIn("_clihub_complete", result.stdout)
            self.assertEqual(rc.read_text(encoding="utf-8"), rc_before)

        with self.subTest("--remove takes the rc line with it"):
            # A source line pointing at a deleted file errors on every new shell,
            # which is worse than never having installed.
            self.assertEqual(self.run_cli("tools", "completion", "--remove").returncode, 0)
            self.assertFalse(script.exists())
            self.assertNotIn("clihub completions", rc.read_text(encoding="utf-8"))

    def test_completion_follows_zdotdir_because_zsh_does(self) -> None:
        """With ZDOTDIR set, zsh never reads ~/.zshrc, so a line installed there is
        inert and doctor would call it installed."""
        tool = self.write_router_tool("done.py", "done")
        self.run_cli("registry", "add", "notes", "--", str(tool))
        zdotdir = self.base / "zdotdir"
        zdotdir.mkdir()
        self.env["ZDOTDIR"] = str(zdotdir)
        home_rc = self.base / "home" / ".zshrc"

        with self.subTest("the line lands where zsh will read it"):
            self.assertEqual(self.run_cli("tools", "completion").returncode, 0)
            self.assertIn("clihub completions",
                          (zdotdir / ".zshrc").read_text(encoding="utf-8"))
            self.assertFalse(home_rc.exists())

        with self.subTest("doctor agrees it is wired up"):
            self.assertNotIn("completion.zsh", self.run_cli("doctor").stdout)

        with self.subTest("bash is unaffected -- ZDOTDIR is a zsh variable"):
            self.run_cli("tools", "completion", "bash")
            self.assertTrue((self.base / "home" / ".bashrc").is_file())
            self.assertFalse((zdotdir / ".bashrc").exists())

        with self.subTest("--remove cleans the same file it wrote"):
            self.assertEqual(self.run_cli("tools", "completion", "--remove").returncode, 0)
            self.assertNotIn("clihub completions",
                             (zdotdir / ".zshrc").read_text(encoding="utf-8"))

    def test_user_config_reaches_every_setting_that_uses_it(self) -> None:
        config = self.config_file
        config.parent.mkdir(parents=True, exist_ok=True)
        # timeout_seconds now bounds only the --help probe behind the overlap
        # warning; nothing runs a tool to ask what it is for any more.
        slow = self.write_tool("slow.py", """
            import sys, time
            if "--help" in sys.argv:
                time.sleep(1.0)
                print("usage: slow [options]\\n\\nreformat and lint python sources")
                sys.exit(0)
            sys.exit(0)
        """)

        with self.subTest("the shipped default lets a 1s --help probe through"):
            result = self.run_cli("registry", "add", "patient", "--describe",
                                  "reformat and lint python sources",
                                  "--", str(slow), timeout=10)
            self.assertIn("looks like a command list", result.stderr)

        with self.subTest("the user's shorter timeout is honoured"):
            config.write_text("[describe]\ntimeout_seconds = 0.2\n", encoding="utf-8")
            result = self.run_cli("registry", "add", "impatient", "--describe",
                                  "reformat and lint python sources",
                                  "--", str(slow), timeout=10)
            # The probe times out, so there is no help text to compare against and
            # the warning cannot fire.
            self.assertNotIn("looks like a command list", result.stderr)

        with self.subTest("find's typo cutoff is a setting, not a constant"):
            # `dokcer` is a typo of `docker` at 0.7 and not at 0.95. If the config
            # were ignored, both would match.
            tool = self.write_router_tool("docker.py", "docker")
            self.run_cli("registry", "add", "docker","--describe", "containers",
                         "--", str(tool))
            config.write_text("[find]\ntypo_cutoff = 0.7\n", encoding="utf-8")
            self.assertIn("docker", self.run_cli("find", "dokcer").stdout)
            config.write_text("[find]\ntypo_cutoff = 0.95\n", encoding="utf-8")
            self.assertNotIn("docker", self.run_cli("find", "dokcer").stdout)

    def test_the_shipped_default_and_the_code_fallback_agree(self) -> None:
        """`rank` takes a cutoff so it stays pure, and names a fallback for callers
        that have no config. Two statements of one number drift; this is the check
        that they have not."""
        sys.path.insert(0, str(ROOT / "src"))
        from clihub import config as config_module
        from clihub.commands.find import DEFAULT_TYPO_CUTOFF

        import tomllib

        defaults = tomllib.loads(config_module.defaults_text())
        self.assertEqual(defaults["find"]["typo_cutoff"], DEFAULT_TYPO_CUTOFF)

    def test_init_creates_roots_and_links_without_clobbering(self) -> None:
        link_dir = self.base / "bin"

        with self.subTest("creates every root, idempotently"):
            for _ in range(2):
                result = self.run_cli("init", "--no-link")
                self.assertEqual(result.returncode, 0, result.stderr)
            for root in (self.clihub_home, self.clihub_home / "log"):
                self.assertTrue(root.is_dir(), root)
            # config.toml is written as pure commentary, so it documents the keys
            # without shadowing a default that changes in a later version.
            written = (self.clihub_home / "config.toml").read_text(encoding="utf-8")
            self.assertIn("# timeout_seconds = 2.0", written)
            self.assertNotIn("\ntimeout_seconds", written)

        # The console script only exists in a pip-installed venv; under `python -m`
        # there is nothing to link, and init must say so rather than fail.
        script = Path(sys.executable).parent / "ch"
        if not script.is_file():
            with self.subTest("no console script: reports, does not fail"):
                result = self.run_cli("init", "--link-dir", str(link_dir))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("could not locate", result.stderr)
            return

        with self.subTest("links, then refuses to clobber a foreign file"):
            self.assertEqual(self.run_cli("init", "--link-dir", str(link_dir)).returncode, 0)
            self.assertTrue((link_dir / "ch").is_symlink())
            (link_dir / "ch").unlink()
            (link_dir / "ch").write_text("#!/bin/sh\necho foreign\n", encoding="utf-8")
            result = self.run_cli("init", "--link-dir", str(link_dir))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--force", result.stderr)
            self.assertIn("foreign", (link_dir / "ch").read_text(encoding="utf-8"))

        with self.subTest("--force replaces it"):
            result = self.run_cli("init", "--link-dir", str(link_dir), "--force")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((link_dir / "ch").is_symlink())

    def test_init_does_not_link_over_an_install_already_on_path(self) -> None:
        """pip, pipx, uv and Homebrew all put `ch` on PATH themselves. Linking a
        second copy there is init competing with whoever installed clihub."""
        bin_dir = self.write_install()
        link_dir = self.base / "bin"

        with self.subTest("leaves PATH alone"):
            result = self.run_installed(
                bin_dir, "clihub", "init", "--link-dir", str(link_dir), "--no-completions"
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(
                (link_dir / "ch").exists(),
                "init linked a second ch over one already on PATH",
            )

        with self.subTest("--force still links"):
            result = self.run_installed(
                bin_dir, "clihub", "init", "--link-dir", str(link_dir),
                "--no-completions", "--force",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((link_dir / "ch").is_symlink())

    def test_the_link_target_survives_an_upgrade_under_it(self) -> None:
        """Homebrew runs clihub from Cellar/<formula>/<version>/ and deletes that
        directory the moment the formula is upgraded. A link recorded there is
        dangling by the time the user types `ch`."""
        from unittest import mock

        from clihub import install as install_module

        prefix = self.base / "brew"
        old = prefix / "Cellar" / "clihub" / "1.0.1" / "libexec" / "bin"
        old.mkdir(parents=True)
        (old / "ch").write_text("#!/bin/sh\n", encoding="utf-8")
        (prefix / "opt").mkdir()
        (prefix / "opt" / "clihub").symlink_to(old.parent.parent)

        with mock.patch.object(install_module.sys, "executable", str(old / "python")):
            found = install_module.console_script()

        self.assertIsNotNone(found)

        new = prefix / "Cellar" / "clihub" / "1.0.2" / "libexec" / "bin"
        new.mkdir(parents=True)
        (new / "ch").write_text("#!/bin/sh\n", encoding="utf-8")
        (prefix / "opt" / "clihub").unlink()
        (prefix / "opt" / "clihub").symlink_to(new.parent.parent)
        shutil.rmtree(old.parent.parent)

        self.assertTrue(found.is_file(), f"{found} did not survive the upgrade")

    def test_clihub_writes_only_inside_its_configured_roots(self) -> None:
        """Everything lands under the one root, and the disposable parts in
        the subdirectories named for being disposable."""
        namespace = f"isolated-{uuid.uuid4().hex}"
        tool = self.write_router_tool("isolated.py", namespace)

        result = self.run_cli("registry", "add", namespace, "--", str(tool))
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.run_cli(namespace, "run")
        self.assertEqual(result.returncode, 0, result.stderr)

        self.assertTrue((self.clihub_home / "registry.toml").exists())
        self.assertTrue((self.clihub_home / "log" / "invocations.jsonl").exists())
        # Nothing outside it: the old spread is what made stray files invisible.
        strays = [p for p in Path(self.env["HOME"]).rglob("*") if p.is_file()]
        self.assertEqual(strays, [], f"wrote outside CLIHUB_HOME: {strays}")
