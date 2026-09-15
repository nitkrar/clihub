from __future__ import annotations

import json
import os
import signal
import subprocess
import textwrap
import time

from .fixture import PYTHON, ROOT, ClihubFixture


class DispatchTests(ClihubFixture):
    """Running a registered command: what reaches the tool, and what comes back."""

    def test_exit_code_propagation_and_signal_mapping(self) -> None:
        exit_tool = self.write_router_tool("exit7.py", "exiter", behavior="raise SystemExit(7)")
        term_tool = self.write_router_tool(
            "term.py",
            "term",
            behavior=textwrap.dedent(
                """
                import os
                import signal

                os.kill(os.getpid(), signal.SIGTERM)
                """
            ).strip(),
        )

        result = self.run_cli("registry", "add", "exiter", "--", str(exit_tool))
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.run_cli("exiter")
        self.assertEqual(result.returncode, 7)

        result = self.run_cli("registry", "add", "term", "--", str(term_tool))
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.run_cli("term")
        self.assertEqual(result.returncode, 143)

    def test_the_documented_exit_codes_are_the_ones_returned(self) -> None:
        """The table in the README and design.md, held to the running code.

        It had drifted: both promised 126 for a target found but not executable
        and 127 for one missing, which is true of `sh -c` and false of `sh -ec`.
        `-e` returns 1 for either when the target is written as a path.
        """
        missing = self.tools_root / "deleted-since"
        unreadable = self.write_tool("notexec.py", "print('x')")
        unreadable.chmod(0o644)

        self.write_entry("gone", str(missing))
        self.write_entry("notexec", str(unreadable))
        self.write_entry("bare", "definitely-not-a-binary-xyz")
        # Malformed *and* placing $@ itself, so it is used as written and the
        # shell is the one that objects.
        self.write_entry("badsyntax", 'for i in "$@"; do /bin/echo $i')
        self.write_entry("empty", "")

        # A path target's code is the shell's, and the two `sh` implementations
        # disagree: bash under -e collapses both to 1, dash keeps the POSIX
        # 127/126. Whichever runs, clihub passes it through untouched, which is
        # the actual contract -- so both are accepted and the table lists both.
        for name, expected, why in (
            ("gone", (1, 127), "a missing path: 1 under bash -e, 127 under dash"),
            ("notexec", (1, 126), "a non-executable path: 1 under bash -e, 126 under dash"),
            ("bare", (127,), "a bare name keeps the shell's not-found"),
            ("badsyntax", (2,), "the shell cannot parse it"),
            ("empty", (126,), "not a command line at all, decided before any shell"),
        ):
            with self.subTest(f"{name}: {why}"):
                self.assertIn(self.run_cli(name).returncode, expected)

        with self.subTest("an unknown name is 127, like the shell's"):
            self.assertEqual(self.run_cli("no-such-command").returncode, 127)

        with self.subTest("a usage error is 2"):
            self.assertEqual(self.run_cli("registry", "add").returncode, 2)

    def test_sigint_child_exit_and_ignore_behavior(self) -> None:
        interrupted_tool = self.write_router_tool(
            "interrupt.py",
            "interrupt",
            behavior=textwrap.dedent(
                """
                import sys
                import time

                # Signalled on this line, not after a sleep: SIGINT during
                # clihub's own startup kills it before it can map 130.
                sys.stderr.write("ready\\n")
                sys.stderr.flush()
                time.sleep(5)
                """
            ).strip(),
        )
        ignore_tool = self.write_router_tool(
            "ignore.py",
            "ignore",
            behavior=textwrap.dedent(
                """
                import signal
                import sys
                import time

                signal.signal(signal.SIGINT, signal.SIG_IGN)
                # Announce that the handler is installed, so the test signals when
                # the child is actually ready rather than after a guessed delay.
                # Sleeping 0.4s and signalling at 0.2s passed alone and failed under
                # full-suite load, which is a flake, not a behaviour.
                sys.stderr.write("ready\\n")
                sys.stderr.flush()
                time.sleep(0.6)
                print("survived")
                """
            ).strip(),
        )

        result = self.run_cli("registry", "add", "interrupt", "--", str(interrupted_tool))
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.run_cli("registry", "add", "ignore", "--", str(ignore_tool))
        self.assertEqual(result.returncode, 0, result.stderr)

        proc = self.start_cli("interrupt")
        self.assertEqual(proc.stderr.readline().strip(), "ready")
        os.killpg(os.getpgid(proc.pid), signal.SIGINT)
        stdout, stderr = proc.communicate(timeout=5)
        self.assertEqual(proc.returncode, 130, stderr)
        self.assertEqual(stdout, "")

        # A tool that ignores SIGINT is not killed by clihub. What clihub then
        # *reports* depends on whether `sh` is still in the process tree: bash
        # execs a simple command and is gone, so the tool's own 0 comes back;
        # dash stays, takes the signal, and dies, so clihub reports 130 for a
        # tool that in fact survived. Both are the shell's answer, passed
        # through -- clihub never kills the child either way.
        proc = self.start_cli("ignore")
        self.assertEqual(proc.stderr.readline().strip(), "ready")   # handler installed
        os.killpg(os.getpgid(proc.pid), signal.SIGINT)
        stdout, stderr = proc.communicate(timeout=5)
        self.assertIn(proc.returncode, (0, 130), stderr)
        if proc.returncode == 0:
            self.assertEqual(stdout.strip(), "survived")

    def test_a_builtin_always_wins_over_a_registered_name(self) -> None:
        """A registry that could shadow `doctor` could make itself unfixable, so
        the builtin wins and the entry is reported as unreachable."""
        tool = self.write_router_tool("shadow.py", "shadow", behavior='print("THE TOOL RAN")')
        self.run_cli("registry", "add", "notes", "--", str(tool))

        with self.subTest("tools add refuses a reserved name outright"):
            result = self.run_cli("registry", "add", "list", "--", str(tool))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("reserved", result.stderr)

        # Hand-written, because `tools add` is what normally prevents this.
        self.write_entry("list", str(tool))

        with self.subTest("the builtin runs, not the entry"):
            result = self.run_cli("list")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("THE TOOL RAN", result.stdout)
            self.assertIn("notes", result.stdout)

        with self.subTest("and says the entry is unreachable, naming the fix"):
            self.assertIn("builtin name", self.run_cli("list").stderr)
            self.assertIn("registry remove list", self.run_cli("list").stderr)

        with self.subTest("the shadowed entry is not offered as a tool"):
            self.assertNotIn("THE TOOL RAN", self.run_cli("find", "list").stdout)

    def test_an_unknown_name_is_127_whichever_command_asks(self) -> None:
        """127 means "no such name", whichever command was asked.

        A caller handling "command not found" should not need a second vocabulary
        per clihub command.
        """
        tool = self.write_router_tool("real.py", "real")
        # A grouping namespace: tools but no .command, so nothing to fall through to.
        # (With a .command, `ch grp nosuch` correctly dispatches instead of failing.)
        self.run_cli("registry", "add", "grp.leaf", "--", str(tool))
        for argv in (
            ("nosuch",),
            ("help", "nosuch"),
            ("list", "nosuch"),
            ("registry", "show", "nosuch"),
            ("registry", "remove", "nosuch"),
            ("grp", "nosuch"),           # known namespace, no such tool
        ):
            with self.subTest(" ".join(argv)):
                self.assertEqual(self.run_cli(*argv).returncode, 127)

    def test_arguments_are_appended_only_where_that_means_arguments(self) -> None:
        """`"$@"` is appended only to a single simple command.

        Anywhere else the end of the text is not an argument position — inside a
        comment, after a here-doc terminator, past a pipe, beyond a `done` — and
        four separate bugs came from appending there anyway. Each one was silent:
        exit 0, arguments gone.
        """
        self.registry_file.parent.mkdir(parents=True, exist_ok=True)
        self.registry_file.write_text(
            # A trailing `\` inside `"""` is TOML's own continuation and is joined
            # before clihub sees it, so `joined` is one line by the time we look.
            '[joined]\ncommand = """\n/bin/echo one \\\n  two\n"""\n\n'
            '[stacked]\ncommand = """\n/bin/echo first\n/bin/echo second\n"""\n\n'
            "[heredoc]\ncommand = \"\"\"\ncat <<'END'\nhello\nEND\n\"\"\"\n\n"
            '[commented]\ncommand = "/bin/echo before # trailing comment"\n\n'
            '[piped]\ncommand = "/bin/echo hello | /usr/bin/tr a-z A-Z"\n\n'
            '[placed]\ncommand = \'for i in "$@"; do /bin/echo $i; done\'\n',
            encoding="utf-8",
        )

        with self.subTest("one simple command takes them"):
            result = self.run_cli("joined", "ARG")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "one two ARG")

        with self.subTest("a command that places $@ itself takes them anywhere"):
            result = self.run_cli("placed", "A", "B")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.split(), ["A", "B"])

        for name in ("stacked", "heredoc", "commented", "piped"):
            with self.subTest(f"{name}: refused rather than silently dropped"):
                result = self.run_cli(name, "ARG")
                self.assertEqual(result.returncode, 126, result.stdout)
                self.assertIn("does not say where arguments go", result.stderr)
                self.assertNotIn("ARG", result.stdout)

        for name in ("stacked", "heredoc", "commented", "piped"):
            with self.subTest(f"{name}: still runs when given nothing to pass"):
                result = self.run_cli(name)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn('"$@"', result.stdout)

    def test_a_command_may_be_a_string_or_an_argv_list(self) -> None:
        """TOML can express both, so someone will write both.

        The same distinction Docker draws between `RUN cmd` and `RUN ["cmd"]`: a
        string is a command line and gets split; a list is already argv and is
        taken as written -- which is also how a path with spaces arrives without
        anyone having to quote it. clihub only ever *writes* the string form.
        """
        spaced = self.tools_root / "My Tools"
        spaced.mkdir(parents=True, exist_ok=True)
        tool = self.write_tool("sp.py", 'import sys; print(" ".join(sys.argv[1:]))',
                               directory=spaced)
        self.registry_file.parent.mkdir(parents=True, exist_ok=True)
        self.registry_file.write_text(
            # `print(1)` is quoted because the command is shell source now, and
            # parentheses are shell syntax -- the same quoting you would type.
            f"""[asstring]\ncommand = {json.dumps(PYTHON + " -c 'print(1)'")}\n\n"""
            f'[asarray]\ncommand = [{json.dumps(str(tool))}, "--flag"]\n\n'
            f'[wrongtype]\ncommand = 42\n',
            encoding="utf-8",
        )

        with self.subTest("a string is a shell command line"):
            self.assertEqual(self.run_cli("asstring").stdout.strip(), "1")

        with self.subTest("a list is argv already, spaces in the path and all"):
            result = self.run_cli("asarray", "extra")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "--flag extra")

        with self.subTest("anything else is refused by name, not by traceback"):
            result = self.run_cli("wrongtype")
            self.assertEqual(result.returncode, 126)
            self.assertIn("must be a string or a list", result.stderr)

        with self.subTest("doctor does not accuse a list of bad quoting"):
            # The `quoting` check looks for an unquoted space; a list cannot have one.
            self.assertNotIn("unquoted path", self.run_cli("doctor").stdout)

    def test_the_first_word_is_the_whole_command_name(self) -> None:
        """Everything after the command is an argument, whatever else is registered.

        The two targets differ on purpose: sharing one would make pass-through and
        resolution produce identical output, and the test could not fail.
        """
        group = self.write_router_tool("group.py", "group", behavior='print(json.dumps(["GROUP", *args]))')
        leaf = self.write_router_tool("leaf.py", "leaf", behavior='print(json.dumps(["LEAF", *args]))')
        self.run_cli("registry", "add", "llm","--describe", "the stack", "--", str(group))
        self.run_cli("registry", "add", "llm.llama","--describe", "models", "--", str(leaf))

        with self.subTest("the dotted name reaches the tool"):
            self.assertEqual(json.loads(self.run_cli("llm.llama", "start").stdout),
                             ["LEAF", "start"])

        with self.subTest("the spaced form does NOT -- it is an argument now"):
            self.assertEqual(json.loads(self.run_cli("llm", "llama", "start").stdout),
                             ["GROUP", "llama", "start"])

        with self.subTest("any other word behaves identically, so meaning is stable"):
            self.assertEqual(json.loads(self.run_cli("llm", "up").stdout), ["GROUP", "up"])

        with self.subTest("a bare command with .command runs it"):
            self.assertEqual(json.loads(self.run_cli("llm").stdout), ["GROUP"])

    def test_grouping_namespace_lists_instead_of_running(self) -> None:
        tool = self.write_router_tool("grouped.py", "grouped")
        self.run_cli("registry", "add", "group.only","--describe", "the only one", "--", str(tool))

        with self.subTest("no .command: the namespace lists what it holds"):
            result = self.run_cli("group")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("group.only", result.stdout)

        with self.subTest("an unknown tool names the level that failed"):
            result = self.run_cli("group", "nosuch")
            self.assertEqual(result.returncode, 127)
            # Named as the command it would have been, which teaches the spelling.
            self.assertIn("unknown command: group", result.stderr)
            # Deliberately not a list of what the group holds: that grows past the
            # listing it stands in for.
            self.assertNotIn("group.only", result.stderr)

    def test_a_bare_name_is_a_path_lookup_not_a_relative_path(self) -> None:
        """`-- echo` means the echo your shell would run, not ./echo."""
        with self.subTest("a bare name is stored bare, not glued to cwd"):
            result = self.run_cli("registry", "add", "say", "--", "echo")
            self.assertEqual(result.returncode, 0, result.stderr)
            stored = self.registry_file.read_text(encoding="utf-8")
            self.assertIn('command = "echo"\n', stored)
            self.assertNotIn(str(ROOT), stored)
            self.assertEqual(self.run_cli("say", "hello").stdout.strip(), "hello")

        with self.subTest("and it resolves through PATH at dispatch, not at add"):
            # The point of keeping the name bare: whichever one is in front at run
            # time is the one that runs, so an activated venv wins. Storing what
            # `which` returned at add time would pin the first one forever.
            #
            # Deliberately not `echo`: the shell resolves builtins before PATH, so
            # echo, test, printf, pwd and kill are answered by sh itself and can
            # never demonstrate a PATH lookup.
            shadow_dir = self.tools_root / "shadow"
            shadow_dir.mkdir(parents=True, exist_ok=True)
            shadow = shadow_dir / "notabuiltin"
            shadow.write_text(f"#!{PYTHON}\nprint('shadowed')\n")
            shadow.chmod(0o755)
            # Registered with the shadow dir on PATH, since `add` checks the name
            # exists; then dispatched with the same PATH so the shadow is what runs.
            widened = {**self.env, "PATH": f"{shadow_dir}{os.pathsep}{self.env['PATH']}"}
            added = subprocess.run(
                [PYTHON, "-m", "clihub", "registry", "add", "probe","--", "notabuiltin"],
                cwd=ROOT, text=True, capture_output=True, timeout=5.0, env=widened,
            )
            self.assertEqual(added.returncode, 0, added.stderr)
            self.assertIn('command = "notabuiltin"', self.registry_file.read_text())
            shadowed = subprocess.run(
                [PYTHON, "-m", "clihub", "probe"],
                cwd=ROOT, text=True, capture_output=True, timeout=5.0, env=widened,
            )
            self.assertEqual(shadowed.stdout.strip(), "shadowed")

        with self.subTest("a path with a separator is still resolved as a path"):
            tool = self.write_router_tool("rel.py", "rel")
            result = self.run_cli("registry", "add", "rel", "--", str(tool))
            self.assertEqual(result.returncode, 0, result.stderr)

        with self.subTest("a name on neither PATH nor disk says which, and is kept"):
            # Warned, not refused: a bare name resolves at dispatch, so "missing
            # here" is not "missing". doctor is where it counts as broken.
            result = self.run_cli("registry", "add", "nope", "--", "definitely-not-a-binary")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("not found on PATH", result.stderr)
            self.assertNotEqual(self.run_cli("doctor").returncode, 0)
