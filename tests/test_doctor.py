from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .fixture import PYTHON, ROOT, ClihubFixture


class DoctorTests(ClihubFixture):
    """What doctor and `registry validate` report, and which findings fail."""

    def test_the_sibling_ch_is_not_reported_as_another_install(self) -> None:
        """`ch` and `clihub` are two files in one bin. Compared as paths they
        never match, so every install looks like two to the install running it."""
        result = self.run_installed(self.write_install(), "clihub", "doctor")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("different install", result.stdout)

    def test_doctor_names_an_unquoted_space_rather_than_a_missing_target(self) -> None:
        spaced_dir = self.tools_root / "My Tools"
        spaced = self.write_router_tool("space.py", "space", directory=spaced_dir)
        self.write_entry("spacey", str(spaced))       # written raw, so unquoted

        report = self.run_cli("doctor").stdout
        self.assertIn("unquoted path contains a space", report)
        # The generic check would blame the truncated head, which sends you looking
        # for a file that was never meant to exist.
        self.assertNotIn("target missing", report)

    def test_a_command_the_shell_interprets_is_not_a_missing_target(self) -> None:
        """`which export` fails, and should: the shell runs it, there is no file.

        Looking the first word up on PATH called every working script broken, and
        doctor exited 1 on a registry where nothing was wrong.
        """
        self.write_entry("scripted", 'export GREETING=hi\n/bin/echo "$GREETING"')
        self.write_entry("assigned", "GREETING=hi /bin/echo ran")
        self.write_entry("builtin", "cd /tmp")

        with self.subTest("none of them is reported, and doctor passes"):
            result = self.run_cli("doctor")
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertNotIn("target missing", result.stdout)

        with self.subTest("skipped because they work, not because they are hidden"):
            # If the check were merely silenced, these would still be broken. They
            # are not: the shell runs each one.
            self.assertEqual(self.run_cli("scripted").stdout.strip(), "hi")
            self.assertEqual(self.run_cli("assigned").stdout.strip(), "ran")
            self.assertEqual(self.run_cli("builtin").returncode, 0)

        with self.subTest("a target that really is missing is still reported"):
            # The risk in skipping is skipping too much.
            self.write_entry("absent", "definitely-not-a-real-binary-xyz --run")
            result = self.run_cli("doctor")
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn("target missing on PATH: definitely-not-a-real-binary-xyz",
                          result.stdout)

    def test_a_command_the_shell_cannot_parse_is_reported_before_it_is_run(self) -> None:
        """Appending `"$@"` after `done` is a syntax error the stored command does
        not have on its own, so the check has to run on the assembled body.

        `sh -n` parses and exits; it never executes. Asking the shell rather than
        guessing which endings are safe to append to is the point -- the guess was
        wrong twice.
        """
        # Malformed even as written, because it places $@ itself and is still
        # missing its `done` -- nothing clihub does can make this run.
        self.write_entry("broken", 'for i in "$@"; do /bin/echo $i')
        self.write_entry("loop", "for i in 1 2; do /bin/echo $i; done")
        self.write_entry("placed", 'for i in "$@"; do /bin/echo $i; done')
        self.write_entry("plain", "/bin/echo hi")

        result = self.run_cli("doctor")

        with self.subTest("the one that cannot run is broken, and says why"):
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn("will not parse", result.stdout)

        with self.subTest("one that runs but cannot take arguments is advisory"):
            # It works; it just has nowhere to put a tail. Not a reason to fail.
            self.assertIn("takes no arguments", result.stdout)

        with self.subTest("and the two that are fine are named in neither list"):
            for name in ("placed", "plain"):
                self.assertNotIn(f"  {name} ", result.stdout)

        with self.subTest("doctor's verdict matches what running them does"):
            self.assertEqual(self.run_cli("placed", "A", "B").stdout.split(), ["A", "B"])
            self.assertEqual(self.run_cli("plain", "X").stdout.strip(), "hi X")
            self.assertEqual(self.run_cli("loop").returncode, 0)        # no tail: fine
            self.assertEqual(self.run_cli("loop", "X").returncode, 126)  # tail: refused
            self.assertNotEqual(self.run_cli("broken").returncode, 0)

        with self.subTest("syntax is named among the checks"):
            self.assertIn("syntax", self.run_cli("doctor", "--help").stdout)

        with self.subTest("nothing was executed to find out"):
            # `sh -n` must not run the command. A side effect would prove it did.
            witness = self.base / "witness"
            self.write_entry("effect", f"/usr/bin/touch {witness} && /bin/echo done")
            self.run_cli("doctor")
            self.assertFalse(witness.exists(), "doctor executed a registered command")

    def test_doctor_separates_broken_from_advisory(self) -> None:
        """Exit code is the contract: broken fails, advisory does not.

        Doctor is worth putting in a script only if "this cannot run" and "you may
        want to look at this" are distinguishable without reading the text.
        """
        good = self.write_router_tool("good.py", "good")
        self.run_cli("registry", "add", "fine", "--", str(good))

        with self.subTest("a healthy registry says what it checked"):
            result = self.run_cli("doctor")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("1 entry", result.stdout)
            self.assertIn("checked:", result.stdout)

        with self.subTest("an advisory alone does not fail"):
            # Two names, one command: deliberate multi-membership, allowed by design.
            self.run_cli("registry", "add", "alias", "--", str(good))
            result = self.run_cli("doctor")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("advisory", result.stdout)

        with self.subTest("a target that cannot run fails"):
            self.write_entry("gone", str(self.tools_root / "not-there"))
            result = self.run_cli("doctor")
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn("broken", result.stdout)
            self.assertIn("target missing", result.stdout)

    def test_registry_validate_is_the_same_check_without_the_setup(self) -> None:
        tool = self.write_router_tool("v.py", "v")
        self.run_cli("registry", "add", "fine", "--", str(tool))

        with self.subTest("clean"):
            result = self.run_cli("registry", "validate")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("checked:", result.stdout)

        with self.subTest("broken entry fails here too"):
            self.write_entry("gone", str(self.tools_root / "not-there"))
            result = self.run_cli("registry", "validate")
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn("target missing", result.stdout)

        with self.subTest("but it does not run clihub's setup checks"):
            # That is the difference from `ch doctor`, and why both exist.
            self.assertNotIn("PATH", self.run_cli("registry", "validate").stdout)

    def test_self_management_survives_a_broken_registry(self) -> None:
        """The commands you fix a registry with cannot need the registry to parse,
        or a hand-edit typo leaves no way back but editing the file that broke."""
        self.registry_file.parent.mkdir(parents=True, exist_ok=True)
        self.registry_file.write_text("this is not toml [[[\n", encoding="utf-8")

        with self.subTest("init still works"):
            self.assertEqual(self.run_cli("init", "--no-link").returncode, 0)

        with self.subTest("doctor reports the breakage instead of hitting it"):
            result = self.run_cli("doctor")
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn("registry.toml", result.stdout)
            self.assertIn("Expected", result.stdout)

        with self.subTest("commands that need the registry say where to look"):
            result = self.run_cli("list")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("cannot parse", result.stderr)
            self.assertIn("ch doctor", result.stderr)

    def test_doctor_checks_that_completion_is_wired_up_not_just_current(self) -> None:
        """A script whose word list matches the registry exactly is still dead if
        nothing sources it, so freshness is the least useful thing to check."""
        tool = self.write_router_tool("c.py", "c")
        self.run_cli("registry", "add", "noted","--", str(tool))
        script = self.clihub_home / "completion.zsh"
        rc = Path(self.env["HOME"]) / ".zshrc"

        with self.subTest("a correct install is quiet"):
            self.assertEqual(self.run_cli("tools", "completion").returncode, 0)
            self.assertNotIn("completion.zsh", self.run_cli("doctor").stdout)

        with self.subTest("script present, nothing sources it"):
            rc.write_text("# emptied\n", encoding="utf-8")
            self.assertIn("nothing in", self.run_cli("doctor").stdout)

        with self.subTest("rc sources a script that is not there"):
            self.run_cli("tools", "completion")
            script.unlink()
            self.assertIn("is not there", self.run_cli("doctor").stdout)

        with self.subTest("rc points at a path we no longer use"):
            self.run_cli("tools", "completion")
            rc.write_text(f'source "/somewhere/else/completion.zsh"  # clihub completions\n',
                          encoding="utf-8")
            self.assertIn("different path", self.run_cli("doctor").stdout)

    def test_a_hand_written_name_the_add_command_would_refuse_is_reported(self) -> None:
        """load() builds entries from raw text, so a hand-written name `add` would
        reject still works. doctor reports it.

        Advisory rather than broken: it runs, so it is a registry written wrong
        rather than clihub failing.
        """
        self.registry_file.parent.mkdir(parents=True, exist_ok=True)
        self.registry_file.write_text(
            '[Mail]\ncommand = "/bin/echo Mail"\n\n[ok]\n[ok."bad.name"]\ncommand = "/bin/echo badname"\n',
            encoding="utf-8",
        )

        with self.subTest("add refuses these names in the first place"):
            self.assertNotEqual(
                self.run_cli("registry", "add", "Mail", "--", "/bin/echo").returncode, 0)
            self.assertNotEqual(
                self.run_cli("registry", "add", "a.b.c", "--", "/bin/echo").returncode, 0)

        with self.subTest("doctor names both, and stays exit 0"):
            result = self.run_cli("doctor")
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertIn("Mail", result.stdout)
            self.assertIn("ok.bad.name", result.stdout)

        with self.subTest("the wording says command, not namespace or tool (N4a)"):
            result = self.run_cli("doctor")
            self.assertIn("invalid command name", result.stdout)
            self.assertNotIn("invalid namespace", result.stdout)
            self.assertNotIn("invalid tool", result.stdout)

        with self.subTest("they still dispatch; this is advice, not enforcement"):
            self.assertEqual(self.run_cli("Mail").stdout.strip(), "Mail")

    def test_self_management_survives_a_registry_that_will_not_parse(self) -> None:
        """You can fix clihub with clihub: a registry that will not parse must not
        stop `tools completion`, `init` or `doctor`."""
        self.registry_file.parent.mkdir(parents=True, exist_ok=True)
        self.registry_file.write_text("not toml at all\n[[[\n", encoding="utf-8")

        with self.subTest("completion still installs, on builtins alone"):
            result = self.run_cli("tools", "completion", "--print", "zsh")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("doctor", result.stdout)
            self.assertIn("registry", result.stdout)

        with self.subTest("init still runs"):
            result = self.run_cli("init", "--no-link", "--completions")
            self.assertEqual(result.returncode, 0, result.stderr)

        with self.subTest("doctor still reports rather than hitting it"):
            result = self.run_cli("doctor")
            self.assertEqual(result.returncode, 1)
            self.assertIn("registry.toml", result.stdout)

    def test_a_config_that_will_not_parse_is_broken_not_advisory(self) -> None:
        """Nothing stops working, but nothing you wrote in it applies either.

        A single unreachable entry exits 1. A config file discarded whole -- every
        key in it silently inert -- should not be the quieter of the two.
        """
        tool = self.write_router_tool("c.py", "c")
        self.run_cli("registry", "add", "fine","--", str(tool))

        with self.subTest("a good config is silent"):
            self.config_file.write_text("[describe]\ntimeout_seconds = 1.0\n", encoding="utf-8")
            self.assertEqual(self.run_cli("doctor").returncode, 0)

        with self.subTest("a duplicated section is broken, and exits 1"):
            # The real mistake: appending a section the generated file already has.
            self.config_file.write_text(
                "[describe]\ntimeout_seconds = 1.0\n\n[describe]\ntimeout_seconds = 2.0\n",
                encoding="utf-8",
            )
            result = self.run_cli("doctor")
            self.assertEqual(result.returncode, 1)
            self.assertIn("will not parse", result.stdout)

        with self.subTest("but dispatch still works, on the shipped defaults"):
            self.assertEqual(self.run_cli("fine").returncode, 0)

    def test_a_bare_name_only_an_environment_provides_is_called_out(self) -> None:
        """A name only a venv provides works here and nowhere else, so adding it
        warns. One PATH hit, not two -- the dangerous shape is that no binary wins
        elsewhere, not that a different one does.
        """
        venv = self.tools_root / "fakevenv"
        (venv / "bin").mkdir(parents=True, exist_ok=True)
        only_here = venv / "bin" / "venvonly"
        only_here.write_text(f"#!{PYTHON}\nprint('from the venv')\n")
        only_here.chmod(0o755)
        env = {**self.env,
               "VIRTUAL_ENV": str(venv),
               "PATH": f"{venv / 'bin'}{os.pathsep}{self.env['PATH']}"}

        def cli(*args: str, using: dict) -> subprocess.CompletedProcess[str]:
            return subprocess.run([PYTHON, "-m", "clihub", *args], cwd=ROOT, env=using,
                                  text=True, capture_output=True, timeout=5.0)

        with self.subTest("adding it warns that nowhere else has it"):
            result = cli("registry", "add", "vo", "--", "venvonly", using=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("only exists in $VIRTUAL_ENV", result.stderr)

        with self.subTest("it runs inside, and fails with 126 outside"):
            self.assertEqual(cli("vo", using=env).stdout.strip(), "from the venv")
            # 127, the shell's code for "command not found" -- the cost of
            # dispatching through sh, accepted when the model changed.
            self.assertEqual(cli("vo", using=self.env).returncode, 127)

        with self.subTest("a stable name with copies on PATH says nothing"):
            result = cli("registry", "add", "quiet", "--", "echo", using=self.env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("only exists in", result.stderr)
            self.assertNotIn("depends on where", result.stderr)

        with self.subTest("validate repeats it as advisory, and exits 0"):
            result = cli("registry", "validate", using=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("only in $VIRTUAL_ENV", result.stdout)

        with self.subTest("outside the venv the same entry is broken, not advisory"):
            result = cli("doctor", using=self.env)
            self.assertEqual(result.returncode, 1)
            self.assertIn("target missing on PATH: venvonly", result.stdout)

    def test_a_permanent_path_directory_under_cwd_is_not_called_transient(self) -> None:
        """An absolute PATH entry is stable wherever you are standing, even when
        the cwd is its ancestor -- run from $HOME, that covers ~/.local/bin.

        Only declared environments and relative PATH entries count as transient.
        """
        stable_dir = self.tools_root / "stable-bin"
        stable_dir.mkdir(parents=True, exist_ok=True)
        tool = stable_dir / "steady"
        tool.write_text(f"#!{PYTHON}\nprint('steady')\n")
        tool.chmod(0o755)

        # Both sides realpath'd: /tmp is a symlink to /private/tmp here, so
        # otherwise the PATH entry and os.getcwd() share no prefix and this test
        # passes against the bug it exists to catch.
        stable_dir = Path(os.path.realpath(stable_dir))
        working = os.path.realpath(self.tools_root)
        env = {**self.env, "PATH": f"{stable_dir}{os.pathsep}{self.env['PATH']}"}
        result = subprocess.run([PYTHON, "-m", "clihub", "registry", "add", "st", "--", "steady"],
                                cwd=working, env=env, text=True,
                                capture_output=True, timeout=5.0)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("will fail anywhere else", result.stderr)
        self.assertNotIn("depends on where", result.stderr)
