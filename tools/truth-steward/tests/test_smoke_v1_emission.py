"""End-to-end test that run_truth_steward_smoke.py emits v1 telemetry under
_Internal/truth-steward-smoke-runs/<date>/ for every fixture case AND a rollup.

Run from anywhere:
    /opt/homebrew/bin/python3 -m unittest discover -s _00_Online_Presence/tools/truth-steward/tests
"""
from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
import unittest
from pathlib import Path


HERE = Path(__file__).resolve()
AUTHORITY_DIR = HERE.parent.parent
SITE_REPO = AUTHORITY_DIR.parent.parent
SMOKE_SCRIPT = AUTHORITY_DIR / "run_truth_steward_smoke.py"
SMOKE_RUNS_ROOT = SITE_REPO / "_Internal" / "truth-steward-smoke-runs"

if str(AUTHORITY_DIR) not in sys.path:
    sys.path.insert(0, str(AUTHORITY_DIR))

import v1_writer  # noqa: E402


class SmokeV1EmissionTests(unittest.TestCase):
    """Slow integration test (~12s on M-series). Ships a dependable signal:
    every smoke fixture must produce one v1 summary.json that round-trips
    through validate(); plus a _rollup/summary.json describing matrix-level
    outcome."""

    @classmethod
    def setUpClass(cls) -> None:
        result = subprocess.run(
            [sys.executable, str(SMOKE_SCRIPT)],
            cwd=SITE_REPO,
            capture_output=True,
            text=True,
            timeout=120,
        )
        cls.smoke_result = result
        cls.run_root = SMOKE_RUNS_ROOT / dt.date.today().isoformat()

    def test_smoke_script_succeeded(self) -> None:
        if self.smoke_result.returncode != 0:
            self.fail(
                f"smoke runner exited {self.smoke_result.returncode}\n"
                f"stdout:\n{self.smoke_result.stdout}\n"
                f"stderr:\n{self.smoke_result.stderr}"
            )

    def test_run_root_was_created(self) -> None:
        self.assertTrue(self.run_root.is_dir(), f"missing run root {self.run_root}")

    def test_rollup_summary_emitted_and_valid(self) -> None:
        path = self.run_root / "_rollup" / "summary.json"
        self.assertTrue(path.exists(), f"missing rollup at {path}")
        record = json.loads(path.read_text())
        v1_writer.validate(record)
        self.assertEqual(record["stage"], "truth-steward-smoke")
        self.assertEqual(record["variant"], "truth-steward")
        self.assertTrue(record["ok"])

    def test_per_case_summaries_emitted(self) -> None:
        case_dirs = [
            d for d in self.run_root.iterdir()
            if d.is_dir() and d.name != "_rollup"
        ]
        self.assertGreaterEqual(
            len(case_dirs), 8,
            "expected at least 8 fixture case dirs under run root",
        )
        for case_dir in case_dirs:
            with self.subTest(case=case_dir.name):
                summary_path = case_dir / "summary.json"
                self.assertTrue(summary_path.exists(), f"missing {summary_path}")
                record = json.loads(summary_path.read_text())
                v1_writer.validate(record)
                self.assertEqual(record["stage"], "truth-steward-smoke")
                self.assertEqual(record["variant"], "truth-steward")
                self.assertIn(record["ok"], (True, False))

    def test_per_case_attempt_ids_unique(self) -> None:
        ids = []
        for d in self.run_root.iterdir():
            if not d.is_dir():
                continue
            summary_path = d / "summary.json"
            if not summary_path.exists():
                continue
            ids.append(json.loads(summary_path.read_text())["attempt_id"])
        self.assertEqual(
            len(ids), len(set(ids)),
            f"attempt_ids collided across smoke cases: {sorted(ids)}",
        )


if __name__ == "__main__":
    unittest.main()
