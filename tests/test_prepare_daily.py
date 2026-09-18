"""离线验证每日 worktree 的输出路径；所有文件和 Git 响应均为临时夹具。"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPTS = Path(__file__).resolve().parents[1] / "skills/shopee-ugreen-topsales/scripts"
sys.path.insert(0, str(SCRIPTS))
import prepare_daily_worktree as prepare  # noqa: E402


class PrepareDailyTests(unittest.TestCase):
    def test_reused_worktree_reports_its_own_result_without_writing_workbooks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            daily = root / "worktrees/20260917_ugreen_topsales"
            script = Path("skills/shopee-ugreen-topsales/scripts/run_scrape.py")
            for path in (root / ".venv/bin/python", root / script, daily / script):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            legacy = root / "result/ugreen_topsales.xlsx"
            legacy.parent.mkdir()
            legacy.write_bytes(b"legacy main workbook")
            previous = root / "worktrees/20260916_ugreen_topsales/result/ugreen_topsales.xlsx"
            previous.parent.mkdir(parents=True)
            previous.write_bytes(b"previous daily workbook")

            def git(where, *args, **kwargs):
                self.assertIn(where, (root, daily))
                self.assertEqual(args, ("rev-parse", "HEAD"))
                return subprocess.CompletedProcess(args, 0, stdout="reviewed-head\n", stderr="")

            registration = [{"worktree": str(daily), "branch": "refs/heads/daily/20260917-ugreen-topsales"}]
            with patch.object(prepare, "_clean", return_value=True), patch.object(prepare, "_parse_worktrees", return_value=registration), patch.object(prepare, "_git", side_effect=git) as git_read:
                payload = prepare._prepare_locked(root, "2026-09-17")

            self.assertEqual(payload["status"], "reused")
            self.assertFalse(payload["created"])
            self.assertEqual(payload["project_root"], str(root))
            self.assertEqual(payload["worktree"], str(daily))
            self.assertEqual(payload["python"], str(root / ".venv/bin/python"))
            self.assertEqual(payload["runner"], str(daily / script))
            self.assertEqual(payload["output"], str(daily / "result/ugreen_topsales.xlsx"))
            self.assertEqual(git_read.call_count, 2)
            self.assertFalse((daily / "result").exists())
            self.assertEqual(legacy.read_bytes(), b"legacy main workbook")
            self.assertEqual(previous.read_bytes(), b"previous daily workbook")


if __name__ == "__main__":
    unittest.main()
