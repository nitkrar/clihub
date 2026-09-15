from __future__ import annotations

import ast
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


class SuiteIntegrityTests(unittest.TestCase):
    """The suite's own failure modes. A test that stops running says nothing."""

    def test_no_test_name_is_defined_twice(self) -> None:
        """Two methods with one name: Python keeps the last and the first vanishes
        silently, still reported as passing.

        Parsed from the source rather than read off the class, because by the time
        it is a class attribute the duplicate is already gone. Across files as well
        as within one, since a name moved during a split can be left behind.
        """
        everywhere: dict[str, str] = {}
        for path in sorted(HERE.glob("test_*.py")):
            source = path.read_text(encoding="utf-8")
            for node in ast.walk(ast.parse(source)):
                if not isinstance(node, ast.ClassDef):
                    continue
                seen: set[str] = set()
                for item in node.body:
                    if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        continue
                    if not item.name.startswith("test_"):
                        continue
                    where = f"{path.name}::{node.name}"
                    self.assertNotIn(
                        item.name, seen,
                        f"{where}.{item.name} is defined twice; Python keeps the last "
                        f"and the first never runs",
                    )
                    seen.add(item.name)
                    previous = everywhere.get(item.name)
                    self.assertIsNone(
                        previous,
                        f"{item.name} exists in both {previous} and {where}; "
                        f"one of them is a leftover",
                    )
                    everywhere[item.name] = where

    def test_every_test_file_is_reachable_from_discovery(self) -> None:
        """A file whose name does not match the pattern is never collected, and a
        suite that is never collected passes by not existing."""
        stray = [
            path.name for path in HERE.glob("*.py")
            if not path.name.startswith("test_")
            and path.name not in ("__init__.py", "fixture.py")
        ]
        self.assertEqual(stray, [], f"not collected by discovery: {stray}")
