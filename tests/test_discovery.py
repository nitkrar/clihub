from __future__ import annotations

import sys
import unittest

from .fixture import ROOT, ClihubFixture


class DiscoveryTests(ClihubFixture):
    """Reaching a command without knowing its name: list, find, help."""

    def test_description_overlap_warning_and_help_form_fallback(self) -> None:
        help_lines = (
            "Usage: thing\\nCommands:\\n"
            "  start   start the widget\\n  stop    stop the widget\\n"
            "  status  show widget status\\n  logs    show widget logs"
        )
        copied = "thing: start, stop, status, logs"
        purpose = "keep the household widget spinning quietly"

        def tool(name: str, condition: str) -> str:
            body = (
                "import sys\n"
                f"if {condition}:\n"
                f'    print("{help_lines}")\n'
                "    sys.exit(0)\n"
                "sys.exit(1)\n"
            )
            return str(self.write_tool(name, body))

        long_form = tool("hlong", '"--help" in sys.argv')
        sub_form = tool("hsub", 'len(sys.argv) > 1 and sys.argv[1] == "help"')
        short_form = tool("hshort", '"-h" in sys.argv')
        no_help = tool("hnone", "False")
        flagged = "looks like a command list"

        with self.subTest("copied command list is flagged but still registered"):
            result = self.run_cli("registry", "add", "a", "--describe", copied, "--", long_form)
            self.assertIn(flagged, result.stderr)
            self.assertIn(copied, self.run_cli("list").stdout)

        with self.subTest("purpose-stating description is not flagged"):
            result = self.run_cli("registry", "add", "b", "--describe", purpose, "--", long_form)
            self.assertNotIn(flagged, result.stderr)

        with self.subTest("help form: bare 'help' subcommand"):
            result = self.run_cli("registry", "add", "c", "--describe", copied, "--", sub_form)
            self.assertIn(flagged, result.stderr)

        with self.subTest("help form: -h"):
            result = self.run_cli("registry", "add", "d", "--describe", copied, "--", short_form)
            self.assertIn(flagged, result.stderr)

        with self.subTest("no help at all: silent, no false warning"):
            result = self.run_cli("registry", "add", "e", "--describe", copied, "--", no_help)
            self.assertNotIn(flagged, result.stderr)

        with self.subTest("overlap_check = false switches it off"):
            config = self.config_file
            config.parent.mkdir(parents=True, exist_ok=True)
            config.write_text("[describe]\noverlap_check = false\n", encoding="utf-8")
            result = self.run_cli("registry", "add", "f", "--describe", copied, "--", long_form)
            self.assertNotIn(flagged, result.stderr)
            # Still stored — the switch silences the check, it does not reject input.
            self.assertIn(copied, self.run_cli("list").stdout)

    def test_asking_ch_about_itself_works_every_way_it_is_asked(self) -> None:
        """Four spellings of one question, all answering with clihub's own help.
        """
        tool = self.write_router_tool("ht.py", "ht")
        self.run_cli("registry", "add", "notes", "--", str(tool))
        sys.path.insert(0, str(ROOT / "src"))
        from clihub.cli import BUILTIN_COMMANDS

        for argv in ((), ("-h",), ("--help",), ("help",)):
            with self.subTest(" ".join(argv) or "<no arguments>"):
                result = self.run_cli(*argv)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("ch list", result.stdout)

        with self.subTest("the usage text is assembled from the commands"):
            # Not a drift check any more: the text is generated from
            # BUILTIN_COMMANDS and from each group's own parser, so it cannot fall
            # behind them. What can still break is the generator, and a command
            # missing from the output is how that would show.
            usage = self.run_cli("--help").stdout
            missing = [name for name in BUILTIN_COMMANDS if f"ch {name}" not in usage]
            self.assertEqual(missing, [], f"absent from usage: {missing}")
            self.assertIn("ch rg {", usage, "a group's verbs are not listed")

        with self.subTest("a help flag after a tool name still reaches the tool"):
            # The risk in intercepting --help at position 1 is intercepting too much.
            result = self.run_cli("notes", "--help")
            self.assertEqual(result.stdout.strip(), "help for ht")

    def test_version_answers_without_the_registry_and_reserves_no_name(self) -> None:
        """It is the first line of a bug report, so it has to answer when the
        registry does not, and it must not cost anyone the name `version`."""
        sys.path.insert(0, str(ROOT / "src"))
        from clihub import __version__

        for flag in ("--version", "-V"):
            with self.subTest(flag):
                result = self.run_cli(flag)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), f"clihub {__version__}")

        with self.subTest("doctor leads with it"):
            self.assertIn(f"clihub {__version__}", self.run_cli("doctor").stdout)

        with self.subTest("answered without reading the registry"):
            self.registry_file.parent.mkdir(parents=True, exist_ok=True)
            self.registry_file.write_text("[[[ not toml", encoding="utf-8")
            self.assertEqual(self.run_cli("--version").returncode, 0)
            self.registry_file.unlink()

        with self.subTest("a tool may still be called version"):
            # Only the flag spelling is intercepted, so the bare word stays an
            # ordinary name rather than joining the reserved builtins.
            tool = self.write_router_tool("v.py", "v")
            self.assertEqual(
                self.run_cli("registry", "add", "version", "--", str(tool)).returncode,
                0,
            )
            self.assertEqual(self.run_cli("version").stdout.strip(), "[]")

    def test_every_builtin_can_be_asked_what_it_does(self) -> None:
        """Every builtin answers a help flag, and none of them runs instead."""
        sys.path.insert(0, str(ROOT / "src"))
        from clihub.cli import BUILTIN_COMMANDS

        def assert_is_help(result, name: str) -> None:
            # "exited 0 and printed something" is what a builtin does when it
            # *runs*, so it cannot tell answering from running. Every builtin
            # opens with `usage:`, except `help`, whose help is clihub's own.
            self.assertEqual(result.returncode, 0, result.stderr)
            opening = result.stdout.strip().splitlines()[:1]
            if name == "help":
                self.assertIn("ch list", result.stdout)
            else:
                self.assertTrue(
                    opening and opening[0].startswith("usage:"),
                    f"ch {name} --help printed {opening!r}, which is not help",
                )

        for name in sorted(BUILTIN_COMMANDS):
            with self.subTest(f"ch {name} --help"):
                assert_is_help(self.run_cli(name, "--help"), name)

            with self.subTest(f"ch help {name}"):
                # A builtin has help of its own; asking for it is not "reserved
                # name cannot be reached", which is about registered entries.
                assert_is_help(self.run_cli("help", name), name)

        with self.subTest("a group named alone says what is in it"):
            for group in ("registry", "tools"):
                result = self.run_cli(group)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("usage", result.stdout.lower())
                self.assertIn(group, result.stdout)

        with self.subTest("but an incomplete verb is still a usage error"):
            # Naming a group asks a question; naming a verb with no arguments is a
            # half-typed command.
            self.assertEqual(self.run_cli("registry", "add").returncode, 2)

    def test_the_missing_description_notice_names_a_command_that_works(self) -> None:
        """The notice must name a command that runs: `add` needs `-- <path>`, so
        changing one field of an existing entry is `edit`."""
        tool = self.write_tool("silent.py", "import sys; sys.exit(0)")
        self.run_cli("registry", "add", "quiet", "--", str(tool))

        notice = self.run_cli("list").stderr
        self.assertIn("no description", notice)
        self.assertIn("registry edit", notice)
        self.assertNotIn("registry add", notice)

        # Run what it actually tells you to run.
        result = self.run_cli("registry", "edit", "quiet", "--describe", "stays quiet")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("stays quiet", self.run_cli("list").stdout)

    def test_list_find_and_help_behave_as_router_surface(self) -> None:
        tool = self.write_router_tool("notes.py", "notes")

        result = self.run_cli("registry", "add", "notes", "--describe",
                              "manage notes", "--", str(tool))
        self.assertEqual(result.returncode, 0, result.stderr)

        result = self.run_cli("list")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("notes", result.stdout)
        self.assertIn("manage notes", result.stdout)

        result = self.run_cli("find", "manage")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("notes", result.stdout)

        result = self.run_cli("help", "notes")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "help for notes")


class FindRankingTests(unittest.TestCase):
    """`rank` is pure, so each layer can be pinned without spawning anything."""

    ROWS = [
        ("black", "reformat python source files to a standard style"),
        ("relay", "pass messages between processes on this machine"),
        ("claude", "start an interactive AI coding session in the terminal"),
        ("codex", "start an alternative AI coding session in the terminal"),
        ("colima", "start or stop the linux virtual machine that runs containers"),
        ("docker", "run, stop and inspect containers"),
        ("gh", "work with GitHub issues, pull requests and releases"),
        ("jq", "filter and reshape JSON text"),
        ("llama", "run and control local language model servers"),
        ("mcp", "run the search and tool containers that models call out to"),
        ("sqlite3", "query a SQLite database file"),
        ("tmux", "keep terminal sessions running after you disconnect"),
    ]

    def names(self, term: str) -> list[str]:
        from clihub.commands.find import rank

        return [name for name, _ in rank(term, self.ROWS)]

    def test_each_layer_covers_what_the_others_cannot(self) -> None:
        with self.subTest("substring: BM25 cannot tokenise 'sql' out of 'sqlite3'"):
            self.assertEqual(self.names("sql"), ["sqlite3"])

        with self.subTest("BM25: a multi-word query no single word matches"):
            self.assertEqual(self.names("web search")[0], "mcp")

        with self.subTest("difflib: a typo in a name"):
            self.assertEqual(self.names("dokcer"), ["docker"])

        with self.subTest("ranking: the best match leads"):
            self.assertEqual(self.names("start a model")[0], "llama")
            self.assertEqual(self.names("pull request")[0], "gh")

    def test_it_returns_nothing_rather_than_noise(self) -> None:
        # At 0.4 'note' matches unrelated names outright -- codex, docker. Names
        # only, at 0.7, is what makes that class of noise unreachable.
        with self.subTest("a word resembling nothing matches nothing"):
            self.assertEqual(self.names("note"), [])
        with self.subTest("a word resembling nothing at all"):
            self.assertEqual(self.names("xyzzy"), [])
        with self.subTest("a phrase is never treated as a typo of a name"):
            self.assertNotIn("codex", self.names("cod ex machina"))

    def test_relevant_rows_are_not_buried(self) -> None:
        containers = self.names("container")
        self.assertEqual(set(containers), {"colima", "docker", "mcp"})
        self.assertNotIn("claude", containers)
