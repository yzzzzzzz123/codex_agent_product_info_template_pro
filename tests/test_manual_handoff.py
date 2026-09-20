"""人工交还控制协议：离线测试，不启动浏览器或读取真实 profile。"""

import asyncio
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/shopee-ugreen-topsales/scripts"))
import scraper
import run_scrape as runner
from test_scraper import FIXTURE_VERSION, US_REGION, fingerprint


def child_with_events(events):
    stdout, stderr = asyncio.StreamReader(limit=64 * 1024 * 1024), asyncio.StreamReader()
    for event in events:
        stdout.feed_data((json.dumps(event) + "\n").encode())
    stderr.feed_eof()
    ended = asyncio.Event()
    commands = []

    def write(data):
        value = json.loads(data)
        commands.append(value)
        if value.get("command") == "accept":
            ended.set()

    async def wait():
        await ended.wait()
        return 0

    child = SimpleNamespace(stdin=SimpleNamespace(write=write, drain=AsyncMock(), close=MagicMock()),
                            stdout=stdout, stderr=stderr, wait=wait)
    return child, commands


class ManualBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_valid_first_snapshot_continues_without_human_prompt(self):
        child, commands = child_with_events([{"event": "manual_snapshot", "snapshot": {}}])
        with patch.object(scraper, "_wait_for_manual_resume", new_callable=AsyncMock) as resume, \
                patch.object(scraper, "_validate_list_snapshot", return_value={}):
            await scraper._communicate_manual_capture(child, {}, 0, None, 1, None, fingerprint())
        resume.assert_not_awaited()
        self.assertEqual([c.get("command") for c in commands], [None, "accept"])

    async def test_real_parser_accepts_valid_list_with_internal_html_comments(self):
        from test_list_html import document, card, URL
        from test_node_bridge import snapshot
        value = snapshot()
        value.update(html=document(''.join(card(str(i)) for i in range(100, 130)),
                                   body='<!-- React marker -->'), final_url=URL)
        child, commands = child_with_events([
            {"event": "manual_handoff_ready"}, {"event": "manual_snapshot", "snapshot": value},
        ])
        with patch.object(scraper, "_wait_for_manual_resume", new_callable=AsyncMock):
            result = await scraper._communicate_manual_capture(child, {}, 0, None, 1, None, fingerprint())
        self.assertEqual(result, value)
        self.assertEqual(commands[-1], {"command": "accept"})

    async def test_snapshot_read_error_returns_to_manual_hold_without_closing(self):
        child, commands = child_with_events([
            {"event": "manual_handoff_ready"},
            {"event": "manual_snapshot_error", "error_kind": "runtime", "stage": "content"},
            {"event": "manual_handoff_ready"}, {"event": "manual_snapshot", "snapshot": {}},
        ])
        with patch.object(scraper, "_wait_for_manual_resume", new_callable=AsyncMock) as resume, \
                patch.object(scraper, "_validate_list_snapshot", return_value={}):
            await scraper._communicate_manual_capture(child, {}, 0, None, 1, None, fingerprint())
        self.assertEqual(resume.await_count, 2)
        self.assertEqual([c.get("command") for c in commands], [None, "resume", "resume", "accept"])

    async def test_parser_internal_error_keeps_window_for_recovery(self):
        child, commands = child_with_events([
            {"event": "manual_handoff_ready"}, {"event": "manual_snapshot", "snapshot": {}},
            {"event": "manual_handoff_ready"}, {"event": "manual_snapshot", "snapshot": {}},
        ])
        with patch.object(scraper, "_wait_for_manual_resume", new_callable=AsyncMock), \
                patch.object(scraper, "_validate_list_snapshot", side_effect=[AttributeError("private"), {}]):
            await scraper._communicate_manual_capture(child, {}, 0, None, 1, None, fingerprint())
        self.assertEqual([c.get("command") for c in commands], [None, "resume", "hold", "resume", "accept"])

    async def test_rejected_snapshot_holds_same_window_then_accepts_only_validated_snapshot(self):
        invalid, valid = {"html": "private-invalid"}, {"html": "private-valid"}
        child, commands = child_with_events([
            {"event": "manual_handoff_ready"}, {"event": "manual_snapshot", "snapshot": invalid},
            {"event": "manual_handoff_ready"}, {"event": "manual_snapshot", "snapshot": valid},
        ])
        messages = []
        with patch.object(scraper, "_wait_for_manual_resume", new_callable=AsyncMock) as resume, \
                patch.object(scraper, "_validate_list_snapshot", side_effect=[scraper.ScrapeError("blocked"), {}]) as validate:
            result = await scraper._communicate_manual_capture(child, {"url": "fixture"}, 0, None, 1, messages.append, fingerprint())
        self.assertEqual(result, valid)
        self.assertEqual(resume.await_count, 2)
        self.assertEqual(validate.call_count, 2)
        self.assertEqual([c.get("command") for c in commands], [None, "resume", "hold", "resume", "accept"])
        self.assertNotIn("private-", "".join(messages))

    async def test_human_wait_is_not_subject_to_capture_timeout(self):
        child, commands = child_with_events([
            {"event": "manual_handoff_ready"}, {"event": "manual_snapshot", "snapshot": {}},
        ])
        permission = asyncio.Event()
        async def resume(_):
            await permission.wait()
        with patch.object(scraper, "_wait_for_manual_resume", new=resume), \
                patch.object(scraper, "_validate_list_snapshot", return_value={}):
            task = asyncio.create_task(scraper._communicate_manual_capture(child, {}, 0, None, 0.01, None, fingerprint()))
            await asyncio.sleep(0.04)
            self.assertFalse(task.done())
            self.assertEqual(commands, [{}])
            permission.set()
            await task

    async def test_manual_failure_never_runs_automatic_three_attempt_restart(self):
        config = scraper.BrowserConfig(browser_profile="windows-intel", chrome_version=FIXTURE_VERSION, region=US_REGION, manual_list_handoff=True)
        with patch.object(scraper, "_capture_list_page_attempt", new=AsyncMock(side_effect=scraper.ScrapeError("cancelled"))) as capture, \
                patch.object(scraper.asyncio, "sleep", new_callable=AsyncMock) as sleep:
            with self.assertRaises(scraper.ScrapeError):
                await scraper._capture_list_page_with_profile(Path("/fixture"), 0, config, None)
        capture.assert_awaited_once()
        sleep.assert_not_awaited()


class ManualCliTests(unittest.TestCase):
    def test_cli_exposes_eight_profiles_and_defaults_to_auto(self):
        base = ["--project-root", "/fixture", "--verify-access"]
        self.assertEqual(runner._parser().parse_args(base).browser_profile, "auto")
        self.assertEqual(len(scraper.APPROVED_PROFILE_IDS), 8)
        for profile_id in scraper.APPROVED_PROFILE_IDS:
            args = runner._parser().parse_args(base + ["--browser-profile", profile_id])
            self.assertEqual(args.browser_profile, profile_id)

    def test_manual_mode_is_explicit_interactive_single_worker(self):
        base = ["--project-root", "/fixture", "--manual-list-handoff"]
        with patch.object(runner.sys.stdin, "isatty", return_value=True):
            args = runner._parser().parse_args(base + ["--verify-access"])
            runner._validate_mode_args(args)
            for tail in (["--verify-access", "--headless"], ["--verify-access", "--historical-list-preflight"],
                         ["--detail-shards", "2"]):
                with self.subTest(tail=tail), self.assertRaises(ValueError):
                    runner._validate_mode_args(runner._parser().parse_args(base + tail))
            runner._validate_mode_args(runner._parser().parse_args(base))
            canonical = runner._parser().parse_args(["--project-root", "/fixture", "--manual-access"])
            self.assertTrue(canonical.manual_list_handoff)
            runner._validate_mode_args(canonical)
        with patch.object(runner.sys.stdin, "isatty", return_value=False), self.assertRaises(ValueError):
            runner._validate_mode_args(args)


if __name__ == "__main__":
    unittest.main()
