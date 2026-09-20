"""离线行为契约：不启动浏览器、不联网、不读取真实 Cookie、不发布 Excel。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/shopee-ugreen-topsales/scripts"
sys.path.insert(0, str(SCRIPTS))
import scraper  # noqa: E402

US_REGION = scraper.BrowserRegion("US", "en-US", ("en-US", "en"), "America/New_York")
FIXTURE_VERSION = "153.0.8010.50"


def fingerprint(region=US_REGION, profile_id="windows-intel") -> dict:
    return scraper.load_fingerprint(profile_id, FIXTURE_VERSION, region)


def card(item_id: str = "100", source_page: int = 0) -> scraper.ProductCard:
    return scraper.ProductCard(
        source_page=source_page,
        source_position=1,
        shop_id=scraper.SHOP_ID,
        item_id=item_id,
        title="仅供离线测试",
        product_url=f"https://shopee.ph/product/{scraper.SHOP_ID}/{item_id}",
        price_php=123,
        monthly_sales_display=None,
        monthly_sales_text=None,
        monthly_sales_count_lower_bound=None,
        monthly_sales_observation="not_displayed",
    )


def probe() -> dict:
    return {
        **{key: value for key, value in fingerprint().items()
           if key not in {"region", "profile_id"}},
        "webdriver_is_undefined": True,
        "user_agent": fingerprint()["user_agent"],
        "user_agent_data": {
            "brands": [
                {"brand": "Google Chrome", "version": "153"},
                {"brand": "Chromium", "version": "153"},
                {"brand": "Not_A Brand", "version": "8"},
            ],
            "platform": "Windows", "mobile": False,
        },
        "language": "en-US",
        "languages": ["en-US", "en"],
        "platform": "Win32",
        "vendor": "Google Inc.",
        "plugin_count": 5,
        "hardware_concurrency": 8,
        "device_memory": 8,
        "chrome_runtime_present": True,
        "time_zone": "America/New_York",
        "screen_width": 1366,
        "screen_height": 768,
    }


def detail_payload(item_id: str = "100") -> dict:
    return {
        "challenge": False,
        "bff": {"test": "in-memory only"},
        "location_identity": {"shop_id": scraper.SHOP_ID, "item_id": item_id},
        "canonical_present": False,
        "og_present": False,
        "stealth_probe": probe(),
    }


class FakePage:
    def __init__(self, url: str = "about:blank") -> None:
        self.url = url
        self.context = SimpleNamespace()
        self.listeners: dict[str, object] = {}
        self.goto = AsyncMock()
        self.evaluate = AsyncMock()
        self.wait_for_timeout = AsyncMock()
        self.close = AsyncMock()

    def on(self, event: str, callback: object) -> None:
        self.listeners[event] = callback


class ConfigurationTests(unittest.TestCase):
    def test_product_identity_only_accepts_https_on_shopee_ph(self) -> None:
        identity = (scraper.SHOP_ID, "123")
        for url in (
            f"https://shopee.ph/product/{scraper.SHOP_ID}/123",
            f"https://shopee.ph/UGREEN-item-i.{scraper.SHOP_ID}.123?test=1",
        ):
            with self.subTest(url=url):
                self.assertEqual(scraper._url_identity(url), identity)
        for url in (
            f"http://shopee.ph/product/{scraper.SHOP_ID}/123",
            f"https://unrelated.example/product/{scraper.SHOP_ID}/123",
            f"https://shopee.ph.example/product/{scraper.SHOP_ID}/123",
            f"https://shopee.ph@unrelated.example/product/{scraper.SHOP_ID}/123",
            f"file:///product/{scraper.SHOP_ID}/123",
        ):
            with self.subTest(url=url):
                self.assertIsNone(scraper._url_identity(url))

    def test_current_init_script_preserves_blocks_and_uses_one_payload_token(self) -> None:
        script = scraper._stealth_template().encode("utf-8")
        self.assertEqual(len(script), 5157)
        self.assertEqual(
            hashlib.sha256(script).hexdigest(),
            scraper.STEALTH_SHA256,
        )
        self.assertEqual(script.count(b"__UGREEN_FINGERPRINT__"), 1)
        for block in (b"'webdriver'", b"Object.getOwnPropertyNames", b"window.chrome =",
                      b"originalPermissionQuery", b"'plugins'", b"'languages'", b"patchWebGL"):
            self.assertIn(block, script)

    def test_user_agent_tracks_chrome_major_without_randomization(self) -> None:
        for version in ("153.0.8010.50", "154.0.10.20"):
            with self.subTest(version=version):
                ua = scraper._windows_chrome_user_agent(version)
                self.assertIn("Windows NT 10.0; Win64; x64", ua)
                self.assertIn(f"Chrome/{version.split('.')[0]}.0.0.0", ua)
                self.assertEqual(ua, scraper._windows_chrome_user_agent(version))
        for version in ("", "0.0.0.0", "153", "153.0.1.2 extra"):
            with self.subTest(version=version):
                with self.assertRaises(scraper.ScrapeError):
                    scraper._windows_chrome_user_agent(version)

    def test_probe_requires_current_153_user_agent_and_existing_fields(self) -> None:
        self.assertTrue(scraper._valid_stealth_probe(probe(), fingerprint()))
        self.assertIn("Chrome/153.0.0.0", probe()["user_agent"])
        self.assertEqual(probe()["user_agent_data"]["brands"][0]["version"], "153")
        for key, value in (
            ("language", "en-PH"), ("languages", ["en-US", "en", "zh-CN"]),
            ("time_zone", "Asia/Manila"), ("platform", "MacIntel"),
            ("plugin_count", 0), ("chrome_runtime_present", False),
            ("user_agent", scraper._windows_chrome_user_agent("122.0.0.0")),
            ("user_agent", scraper._windows_chrome_user_agent("154.0.10.20")),
        ):
            with self.subTest(key=key):
                self.assertFalse(scraper._valid_stealth_probe({**probe(), key: value}, fingerprint()))

    def test_changed_init_script_is_rejected(self) -> None:
        with patch.object(Path, "read_bytes", return_value=b"simplified"):
            with self.assertRaisesRegex(scraper.ScrapeError, "哈希不匹配"):
                scraper._stealth_script(fingerprint())

    def test_default_is_single_worker_and_slow_access(self) -> None:
        config = scraper.BrowserConfig(browser_profile="windows-intel", chrome_version=FIXTURE_VERSION, region=US_REGION, chrome_executable=Path(__file__))
        config.validate()
        self.assertEqual(config.detail_shards, 1)
        self.assertEqual(config.list_interval_ms, 10_000)
        self.assertEqual(config.detail_interval_ms, 10_000)
        self.assertEqual(config.list_settle_ms, 15_000)
        self.assertEqual(config.detail_settle_ms, 300)
        self.assertEqual(config.detail_identity_timeout_ms, 15_000)

    def test_intervals_below_ten_seconds_are_rejected(self) -> None:
        for field in ("list_interval_ms", "detail_interval_ms"):
            for interval in (9999, 0, -1):
                with self.subTest(field=field, interval=interval):
                    config = scraper.BrowserConfig(browser_profile="windows-intel", chrome_version=FIXTURE_VERSION, region=US_REGION,
                        chrome_executable=Path(__file__), **{field: interval}
                    )
                    with self.assertRaisesRegex(ValueError, "不得少于 10 秒"):
                        config.validate()


class ProfileTests(unittest.TestCase):
    def test_profile_snapshot_copies_session_wal_and_cleans_up_without_source_writes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ugreen-offline-test-") as directory:
            source = Path(directory) / "chrome-source"
            values = {
                "Local State": b'{"profile":{"last_used":"Profile 2"}}',
                "Default/Preferences": b"preferences",
                "Default/Secure Preferences": b"secure preferences",
                "Default/Cookies": b"fixture cookie db, not real credentials",
                "Default/Cookies-wal": b"fixture wal",
                "Default/Cookies-shm": b"fixture shm",
                "Default/Local Storage/leveldb/00001.ldb": b"local state",
                "Default/Local Storage/leveldb/LOG": b"fixture database log",
                "Default/Local Storage/leveldb/LOG.old": b"fixture previous log",
                "Default/Local Storage/leveldb/LOCK": b"lock not copied",
                "Default/Session Storage/00002.ldb": b"session state",
                "Default/Session Storage/fixture-journal": b"fixture database journal",
                "Default/Session Storage/fixture-wal": b"fixture database wal",
                "Default/Session Storage/fixture-shm": b"fixture database shm",
                "Default/Service Worker/CacheStorage/unused": b"not needed",
            }
            for name, value in values.items():
                target = source / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(value)
            before = {
                name: ((source / name).read_bytes(), (source / name).stat().st_mtime_ns)
                for name in values
            }
            with patch.object(scraper, "DEFAULT_CHROME_DATA", source):
                with scraper._temporary_chrome_profile_base() as base:
                    snapshot_parent = base.parent
                    self.assertEqual(base.stat().st_mode & 0o777, 0o700)
                    self.assertEqual(snapshot_parent.stat().st_mode & 0o777, 0o700)
                    for name in values:
                        if "LOCK" in name or "Service Worker" in name:
                            self.assertFalse((base / name).exists())
                        else:
                            self.assertEqual((base / name).read_bytes(), values[name])
                    runtime_lock = base / "SingletonLock"
                    runtime_lock.write_bytes(b"fixture process lock")
                    scraper._clean_profile_transients(base)
                    clone = Path(directory) / "cloned-profile"
                    scraper._clone_profile_tree(base, clone)
                    self.assertFalse(runtime_lock.exists())
                    self.assertFalse((clone / "SingletonLock").exists())
                    for name, value in values.items():
                        if "LOCK" not in name and "Service Worker" not in name:
                            self.assertEqual((base / name).read_bytes(), value)
                            self.assertEqual((clone / name).read_bytes(), value)
                    self.assertNotEqual(base, source)
                self.assertFalse(snapshot_parent.exists())
            after = {
                name: ((source / name).read_bytes(), (source / name).stat().st_mtime_ns)
                for name in values
            }
            self.assertEqual(after, before)

    def test_temporary_profile_is_removed_when_caller_fails(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ugreen-offline-test-") as directory:
            source = Path(directory)
            (source / "Default").mkdir()
            with patch.object(scraper, "DEFAULT_CHROME_DATA", source):
                with self.assertRaisesRegex(RuntimeError, "fixture failure"):
                    with scraper._temporary_chrome_profile_base() as base:
                        snapshot_parent = base.parent
                        raise RuntimeError("fixture failure")
            self.assertFalse(snapshot_parent.exists())


class BrowserStartupTests(unittest.IsolatedAsyncioTestCase):
    async def test_startup_registers_injection_and_preserves_default_tab(self) -> None:
        default_page = FakePage("chrome://newtab/")
        context = SimpleNamespace(
            pages=[default_page],
            add_init_script=AsyncMock(),
            close=AsyncMock(),
        )
        playwright = SimpleNamespace(
            chromium=SimpleNamespace(
                launch_persistent_context=AsyncMock(return_value=context)
            ),
            stop=AsyncMock(),
        )
        manager = SimpleNamespace(start=AsyncMock(return_value=playwright))
        with (
            patch.object(scraper, "async_playwright", return_value=manager),
            patch.object(scraper, "_chrome_version", new_callable=AsyncMock) as version_reader,
        ):
            result = await scraper._launch_context(
                scraper.BrowserConfig(browser_profile="windows-intel", chrome_version=FIXTURE_VERSION, region=US_REGION, chrome_executable=Path(__file__)),
                Path("/unused-fixture-profile"),
            )

        self.assertIs(result, context)
        options = playwright.chromium.launch_persistent_context.await_args.kwargs
        self.assertEqual(options["user_agent"], fingerprint()["user_agent"])
        self.assertEqual(options["locale"], "en-US")
        self.assertEqual(options["timezone_id"], "America/New_York")
        version_reader.assert_not_awaited()
        self.assertNotIn("extra_http_headers", options)
        context.add_init_script.assert_awaited_once_with(
            script=scraper._stealth_script(fingerprint())
        )
        default_page.goto.assert_not_awaited()
        default_page.close.assert_not_awaited()
        context.close.assert_not_awaited()
        playwright.stop.assert_not_awaited()

    async def test_version_reader_uses_only_executable_version_command(self) -> None:
        process = SimpleNamespace(
            communicate=AsyncMock(return_value=(b"Google Chrome 153.0.8010.50 \n", None)),
            returncode=0,
        )
        with patch.object(asyncio, "create_subprocess_exec", new=AsyncMock(return_value=process)) as run:
            ua = await scraper._chrome_version(Path("/fixture/Google Chrome"))
        self.assertEqual(ua, FIXTURE_VERSION)
        self.assertEqual(run.await_args.args, ("/fixture/Google Chrome", "--version"))

    async def test_unreadable_version_never_falls_back_to_stale_user_agent(self) -> None:
        for output, code in ((b"unexpected", 0), (b"Google Chrome 153.0.1.2", 1)):
            with self.subTest(output=output, code=code):
                process = SimpleNamespace(
                    communicate=AsyncMock(return_value=(output, None)), returncode=code,
                )
                with patch.object(asyncio, "create_subprocess_exec", new=AsyncMock(return_value=process)):
                    with self.assertRaises(scraper.ScrapeError):
                        await scraper._chrome_version(Path("/fixture/Chrome"))

    async def test_version_timeout_and_cancellation_reap_the_process(self) -> None:
        for error, expected in (
            (asyncio.TimeoutError(), scraper.ScrapeError),
            (asyncio.CancelledError(), asyncio.CancelledError),
        ):
            with self.subTest(error=type(error).__name__):
                process = SimpleNamespace(
                    communicate=AsyncMock(side_effect=error), returncode=None,
                    kill=MagicMock(), wait=AsyncMock(),
                )
                with patch.object(asyncio, "create_subprocess_exec", new=AsyncMock(return_value=process)):
                    with self.assertRaises(expected):
                        await scraper._chrome_version(Path("/fixture/Chrome"))
                process.kill.assert_called_once_with()
                process.wait.assert_awaited_once_with()


class DetailReadinessTests(unittest.IsolatedAsyncioTestCase):
    async def test_identity_is_matched_before_300ms_settle_not_fixed_15s_sleep(self) -> None:
        page = FakePage()
        pending = {"bff": None, "challenge": False}
        initial = detail_payload()
        settled = detail_payload()
        settled["bff"] = {"fresh": "second snapshot"}
        page.evaluate.side_effect = [pending, initial, settled]
        events = MagicMock()
        events.attach_mock(page.evaluate, "evaluate")
        events.attach_mock(page.wait_for_timeout, "wait")

        result = await scraper._wait_for_detail(page, card(), scraper.BrowserConfig(browser_profile="windows-intel", chrome_version=FIXTURE_VERSION, region=US_REGION))

        self.assertIs(result, settled)
        self.assertEqual(page.wait_for_timeout.await_args_list, [call(350), call(300)])
        args = {"shop_id": scraper.SHOP_ID, "item_id": "100"}
        self.assertEqual(events.mock_calls, [
            call.evaluate(scraper.DETAIL_PAGE_SCRIPT, args),
            call.wait(350),
            call.evaluate(scraper.DETAIL_PAGE_SCRIPT, args),
            call.wait(300),
            call.evaluate(scraper.DETAIL_PAGE_SCRIPT, args),
        ])

    async def test_second_snapshot_wrong_identity_is_rejected(self) -> None:
        page = FakePage()
        page.evaluate.side_effect = [detail_payload(), detail_payload("999")]
        with self.assertRaisesRegex(scraper.ScrapeError, "最终页面 URL"):
            await scraper._wait_for_detail(page, card(), scraper.BrowserConfig(browser_profile="windows-intel", chrome_version=FIXTURE_VERSION, region=US_REGION))
        page.wait_for_timeout.assert_awaited_once_with(300)

    async def test_second_snapshot_challenge_is_rejected(self) -> None:
        page = FakePage()
        page.evaluate.side_effect = [detail_payload(), {"challenge": True}]
        with self.assertRaises(scraper.AccessChallengeError):
            await scraper._wait_for_detail(page, card(), scraper.BrowserConfig(browser_profile="windows-intel", chrome_version=FIXTURE_VERSION, region=US_REGION))

    async def test_initial_canonical_mismatch_does_not_settle(self) -> None:
        page = FakePage()
        payload = detail_payload()
        payload.update(canonical_present=True, canonical_identity={
            "shop_id": scraper.SHOP_ID, "item_id": "999"
        })
        page.evaluate.return_value = payload
        with self.assertRaisesRegex(scraper.ScrapeError, "canonical_identity"):
            await scraper._wait_for_detail(page, card(), scraper.BrowserConfig(browser_profile="windows-intel", chrome_version=FIXTURE_VERSION, region=US_REGION))
        page.wait_for_timeout.assert_not_awaited()


class LoginWindowTests(unittest.IsolatedAsyncioTestCase):
    async def test_visible_login_never_waits_for_manual_action(self) -> None:
        page = FakePage("https://shopee.ph/buyer/login")
        with patch("builtins.print") as output:
            with self.assertRaisesRegex(scraper.AccessChallengeError, "不等待人工操作"):
                await scraper._wait_for_login(page, scraper.BrowserConfig(browser_profile="windows-intel", chrome_version=FIXTURE_VERSION, region=US_REGION), scraper.STORE_URL)
        page.wait_for_timeout.assert_not_awaited()
        page.goto.assert_not_awaited()
        output.assert_not_called()
        self.assertFalse(hasattr(page.context, "_ugreen_login_waited"))

    async def test_both_login_routes_are_rejected_without_revisit(self) -> None:
        for url in (
            "https://shopee.ph/buyer/login",
            "https://shopee.ph/account/login",
        ):
            with self.subTest(url=url):
                page = FakePage(url)
                with self.assertRaisesRegex(scraper.AccessChallengeError, "不等待人工操作"):
                    await scraper._wait_for_login(page, scraper.BrowserConfig(browser_profile="windows-intel", chrome_version=FIXTURE_VERSION, region=US_REGION), scraper.STORE_URL)
                page.wait_for_timeout.assert_not_awaited()
                page.goto.assert_not_awaited()

    async def test_non_login_page_does_not_wait(self) -> None:
        for url in (scraper.STORE_URL, "https://shopee.ph/traffic/error", "about:blank"):
            with self.subTest(url=url):
                page = FakePage(url)
                result = await scraper._wait_for_login(page, scraper.BrowserConfig(browser_profile="windows-intel", chrome_version=FIXTURE_VERSION, region=US_REGION), scraper.STORE_URL)
                self.assertFalse(result)
                page.wait_for_timeout.assert_not_awaited()
                page.goto.assert_not_awaited()
                self.assertFalse(hasattr(page.context, "_ugreen_login_waited"))

    async def test_headless_or_repeated_login_fails_without_waiting_again(self) -> None:
        for headless, already_waited in ((True, False), (False, True)):
            with self.subTest(headless=headless, already_waited=already_waited):
                page = FakePage("https://shopee.ph/account/login")
                if already_waited:
                    page.context._ugreen_login_waited = True
                with self.assertRaises(scraper.AccessChallengeError):
                    await scraper._wait_for_login(
                        page, scraper.BrowserConfig(browser_profile="windows-intel", chrome_version=FIXTURE_VERSION, region=US_REGION, headless=headless), scraper.STORE_URL
                    )
                page.wait_for_timeout.assert_not_awaited()
                page.goto.assert_not_awaited()


class AccessWatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_http_200_business_denial_is_detected_without_retaining_response(self) -> None:
        for key in ("error", "error_code", "code"):
            with self.subTest(key=key):
                page = FakePage()
                watch = scraper._watch_access(page)
                payload = {key: 90309999, "private_fixture": "must not be retained"}
                response = SimpleNamespace(
                    url="https://shopee.ph/api/v4/shop/rcmd_items?private_fixture=hidden",
                    status=200,
                    json=AsyncMock(return_value=payload),
                )
                page.listeners["response"](response)
                with self.assertRaisesRegex(scraper.AccessChallengeError, "90309999"):
                    await watch.check()
                await asyncio.sleep(0)
                self.assertEqual(
                    set(vars(watch)),
                    {"error", "tasks", "ignore_shop_tab_90309999"},
                )
                self.assertEqual(watch.tasks, set())
                self.assertNotIn("hidden", watch.error)
                self.assertNotIn("private_fixture", watch.error)
                self.assertNotIn("must not be retained", watch.error)

    async def test_second_tab_can_ignore_only_shop_tab_90309999(self) -> None:
        page = FakePage()
        watch = scraper._watch_access(page, ignore_shop_tab_90309999=True)
        response = SimpleNamespace(
            url="https://shopee.ph/api/v4/shop/get_shop_tab?fixture=hidden",
            status=200,
            json=AsyncMock(return_value={"error": 90309999}),
        )
        page.listeners["response"](response)
        await watch.check()
        self.assertIsNone(watch.error)

        other_page = FakePage()
        other_watch = scraper._watch_access(
            other_page, ignore_shop_tab_90309999=True
        )
        other_response = SimpleNamespace(
            url="https://shopee.ph/api/v4/shop/rcmd_items",
            status=200,
            json=AsyncMock(return_value={"error": 90309999}),
        )
        other_page.listeners["response"](other_response)
        with self.assertRaisesRegex(scraper.AccessChallengeError, "90309999"):
            await other_watch.check()

    async def test_unrelated_hosts_and_paths_are_not_read(self) -> None:
        page = FakePage()
        watch = scraper._watch_access(page)
        for url in (
            "https://unrelated.example/api/v4/shop/items",
            "https://shopee.ph/api/v4/account/info",
        ):
            response = SimpleNamespace(url=url, status=403, json=AsyncMock())
            page.listeners["response"](response)
            response.json.assert_not_awaited()
        await watch.check()
        self.assertIsNone(watch.error)
        self.assertFalse(watch.tasks)

    async def test_http_denial_is_not_hidden_by_non_json_body(self) -> None:
        page = FakePage()
        watch = scraper._watch_access(page)
        response = SimpleNamespace(
            url="https://shopee.ph/api/v4/pdp/get_pc",
            status=429,
            json=AsyncMock(side_effect=ValueError("not JSON")),
        )
        page.listeners["response"](response)
        with self.assertRaisesRegex(scraper.AccessChallengeError, "HTTP 429"):
            await watch.check()
        await asyncio.gather(*tuple(watch.tasks), return_exceptions=True)

    async def test_ignored_shop_tab_business_code_does_not_clear_http_429(self) -> None:
        page = FakePage()
        watch = scraper._watch_access(page, ignore_shop_tab_90309999=True)
        response = SimpleNamespace(
            url="https://shopee.ph/api/v4/shop/get_shop_tab",
            status=429,
            json=AsyncMock(return_value={"error": 90309999}),
        )
        page.listeners["response"](response)
        await asyncio.gather(*tuple(watch.tasks))
        with self.assertRaisesRegex(scraper.AccessChallengeError, "HTTP 429"):
            await watch.check()

    async def test_page_close_cancels_pending_response_read(self) -> None:
        page = FakePage()
        watch = scraper._watch_access(page)
        blocker = asyncio.Event()
        response = SimpleNamespace(
            url="https://shopee.ph/api/v4/search/search_items",
            status=200,
            json=AsyncMock(side_effect=blocker.wait),
        )
        page.listeners["response"](response)
        await asyncio.sleep(0)
        pending = tuple(watch.tasks)
        page.listeners["close"]()
        await asyncio.gather(*pending, return_exceptions=True)
        self.assertTrue(all(task.cancelled() for task in pending))


class PacingTests(unittest.IsolatedAsyncioTestCase):
    async def test_observed_challenge_is_not_hidden_by_blank_navigation(self) -> None:
        page = FakePage()
        scraper._watch_access(page).error = "已观察业务错误码 90309999"
        with patch.object(scraper.asyncio, "sleep", new_callable=AsyncMock) as sleep:
            with self.assertRaises(scraper.AccessChallengeError):
                await scraper._park_and_wait(page, 10_000)
        page.goto.assert_not_awaited()
        sleep.assert_not_awaited()

    async def test_normal_pacing_checks_then_parks_then_sleeps_and_rechecks(self) -> None:
        page = FakePage()
        events = MagicMock()
        events.attach_mock(page.goto, "goto")
        with patch.object(scraper, "_check_access", new_callable=AsyncMock) as check:
            with patch.object(scraper.asyncio, "sleep", new_callable=AsyncMock) as sleep:
                events.attach_mock(check, "check")
                events.attach_mock(sleep, "sleep")
                await scraper._park_and_wait(page, 10_000)
        self.assertEqual(events.mock_calls, [
            call.check(page),
            call.goto("about:blank", wait_until="commit", timeout=10_000),
            call.check(page),
            call.sleep(10),
            call.check(page),
        ])


class SecondTabListingTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_startup_tabs_are_preserved_on_success_and_failure(self) -> None:
        for fails in (False, True):
            with self.subTest(fails=fails):
                startup_pages = [FakePage("chrome://newtab/"), FakePage()]
                listing_page = FakePage()
                context = SimpleNamespace(
                    pages=startup_pages,
                    new_page=AsyncMock(return_value=listing_page),
                )
                config = scraper.BrowserConfig(browser_profile="windows-intel", chrome_version=FIXTURE_VERSION, region=US_REGION, chrome_executable=Path(__file__))
                payload = {"total": 28, "cards": [object()] * 30}
                load = AsyncMock(return_value=payload)
                if fails:
                    load.side_effect = scraper.AccessChallengeError("列表页出现验证码")
                with patch.object(scraper, "_load_list_page", new=load):
                    if fails:
                        with self.assertRaises(scraper.AccessChallengeError):
                            await scraper._load_list_page_with_extra_tab(
                                context, 0, config, None
                            )
                        listing_page.close.assert_awaited_once()
                    else:
                        result, accepted_page = await scraper._load_list_page_with_extra_tab(
                            context, 0, config, None
                        )
                        self.assertIs(result, payload)
                        self.assertIs(accepted_page, listing_page)
                        listing_page.close.assert_not_awaited()

                context.new_page.assert_awaited_once()
                load.assert_awaited_once_with(
                    listing_page, 0, config, None, ignore_shop_tab_90309999=True
                )
                for startup_page in startup_pages:
                    startup_page.goto.assert_not_awaited()
                    startup_page.close.assert_not_awaited()

    async def test_listing_loads_in_second_tab_with_first_tab_kept_blank(self) -> None:
        first_page, second_page = FakePage(), FakePage()
        context = SimpleNamespace(
            pages=[],
            new_page=AsyncMock(side_effect=[first_page, second_page])
        )
        config = scraper.BrowserConfig(browser_profile="windows-intel", chrome_version=FIXTURE_VERSION, region=US_REGION, chrome_executable=Path(__file__))
        payload = {"total": 28, "cards": [object()] * 30}
        with patch.object(
            scraper,
            "_load_list_page",
            new=AsyncMock(return_value=payload),
        ) as load:
            result, accepted_page = await scraper._load_list_page_with_extra_tab(
                context, 7, config, 28
            )

        self.assertIs(result, payload)
        self.assertIs(accepted_page, second_page)
        self.assertEqual(context.new_page.await_count, 2)
        load.assert_awaited_once_with(
            second_page, 7, config, 28, ignore_shop_tab_90309999=True
        )
        first_page.goto.assert_not_awaited()
        first_page.close.assert_awaited_once()
        second_page.close.assert_not_awaited()

    async def test_http_denial_closes_both_tabs_without_retry(self) -> None:
        first_page, second_page = FakePage(), FakePage()
        context = SimpleNamespace(
            pages=[],
            new_page=AsyncMock(side_effect=[first_page, second_page])
        )
        config = scraper.BrowserConfig(browser_profile="windows-intel", chrome_version=FIXTURE_VERSION, region=US_REGION, chrome_executable=Path(__file__))
        with patch.object(
            scraper,
            "_load_list_page",
            new=AsyncMock(
                side_effect=scraper.AccessChallengeError(
                    "商品接口拒绝访问：/api/v4/shop/get_shop_tab，HTTP 429"
                )
            ),
        ) as load:
            with self.assertRaisesRegex(scraper.AccessChallengeError, "HTTP 429"):
                await scraper._load_list_page_with_extra_tab(
                    context, 0, config, None
                )
        self.assertEqual(context.new_page.await_count, 2)
        load.assert_awaited_once()
        first_page.close.assert_awaited_once()
        second_page.close.assert_awaited_once()

    async def test_second_tab_failure_stops_without_third_tab(self) -> None:
        first_page, second_page = FakePage(), FakePage()
        context = SimpleNamespace(
            pages=[],
            new_page=AsyncMock(side_effect=[first_page, second_page])
        )
        config = scraper.BrowserConfig(browser_profile="windows-intel", chrome_version=FIXTURE_VERSION, region=US_REGION, chrome_executable=Path(__file__))
        denial = scraper.AccessChallengeError("列表页出现验证码")
        with patch.object(
            scraper,
            "_load_list_page",
            new=AsyncMock(side_effect=denial),
        ) as load:
            with self.assertRaisesRegex(scraper.AccessChallengeError, "验证码"):
                await scraper._load_list_page_with_extra_tab(
                    context, 0, config, None
                )
        self.assertEqual(context.new_page.await_count, 2)
        load.assert_awaited_once()
        first_page.close.assert_awaited_once()
        second_page.close.assert_awaited_once()

    async def test_second_tab_creation_failure_releases_first_tab(self) -> None:
        first_page = FakePage()
        context = SimpleNamespace(
            pages=[],
            new_page=AsyncMock(side_effect=[first_page, RuntimeError("新标签页创建失败")])
        )
        config = scraper.BrowserConfig(browser_profile="windows-intel", chrome_version=FIXTURE_VERSION, region=US_REGION, chrome_executable=Path(__file__))
        with patch.object(scraper, "_load_list_page", new_callable=AsyncMock) as load:
            with self.assertRaisesRegex(RuntimeError, "新标签页创建失败"):
                await scraper._load_list_page_with_extra_tab(
                    context, 0, config, None
                )
        self.assertEqual(context.new_page.await_count, 2)
        load.assert_not_awaited()
        first_page.close.assert_awaited_once()

    async def test_failure_progress_reuses_diagnostic_without_reading_again(self) -> None:
        for has_diagnostic in (False, True):
            with self.subTest(has_diagnostic=has_diagnostic):
                startup_page, listing_page = FakePage(), FakePage()
                context = SimpleNamespace(
                    pages=[startup_page], new_page=AsyncMock(return_value=listing_page)
                )
                failure = scraper.ScrapeError("首次列表快照无效")
                if has_diagnostic:
                    failure.snapshot_diagnostic = "已有快照：商品卡=0，结果区域=0"
                progress = MagicMock()
                with patch.object(scraper, "_load_list_page", new=AsyncMock(side_effect=failure)):
                    with self.assertRaises(scraper.ScrapeError) as raised:
                        await scraper._load_list_page_with_extra_tab(
                            context, 0, scraper.BrowserConfig(browser_profile="windows-intel", chrome_version=FIXTURE_VERSION, region=US_REGION), None, progress=progress
                        )
                self.assertIs(raised.exception, failure)
                listing_page.evaluate.assert_not_awaited()
                listing_page.close.assert_awaited_once()
                startup_page.close.assert_not_awaited()
                self.assertTrue(progress.called)
                if has_diagnostic:
                    self.assertTrue(any(
                        failure.snapshot_diagnostic in entry.args[0]
                        for entry in progress.call_args_list
                    ))


class ListReadinessTests(unittest.IsolatedAsyncioTestCase):
    def ready_payload(self) -> dict:
        return {
            "challenge": False,
            "result_view_count": 1,
            "final_url": scraper.STORE_PAGE_URL_TEMPLATE.format(page=0),
            "current_values": ["1"],
            "total_values": ["2"],
            "cards": [{
                "shop_id": scraper.SHOP_ID,
                "item_id": str(100 + index),
                "title": f"离线列表商品 {index}",
                "product_url": f"https://shopee.ph/product/{scraper.SHOP_ID}/{100 + index}",
                "price_text": "123.45",
                "monthly_sales_display": None,
                "monthly_sales_text": None,
            } for index in range(30)],
            "stealth_probe": probe(),
            "next_button_count": 1,
            "next_url": scraper.STORE_PAGE_URL_TEMPLATE.format(page=1),
            "next_disabled": False,
            "scoped_anchor_count": 30,
        }

    async def test_list_waits_fifteen_seconds_then_reads_exactly_one_snapshot(self) -> None:
        page = FakePage(scraper.STORE_PAGE_URL_TEMPLATE.format(page=0))
        page.goto.return_value = SimpleNamespace(status=200)
        payload = self.ready_payload()
        page.evaluate.return_value = payload
        events = MagicMock()
        events.attach_mock(page.goto, "goto")
        events.attach_mock(page.wait_for_timeout, "wait")
        events.attach_mock(page.evaluate, "evaluate")

        with patch.object(scraper, "_wait_for_login", new_callable=AsyncMock) as login:
            result = await scraper._load_list_page(
                page, 0, scraper.BrowserConfig(browser_profile="windows-intel", chrome_version=FIXTURE_VERSION, region=US_REGION), None
            )

        self.assertIs(result, payload)
        self.assertEqual(result["total"], 2)
        self.assertEqual([entry[0] for entry in events.mock_calls], ["goto", "wait", "evaluate"])
        page.wait_for_timeout.assert_awaited_once_with(15_000)
        page.evaluate.assert_awaited_once_with(
            scraper.LIST_PAGE_SCRIPT, {"expected_shop_id": scraper.SHOP_ID}
        )
        login.assert_not_awaited()

    async def test_challenge_during_list_wait_is_rejected_after_single_snapshot(self) -> None:
        page = FakePage(scraper.STORE_PAGE_URL_TEMPLATE.format(page=0))
        page.goto.return_value = SimpleNamespace(status=200)
        page.evaluate.return_value = self.ready_payload()

        async def redirect_to_challenge(milliseconds):
            page.url = "https://shopee.ph/verify/traffic"

        page.wait_for_timeout.side_effect = redirect_to_challenge
        with self.assertRaises(scraper.AccessChallengeError):
            await scraper._load_list_page(page, 0, scraper.BrowserConfig(browser_profile="windows-intel", chrome_version=FIXTURE_VERSION, region=US_REGION), None)

        page.wait_for_timeout.assert_awaited_once_with(15_000)
        page.evaluate.assert_awaited_once()
        page.goto.assert_awaited_once()

    async def test_initial_denial_waits_and_reads_once_before_rejection(self) -> None:
        store_url = scraper.STORE_PAGE_URL_TEMPLATE.format(page=0)
        cases = (
            (429, store_url, False, scraper.AccessChallengeError),
            (404, store_url, False, scraper.ScrapeError),
            (200, "https://shopee.ph/buyer/login", False, scraper.AccessChallengeError),
            (200, "https://shopee.ph/verify/captcha", False, scraper.AccessChallengeError),
            (200, "https://shopee.ph/verify/traffic", False, scraper.AccessChallengeError),
            (200, store_url, True, scraper.AccessChallengeError),
        )
        for status, url, challenge, error_type in cases:
            with self.subTest(status=status, url=url, challenge=challenge):
                page = FakePage(url)
                page.goto.return_value = SimpleNamespace(status=status)
                page.evaluate.return_value = {**self.ready_payload(), "challenge": challenge}
                events = MagicMock()
                events.attach_mock(page.goto, "goto")
                events.attach_mock(page.wait_for_timeout, "wait")
                events.attach_mock(page.evaluate, "evaluate")
                with patch.object(scraper, "_wait_for_login", new_callable=AsyncMock) as login:
                    with self.assertRaises(error_type):
                        await scraper._load_list_page(page, 0, scraper.BrowserConfig(browser_profile="windows-intel", chrome_version=FIXTURE_VERSION, region=US_REGION), None)
                self.assertEqual([entry[0] for entry in events.mock_calls], ["goto", "wait", "evaluate"])
                page.wait_for_timeout.assert_awaited_once_with(15_000)
                login.assert_not_awaited()

    async def test_existing_api_denial_is_preserved_after_wait_and_snapshot(self) -> None:
        page = FakePage(scraper.STORE_PAGE_URL_TEMPLATE.format(page=0))
        page.goto.return_value = SimpleNamespace(status=200)
        page.evaluate.return_value = self.ready_payload()
        watch = scraper._watch_access(page)
        watch.error = "商品接口拒绝访问：HTTP 429"
        with self.assertRaisesRegex(scraper.AccessChallengeError, "HTTP 429"):
            await scraper._load_list_page(page, 0, scraper.BrowserConfig(browser_profile="windows-intel", chrome_version=FIXTURE_VERSION, region=US_REGION), None)
        self.assertEqual(watch.error, "商品接口拒绝访问：HTTP 429")
        page.wait_for_timeout.assert_awaited_once_with(15_000)
        page.evaluate.assert_awaited_once()

    async def test_invalid_snapshot_is_rejected_without_polling_or_scrolling(self) -> None:
        changes = (
            {"final_url": "https://example.invalid/ugreen.ph?page=0&sortBy=sales&tab=0"},
            {"current_values": ["2"]},
            {"total_values": []},
            {"total_values": ["2", "3"]},
            {"total_values": ["0"]},
            {"total_values": ["unknown"]},
            {"result_view_count": 0},
            {"errors": ["missing title"]},
            {"errors": ["expected one price, found 2"]},
            {"errors": ["conflicting monthly sales"]},
            {"cards": []},
            {"scoped_anchor_count": 29},
            {"next_button_count": 2},
            {"next_url": None},
            {"next_disabled": True},
            {"stealth_probe": {**probe(), "plugin_count": 0}},
        )
        for change in changes:
            with self.subTest(change=change):
                page = FakePage(scraper.STORE_PAGE_URL_TEMPLATE.format(page=0))
                page.goto.return_value = SimpleNamespace(status=200)
                page.evaluate.return_value = {**self.ready_payload(), **change}
                with self.assertRaises(scraper.ScrapeError):
                    await scraper._load_list_page(page, 0, scraper.BrowserConfig(browser_profile="windows-intel", chrome_version=FIXTURE_VERSION, region=US_REGION), None)
                page.goto.assert_awaited_once()
                page.wait_for_timeout.assert_awaited_once_with(15_000)
                page.evaluate.assert_awaited_once_with(
                    scraper.LIST_PAGE_SCRIPT, {"expected_shop_id": scraper.SHOP_ID}
                )

    async def test_each_snapshot_card_keeps_identity_price_and_monthly_validation(self) -> None:
        changes = (
            {"shop_id": "999"},
            {"product_url": f"https://example.invalid/product/{scraper.SHOP_ID}/100"},
            {"product_url": f"https://shopee.ph/product/{scraper.SHOP_ID}/999"},
            {"price_text": "not a price"},
            {"price_text": "-1"},
            {"monthly_sales_display": "-1"},
            {"monthly_sales_display": "invalid"},
        )
        for change in changes:
            with self.subTest(change=change):
                page = FakePage(scraper.STORE_PAGE_URL_TEMPLATE.format(page=0))
                page.goto.return_value = SimpleNamespace(status=200)
                payload = self.ready_payload()
                payload["cards"][0].update(change)
                page.evaluate.return_value = payload
                with self.assertRaises(scraper.ScrapeError):
                    await scraper._load_list_page(page, 0, scraper.BrowserConfig(browser_profile="windows-intel", chrome_version=FIXTURE_VERSION, region=US_REGION), None)
                page.evaluate.assert_awaited_once()

    async def test_total_change_and_incomplete_nonterminal_page_are_rejected(self) -> None:
        for expected_total, count in ((3, 30), (2, 29), (2, 31)):
            with self.subTest(expected_total=expected_total, count=count):
                page = FakePage(scraper.STORE_PAGE_URL_TEMPLATE.format(page=0))
                page.goto.return_value = SimpleNamespace(status=200)
                payload = self.ready_payload()
                payload["cards"] = (payload["cards"] + [dict(payload["cards"][0])])[:count]
                payload["scoped_anchor_count"] = count
                page.evaluate.return_value = payload
                with self.assertRaises(scraper.ScrapeError):
                    await scraper._load_list_page(page, 0, scraper.BrowserConfig(browser_profile="windows-intel", chrome_version=FIXTURE_VERSION, region=US_REGION), expected_total)
                page.evaluate.assert_awaited_once()

    async def test_terminal_page_accepts_one_snapshot_only_with_valid_end_marker(self) -> None:
        for count, disabled, next_url, valid in (
            (1, True, None, True), (30, True, None, True),
            (0, True, None, False), (31, True, None, False),
            (1, False, None, False), (1, True, "https://shopee.ph/next", False),
        ):
            with self.subTest(count=count, disabled=disabled, next_url=next_url):
                page = FakePage(scraper.STORE_PAGE_URL_TEMPLATE.format(page=0))
                page.goto.return_value = SimpleNamespace(status=200)
                payload = self.ready_payload()
                payload.update(total_values=["1"], next_disabled=disabled, next_url=next_url)
                payload["cards"] = (payload["cards"] + [dict(payload["cards"][0])])[:count]
                payload["scoped_anchor_count"] = count
                page.evaluate.return_value = payload
                if valid:
                    self.assertIs(
                        await scraper._load_list_page(page, 0, scraper.BrowserConfig(browser_profile="windows-intel", chrome_version=FIXTURE_VERSION, region=US_REGION), 1), payload
                    )
                else:
                    with self.assertRaises(scraper.ScrapeError):
                        await scraper._load_list_page(page, 0, scraper.BrowserConfig(browser_profile="windows-intel", chrome_version=FIXTURE_VERSION, region=US_REGION), 1)
                page.wait_for_timeout.assert_awaited_once_with(15_000)
                page.evaluate.assert_awaited_once()

    async def test_snapshot_execution_error_is_wrapped_without_in_page_retry(self) -> None:
        page = FakePage(scraper.STORE_PAGE_URL_TEMPLATE.format(page=0))
        page.goto.return_value = SimpleNamespace(status=200)
        page.evaluate.side_effect = RuntimeError("离线模拟页面脚本执行失败")
        with self.assertRaisesRegex(scraper.ScrapeError, "脚本执行失败"):
            await scraper._load_list_page(page, 0, scraper.BrowserConfig(browser_profile="windows-intel", chrome_version=FIXTURE_VERSION, region=US_REGION, retries=3), None)
        page.goto.assert_awaited_once()
        page.wait_for_timeout.assert_awaited_once_with(15_000)
        page.evaluate.assert_awaited_once()


class ListBrowserRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_ordinary_failures_restart_browser_with_same_profile_and_backoff(self) -> None:
        profile = Path("/unused-fixture-profile")
        config = scraper.BrowserConfig(browser_profile="windows-intel", chrome_version=FIXTURE_VERSION, region=US_REGION, retries=3)
        payload = {"total": 28, "cards": [object()] * 30}
        events = MagicMock()
        with ExitStack() as stack:
            load = stack.enter_context(patch.object(
                scraper, "_capture_list_page_attempt",
                new=AsyncMock(side_effect=[
                    scraper.ScrapeError("暂时缺少分页"),
                    scraper.ScrapeError("商品卡尚未稳定"),
                    payload,
                ]),
            ))
            sleep = stack.enter_context(patch.object(
                scraper.asyncio, "sleep", new_callable=AsyncMock
            ))
            events.attach_mock(load, "capture")
            events.attach_mock(sleep, "sleep")
            result = await scraper._capture_list_page_with_profile(
                profile, 4, config, 28
            )

        self.assertIs(result, payload)
        self.assertEqual([entry[0] for entry in events.mock_calls], [
            "capture", "sleep", "capture", "sleep", "capture"
        ])
        self.assertEqual(sleep.await_args_list, [call(10), call(20)])
        self.assertEqual([entry.args[0] for entry in load.await_args_list], [profile] * 3)
        self.assertEqual([entry.args[1] for entry in load.await_args_list], [4] * 3)
        self.assertEqual([entry.args[3] for entry in load.await_args_list], [28] * 3)
        self.assertTrue(all(entry.args[2].retries == 1 for entry in load.await_args_list))
        self.assertEqual(config.retries, 3)

    async def test_access_challenge_restarts_at_most_three_times_with_bounded_backoff(self) -> None:
        profile = Path("/unused-fixture-profile")
        events = MagicMock()
        with ExitStack() as stack:
            load = stack.enter_context(patch.object(
                scraper, "_capture_list_page_attempt",
                new=AsyncMock(side_effect=scraper.AccessChallengeError("页面进入验证")),
            ))
            sleep = stack.enter_context(patch.object(
                scraper.asyncio, "sleep", new_callable=AsyncMock
            ))
            events.attach_mock(load, "capture")
            events.attach_mock(sleep, "sleep")
            with self.assertRaises(scraper.AccessChallengeError):
                await scraper._capture_list_page_with_profile(
                    profile, 0, scraper.BrowserConfig(browser_profile="windows-intel", chrome_version=FIXTURE_VERSION, region=US_REGION, retries=3), None
                )

        self.assertEqual([entry[0] for entry in events.mock_calls], [
            "capture", "sleep", "capture", "sleep", "capture"
        ])
        self.assertEqual(load.await_count, 3)
        self.assertEqual([entry.args[0] for entry in load.await_args_list], [profile] * 3)
        self.assertTrue(all(entry.args[2].retries == 1 for entry in load.await_args_list))
        self.assertEqual(sleep.await_args_list, [call(10), call(20)])

    async def test_second_browser_can_succeed_after_first_access_challenge(self) -> None:
        profile = Path("/unused-fixture-profile")
        config = scraper.BrowserConfig(browser_profile="windows-intel", chrome_version=FIXTURE_VERSION, region=US_REGION, retries=3)
        payload = {"total": 28, "cards": [object()] * 30}
        with (
            patch.object(scraper, "_capture_list_page_attempt", new=AsyncMock(side_effect=[
                scraper.AccessChallengeError("首次页面进入验证"), payload,
            ])) as attempt,
            patch.object(scraper.asyncio, "sleep", new_callable=AsyncMock) as sleep,
        ):
            result = await scraper._capture_list_page_with_profile(profile, 0, config, None)

        self.assertIs(result, payload)
        self.assertEqual(attempt.await_count, 2)
        self.assertEqual([entry.args[0] for entry in attempt.await_args_list], [profile] * 2)
        self.assertTrue(all(entry.args[2].retries == 1 for entry in attempt.await_args_list))
        sleep.assert_awaited_once_with(10)


class FullTraversalTests(unittest.IsolatedAsyncioTestCase):
    async def test_listing_visits_every_page_and_deduplicates_without_skipping_pages(self) -> None:
        page_ids = ("100", "101", "102", "100", "103")

        async def capture(
            base, page_index, config, expected_total, *, progress=None
        ):
            self.assertIsNone(progress)
            self.assertEqual(expected_total, None if page_index == 0 else 5)
            item_id = page_ids[page_index]
            return {"total": 5, "cards": [{
                "shop_id": scraper.SHOP_ID,
                "item_id": item_id,
                "title": f"离线商品 {item_id}",
                "product_url": f"https://shopee.ph/product/{scraper.SHOP_ID}/{item_id}",
                "price_text": "123",
            }]}

        with patch.object(scraper, "_capture_list_page_with_profile", side_effect=capture) as fetch:
            with patch.object(scraper.asyncio, "sleep", new_callable=AsyncMock) as sleep:
                cards, pages, occurrences, duplicates = await scraper._collect_listing(
                    Path("/unused-fixture-profile"), scraper.BrowserConfig(browser_profile="windows-intel", chrome_version=FIXTURE_VERSION, region=US_REGION), None
                )
        self.assertEqual([args.args[1] for args in fetch.await_args_list], [0, 1, 2, 3, 4])
        self.assertEqual((pages, occurrences, duplicates), (5, 5, 1))
        self.assertEqual([value.item_id for value in cards], ["100", "101", "102", "103"])
        self.assertEqual([value.source_page for value in cards], [0, 1, 2, 4])
        self.assertEqual(sleep.await_args_list, [call(10)] * 4)

    async def test_every_unique_detail_is_visited_with_slow_serial_pacing(self) -> None:
        page = FakePage()
        context = SimpleNamespace(new_page=AsyncMock(return_value=page))
        cards = [card(str(100 + index), index) for index in range(4)]
        records = [object() for _ in cards]
        with patch.object(scraper, "_visit_detail", side_effect=records) as visit:
            with patch.object(scraper, "_park_and_wait", new_callable=AsyncMock) as park:
                result = await scraper._collect_details(
                    [context], cards, scraper.BrowserConfig(browser_profile="windows-intel", chrome_version=FIXTURE_VERSION, region=US_REGION), None
                )
        self.assertEqual(result, records)
        self.assertEqual([args.args[1] for args in visit.await_args_list], cards)
        self.assertEqual([args.args[2] for args in visit.await_args_list], [1, 2, 3, 4])
        self.assertEqual(park.await_args_list, [call(page, 10_000)] * 3 + [call(page, 0)])
        page.close.assert_awaited_once()


class VerificationSelectionTests(unittest.TestCase):
    def test_selects_different_source_pages_and_only_reuses_urls_and_ids(self) -> None:
        from openpyxl import Workbook

        with tempfile.TemporaryDirectory(prefix="ugreen-offline-test-") as directory:
            workbook_path = Path(directory) / "reference-fixture.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "商品汇总"
            sheet.append(["只供测试，不是抓取结果"])
            for _ in range(4):
                sheet.append([])
            sheet.append(["列表页", "店铺ID", "商品ID", "商品链接", "价格PHP", "月销量", "商品标题"])
            for number in range(1, 8):
                item_id = str(100 + number)
                sheet.append([
                    number, scraper.SHOP_ID, item_id,
                    f"https://shopee.ph/product/{scraper.SHOP_ID}/{item_id}",
                    987654, 876543, "旧表标题不得复用",
                ])
            sheet.append([
                7, scraper.SHOP_ID, "999",
                f"https://shopee.ph/product/{scraper.SHOP_ID}/999",
                987654, 876543, "旧表末尾标题不得复用",
            ])
            workbook.save(workbook_path)
            workbook.close()
            before = workbook_path.read_bytes()

            selected = scraper._select_verification_targets(workbook_path)

            self.assertEqual([target.source_page for target in selected], [0, 3, 6])
            self.assertEqual([target.item_id for target in selected], ["101", "104", "999"])
            for target in selected:
                self.assertEqual(target.shop_id, scraper.SHOP_ID)
                self.assertEqual(scraper._url_identity(target.product_url), (target.shop_id, target.item_id))
                self.assertEqual(target.title, "")
                self.assertEqual(target.price_php, 0)
                self.assertIsNone(target.monthly_sales_display)
                self.assertIsNone(target.monthly_sales_text)
                self.assertIsNone(target.monthly_sales_count_lower_bound)
                self.assertEqual(target.monthly_sales_observation, "verification_only")
            self.assertEqual(workbook_path.read_bytes(), before)
            self.assertEqual(list(Path(directory).iterdir()), [workbook_path])


class VerificationFlowTests(unittest.IsolatedAsyncioTestCase):
    async def run_verification(self, *, listing_failure=False, detail_failure_at=None):
        targets = [card("100", 0), card("200", 13), card("300", 27)]
        startup_page = FakePage("chrome://newtab/")
        detail_page = FakePage()
        context = SimpleNamespace(
            pages=[startup_page],
            new_page=AsyncMock(return_value=detail_page)
        )
        profile = MagicMock()
        profile.__enter__.return_value = Path("/unused-fixture-profile")
        profile.__exit__.return_value = False
        listing = AsyncMock(return_value={"total": 28, "cards": [object()] * 30})
        if listing_failure:
            denial = scraper.AccessChallengeError(
                "商品接口拒绝访问：/api/v4/shop/get_shop_tab，业务错误码 90309999"
            )
            listing.side_effect = denial

        async def visit(page, target, rank, config):
            if rank == detail_failure_at:
                raise scraper.AccessChallengeError("商品详情访问挑战")
            return SimpleNamespace(
                title=f"本次实时读取 {target.item_id}",
                skus=[object()] * rank,
                secondary_image_urls=["https://image.example/fixture"] * (rank + 1),
            )

        with ExitStack() as stack:
            stack.enter_context(patch.object(scraper, "_select_verification_targets", return_value=targets))
            stack.enter_context(patch.object(scraper, "_temporary_chrome_profile_base", return_value=profile))
            launch = stack.enter_context(patch.object(scraper, "_launch_context", new=AsyncMock(return_value=context)))
            close = stack.enter_context(patch.object(scraper, "_close_context", new_callable=AsyncMock))
            stack.enter_context(patch.object(scraper, "_capture_list_page_with_profile", new=listing))
            visited = stack.enter_context(patch.object(scraper, "_visit_detail", side_effect=visit))
            park = stack.enter_context(patch.object(scraper, "_park_and_wait", new_callable=AsyncMock))
            sleep = stack.enter_context(patch.object(scraper.asyncio, "sleep", new_callable=AsyncMock))
            publish = stack.enter_context(patch("excel.write_excel", side_effect=AssertionError("验证不得导出 Excel")))
            save = stack.enter_context(patch("openpyxl.workbook.workbook.Workbook.save", side_effect=AssertionError("验证不得写工作簿")))
            full_crawl = stack.enter_context(patch.object(scraper, "scrape_all", side_effect=AssertionError("验证不得冒充全量")))
            config = scraper.BrowserConfig(browser_profile="windows-intel", chrome_version=FIXTURE_VERSION, region=US_REGION, chrome_executable=Path(__file__))
            report = await scraper.verify_access(
                config,
                Path("/unused-fixture-reference.xlsx"),
            )
            publish.assert_not_called()
            save.assert_not_called()
            full_crawl.assert_not_called()
            launch.assert_awaited_once_with(config, profile.__enter__.return_value)
            close.assert_awaited_once_with(context)
            context.new_page.assert_awaited_once()
            listing.assert_awaited_once_with(
                profile.__enter__.return_value, 0, config, None, progress=None
            )
            sleep.assert_awaited_once_with(10)
            startup_page.goto.assert_not_awaited()
            startup_page.close.assert_not_awaited()
            detail_page.close.assert_awaited_once()
            self.assertFalse(report["full_crawl_completed"])
            self.assertFalse(report["workbook_written"])
            return report, visited, park

    async def test_failed_listing_and_successful_details_are_partial_without_excel(self) -> None:
        report, visited, park = await self.run_verification(listing_failure=True)
        self.assertFalse(report["list_pass"])
        self.assertEqual(report["list_pages_checked"], 0)
        self.assertIn("90309999", report["list_error"])
        self.assertEqual(report["detail_success_count"], 3)
        self.assertEqual(report["detail_attempted_count"], 3)
        self.assertEqual([value["reference_source_page"] for value in report["details"]], [1, 14, 28])
        self.assertEqual([value["sku_count"] for value in report["details"]], [1, 2, 3])
        self.assertEqual([value["gallery_count"] for value in report["details"]], [3, 4, 5])
        self.assertTrue(all(value["passed"] for value in report["details"]))
        self.assertEqual(visited.await_count, 3)
        self.assertEqual([args.args[1] for args in park.await_args_list], [10_000, 10_000, 0])
        self.assertTrue(all("price_php" not in value for value in report["details"]))

    async def test_detail_challenge_stops_without_visiting_remaining_targets(self) -> None:
        report, visited, park = await self.run_verification(detail_failure_at=2)
        self.assertTrue(report["list_pass"])
        self.assertEqual(report["list_pages_checked"], 1)
        self.assertEqual(report["detail_success_count"], 1)
        self.assertEqual(report["detail_attempted_count"], 2)
        self.assertEqual(report["detail_target_count"], 3)
        self.assertEqual(visited.await_count, 2)
        self.assertEqual([value["item_id"] for value in report["details"]], ["100", "200"])
        self.assertFalse(report["details"][1]["passed"])
        self.assertIn("访问挑战", report["details"][1]["error"])

    async def test_even_all_diagnostic_checks_passing_is_not_full_crawl(self) -> None:
        report, visited, park = await self.run_verification()
        self.assertTrue(report["list_pass"])
        self.assertEqual(report["detail_success_count"], 3)
        self.assertFalse(report["full_crawl_completed"])
        self.assertFalse(report["workbook_written"])


class DynamicRegionTests(unittest.IsolatedAsyncioTestCase):
    async def test_eight_profiles_use_matching_context_and_probe(self) -> None:
        self.assertEqual(len(scraper.APPROVED_PROFILE_IDS), 8)
        region = scraper.BrowserRegion("SG", "en-SG", ("en-SG", "en"), "Asia/Singapore")
        for profile_id in scraper.APPROVED_PROFILE_IDS:
            with self.subTest(profile=profile_id):
                fp = fingerprint(region, profile_id)
                config = scraper.BrowserConfig(region=region, browser_profile=profile_id,
                                               chrome_version=FIXTURE_VERSION)
                observed = {**probe(), **{k: v for k, v in fp.items() if k not in {"region", "profile_id"}},
                            "language": region.locale, "languages": list(region.languages),
                            "time_zone": region.timezone_id}
                self.assertTrue(scraper._valid_stealth_probe(observed, fp))
                for key in ("webgl_renderer", "webgl_vendor", "max_touch_points", "pdf_viewer_enabled",
                            "chrome_version", "platform", "hardware_concurrency", "screen_width"):
                    self.assertFalse(scraper._valid_stealth_probe({**observed, key: None}, fp), key)
                context = SimpleNamespace(add_init_script=AsyncMock(), close=AsyncMock())
                playwright = SimpleNamespace(chromium=SimpleNamespace(
                    launch_persistent_context=AsyncMock(return_value=context)), stop=AsyncMock())
                with patch.object(scraper, "async_playwright", return_value=SimpleNamespace(
                        start=AsyncMock(return_value=playwright))):
                    await scraper._launch_context(config, Path("/unused-profile"))
                options = playwright.chromium.launch_persistent_context.await_args.kwargs
                self.assertEqual(options["user_agent"], fp["user_agent"])
                self.assertEqual(options["screen"], {"width": fp["screen_width"], "height": fp["screen_height"]})
                self.assertEqual(options["viewport"], options["screen"])
                context.add_init_script.assert_awaited_once_with(script=scraper._stealth_script(fp))

    async def test_bound_config_returns_independent_snapshots_and_never_reloads_catalog(self) -> None:
        config = scraper.BrowserConfig(region=US_REGION, browser_profile="windows-nvidia", chrome_version=FIXTURE_VERSION)
        first = scraper._require_fingerprint(config)
        expected = fingerprint(US_REGION, "windows-nvidia")
        first["region"]["languages"].append("changed")
        first["webgl_renderer"] = "changed"
        with patch.object(scraper, "load_fingerprint", side_effect=AssertionError("must stay frozen")):
            self.assertEqual(scraper._require_fingerprint(config), expected)
        config.browser_profile = "linux-amd"
        with self.assertRaisesRegex(scraper.ScrapeError, "同轮切换"):
            scraper._require_fingerprint(config)

    async def test_fresh_runs_select_once_each_but_explicit_profile_never_draws(self) -> None:
        with (patch.object(scraper, "choose_profile_id", side_effect=["windows-amd", "linux-amd"]) as choose,
              patch.object(scraper, "_chrome_version", new=AsyncMock(return_value=FIXTURE_VERSION)) as version):
            one = await scraper._prepare_browser_config(scraper.BrowserConfig(region=US_REGION), None)
            two = await scraper._prepare_browser_config(scraper.BrowserConfig(region=US_REGION), None)
            three = await scraper._prepare_browser_config(scraper.BrowserConfig(region=US_REGION, browser_profile="macos-amd"), None)
            self.assertEqual((one.browser_profile, two.browser_profile, three.browser_profile),
                             ("windows-amd", "linux-amd", "macos-amd"))
            await scraper._prepare_browser_config(one, None)
            self.assertEqual(choose.call_count, 2)
            self.assertEqual(version.await_count, 3)

    async def test_list_retry_clone_keeps_frozen_fingerprint(self) -> None:
        config = scraper.BrowserConfig(region=US_REGION, browser_profile="linux-amd", chrome_version=FIXTURE_VERSION)
        expected = scraper._require_fingerprint(config)
        attempts = []
        async def capture(profile, page_index, attempt_config, expected_total, **kwargs):
            attempts.append(scraper._require_fingerprint(attempt_config))
            if len(attempts) == 1:
                raise scraper.ScrapeError("offline transient")
            return {"total": 1, "cards": []}
        with (patch.object(scraper, "load_fingerprint", side_effect=AssertionError("catalog reloaded")),
              patch.object(scraper, "_capture_list_page_attempt", new=AsyncMock(side_effect=capture)),
              patch.object(scraper.asyncio, "sleep", new_callable=AsyncMock)):
            await scraper._capture_list_page_with_profile(Path("/unused-profile"), 0, config, None)
        self.assertEqual(attempts, [expected, expected])

    async def test_resolved_region_is_frozen_for_one_run_and_reused(self) -> None:
        region = scraper.BrowserRegion("SG", "en-SG", ("en-SG", "en"), "Asia/Singapore")
        original = scraper.BrowserConfig()
        self.assertIsNone(original.region)
        with (patch.object(scraper, "detect_browser_region", new=AsyncMock(return_value=region)) as detect,
              patch.object(scraper, "_chrome_version", new=AsyncMock(return_value=FIXTURE_VERSION)) as version,
              patch.object(scraper, "choose_profile_id", return_value="windows-intel") as choose):
            prepared = await scraper._prepare_browser_config(original, None)
            self.assertIs(await scraper._prepare_browser_config(prepared, None), prepared)
        version.assert_awaited_once()
        choose.assert_called_once()
        self.assertEqual(prepared.browser_profile, "windows-intel")
        detect.assert_awaited_once_with(original.chrome_executable, headless=False)
        self.assertIs(prepared.region, region)
        self.assertIsNone(original.region)

    async def test_lookup_failure_stops_before_real_profile_or_store_access(self) -> None:
        with (
            patch.object(scraper, "detect_browser_region", new=AsyncMock(side_effect=ValueError("fixture"))),
            patch.object(scraper, "_temporary_chrome_profile_base") as profile,
            patch.object(scraper, "_collect_listing", new_callable=AsyncMock) as listing,
            patch.object(scraper, "_launch_context", new_callable=AsyncMock) as launch,
        ):
            with self.assertRaisesRegex(scraper.ScrapeError, "地区识别失败"):
                await scraper.scrape_all(scraper.BrowserConfig(chrome_executable=Path(__file__)))
        profile.assert_not_called()
        listing.assert_not_awaited()
        launch.assert_not_awaited()

    async def test_unresolved_lower_level_never_falls_back_to_us(self) -> None:
        with patch.object(scraper, "async_playwright") as browser, \
                patch.object(scraper.asyncio, "create_subprocess_exec", new_callable=AsyncMock) as node:
            with self.assertRaisesRegex(scraper.ScrapeError, "尚未识别"):
                await scraper._launch_context(scraper.BrowserConfig(), Path("/unused-profile"))
            with self.assertRaisesRegex(scraper.ScrapeError, "尚未识别"):
                await scraper._capture_node_list_snapshot(Path("/unused-profile"), 0, scraper.BrowserConfig())
        browser.assert_not_called()
        node.assert_not_awaited()

    async def test_locales_render_payload_token_and_require_matching_probe(self) -> None:
        for region in (
            US_REGION,
            scraper.BrowserRegion("SG", "en-SG", ("en-SG", "en"), "Asia/Singapore"),
            scraper.BrowserRegion("PH", "en-PH", ("en-PH", "en"), "Asia/Manila"),
        ):
            with self.subTest(country=region.country_code):
                rendered = scraper._stealth_script(fingerprint(region))
                normalized = rendered.replace(
                    json.dumps(fingerprint(region), ensure_ascii=True, sort_keys=True, separators=(",", ":")),
                    "__UGREEN_FINGERPRINT__",
                )
                self.assertEqual(normalized, scraper._stealth_template())
                observed = {**probe(), "language": region.locale, "languages": list(region.languages),
                            "time_zone": region.timezone_id}
                self.assertTrue(scraper._valid_stealth_probe(observed, fingerprint(region)))
                if region.country_code != "US":
                    self.assertFalse(scraper._valid_stealth_probe(probe(), fingerprint(region)))
                context = SimpleNamespace(add_init_script=AsyncMock(), close=AsyncMock())
                playwright = SimpleNamespace(chromium=SimpleNamespace(
                    launch_persistent_context=AsyncMock(return_value=context)), stop=AsyncMock())
                manager = SimpleNamespace(start=AsyncMock(return_value=playwright))
                with patch.object(scraper, "async_playwright", return_value=manager):
                    await scraper._launch_context(scraper.BrowserConfig(browser_profile="windows-intel", chrome_version=FIXTURE_VERSION, region=region), Path("/unused-profile"))
                options = playwright.chromium.launch_persistent_context.await_args.kwargs
                self.assertEqual((options["locale"], options["timezone_id"]), (region.locale, region.timezone_id))
                context.add_init_script.assert_awaited_once_with(script=rendered)


if __name__ == "__main__":
    unittest.main()
