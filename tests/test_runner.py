"""离线验证 runner 的诊断/发布边界；不启动浏览器或连接网站。"""

from __future__ import annotations

import asyncio
import io
import json
import sys
import tempfile
import unittest
from contextlib import nullcontext, redirect_stderr, redirect_stdout
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


SCRIPTS = Path(__file__).resolve().parents[1] / "skills/shopee-ugreen-topsales/scripts"
sys.path.insert(0, str(SCRIPTS))
import run_scrape as runner  # noqa: E402


def verification(*, listing: bool = True, success: int = 3, attempted: int = 3, target: int = 3) -> dict:
    return {
        "mode": "verify_access",
        "list_pass": listing,
        "details": [{"item_id": str(index)} for index in range(attempted)],
        "detail_success_count": success,
        "detail_attempted_count": attempted,
        "detail_target_count": target,
        "full_crawl_completed": False,
        "workbook_written": False,
        "说明": "仅验证访问",
    }


class RunnerTests(unittest.TestCase):
    def setUp(self):
        clock_patch = patch.object(runner, "datetime")
        self.clock = clock_patch.start()
        self.addCleanup(clock_patch.stop)
        self.clock.now.side_effect = lambda zone=None: datetime(2026, 9, 17, 12, tzinfo=zone)

    def args(self, root: Path, *extra: str):
        return runner._parser().parse_args(["--project-root", str(root), *extra])

    def daily_output(self, root: Path, compact: str = "20260917") -> Path:
        return root / "worktrees" / f"{compact}_ugreen_topsales/result/ugreen_topsales.xlsx"

    def test_defaults_are_serial_and_slow(self):
        args = self.args(Path("/example"))
        self.assertEqual(args.detail_shards, 1)
        self.assertEqual(args.list_interval_seconds, 10)
        self.assertEqual(args.detail_interval_seconds, 10)

    def test_intervals_cannot_speed_up_or_be_nonfinite(self):
        for option in ("--list-interval-seconds", "--detail-interval-seconds"):
            for value in ("0", "9.9", "-1", "nan", "inf", "abc"):
                with self.subTest(option=option, value=value), redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        self.args(Path("/example"), option, value)
        self.assertEqual(self.args(Path("/example"), "--detail-interval-seconds", "30").detail_interval_seconds, 30)

    def test_verify_ignores_unknown_result_files_and_never_publishes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "result/ugreen_topsales.xlsx"
            output.parent.mkdir()
            output.write_bytes(b"previous valid workbook")
            unknown = output.parent / "user-notes.txt"
            unknown.write_text("do not delete", encoding="utf-8")
            access = AsyncMock(return_value=verification())
            with patch.object(runner, "verify_access", access), patch.object(runner, "scrape_all", AsyncMock()) as scrape, patch.object(runner, "write_excel") as publish, patch.object(runner, "_validate_daily_run") as daily:
                result = asyncio.run(runner._run(self.args(root, "--verify-access")))
            self.assertEqual(result["mode"], "verify_access")
            scrape.assert_not_called()
            publish.assert_not_called()
            daily.assert_not_called()
            self.assertEqual(access.call_args.args[1], output.resolve())
            self.assertEqual(access.call_args.args[0].detail_interval_ms, 10_000)
            self.assertEqual(output.read_bytes(), b"previous valid workbook")
            self.assertEqual(unknown.read_text(encoding="utf-8"), "do not delete")
            self.assertFalse((root / "worktrees").exists())

    def test_verify_can_take_explicit_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = root / "old-reference.xlsx"
            access = AsyncMock(return_value=verification())
            with patch.object(runner, "verify_access", access), patch.object(runner, "_default_reference", side_effect=AssertionError("explicit reference must not select a default")):
                asyncio.run(runner._run(self.args(root, "--verify-access", "--reference-workbook", str(reference), "--list-interval-seconds", "20")))
            self.assertEqual(access.call_args.args[1], reference.resolve())
            self.assertEqual(access.call_args.args[0].list_interval_ms, 20_000)
            self.assertFalse((root / "result").exists())

    def test_verify_uses_latest_daily_reference_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            references = {
                root / "result/ugreen_topsales.xlsx": b"legacy main workbook",
                self.daily_output(root, "20260915"): b"older daily workbook",
                self.daily_output(root, "20260916"): b"latest prior workbook",
                self.daily_output(root, "20260918"): b"future workbook",
            }
            for path, content in references.items():
                path.parent.mkdir(parents=True)
                path.write_bytes(content)
            access = AsyncMock(return_value=verification())
            with patch.object(runner, "verify_access", access), patch.object(runner, "write_excel") as publish, patch.object(runner, "_validate_daily_run") as daily:
                asyncio.run(runner._run(self.args(root, "--verify-access")))
            self.assertEqual(access.call_args.args[1], self.daily_output(root, "20260916").resolve())
            publish.assert_not_called()
            daily.assert_not_called()
            self.assertFalse(self.daily_output(root).parent.exists())
            for path, content in references.items():
                self.assertEqual(path.read_bytes(), content)

    def test_default_reference_prefers_today_over_older_and_future_workbooks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for compact in ("20260916", "20260917", "20260918"):
                path = self.daily_output(root, compact)
                path.parent.mkdir(parents=True)
                path.write_bytes(compact.encode())
            legacy = root / "result/ugreen_topsales.xlsx"
            legacy.parent.mkdir()
            legacy.write_bytes(b"legacy")
            self.assertEqual(runner._default_reference(root, date(2026, 9, 17)), self.daily_output(root))
            self.assertEqual(legacy.read_bytes(), b"legacy")

    def test_default_reference_falls_back_to_main_when_only_future_daily_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            future = self.daily_output(root, "20260918")
            future.parent.mkdir(parents=True)
            future.write_bytes(b"future")
            legacy = root / "result/ugreen_topsales.xlsx"
            legacy.parent.mkdir()
            legacy.write_bytes(b"legacy")
            self.assertEqual(runner._default_reference(root, date(2026, 9, 17)), legacy)
            self.assertEqual(legacy.read_bytes(), b"legacy")
            self.assertEqual(future.read_bytes(), b"future")
            self.assertFalse(self.daily_output(root).parent.exists())

    def test_default_reference_requires_an_existing_workbook_without_creating_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(FileNotFoundError):
                runner._default_reference(root, date(2026, 9, 17))
            self.assertEqual(list(root.iterdir()), [])

    def test_full_mode_checks_daily_state_before_crawl_and_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = self.daily_output(root)
            preserved = {
                root / "result/ugreen_topsales.xlsx": b"legacy main workbook",
                root / "result/user-notes.txt": b"main notes must not block publication",
                self.daily_output(root, "20260916"): b"previous day workbook",
            }
            for path, content in preserved.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            events = []

            async def scrape(*args, **kwargs):
                events.append("crawl")
                return SimpleNamespace(audit=SimpleNamespace(list_page_count=2), products=[1])

            def publish(result, target):
                events.append("publish")
                self.assertEqual(target, output)
                target.parent.mkdir(parents=True)
                target.write_bytes(b"new workbook")
                return target

            with patch.object(runner, "_validate_daily_run", side_effect=lambda root, run_date: events.append("daily_check")), patch.object(runner, "scrape_all", scrape), patch.object(runner, "write_excel", publish), redirect_stderr(io.StringIO()):
                self.assertEqual(asyncio.run(runner._run(self.args(root))), output)
            self.assertEqual(events, ["daily_check", "crawl", "daily_check", "publish"])
            self.assertEqual(output.read_bytes(), b"new workbook")
            for path, content in preserved.items():
                self.assertEqual(path.read_bytes(), content)

    def test_full_run_keeps_starting_shanghai_date_across_midnight(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = self.daily_output(root)
            started = datetime(2026, 9, 17, 23, 59)
            finished = datetime(2026, 9, 18, 0, 1)
            now = [started]

            async def scrape(*args, **kwargs):
                now[0] = finished
                return SimpleNamespace(audit=SimpleNamespace(list_page_count=1), products=[1])

            def publish(result, target):
                self.assertEqual(target, output)
                target.parent.mkdir(parents=True)
                target.write_bytes(b"new workbook")
                return target

            with patch.object(runner, "datetime") as clock, patch.object(runner, "_validate_daily_run") as daily, patch.object(runner, "scrape_all", scrape), patch.object(runner, "write_excel", publish), patch.object(runner, "_progress"):
                clock.now.side_effect = lambda zone: now[0].replace(tzinfo=zone)
                self.assertEqual(asyncio.run(runner._run(self.args(root))), output)
            self.assertEqual(now[0], finished)
            self.assertEqual([call.args for call in daily.call_args_list], [(root, date(2026, 9, 17)), (root, date(2026, 9, 17))])
            clock.now.assert_called_once()
            self.assertEqual(clock.now.call_args.args[0].key, "Asia/Shanghai")
            self.assertTrue(output.is_file())
            self.assertFalse(self.daily_output(root, "20260918").parent.exists())
            self.assertFalse((root / "result").exists())

    def test_changes_during_crawl_prevent_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = self.daily_output(root)
            output.parent.mkdir(parents=True)
            output.write_bytes(b"old workbook")
            result = SimpleNamespace(audit=SimpleNamespace(list_page_count=1), products=[1])
            with patch.object(runner, "_validate_daily_run", side_effect=[None, ValueError("主项目存在改动")]), patch.object(runner, "scrape_all", AsyncMock(return_value=result)), patch.object(runner, "write_excel") as publish, redirect_stderr(io.StringIO()):
                with self.assertRaisesRegex(ValueError, "改动"):
                    asyncio.run(runner._run(self.args(root)))
            publish.assert_not_called()
            self.assertEqual(output.read_bytes(), b"old workbook")

    def test_crawl_failure_preserves_existing_daily_and_main_workbooks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            preserved = {
                self.daily_output(root): b"existing daily workbook",
                root / "result/ugreen_topsales.xlsx": b"legacy main workbook",
                self.daily_output(root, "20260916"): b"previous day workbook",
            }
            for path, content in preserved.items():
                path.parent.mkdir(parents=True)
                path.write_bytes(content)
            with patch.object(runner, "_validate_daily_run"), patch.object(runner, "scrape_all", AsyncMock(side_effect=runner.ScrapeError("详情抓取失败"))), patch.object(runner, "write_excel") as publish:
                with self.assertRaisesRegex(runner.ScrapeError, "详情抓取失败"):
                    asyncio.run(runner._run(self.args(root)))
            publish.assert_not_called()
            for path, content in preserved.items():
                self.assertEqual(path.read_bytes(), content)

    def test_unknown_daily_result_file_prevents_full_crawl_and_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            unknown = self.daily_output(root).parent / "user.txt"
            unknown.parent.mkdir(parents=True)
            unknown.write_text("preserve", encoding="utf-8")
            with patch.object(runner, "_validate_daily_run"), patch.object(runner, "scrape_all", AsyncMock()) as scrape:
                with self.assertRaisesRegex(ValueError, "非目标文件"):
                    asyncio.run(runner._run(self.args(root)))
            scrape.assert_not_called()
            self.assertEqual(unknown.read_text(encoding="utf-8"), "preserve")
            self.assertFalse((root / "result").exists())

    def test_unknown_file_created_during_crawl_prevents_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = self.daily_output(root)
            output.parent.mkdir(parents=True)
            output.write_bytes(b"old workbook")

            async def scrape(*args, **kwargs):
                (output.parent / "user.txt").write_text("preserve")
                return SimpleNamespace(audit=SimpleNamespace(list_page_count=1), products=[1])

            with patch.object(runner, "_validate_daily_run"), patch.object(runner, "scrape_all", scrape), patch.object(runner, "write_excel") as publish, redirect_stderr(io.StringIO()):
                with self.assertRaisesRegex(ValueError, "非目标文件"):
                    asyncio.run(runner._run(self.args(root)))
            publish.assert_not_called()
            self.assertEqual(output.read_bytes(), b"old workbook")
            self.assertEqual((output.parent / "user.txt").read_text(), "preserve")

    def test_main_verification_exit_codes_and_machine_readable_output(self):
        cases = ((verification(), 0), (verification(listing=False), 2), (verification(success=2), 2), (verification(success=0, attempted=0), 2))
        for payload, expected in cases:
            with self.subTest(expected=expected, payload=payload):
                out, err = io.StringIO(), io.StringIO()
                with patch.object(runner, "_bound_project_root", return_value=Path("/example")), patch.object(runner, "_exclusive_run_lock", return_value=nullcontext()), patch.object(runner, "_run", AsyncMock(return_value=payload)), redirect_stdout(out), redirect_stderr(err):
                    code = runner.main(["--project-root", "/example", "--verify-access"])
                self.assertEqual(code, expected)
                self.assertEqual(json.loads(out.getvalue()), payload)
                self.assertIn("仅验证访问", out.getvalue())
                self.assertIn("不是完整抓取", err.getvalue())

    def test_main_verification_rejects_false_publication_claim(self):
        payload = verification()
        payload["full_crawl_completed"] = True
        with patch.object(runner, "_bound_project_root", return_value=Path("/example")), patch.object(runner, "_exclusive_run_lock", return_value=nullcontext()), patch.object(runner, "_run", AsyncMock(return_value=payload)), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(runner.main(["--project-root", "/example", "--verify-access"]), 1)

    def test_main_verification_does_not_pass_an_unfinished_target(self):
        payload = verification(success=2, attempted=2, target=3)
        with patch.object(runner, "_bound_project_root", return_value=Path("/example")), patch.object(runner, "_exclusive_run_lock", return_value=nullcontext()), patch.object(runner, "_run", AsyncMock(return_value=payload)), redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()):
            self.assertEqual(runner.main(["--project-root", "/example", "--verify-access"]), 2)
        self.assertEqual(json.loads(out.getvalue())["detail_target_count"], 3)

    def test_main_runtime_exception_returns_one(self):
        with patch.object(runner, "_bound_project_root", return_value=Path("/example")), patch.object(runner, "_exclusive_run_lock", return_value=nullcontext()), patch.object(runner, "_run", AsyncMock(side_effect=ValueError("测试失败"))), redirect_stderr(io.StringIO()):
            self.assertEqual(runner.main(["--project-root", "/example", "--verify-access"]), 1)

    def test_reference_not_allowed_for_full_refresh(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            runner.main(["--project-root", "/example", "--reference-workbook", "/old.xlsx"])

    def test_same_lock_excludes_another_run(self):
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / "shared.lock"
            with runner._exclusive_run_lock(lock):
                with self.assertRaisesRegex(ValueError, "另一个"):
                    with runner._exclusive_run_lock(lock):
                        self.fail("second run acquired the shared lock")
            with runner._exclusive_run_lock(lock):
                pass


class DailyPublicationTests(unittest.TestCase):
    def check(self, root: Path, *, dirty: str | None = None, same_head=True, branch=None):
        daily = root / "worktrees/20260917_ugreen_topsales"
        source = daily / "skills/shopee-ugreen-topsales/scripts/run_scrape.py"
        calls = []

        def git_read(where, *args):
            calls.append((where, args))
            if args == ("rev-parse", "--show-toplevel"):
                return str(daily)
            if args == ("symbolic-ref", "--quiet", "--short", "HEAD"):
                return branch or "daily/20260917-ugreen-topsales"
            if args == ("status", "--porcelain", "--untracked-files=all"):
                return " M user.py" if (dirty == "main" and where == root) or (dirty == "daily" and where == daily) else ""
            if args == ("rev-parse", "HEAD"):
                return "same" if same_head or where == root else "different"
            self.fail(f"unexpected Git command: {args}")

        with patch.object(runner, "__file__", str(source)), patch.object(runner, "datetime") as clock, patch.object(runner, "_git_read", side_effect=git_read):
            clock.now.side_effect = lambda zone: datetime(2026, 9, 17, 23, 0, tzinfo=zone)
            runner._validate_daily_run(root)
        return calls

    def test_clean_same_head_daily_path_is_allowed(self):
        with tempfile.TemporaryDirectory() as directory:
            calls = self.check(Path(directory))
        self.assertEqual(sum(args[0] == "status" for _, args in calls), 2)
        self.assertTrue(all(args[0] in {"rev-parse", "symbolic-ref", "status"} for _, args in calls))

    def test_dirty_main_or_daily_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            for dirty in ("main", "daily"):
                with self.subTest(dirty=dirty), self.assertRaisesRegex(ValueError, "未提交改动"):
                    self.check(Path(directory), dirty=dirty)

    def test_different_head_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(ValueError, "HEAD 不一致"):
            self.check(Path(directory), same_head=False)

    def test_wrong_branch_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(ValueError, "分支不符"):
            self.check(Path(directory), branch="daily/old")

    def test_main_project_runner_cannot_publish(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(runner, "__file__", str(root / "skills/shopee-ugreen-topsales/scripts/run_scrape.py")), patch.object(runner, "_git_read") as git:
                with self.assertRaisesRegex(ValueError, "每日 worktree"):
                    runner._validate_daily_run(root)
            git.assert_not_called()


if __name__ == "__main__":
    unittest.main()
