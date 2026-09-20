"""历史 page=1 预访问的离线契约；不启动浏览器、不读取或发布工作簿。"""

from __future__ import annotations

import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/shopee-ugreen-topsales/scripts"
sys.path.insert(0, str(SCRIPTS))
import run_scrape as runner  # noqa: E402
import scraper  # noqa: E402
from test_scraper import FIXTURE_VERSION, fingerprint

US_REGION = scraper.BrowserRegion("US", "en-US", ("en-US", "en"), "America/New_York")


PROFILE = Path("/unused-fixture-profile")


def config(*, enabled=True, interval=10_000) -> scraper.BrowserConfig:
    return scraper.BrowserConfig(browser_profile="windows-intel", chrome_version=FIXTURE_VERSION, region=US_REGION,
        chrome_executable=Path(__file__), historical_list_preflight=enabled,
        list_interval_ms=interval,
    )


def raw_card(item_id: str) -> dict:
    return {
        "shop_id": scraper.SHOP_ID, "item_id": item_id,
        "title": f"离线商品 {item_id}",
        "product_url": f"https://shopee.ph/product/{scraper.SHOP_ID}/{item_id}",
        "price_text": "123.45",
        "monthly_sales_display": None, "monthly_sales_text": None,
    }


def target() -> scraper.ProductCard:
    return scraper._card_from_payload(raw_card("100"), 0, 1)


def profile_context():
    profile = MagicMock()
    profile.__enter__.return_value = PROFILE
    profile.__exit__.return_value = False
    return profile


class PreflightConfigurationTests(unittest.IsolatedAsyncioTestCase):
    async def test_cli_defaults_off_and_passes_explicit_switch_to_verify_and_full_modes(self) -> None:
        self.assertFalse(scraper.BrowserConfig(browser_profile="windows-intel", chrome_version=FIXTURE_VERSION, region=US_REGION).historical_list_preflight)
        for enabled in (False, True):
            for verify in (False, True):
                with self.subTest(enabled=enabled, verify=verify):
                    argv = ["--project-root", "/unused-fixture-root"]
                    if enabled:
                        argv.append("--historical-list-preflight")
                    if verify:
                        argv.extend(["--verify-access", "--reference-workbook", "/unused-reference.xlsx"])
                    args = runner._parser().parse_args(argv)
                    self.assertIs(args.historical_list_preflight, enabled)
                    with (
                        patch.object(runner, "verify_access", new=AsyncMock(return_value={})) as access,
                        patch.object(runner, "scrape_all", new=AsyncMock(side_effect=scraper.ScrapeError("离线透传结束"))) as scrape,
                        patch.object(runner, "_validate_daily_run"),
                        patch.object(runner, "_check_output_directory"),
                        patch.object(runner, "write_excel") as publish,
                    ):
                        if verify:
                            await runner._run(args)
                            self.assertIs(access.await_args.args[0].historical_list_preflight, enabled)
                            scrape.assert_not_awaited()
                        else:
                            with self.assertRaisesRegex(scraper.ScrapeError, "离线透传结束"):
                                await runner._run(args)
                            self.assertIs(scrape.await_args.args[0].historical_list_preflight, enabled)
                            access.assert_not_awaited()
                        publish.assert_not_called()


class PreflightTraversalTests(unittest.IsolatedAsyncioTestCase):
    async def test_preflight_uses_second_page_and_preserves_configured_slow_interval(self) -> None:
        browser_config = config(interval=20_000)
        progress = MagicMock()
        with (
            patch.object(scraper, "_capture_list_page_with_profile", new=AsyncMock(return_value={
                "total": 2, "cards": [raw_card("999")],
            })) as capture,
            patch.object(scraper.asyncio, "sleep", new_callable=AsyncMock) as sleep,
        ):
            total = await scraper._historical_list_preflight(PROFILE, browser_config, progress)
        self.assertEqual(total, 2)
        capture.assert_awaited_once_with(PROFILE, 1, browser_config, None, progress=progress)
        sleep.assert_awaited_once_with(20)

    async def test_preflight_does_not_pollute_full_traversal_order_counts_or_ranks(self) -> None:
        browser_config = config()
        snapshots = [
            {"total": 2, "cards": [raw_card("999")]},
            {"total": 2, "cards": [raw_card(str(100 + index)) for index in range(30)]},
            {"total": 2, "cards": [raw_card("200")]},
        ]
        with (
            patch.object(scraper, "_capture_list_page_with_profile", new=AsyncMock(side_effect=snapshots)) as capture,
            patch.object(scraper.asyncio, "sleep", new_callable=AsyncMock) as sleep,
        ):
            products, pages, occurrences, duplicates = await scraper._collect_listing(
                PROFILE, browser_config, None
            )
        self.assertEqual([entry.args[0] for entry in capture.await_args_list], [PROFILE] * 3)
        self.assertEqual([entry.args[1] for entry in capture.await_args_list], [1, 0, 1])
        self.assertEqual([entry.args[3] for entry in capture.await_args_list], [None, 2, 2])
        self.assertEqual((pages, occurrences, duplicates), (2, 31, 0))
        self.assertEqual([product.item_id for product in products], [str(100 + index) for index in range(30)] + ["200"])
        self.assertEqual([product.source_page for product in products], [0] * 30 + [1])
        self.assertEqual([product.source_position for product in products], list(range(1, 31)) + [1])
        self.assertEqual(sleep.await_args_list, [call(10), call(10)])

    async def test_disabled_preflight_starts_at_page_zero(self) -> None:
        browser_config = config(enabled=False)
        with (
            patch.object(scraper, "_historical_list_preflight", new_callable=AsyncMock) as preflight,
            patch.object(scraper, "_capture_list_page_with_profile", new=AsyncMock(return_value={
                "total": 1, "cards": [raw_card("100")],
            })) as capture,
        ):
            products, pages, occurrences, _ = await scraper._collect_listing(PROFILE, browser_config, None)
        preflight.assert_not_awaited()
        capture.assert_awaited_once_with(PROFILE, 0, browser_config, None, progress=None)
        self.assertEqual((pages, occurrences, len(products)), (1, 1, 1))

    async def test_preflight_total_is_enforced_on_first_full_page(self) -> None:
        captured_pages = []

        async def capture(profile, page_index, browser_config, expected_total, *, progress=None):
            captured_pages.append((page_index, expected_total))
            if page_index == 1:
                return {"total": 2, "cards": [raw_card("999")]}
            if expected_total != 3:
                raise scraper.ScrapeError("分页总数从 2 变为 3")
            return {"total": 3, "cards": [raw_card("100")]}

        with (
            patch.object(scraper, "_capture_list_page_with_profile", new=AsyncMock(side_effect=capture)),
            patch.object(scraper.asyncio, "sleep", new_callable=AsyncMock),
        ):
            with self.assertRaisesRegex(scraper.ScrapeError, "分页总数从 2 变为 3"):
                await scraper._collect_listing(PROFILE, config(), None)
        self.assertEqual(captured_pages, [(1, None), (0, 2)])

    async def test_failed_full_preflight_never_publishes_or_starts_detail_capture(self) -> None:
        args = runner._parser().parse_args([
            "--project-root", "/unused-fixture-root", "--historical-list-preflight",
            "--chrome-executable", __file__,
        ])
        with (
            patch.object(scraper, "detect_browser_region", new=AsyncMock(return_value=US_REGION)),
            patch.object(scraper, "_chrome_version", new=AsyncMock(return_value=FIXTURE_VERSION)),
            patch.object(scraper, "_temporary_chrome_profile_base", return_value=profile_context()),
            patch.object(scraper, "_capture_list_page_with_profile", new=AsyncMock(side_effect=scraper.ScrapeError("预访问失败"))) as capture,
            patch.object(scraper, "_clone_detail_profiles") as clone,
            patch.object(scraper, "_launch_contexts", new_callable=AsyncMock) as details,
            patch.object(runner, "_validate_daily_run"),
            patch.object(runner, "_check_output_directory"),
            patch.object(runner, "write_excel") as publish,
        ):
            with self.assertRaisesRegex(scraper.ScrapeError, "预访问失败"):
                await runner._run(args)
        self.assertEqual(capture.await_count, 1)
        self.assertEqual(capture.await_args.args[1], 1)
        clone.assert_not_called()
        details.assert_not_awaited()
        publish.assert_not_called()


class PreflightVerificationTests(unittest.IsolatedAsyncioTestCase):
    async def verify(self, *, enabled=True, failing_page=None, fatal=False):
        browser_config = config(enabled=enabled)
        page = SimpleNamespace(close=AsyncMock())
        context = SimpleNamespace(new_page=AsyncMock(return_value=page))

        async def capture(profile, page_index, supplied_config, expected_total, *, progress=None):
            self.assertEqual(profile, PROFILE)
            self.assertIs(supplied_config, browser_config)
            self.assertEqual(expected_total, 2 if enabled and page_index == 0 else None)
            if page_index == failing_page:
                error_type = scraper.CaptureCleanupError if fatal else scraper.ScrapeError
                raise error_type(f"列表页 {page_index} 离线失败")
            return {"total": 2, "cards": [raw_card("999" if page_index == 1 else "100")]}

        with ExitStack() as stack:
            stack.enter_context(patch.object(scraper, "_temporary_chrome_profile_base", return_value=profile_context()))
            stack.enter_context(patch.object(scraper, "_select_verification_targets", return_value=[target()]))
            captured = stack.enter_context(patch.object(scraper, "_capture_list_page_with_profile", new=AsyncMock(side_effect=capture)))
            launch = stack.enter_context(patch.object(scraper, "_launch_context", new=AsyncMock(return_value=context)))
            stack.enter_context(patch.object(scraper, "_close_context", new_callable=AsyncMock))
            visit = stack.enter_context(patch.object(scraper, "_visit_detail", new=AsyncMock(return_value=SimpleNamespace(
                title="实时离线fixture", skus=[object()], secondary_image_urls=[],
            ))))
            stack.enter_context(patch.object(scraper, "_park_and_wait", new_callable=AsyncMock))
            sleep = stack.enter_context(patch.object(scraper.asyncio, "sleep", new_callable=AsyncMock))
            publish = stack.enter_context(patch.object(runner, "write_excel"))
            if fatal:
                with self.assertRaises(scraper.CaptureCleanupError):
                    await scraper.verify_access(browser_config, Path("/unused-reference.xlsx"))
                launch.assert_not_awaited()
                visit.assert_not_awaited()
                sleep.assert_not_awaited()
                publish.assert_not_called()
                return None, captured
            report = await scraper.verify_access(browser_config, Path("/unused-reference.xlsx"))
            visit.assert_awaited_once()
            publish.assert_not_called()
            self.assertFalse(report["full_crawl_completed"])
            self.assertFalse(report["workbook_written"])
            return report, captured

    async def test_two_successful_pages_are_reported_without_claiming_full_refresh(self) -> None:
        report, capture = await self.verify()
        self.assertTrue(report["historical_list_preflight"])
        self.assertTrue(report["preflight_pass"])
        self.assertTrue(report["list_pass"])
        self.assertEqual(report["list_pages_checked"], 2)
        self.assertEqual([entry.args[1] for entry in capture.await_args_list], [1, 0])

    async def test_disabled_preflight_reports_only_one_list_page(self) -> None:
        report, capture = await self.verify(enabled=False)
        self.assertFalse(report["historical_list_preflight"])
        self.assertIsNone(report["preflight_pass"])
        self.assertTrue(report["list_pass"])
        self.assertEqual(report["list_pages_checked"], 1)
        self.assertEqual([entry.args[1] for entry in capture.await_args_list], [0])

    async def test_failed_preflight_is_not_reported_as_list_success(self) -> None:
        report, capture = await self.verify(failing_page=1)
        self.assertFalse(report["preflight_pass"])
        self.assertFalse(report["list_pass"])
        self.assertEqual(report["list_pages_checked"], 0)
        self.assertEqual(report["detail_success_count"], 1)
        self.assertIn("离线失败", report["list_error"])
        self.assertEqual([entry.args[1] for entry in capture.await_args_list], [1])

    async def test_successful_preflight_does_not_hide_failed_page_zero(self) -> None:
        report, capture = await self.verify(failing_page=0)
        self.assertTrue(report["preflight_pass"])
        self.assertFalse(report["list_pass"])
        self.assertEqual(report["list_pages_checked"], 1)
        self.assertEqual([entry.args[1] for entry in capture.await_args_list], [1, 0])

    async def test_fatal_preflight_cleanup_prevents_detail_diagnostics(self) -> None:
        _, capture = await self.verify(failing_page=1, fatal=True)
        capture.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
