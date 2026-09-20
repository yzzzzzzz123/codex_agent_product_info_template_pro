"""出口地区配置的离线 mock 测试；不联网、不启动 Chrome、不读取真实会话。"""

from __future__ import annotations

import asyncio
import io
import json
import stat
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/shopee-ugreen-topsales/scripts"))
import browser_region  # noqa: E402


PRIVATE_MARKER = "OFFLINE_PRIVATE_RESPONSE_MUST_NOT_BE_LOGGED"
CHROME_FIXTURE = Path(__file__).resolve()  # 只通过存在性检查；所有浏览器 API 均被 mock。


def payload(country: str = "SG", timezone: str = "Asia/Singapore") -> dict:
    return {"success": True, "country_code": country, "timezone": {"id": timezone}}


class BrowserRegionTests(unittest.TestCase):
    def test_required_country_defaults_and_serialization(self) -> None:
        for country, locale, timezone in (
            ("US", "en-US", "America/New_York"),
            ("SG", "en-SG", "Asia/Singapore"),
            ("PH", "en-PH", "Asia/Manila"),
        ):
            with self.subTest(country=country):
                region = browser_region.region_from_payload(payload(country, timezone))
                self.assertEqual(region, browser_region.BrowserRegion(country, locale, (locale, "en"), timezone))
                self.assertEqual(region.to_dict(), {
                    "country_code": country, "locale": locale,
                    "languages": [locale, "en"], "timezone_id": timezone,
                })

    def test_common_non_english_country_has_explicit_local_locale(self) -> None:
        for country, locale, language, timezone in (
            ("JP", "ja-JP", "ja", "Asia/Tokyo"),
            ("DE", "de-DE", "de", "Europe/Berlin"),
            ("TW", "zh-TW", "zh", "Asia/Taipei"),
        ):
            with self.subTest(country=country):
                region = browser_region.region_from_payload(payload(country, timezone))
                self.assertEqual(region.locale, locale)
                self.assertEqual(region.languages, (locale, language))

    def test_only_required_fields_are_used(self) -> None:
        value = payload()
        value.update(ip=PRIVATE_MARKER, city=PRIVATE_MARKER, message=PRIVATE_MARKER)
        value["timezone"].update(offset=PRIVATE_MARKER, utc=PRIVATE_MARKER)
        self.assertEqual(browser_region.region_from_payload(value), browser_region.region_from_payload(payload()))

    def test_success_must_be_exact_true(self) -> None:
        for value in (None, [], "success", {}, {"success": 1}, {"success": "true"}, {"success": False}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                browser_region.region_from_payload(value)

    def test_unknown_missing_or_malformed_country_never_falls_back(self) -> None:
        for country in (None, [], "", "us", "ZZ", PRIVATE_MARKER):
            with self.subTest(country=country), self.assertRaises(ValueError) as raised:
                browser_region.region_from_payload({**payload(), "country_code": country})
            self.assertNotIn(PRIVATE_MARKER, str(raised.exception))

    def test_missing_or_invalid_timezone_rejected(self) -> None:
        for timezone in (None, "Asia/Singapore", {}, {"id": None}, {"id": ""},
                         {"id": "Not/A_Timezone"}, {"id": "../UTC"}, {"id": "/etc/passwd"},
                         {"id": "UTC\n"}, {"id": "A" * 129}, {"id": PRIVATE_MARKER}):
            with self.subTest(timezone=timezone), self.assertRaises(ValueError) as raised:
                browser_region.region_from_payload({**payload(), "timezone": timezone})
            self.assertNotIn(PRIVATE_MARKER, str(raised.exception))

    def test_iana_timezone_alias_is_validated_not_guessed(self) -> None:
        region = browser_region.region_from_payload(payload("IN", "Asia/Kolkata"))
        self.assertEqual(region.timezone_id, "Asia/Kolkata")
        self.assertEqual(replace(region, timezone_id="Asia/Calcutta").to_dict()["timezone_id"], "Asia/Calcutta")

    def test_region_is_frozen_and_serialized_languages_are_independent(self) -> None:
        region = browser_region.region_from_payload(payload())
        with self.assertRaises(FrozenInstanceError):
            region.locale = "en-US"
        serialized = region.to_dict()
        serialized["languages"].append("private-fixture")
        self.assertEqual(region.languages, ("en-SG", "en"))

    def test_direct_constructor_must_match_country_mapping(self) -> None:
        region = browser_region.region_from_payload(payload())
        for changed in (
            replace(region, country_code="ZZ"), replace(region, locale="en-US"),
            replace(region, languages=("en-SG", "zh")), replace(region, languages=["en-SG", "en"]),
            replace(region, timezone_id="No/Such_Zone"),
        ):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                changed.to_dict()


class BrowserRegionDetectionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        body = json.dumps(payload()).encode("utf-8")
        self.response = SimpleNamespace(
            status=200, url=browser_region.LOOKUP_URL,
            all_headers=AsyncMock(return_value={
                "content-type": "application/json; charset=utf-8", "content-length": str(len(body)),
            }),
            body=AsyncMock(return_value=body),
        )
        self.page = SimpleNamespace(
            url=browser_region.LOOKUP_URL,
            goto=AsyncMock(return_value=self.response),
            evaluate=AsyncMock(return_value="Asia/Singapore"),
        )
        self.context = SimpleNamespace(
            route=AsyncMock(), new_page=AsyncMock(return_value=self.page), close=AsyncMock(),
        )
        self.profile = None
        self.profile_was_empty = None
        self.profile_mode = None

        async def launch(directory, **_):
            self.profile = Path(directory)
            self.profile_was_empty = list(self.profile.iterdir()) == []
            self.profile_mode = stat.S_IMODE(self.profile.stat().st_mode)
            return self.context

        self.playwright = SimpleNamespace(
            chromium=SimpleNamespace(launch_persistent_context=AsyncMock(side_effect=launch)),
            stop=AsyncMock(),
        )
        self.manager = SimpleNamespace(start=AsyncMock(return_value=self.playwright))
        factory_patch = patch.object(browser_region, "async_playwright", return_value=self.manager)
        self.factory = factory_patch.start()
        self.addCleanup(factory_patch.stop)

    async def detect(self, *, headless=False):
        return await browser_region.detect_browser_region(CHROME_FIXTURE, headless=headless)

    def assert_closed_and_removed(self) -> None:
        self.context.close.assert_awaited_once()
        self.playwright.stop.assert_awaited_once()
        self.assertIsNotNone(self.profile)
        self.assertFalse(self.profile.parent.exists())

    async def test_detect_uses_empty_profile_and_fixed_query_without_proxy_overrides(self) -> None:
        private_proxy = PRIVATE_MARKER
        with patch.dict(browser_region.os.environ, {
            "HTTP_PROXY": private_proxy, "https_proxy": private_proxy, "AlL_PrOxY": private_proxy,
            "PLAYWRIGHT_NODEJS_PATH": "/opt/homebrew/bin/node", "LOCAL_TEST_VALUE": "kept",
        }, clear=True):
            result = await self.detect(headless=True)
        self.assertEqual(result, browser_region.region_from_payload(payload()))
        launch = self.playwright.chromium.launch_persistent_context.await_args
        self.assertEqual(launch.kwargs, {
            "executable_path": str(CHROME_FIXTURE), "headless": True, "ignore_https_errors": False,
            "timeout": 20_000,
            "env": {"PLAYWRIGHT_NODEJS_PATH": "/opt/homebrew/bin/node", "LOCAL_TEST_VALUE": "kept"},
        })
        self.assertTrue(self.profile_was_empty)
        self.assertEqual(self.profile_mode, 0o700)
        self.context.route.assert_awaited_once()
        self.assertEqual(self.context.route.await_args.args[0], "**/*")
        self.page.goto.assert_awaited_once_with(browser_region.LOOKUP_URL, wait_until="commit", timeout=20_000)
        self.page.evaluate.assert_awaited_once_with(browser_region._NORMALIZE_TIMEZONE, "Asia/Singapore")
        self.assert_closed_and_removed()

    async def test_route_allows_only_fixed_get_and_blocks_other_destinations(self) -> None:
        await self.detect()
        callback = self.context.route.await_args.args[1]
        for method, url, allowed in (
            ("GET", browser_region.LOOKUP_URL, True),
            ("POST", browser_region.LOOKUP_URL, False),
            ("GET", "https://ipwho.is/", False),
            ("GET", "https://ipwho.is/favicon.ico", False),
            ("GET", "https://shopee.ph/", False),
            ("GET", "http://ipwho.is/", False),
        ):
            with self.subTest(method=method, url=url):
                route = SimpleNamespace(request=SimpleNamespace(method=method, url=url),
                                        continue_=AsyncMock(), abort=AsyncMock())
                await callback(route)
                self.assertEqual(route.continue_.await_count, int(allowed))
                self.assertEqual(route.abort.await_count, int(not allowed))

    async def test_timezone_alias_normalized_by_browser(self) -> None:
        self.response.body.return_value = json.dumps(payload("IN", "Asia/Kolkata")).encode()
        self.page.evaluate.return_value = "Asia/Calcutta"
        result = await self.detect()
        self.assertEqual(result.timezone_id, "Asia/Calcutta")
        self.assertEqual(result.locale, "en-IN")
        self.page.evaluate.assert_awaited_once_with(browser_region._NORMALIZE_TIMEZONE, "Asia/Kolkata")
        self.assert_closed_and_removed()

    async def test_browser_normalization_must_return_valid_timezone(self) -> None:
        self.page.evaluate.return_value = PRIVATE_MARKER
        with self.assertRaises(ValueError) as raised:
            await self.detect()
        self.assertNotIn(PRIVATE_MARKER, str(raised.exception))
        self.assert_closed_and_removed()

    async def test_http_status_rejected_before_reading_body(self) -> None:
        self.response.status = 403
        with self.assertRaisesRegex(ValueError, "HTTP 200"):
            await self.detect()
        self.response.body.assert_not_awaited()
        self.assert_closed_and_removed()

    async def test_missing_response_rejected(self) -> None:
        self.page.goto.return_value = None
        with self.assertRaisesRegex(ValueError, "HTTP 200"):
            await self.detect()
        self.assert_closed_and_removed()

    async def test_cross_origin_response_rejected(self) -> None:
        self.response.url = "https://ipwho.is.invalid/"
        with self.assertRaisesRegex(ValueError, "非预期来源"):
            await self.detect()
        self.response.body.assert_not_awaited()
        self.assert_closed_and_removed()

    async def test_cross_origin_current_document_rejected(self) -> None:
        self.page.url = "https://another.invalid/"
        with self.assertRaisesRegex(ValueError, "非预期来源"):
            await self.detect()
        self.response.body.assert_not_awaited()
        self.assert_closed_and_removed()

    async def test_lookup_origin_rejects_credentials_ports_and_host_lookalikes(self) -> None:
        for url in (
            "http://ipwho.is/", "https://ipwho.is:444/", "https://ipwho.is.invalid/",
            "https://user@ipwho.is/", "https://@ipwho.is/", "https://ipwho.is@another.invalid/",
            "https://ipwho.is:invalid/", "not a URL", None,
        ):
            with self.subTest(url=url):
                self.assertFalse(browser_region._same_lookup_origin(url))
        self.assertTrue(browser_region._same_lookup_origin(browser_region.LOOKUP_URL))
        self.assertTrue(browser_region._same_lookup_origin("https://ipwho.is:443/"))
        self.factory.assert_not_called()

    async def test_non_json_response_rejected(self) -> None:
        self.response.all_headers.return_value = {"content-type": "text/html"}
        with self.assertRaisesRegex(ValueError, "JSON 内容类型"):
            await self.detect()
        self.response.body.assert_not_awaited()
        self.assert_closed_and_removed()

    async def test_oversized_content_length_rejected_before_body(self) -> None:
        self.response.all_headers.return_value["content-length"] = str(browser_region.MAX_RESPONSE_BYTES + 1)
        with self.assertRaisesRegex(ValueError, "大小上限"):
            await self.detect()
        self.response.body.assert_not_awaited()
        self.assert_closed_and_removed()

    async def test_malformed_content_length_rejected(self) -> None:
        self.response.all_headers.return_value["content-length"] = PRIVATE_MARKER
        with self.assertRaisesRegex(ValueError, "响应长度无效") as raised:
            await self.detect()
        self.assertNotIn(PRIVATE_MARKER, str(raised.exception))
        self.response.body.assert_not_awaited()
        self.assert_closed_and_removed()

    async def test_actual_body_limit_is_checked_without_content_length(self) -> None:
        self.response.all_headers.return_value.pop("content-length")
        self.response.body.return_value = b" " * (browser_region.MAX_RESPONSE_BYTES + 1)
        with self.assertRaisesRegex(ValueError, "大小上限"):
            await self.detect()
        self.page.evaluate.assert_not_awaited()
        self.assert_closed_and_removed()

    async def test_invalid_json_does_not_log_raw_content(self) -> None:
        self.response.body.return_value = PRIVATE_MARKER.encode()
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr), self.assertRaisesRegex(ValueError, "无效 JSON") as raised:
            await self.detect()
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")
        self.assertNotIn(PRIVATE_MARKER, str(raised.exception))
        self.assert_closed_and_removed()

    async def test_unknown_country_is_not_replaced_with_us(self) -> None:
        self.response.body.return_value = json.dumps(payload("ZZ")).encode()
        with self.assertRaisesRegex(ValueError, "不猜测"):
            await self.detect()
        self.page.evaluate.assert_not_awaited()
        self.assert_closed_and_removed()

    async def test_success_false_is_not_replaced_with_us(self) -> None:
        self.response.body.return_value = json.dumps({**payload(), "success": False}).encode()
        with self.assertRaisesRegex(ValueError, "未明确成功"):
            await self.detect()
        self.assert_closed_and_removed()

    async def test_browser_error_is_sanitized_and_cleanup_runs(self) -> None:
        self.page.goto.side_effect = RuntimeError(PRIVATE_MARKER)
        with self.assertRaisesRegex(ValueError, "查询失败") as raised:
            await self.detect()
        self.assertNotIn(PRIVATE_MARKER, str(raised.exception))
        self.assert_closed_and_removed()

    async def test_detection_timeout_cleans_up(self) -> None:
        async def hang(*_, **__):
            await asyncio.Future()
        self.page.goto.side_effect = hang
        with patch.object(browser_region, "LOOKUP_TIMEOUT_SECONDS", 0.01):
            with self.assertRaisesRegex(ValueError, "超过 20 秒"):
                await self.detect()
        self.assert_closed_and_removed()

    async def test_cancellation_cleans_up_and_remains_cancellation(self) -> None:
        started = asyncio.Event()
        async def hang(*_, **__):
            started.set()
            await asyncio.Future()
        self.page.goto.side_effect = hang
        task = asyncio.create_task(self.detect())
        await asyncio.wait_for(started.wait(), timeout=1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assert_closed_and_removed()

    async def test_context_close_failure_still_stops_driver_and_rejects_result(self) -> None:
        self.context.close.side_effect = RuntimeError(PRIVATE_MARKER)
        with self.assertRaisesRegex(ValueError, "未能确认正常关闭") as raised:
            await self.detect()
        self.assertNotIn(PRIVATE_MARKER, str(raised.exception))
        self.assert_closed_and_removed()

    async def test_context_close_timeout_still_stops_driver(self) -> None:
        async def hang():
            await asyncio.Future()
        self.context.close.side_effect = hang
        with patch.object(browser_region, "CLEANUP_TIMEOUT_SECONDS", 0.01):
            with self.assertRaisesRegex(ValueError, "未能确认正常关闭"):
                await self.detect()
        self.assert_closed_and_removed()

    async def test_driver_stop_failure_rejects_success(self) -> None:
        self.playwright.stop.side_effect = RuntimeError(PRIVATE_MARKER)
        with self.assertRaisesRegex(ValueError, "未能确认正常关闭"):
            await self.detect()
        self.assert_closed_and_removed()

    async def test_cancellation_during_context_close_still_stops_driver(self) -> None:
        self.context.close.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await self.detect()
        self.assert_closed_and_removed()

    async def test_browser_launch_failure_stops_started_driver(self) -> None:
        self.playwright.chromium.launch_persistent_context.side_effect = RuntimeError(PRIVATE_MARKER)
        with self.assertRaisesRegex(ValueError, "查询失败"):
            await self.detect()
        self.context.close.assert_not_awaited()
        self.playwright.stop.assert_awaited_once()
        directory = self.playwright.chromium.launch_persistent_context.await_args.args[0]
        self.assertFalse(Path(directory).parent.exists())

    async def test_driver_start_failure_is_sanitized_without_launching_browser(self) -> None:
        self.manager.start.side_effect = RuntimeError(PRIVATE_MARKER)
        with self.assertRaisesRegex(ValueError, "查询失败") as raised:
            await self.detect()
        self.assertNotIn(PRIVATE_MARKER, str(raised.exception))
        self.playwright.chromium.launch_persistent_context.assert_not_awaited()
        self.context.close.assert_not_awaited()

    async def test_missing_browser_does_not_start_driver(self) -> None:
        with self.assertRaisesRegex(ValueError, "找不到"):
            await browser_region.detect_browser_region(ROOT / "definitely-not-installed-chrome")
        self.factory.assert_not_called()

    async def test_invalid_headless_does_not_start_driver(self) -> None:
        with self.assertRaisesRegex(ValueError, "布尔值"):
            await browser_region.detect_browser_region(CHROME_FIXTURE, headless="false")
        self.factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
