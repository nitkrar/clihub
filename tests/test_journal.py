from __future__ import annotations

import json

from .fixture import ClihubFixture


class JournalTests(ClihubFixture):
    """The invocation log, and reading it back."""

    def test_the_journal_rotates_without_losing_order(self) -> None:
        """`.1` is the most recent backup, older ones shift up, and nothing
        survives past backup_count."""
        config = self.config_file
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text("[journal]\nmax_bytes = 300\nbackup_count = 2\n", encoding="utf-8")
        tool = self.write_tool("quiet.py", "import sys; sys.exit(0)")
        self.run_cli("registry", "add", "e", "--", str(tool))

        for index in range(1, 23):
            self.run_cli("e", f"run{index}")

        state = self.clihub_home / "log"
        live = state / "invocations.jsonl"
        first, second = state / "invocations.jsonl.1", state / "invocations.jsonl.2"

        with self.subTest("rotates, and keeps no more than backup_count"):
            self.assertTrue(first.exists() and second.exists())
            self.assertFalse((state / "invocations.jsonl.3").exists())

        with self.subTest("each file respects the size limit"):
            for path in (first, second):
                self.assertLessEqual(path.stat().st_size, 300, path.name)

        with self.subTest(".1 is newer than .2, and the live file is newest"):
            def last_verb(path):
                return json.loads(path.read_text(encoding="utf-8").splitlines()[-1])["verb"]

            order = [int(last_verb(p).removeprefix("run")) for p in (second, first, live)]
            self.assertEqual(order, sorted(order), f"out of order: {order}")

    def test_tools_stats_profiles_the_journal(self) -> None:
        """Runs, failures and time per command, read back out of the log.

        Sorted by total time, not by count -- the ordering is the point. A command
        run a hundred times for 4ms matters less than one run twice for a minute.
        """
        quick = self.write_tool("quick.py", "import sys; sys.exit(0)")
        slow = self.write_tool("slow.py", "import sys, time; time.sleep(0.3); sys.exit(0)")
        failing = self.write_tool("bad.py", "import sys; sys.exit(3)")
        for name, tool in (("quick", quick), ("slow", slow), ("bad", failing)):
            self.run_cli("registry", "add", name,"--describe", name, "--", str(tool))
        for _ in range(4):
            self.run_cli("quick")
        self.run_cli("slow", timeout=10)
        self.run_cli("bad")

        with self.subTest("slow leads despite quick running four times as often"):
            lines = [l.split() for l in self.run_cli("tools", "stats").stdout.splitlines()]
            order = [l[0] for l in lines[1:]]
            self.assertLess(order.index("slow"), order.index("quick"), order)

        with self.subTest("counts and failures are right"):
            rows = {r["command"]: r for r in json.loads(
                self.run_cli("tools", "stats", "--json").stdout)}
            self.assertEqual(rows["quick"]["runs"], 4)
            self.assertEqual(rows["quick"]["fail"], 0)
            self.assertEqual(rows["bad"]["fail"], 1)
            self.assertGreater(rows["slow"]["total_s"], rows["quick"]["total_s"])

        with self.subTest("an empty journal says so rather than failing"):
            (self.clihub_home / "log" / "invocations.jsonl").unlink()
            result = self.run_cli("tools", "stats")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("nothing recorded", result.stdout)

        with self.subTest("a corrupt line is skipped, not fatal"):
            journal = self.clihub_home / "log" / "invocations.jsonl"
            journal.write_text('{"ns":"ok","ms":5,"rc":0,"ts":"2026-01-01T00:00:00Z"}\n'
                               "not json at all\n", encoding="utf-8")
            result = self.run_cli("tools", "stats")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("ok", result.stdout)
