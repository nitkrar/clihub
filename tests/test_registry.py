from __future__ import annotations

import json
import os
import subprocess
import textwrap
from pathlib import Path

from .fixture import PYTHON, ClihubFixture


class RegistryTests(ClihubFixture):
    """Editing the registry: add, edit, remove, show, export."""

    def test_parse_table_cases(self) -> None:
        echo_tool = self.write_router_tool("echo.py", "echo")

        with self.subTest("normal fixed-args dispatch"):
            result = self.run_cli("registry", "add", "llama", "--", str(echo_tool), "llama")
            self.assertEqual(result.returncode, 0, result.stderr)
            result = self.run_cli("llama", "start", "chat")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), ["llama", "start", "chat"])

        with self.subTest("empty command is 126"):
            self.write_entry("empty", "")
            result = self.run_cli("empty")
            self.assertEqual(result.returncode, 126)

        with self.subTest("whitespace command is 126"):
            self.write_entry("whitespace", "   ")
            result = self.run_cli("whitespace")
            self.assertEqual(result.returncode, 126)

        with self.subTest("tools add quotes paths with spaces"):
            spaced_dir = self.tools_root / "My Tools"
            spaced_tool = self.write_router_tool("space.py", "space", directory=spaced_dir)
            result = self.run_cli("registry", "add", "spacey", "--", str(spaced_tool), "fixed")
            self.assertEqual(result.returncode, 0, result.stderr)
            result = self.run_cli("spacey", "tail")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), ["fixed", "tail"])

        with self.subTest("unbalanced quotes are a shell syntax error, named"):
            # The shell reports it, and $0 is the clihub name, so the message
            # says which entry is malformed rather than an anonymous `sh:`.
            self.write_entry("brokenquote", f'{echo_tool} "llama')
            result = self.run_cli("brokenquote")
            self.assertEqual(result.returncode, 2)
            self.assertIn("ch brokenquote", result.stderr)

        with self.subTest("hash remains literal"):
            # Inline '#' comments are deliberately disabled for the registry, unlike
            # config.toml: a path may contain a '#' and would otherwise truncate.
            hashed_dir = self.tools_root / "we#ird"
            hashed_tool = self.write_router_tool("hash.py", "hash", directory=hashed_dir)
            self.write_entry("hashy", str(hashed_tool))
            result = self.run_cli("hashy", "tail")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), ["tail"])

    def test_a_rewritten_path_is_announced_and_an_unchanged_one_is_not(self) -> None:
        """A relative path is the only target whose stored text differs from what
        was typed. Silent, it reads as though `./bin/tool` was kept -- which would
        mean a different file from every directory."""
        tool = self.write_router_tool("rel.py", "rel")
        here = tool.parent

        with self.subTest("relative: says what it stored, and why"):
            result = subprocess.run(
                [PYTHON, "-m", "clihub", "registry", "add", "rel",
                 "--describe", "a relative path entry", "--", "./rel.py"],
                cwd=here, env=self.env, text=True, capture_output=True, timeout=5,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("./rel.py: stored as", result.stderr)
            self.assertIn("you will not be here later", result.stderr)
            self.assertIn(str(tool.resolve()), self.run_cli("registry", "show", "rel").stdout)

        with self.subTest("absolute: nothing was rewritten, so nothing is said"):
            result = self.run_cli("registry", "add", "abs",
                                  "--describe", "an absolute path entry", "--", str(tool))
            self.assertNotIn("stored as", result.stderr)

        with self.subTest("bare: kept as written, so nothing is said"):
            widened = {**self.env, "PATH": f"{here}{os.pathsep}{self.env['PATH']}"}
            result = subprocess.run(
                [PYTHON, "-m", "clihub", "registry", "add", "bare",
                 "--describe", "a bare name entry", "--", "rel.py"],
                cwd=here, env=widened, text=True, capture_output=True, timeout=5,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("stored as", result.stderr)
            self.assertIn('command = "rel.py"',
                          self.run_cli("registry", "show", "bare").stdout)

    def test_add_and_doctor_agree_on_what_a_legal_command_is(self) -> None:
        """Both ask the same question of a command's first word, from the same
        function. Relaxed in one and not the other, `add` refuses what doctor
        calls fine, and the registry has two definitions of legal.
        """
        with self.subTest("a word the shell runs itself is accepted by both"):
            result = self.run_cli("registry", "add", "envd",
                                  "--describe", "an assignment prefix then echo",
                                  "--", "V=1", "/bin/echo", "hi")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(self.run_cli("envd", "ARG").stdout.strip(), "hi ARG")
            report = self.run_cli("doctor")
            self.assertEqual(report.returncode, 0, report.stdout)
            self.assertNotIn("envd", report.stdout)

        with self.subTest("a target that is not here is said, not refused"):
            # It may be installed later, or live in a venv you are not standing in.
            result = self.run_cli("registry", "add", "typo",
                                  "--describe", "a misspelt binary name", "--", "jqq")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("not found on PATH: jqq", result.stderr)
            self.assertIn('command = "jqq"',
                          self.run_cli("registry", "show", "typo").stdout)
            self.assertNotEqual(self.run_cli("doctor").returncode, 0)

        with self.subTest("a command the shell cannot parse is refused outright"):
            # No install and no change of PATH will ever make this run, which is
            # what separates it from a target that is merely absent.
            result = self.run_cli("registry", "add", "bad",
                                  "--describe", "a keyword that cannot parse",
                                  "--", "done", "--flag")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("will not parse", result.stderr)
            self.assertIn("unknown command", self.run_cli("registry", "show", "bad").stderr)

    def test_tools_add_refuses_to_clobber_without_force(self) -> None:
        first_tool = self.write_router_tool("first.py", "mail", behavior='print("first")')
        second_tool = self.write_router_tool("second.py", "mail", behavior='print("second")')

        result = self.run_cli("registry", "add", "mail", "--", str(first_tool))
        self.assertEqual(result.returncode, 0, result.stderr)

        result = self.run_cli("registry", "add", "mail", "--", str(second_tool))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("already registered", result.stderr)

        result = self.run_cli("mail")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "first")

        result = self.run_cli("registry", "add", "mail", "--force", "--", str(second_tool))
        self.assertEqual(result.returncode, 0, result.stderr)

        result = self.run_cli("mail")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "second")

    def test_edit_changes_one_thing_and_leaves_the_rest(self) -> None:
        """The half `add --force` is not: force replaces an entry whole."""
        first = self.write_router_tool("e1.py", "e1")
        second = self.write_router_tool("e2.py", "e2")
        self.run_cli("registry", "add", "llm.llama","--describe", "run models",
                     "--", str(first))

        with self.subTest("a new command keeps the description"):
            self.run_cli("registry", "edit", "llm.llama", "--", str(second))
            shown = self.run_cli("registry", "show", "llm.llama").stdout
            self.assertIn("run models", shown)
            self.assertIn("e2.py", shown)

        with self.subTest("a new description keeps the command"):
            self.run_cli("registry", "edit", "llm.llama", "--describe", "changed")
            shown = self.run_cli("registry", "show", "llm.llama").stdout
            self.assertIn("changed", shown)
            self.assertIn("e2.py", shown)

        with self.subTest("an empty description clears it"):
            self.run_cli("registry", "edit", "llm.llama", "--describe", "")
            self.assertNotIn("changed", self.run_cli("registry", "show", "llm.llama").stdout)

    def test_rename_moves_a_name_but_never_between_groups(self) -> None:
        tool = self.write_router_tool("r.py", "r")
        self.run_cli("registry", "add", "llm.llama","--describe", "models", "--", str(tool))
        self.run_cli("registry", "add", "llm","--describe", "the stack", "--", str(tool))

        with self.subTest("a command renames within its group, keeping its description"):
            self.assertEqual(self.run_cli("registry", "edit", "llm.llama",
                                          "--name", "llm.serve").returncode, 0)
            shown = self.run_cli("registry", "show", "llm").stdout
            self.assertIn("[llm.serve]", shown)
            self.assertIn("models", shown)
            self.assertNotIn("llama", shown)

        with self.subTest("renaming a group takes its commands with it"):
            # Which is the thing a group is for.
            self.assertEqual(self.run_cli("registry", "edit", "llm",
                                          "--name", "models").returncode, 0)
            listing = self.run_cli("list").stdout
            self.assertIn("models.serve", listing)
            self.assertNotIn("llm", listing)

        with self.subTest("across groups is a move, and refused"):
            result = self.run_cli("registry", "edit", "models.serve", "--name", "repo.serve")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("between groups", result.stderr)

        with self.subTest("a group and a command are different shapes"):
            result = self.run_cli("registry", "edit", "models.serve", "--name", "plain")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("different shapes", result.stderr)

        with self.subTest("renaming onto a taken name is refused, not merged"):
            self.run_cli("registry", "add", "models.taken","--", str(tool))
            result = self.run_cli("registry", "edit", "models.serve", "--name", "models.taken")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("already registered", result.stderr)

        with self.subTest("editing nothing is a usage error, not a silent success"):
            self.assertEqual(self.run_cli("registry", "edit", "models.serve").returncode, 2)

    def test_export_copies_the_file_rather_than_regenerating_it(self) -> None:
        tool = self.write_router_tool("x.py", "x")
        self.run_cli("registry", "add", "jq","--describe", "filter JSON", "--", str(tool))
        out = self.base / "out"
        out.mkdir()

        with self.subTest("a directory means: put registry.toml in here"):
            self.assertEqual(self.run_cli("registry", "export", str(out)).returncode, 0)
            self.assertEqual((out / "registry.toml").read_bytes(),
                             self.registry_file.read_bytes())

        with self.subTest("anything else is the filename to write"):
            named = out / "backup-2026.ini"
            self.run_cli("registry", "export", str(named))
            self.assertEqual(named.read_bytes(), self.registry_file.read_bytes())

        with self.subTest("hand-written comments survive, so it is a copy not a render"):
            # An export that quietly differs from its source is worse than none,
            # so it copies bytes rather than re-rendering through the parser.
            with self.registry_file.open("a", encoding="utf-8") as handle:
                handle.write("\n# a note I added by hand\n")
            self.run_cli("registry", "export", str(out), "--force")
            self.assertIn("# a note I added by hand",
                          (out / "registry.toml").read_text(encoding="utf-8"))

        with self.subTest("an existing file is not replaced without --force"):
            result = self.run_cli("registry", "export", str(out / "backup-2026.ini"))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("already exists", result.stderr)

        with self.subTest("a missing parent directory is named, not created"):
            result = self.run_cli("registry", "export", str(out / "nope" / "x.ini"))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("no such directory", result.stderr)

    def test_export_with_no_argument_writes_here(self) -> None:
        tool = self.write_router_tool("here.py", "here")
        self.run_cli("registry", "add", "jq","--", str(tool))
        landing = self.base / "landing"
        landing.mkdir()

        # run_cli runs from the repo root, so point the command at a directory the
        # test owns rather than letting it write into the source tree.
        result = subprocess.run(
            [PYTHON, "-m", "clihub", "registry", "export"],
            cwd=landing, env=self.env, text=True, capture_output=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((landing / "registry.toml").read_bytes(),
                         self.registry_file.read_bytes())

    def test_show_prints_what_the_file_holds(self) -> None:
        """INI rather than a prettier summary: what you read is what you would edit."""
        tool = self.write_router_tool("s.py", "s")
        self.run_cli("registry", "add", "grp.one","--describe", "the first", "--", str(tool))
        self.run_cli("registry", "add", "grp.two","--describe", "the second", "--", str(tool))
        self.run_cli("registry", "add", "solo","--describe", "on its own", "--", str(tool))

        with self.subTest("a bare name shows the whole group"):
            out = self.run_cli("registry", "show", "grp").stdout
            self.assertIn("[grp]", out)
            self.assertIn("[grp.one]", out)
            self.assertIn("[grp.two]", out)

        with self.subTest("a dotted name shows only that command"):
            out = self.run_cli("registry", "show", "grp.one").stdout
            self.assertIn("[grp.one]", out)
            self.assertNotIn("[grp.two]", out)

        with self.subTest("what it prints appears verbatim in the file"):
            stored = self.registry_file.read_text(encoding="utf-8")
            for line in self.run_cli("registry", "show", "solo").stdout.splitlines():
                if line.strip():
                    self.assertIn(line, stored, line)

        with self.subTest("an unknown name is 127, not an empty success"):
            self.assertEqual(self.run_cli("registry", "show", "nosuch").returncode, 127)
            self.assertEqual(self.run_cli("registry", "show", "grp.nosuch").returncode, 127)

        with self.subTest("an entry that cannot run still shows, and says why"):
            self.write_entry("gone", str(self.tools_root / "not-there"))
            result = self.run_cli("registry", "show", "gone")
            self.assertIn("[gone]", result.stdout)
            self.assertIn("target missing", result.stderr)
            self.assertEqual(result.returncode, 1)

    def test_force_replaces_the_entry_rather_than_just_its_command(self) -> None:
        first = self.write_router_tool("first.py", "first")
        second = self.write_tool("second.py", """
            import sys
            sys.exit(0)
        """)
        self.run_cli("registry", "add", "repoint",
                     "--describe", "describes the FIRST tool", "--", str(first))
        self.assertIn("describes the FIRST tool", self.run_cli("list").stdout)

        # Repointed at a different binary, the old sentence is now a lie.
        self.run_cli("registry", "add", "repoint", "--force", "--", str(second))
        self.assertNotIn("describes the FIRST tool", self.run_cli("list").stdout)

        with self.subTest("an explicit --describe is still honoured"):
            self.run_cli("registry", "add", "repoint", "--force",
                         "--describe", "describes the SECOND tool", "--", str(second))
            self.assertIn("describes the SECOND tool", self.run_cli("list").stdout)

    def test_a_hand_written_comment_survives_a_rewrite(self) -> None:
        """A comment you write in the registry survives clihub rewriting it."""
        tool = self.write_router_tool("c.py", "c")
        self.run_cli("registry", "add", "first","--describe", "one", "--", str(tool))
        annotated = self.registry_file.read_text(encoding="utf-8").replace(
            "[first]", "# do not point this at the 2B\n[first]")
        self.registry_file.write_text(annotated, encoding="utf-8")

        self.run_cli("registry", "add", "second","--describe", "two", "--", str(tool))

        after = self.registry_file.read_text(encoding="utf-8")
        self.assertIn("# do not point this at the 2B", after)
        self.assertIn("[second]", after)

    def test_remove_drops_only_the_entry_named(self) -> None:
        tool = self.write_router_tool("rm.py", "rm")
        self.run_cli("registry", "add", "llm","--describe", "stack", "--", str(tool))
        self.run_cli("registry", "add", "llm.llama","--describe", "models", "--", str(tool), "llama")

        with self.subTest("removing the namespace's command keeps its tools"):
            self.assertEqual(self.run_cli("registry", "remove", "llm").returncode, 0)
            listing = self.run_cli("list").stdout
            self.assertIn("llm.llama", listing)
            self.assertNotIn("\nllm ", listing)

        with self.subTest("removing the last tool removes the namespace"):
            self.assertEqual(self.run_cli("registry", "remove", "llm.llama").returncode, 0)
            self.assertNotIn("llm", self.run_cli("list").stdout)


class ImportTests(ClihubFixture):
    """`ch registry import` merges another registry file into this one."""

    def source_file(self, body: str) -> Path:
        path = self.base / "incoming.toml"
        path.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
        return path

    def test_a_key_is_the_unit_of_merge(self) -> None:
        """Sections are containers, so two files sharing `[llm]` do not disagree.

        Only a key pointing at two different commands does. Replacing a whole
        section would throw away the entries that agreed, for nothing.
        """
        mine = self.write_router_tool("mine.py", "mine")
        theirs = self.write_router_tool("theirs.py", "theirs")
        self.run_cli("registry", "add", "llm.alpha","--", str(mine))
        source = self.source_file(f"""
            [llm.beta]
            command = "{theirs}"
        """)

        result = self.run_cli("registry", "import", str(source))
        self.assertEqual(result.returncode, 0, result.stderr)
        listed = self.run_cli("list").stdout
        with self.subTest("the new key arrived"):
            self.assertIn("llm.beta", listed)
        with self.subTest("and the existing one in the same section survived"):
            self.assertIn("llm.alpha", listed)

    def test_conflicts_keep_yours_and_are_named(self) -> None:
        mine = self.write_router_tool("mine.py", "mine")
        theirs = self.write_router_tool("theirs.py", "theirs")
        self.run_cli("registry", "add", "tool","--", str(mine))
        source = self.source_file(f"""
            [tool]
            command = "{theirs}"

            [fresh]
            command = "{theirs}"
        """)

        with self.subTest("the disagreement is kept out, the rest goes in"):
            result = self.run_cli("registry", "import", str(source))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("fresh", self.run_cli("list").stdout)
            self.assertIn("tool", result.stdout)
            self.assertIn(str(mine), result.stdout)
            self.assertIn(str(theirs), result.stdout)
            self.assertIn(str(mine), self.registry_file.read_text(encoding="utf-8"))

        with self.subTest("--force takes theirs"):
            self.run_cli("registry", "import", str(source), "--force")
            stored = self.registry_file.read_text(encoding="utf-8")
            self.assertIn(str(theirs), stored)

    def test_importing_what_was_exported_changes_nothing(self) -> None:
        tool = self.write_router_tool("x.py", "x")
        self.run_cli("registry", "add", "jq","--describe", "filter JSON", "--", str(tool))
        out = self.base / "round-trip.ini"
        self.run_cli("registry", "export", str(out))
        before = self.registry_file.read_text(encoding="utf-8")

        result = self.run_cli("registry", "import", str(out))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("already matched", result.stdout)
        self.assertEqual(self.registry_file.read_text(encoding="utf-8"), before)

    def test_a_file_that_will_not_parse_is_refused_whole(self) -> None:
        tool = self.write_router_tool("x.py", "x")
        self.run_cli("registry", "add", "keep","--", str(tool))
        before = self.registry_file.read_text(encoding="utf-8")
        source = self.source_file("not toml at all\n[[[\n")

        result = self.run_cli("registry", "import", str(source))
        self.assertEqual(result.returncode, 1)
        self.assertIn("refusing", result.stdout)
        self.assertEqual(self.registry_file.read_text(encoding="utf-8"), before)

    def test_illegal_entries_are_left_behind_and_unreachable_ones_are_not(self) -> None:
        """The two reasons an entry is "broken" do not travel the same way.

        Shadowing a builtin is wrong on any machine, so that entry stays out.
        A target that is missing *here* may be present on the machine that wrote
        the file, or after an install -- refusing those would make importing from
        another machine impossible, which is most of the point of importing.
        """
        tool = self.write_router_tool("x.py", "x")
        source = self.source_file(f"""
            [list]
            command = "{tool}"

            [fine]
            command = "{tool}"

            [absent]
            command = "/no/such/binary/anywhere"
        """)

        result = self.run_cli("registry", "import", str(source))
        self.assertEqual(result.returncode, 0, result.stderr)
        stored = self.registry_file.read_text(encoding="utf-8")
        with self.subTest("the legal entry is in"):
            self.assertIn("[fine]", stored)
        with self.subTest("the builtin-shadowing one is not, and is named"):
            self.assertNotIn("[list]", stored)
            self.assertIn("shadowed by a builtin", result.stdout)
        with self.subTest("the merely-absent one is imported, and reported"):
            self.assertIn("[absent]", stored)
            self.assertIn("not usable here yet", result.stdout)

    def test_a_skipped_entry_does_not_leave_its_description_behind(self) -> None:
        """A description belongs to a command, so it cannot outlive one."""
        tool = self.write_router_tool("x.py", "x")
        source = self.source_file(f"""
            [list]
            command = "{tool}"
            description = "a sentence about a command that will not be imported"
        """)
        self.run_cli("registry", "import", str(source))
        self.assertNotIn("a sentence about", self.registry_file.read_text(encoding="utf-8"))

    def test_a_directory_means_the_registry_inside_it(self) -> None:
        """The mirror of export, so exporting to a folder and importing it works."""
        tool = self.write_router_tool("x.py", "x")
        self.run_cli("registry", "add", "jq","--", str(tool))
        folder = self.base / "backup"
        folder.mkdir()
        self.run_cli("registry", "export", str(folder))
        self.run_cli("registry", "remove", "jq")

        result = self.run_cli("registry", "import", str(folder))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("jq", self.run_cli("list").stdout)

    def test_importing_this_registry_is_refused(self) -> None:
        tool = self.write_router_tool("x.py", "x")
        self.run_cli("registry", "add", "jq","--", str(tool))
        result = self.run_cli("registry", "import", str(self.registry_file))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("that is this registry", result.stderr)

    def test_a_path_that_resolves_to_nothing_is_named(self) -> None:
        result = self.run_cli("registry", "import", str(self.base / "no-such-file.ini"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("nothing to import", result.stderr)
