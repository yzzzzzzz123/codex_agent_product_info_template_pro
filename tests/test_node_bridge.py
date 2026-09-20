"""Node 列表桥接的离线契约：仅 mock 子进程，不启动 Chrome、不读取真实会话。"""

from __future__ import annotations

import asyncio
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/shopee-ugreen-topsales/scripts"
sys.path.insert(0, str(SCRIPTS))
import scraper  # noqa: E402
from test_scraper import FIXTURE_VERSION, fingerprint

US_REGION = scraper.BrowserRegion("US", "en-US", ("en-US", "en"), "America/New_York")


PRIVATE_MARKER = "OFFLINE_PRIVATE_FIXTURE_MUST_NOT_BE_LOGGED"
NODE_FIXTURE = str(Path(__file__).resolve())  # 仅验证存在性；启动已被 mock。


def probe() -> dict:
    return {
        **{key: value for key, value in fingerprint().items()
           if key not in {"region", "profile_id"}},
        "webdriver_is_undefined": True,
        "user_agent": fingerprint()["user_agent"],
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


def snapshot() -> dict:
    return {
        "html": f"<!doctype html><title>{PRIVATE_MARKER}</title>",
        "final_url": scraper.STORE_PAGE_URL_TEMPLATE.format(page=0),
        "http_status": 200,
        "title": "离线列表快照",
        "stealth_probe": probe(),
        "access_error": None,
        "node_version": "24.11.0",
        "playwright_version": "1.63.0",
        "startup_page_count": 1,
    }


def process(stdout: bytes, stderr: bytes = b"", returncode: int = 0):
    return SimpleNamespace(
        pid=43210,
        returncode=returncode,
        communicate=AsyncMock(return_value=(stdout, stderr)),
        wait=AsyncMock(return_value=returncode),
    )


def parsed_payload() -> dict:
    return {
        "challenge": False,
        "result_view_count": 1,
        "final_url": scraper.STORE_PAGE_URL_TEMPLATE.format(page=0),
        "current_values": ["1"],
        "total_values": ["1"],
        "cards": [{
            "shop_id": scraper.SHOP_ID,
            "item_id": "100",
            "title": "离线单页商品",
            "product_url": f"https://shopee.ph/product/{scraper.SHOP_ID}/100",
            "price_text": "123.45",
            "monthly_sales_display": None,
            "monthly_sales_text": None,
        }],
        "scoped_anchor_count": 1,
        "next_button_count": 1,
        "next_url": None,
        "next_disabled": True,
        "errors": [],
    }


class NodeSubprocessTests(unittest.IsolatedAsyncioTestCase):
    async def test_region_is_identical_in_node_options_and_init_script(self) -> None:
        for region in (
            US_REGION,
            scraper.BrowserRegion("SG", "en-SG", ("en-SG", "en"), "Asia/Singapore"),
            scraper.BrowserRegion("PH", "en-PH", ("en-PH", "en"), "Asia/Manila"),
        ):
            with self.subTest(country=region.country_code):
                child = process(json.dumps(snapshot()).encode())
                with (
                    patch.dict(scraper.os.environ, {"PLAYWRIGHT_NODEJS_PATH": NODE_FIXTURE}, clear=True),
                    patch.object(scraper.asyncio, "create_subprocess_exec", new=AsyncMock(return_value=child)),
                ):
                    await scraper._capture_node_list_snapshot(
                        Path("/unused-fixture-profile"), 0, scraper.BrowserConfig(browser_profile="windows-intel", chrome_version=FIXTURE_VERSION, region=region)
                    )
                request = json.loads(child.communicate.await_args.args[0])
                self.assertEqual(request["region"], region.to_dict())
                self.assertEqual(request["locale"], region.locale)
                self.assertEqual(request["timezone_id"], region.timezone_id)
                self.assertEqual(request["init_script"], scraper._stealth_script(fingerprint(region)))

    async def test_success_returns_snapshot_in_memory_without_printing_or_writing(self) -> None:
        expected = snapshot()
        child = process(json.dumps(expected).encode())
        captured_stdout, captured_stderr = io.StringIO(), io.StringIO()
        with (
            patch.dict(scraper.os.environ, {"PLAYWRIGHT_NODEJS_PATH": NODE_FIXTURE}, clear=True),
            patch.object(scraper.asyncio, "create_subprocess_exec", new=AsyncMock(return_value=child)) as launch,
            patch.object(Path, "write_text") as write_text,
            patch.object(Path, "write_bytes") as write_bytes,
            redirect_stdout(captured_stdout), redirect_stderr(captured_stderr),
        ):
            result = await scraper._capture_node_list_snapshot(
                Path("/unused-fixture-profile"), 0, scraper.BrowserConfig(browser_profile="windows-intel", chrome_version=FIXTURE_VERSION, region=US_REGION)
            )
        self.assertEqual(result, expected)
        self.assertEqual(launch.await_args.args[0], NODE_FIXTURE)
        self.assertEqual(Path(launch.await_args.args[1]).name, "capture_list_page.cjs")
        self.assertTrue(launch.await_args.kwargs["start_new_session"])
        for stream in ("stdin", "stdout", "stderr"):
            self.assertEqual(launch.await_args.kwargs[stream], asyncio.subprocess.PIPE)
        request = json.loads(child.communicate.await_args.args[0])
        self.assertEqual(request["user_data_dir"], "/unused-fixture-profile")
        self.assertEqual(request["url"], scraper.STORE_PAGE_URL_TEMPLATE.format(page=0))
        self.assertEqual(request["chrome_executable"], str(scraper.DEFAULT_CHROME))
        self.assertEqual(request["init_script"], scraper._stealth_script(fingerprint()))
        self.assertEqual(request["region"], US_REGION.to_dict())
        self.assertEqual(request["locale"], US_REGION.locale)
        self.assertEqual(request["timezone_id"], US_REGION.timezone_id)
        self.assertEqual(request["playwright_module"], str(
            Path(scraper.playwright_package.__file__).resolve().parent / "driver/package"
        ))
        self.assertEqual(request["navigation_timeout_ms"], 120_000)
        self.assertEqual(request["post_load_wait_ms"], 15_000)
        write_text.assert_not_called()
        write_bytes.assert_not_called()
        self.assertEqual(captured_stdout.getvalue(), "")
        self.assertEqual(captured_stderr.getvalue(), "")

    async def test_child_environment_and_stdin_do_not_forward_proxy_credentials(self) -> None:
        child = process(json.dumps(snapshot()).encode())
        environment = {
            "PLAYWRIGHT_NODEJS_PATH": NODE_FIXTURE,
            "PATH": "/fixture/bin",
            "NO_PROXY": "localhost",
            **{name: f"http://{PRIVATE_MARKER}@proxy.invalid:8888" for name in (
                "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy",
            )},
        }
        with (
            patch.dict(scraper.os.environ, environment, clear=True),
            patch.object(scraper.asyncio, "create_subprocess_exec", new=AsyncMock(return_value=child)) as launch,
        ):
            await scraper._capture_node_list_snapshot(
                Path("/unused-fixture-profile"), 2, scraper.BrowserConfig(browser_profile="windows-intel", chrome_version=FIXTURE_VERSION, region=US_REGION)
            )
        child_env = launch.await_args.kwargs["env"]
        self.assertFalse(any(key.lower() in {"http_proxy", "https_proxy", "all_proxy"} for key in child_env))
        self.assertEqual(child_env["PATH"], environment["PATH"])
        self.assertEqual(child_env["NO_PROXY"], environment["NO_PROXY"])
        input_bytes = child.communicate.await_args.args[0]
        input_text = input_bytes.decode()
        self.assertIsInstance(json.loads(input_text), dict)
        self.assertNotIn(PRIVATE_MARKER, input_text)
        self.assertNotIn(PRIVATE_MARKER, repr(child_env))

    async def test_system_node_path_falls_back_to_path_lookup(self) -> None:
        child = process(json.dumps(snapshot()).encode())
        with (
            patch.dict(scraper.os.environ, {}, clear=True),
            patch.object(scraper.shutil, "which", return_value=NODE_FIXTURE) as which,
            patch.object(scraper.asyncio, "create_subprocess_exec", new=AsyncMock(return_value=child)) as launch,
        ):
            await scraper._capture_node_list_snapshot(
                Path("/unused-fixture-profile"), 0, scraper.BrowserConfig(browser_profile="windows-intel", chrome_version=FIXTURE_VERSION, region=US_REGION)
            )
        which.assert_called_once_with("node")
        self.assertEqual(launch.await_args.args[0], NODE_FIXTURE)

    async def test_no_system_node_is_an_error_without_starting_a_process(self) -> None:
        with (
            patch.dict(scraper.os.environ, {}, clear=True),
            patch.object(scraper.shutil, "which", return_value=None),
            patch.object(scraper.asyncio, "create_subprocess_exec", new_callable=AsyncMock) as launch,
        ):
            with self.assertRaises(scraper.ScrapeError):
                await scraper._capture_node_list_snapshot(
                    Path("/unused-fixture-profile"), 0, scraper.BrowserConfig(browser_profile="windows-intel", chrome_version=FIXTURE_VERSION, region=US_REGION)
                )
        launch.assert_not_awaited()

    async def test_invalid_stdout_and_failed_stderr_never_enter_public_errors(self) -> None:
        for stdout, stderr, code in (
            (PRIVATE_MARKER.encode(), b"", 0),
            (b"", PRIVATE_MARKER.encode(), 1),
            (json.dumps({"error": PRIVATE_MARKER}).encode(), PRIVATE_MARKER.encode(), 2),
        ):
            with self.subTest(code=code):
                child = process(stdout, stderr, code)
                public_stdout, public_stderr = io.StringIO(), io.StringIO()
                with (
                    patch.dict(scraper.os.environ, {"PLAYWRIGHT_NODEJS_PATH": NODE_FIXTURE}, clear=True),
                    patch.object(scraper.asyncio, "create_subprocess_exec", new=AsyncMock(return_value=child)),
                    patch.object(scraper, "_stop_capture_process", new_callable=AsyncMock) as stop,
                    redirect_stdout(public_stdout), redirect_stderr(public_stderr),
                ):
                    with self.assertRaises(scraper.ScrapeError) as raised:
                        await scraper._capture_node_list_snapshot(
                            Path("/unused-fixture-profile"), 0, scraper.BrowserConfig(browser_profile="windows-intel", chrome_version=FIXTURE_VERSION, region=US_REGION)
                        )
                self.assertNotIn(PRIVATE_MARKER, str(raised.exception))
                self.assertNotIn(PRIVATE_MARKER, public_stdout.getvalue() + public_stderr.getvalue())
                stop.assert_awaited_once_with(
                    child, user_data_dir=Path("/unused-fixture-profile"),
                    chrome_executable=scraper.DEFAULT_CHROME,
                )

    async def test_protocol_errors_stop_private_process_group_without_exposing_payload(self) -> None:
        valid = snapshot()
        cases = (
            ("non_object_array", [PRIVATE_MARKER], 0),
            ("non_object_null", None, 0),
            ("nonzero_exit", valid, 1),
            ("error_field", {**valid, "error": PRIVATE_MARKER}, 0),
            ("missing_html", {key: value for key, value in valid.items() if key != "html"}, 0),
            ("missing_final_url", {key: value for key, value in valid.items() if key != "final_url"}, 0),
            ("html_not_string", {**valid, "html": {"private": PRIVATE_MARKER}}, 0),
            ("final_url_not_string", {**valid, "final_url": [PRIVATE_MARKER]}, 0),
            ("status_not_integer", {**valid, "http_status": PRIVATE_MARKER}, 0),
            ("status_boolean", {**valid, "http_status": True}, 0),
            ("access_error_not_string", {**valid, "access_error": {"private": PRIVATE_MARKER}}, 0),
            ("probe_not_dict", {**valid, "stealth_probe": [PRIVATE_MARKER]}, 0),
            ("probe_null", {**valid, "stealth_probe": None}, 0),
        )
        for label, payload, code in cases:
            with self.subTest(case=label):
                child = process(json.dumps(payload).encode(), PRIVATE_MARKER.encode(), code)
                public_stdout, public_stderr = io.StringIO(), io.StringIO()
                with (
                    patch.dict(scraper.os.environ, {"PLAYWRIGHT_NODEJS_PATH": NODE_FIXTURE}, clear=True),
                    patch.object(scraper.asyncio, "create_subprocess_exec", new=AsyncMock(return_value=child)),
                    patch.object(scraper, "_stop_capture_process", new_callable=AsyncMock) as stop,
                    redirect_stdout(public_stdout), redirect_stderr(public_stderr),
                ):
                    with self.assertRaises(scraper.ScrapeError) as raised:
                        await scraper._capture_node_list_snapshot(
                            Path("/unused-fixture-profile"), 0, scraper.BrowserConfig(browser_profile="windows-intel", chrome_version=FIXTURE_VERSION, region=US_REGION)
                        )
                stop.assert_awaited_once_with(
                    child, user_data_dir=Path("/unused-fixture-profile"),
                    chrome_executable=scraper.DEFAULT_CHROME,
                )
                self.assertNotIn(PRIVATE_MARKER, str(raised.exception))
                self.assertNotIn(PRIVATE_MARKER, public_stdout.getvalue() + public_stderr.getvalue())

    async def test_timeout_and_cancellation_stop_capture_before_propagating(self) -> None:
        for failure, expected_error in (
            (asyncio.TimeoutError(), scraper.ScrapeError),
            (asyncio.CancelledError(), asyncio.CancelledError),
        ):
            with self.subTest(failure=type(failure).__name__):
                child = process(b"")
                child.returncode = None
                child.communicate.side_effect = failure
                with (
                    patch.dict(scraper.os.environ, {"PLAYWRIGHT_NODEJS_PATH": NODE_FIXTURE}, clear=True),
                    patch.object(scraper.asyncio, "create_subprocess_exec", new=AsyncMock(return_value=child)),
                    patch.object(scraper, "_stop_capture_process", new_callable=AsyncMock) as stop,
                    patch.object(scraper.asyncio, "wait_for", wraps=asyncio.wait_for) as wait_for,
                ):
                    with self.assertRaises(expected_error):
                        await scraper._capture_node_list_snapshot(
                            Path("/unused-fixture-profile"), 0, scraper.BrowserConfig(browser_profile="windows-intel", chrome_version=FIXTURE_VERSION, region=US_REGION)
                        )
                stop.assert_awaited_once_with(
                    child, user_data_dir=Path("/unused-fixture-profile"),
                    chrome_executable=scraper.DEFAULT_CHROME,
                )
                self.assertEqual(wait_for.call_args.kwargs["timeout"], 180)


class PrivateChromeGroupSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="shopees-ugreen-profile-", dir="/private/tmp")
        self.addCleanup(temporary.cleanup)
        self.profile = Path(temporary.name) / "base"
        self.profile.mkdir()
        self.profile = self.profile.resolve()

    def test_exact_profile_and_executable_match_only_private_browser_group_leaders(self) -> None:
        profile = self.profile
        executable = scraper.DEFAULT_CHROME.resolve()
        rows = [
            f"61001 61001 {executable} --disable-test --user-data-dir={profile}",
            f"61002 61002 {executable} --user-data-dir='{profile}' --remote-debugging-pipe",
            f"61003 61003 {executable} --user-data-dir={profile}-other",
            f"61004 61004 {executable} --user-data-dir=/Users/fixture/Chrome/Default",
            f"61005 61001 {executable} --user-data-dir={profile}",
            f"61006 61006 {executable} --user-data-dir={profile} --type=renderer",
            f"61007 61007 {executable} --user-data-dir={profile} --user-data-dir={profile}-other",
            f"61008 61008 {executable}Helper --user-data-dir={profile}",
            f"61009 61009 /bin/sh -c '{executable} --user-data-dir={profile}'",
            f"61010 61010 /Applications/Other Chrome --user-data-dir={profile}",
            f"1 1 {executable} --user-data-dir={profile}",
            f"61011 61011 {executable} --user-data-dir='{profile}",
            PRIVATE_MARKER,
        ]
        self.assertEqual(
            scraper._private_chrome_groups("\n".join(rows), profile, executable),
            {61001, 61002},
        )

    def test_same_profile_text_in_another_flag_does_not_match_user_data_directory(self) -> None:
        profile = self.profile
        executable = scraper.DEFAULT_CHROME.resolve()
        rows = [
            f"62001 62001 {executable} --note=--user-data-dir={profile}",
            f"62002 62002 {executable} --user-data-dir={profile}/nested",
            f"62003 62003 {executable} --user-data-dir={profile.parent}",
        ]
        self.assertEqual(scraper._private_chrome_groups("\n".join(rows), profile, executable), set())

    def test_cleanup_scope_rejects_unknown_roots_and_symlinks_outside_task_profile(self) -> None:
        self.assertEqual(scraper._capture_cleanup_profile(self.profile), self.profile)
        for invalid in (None, self.profile.parent, Path("/private/tmp"), Path("/"), self.profile / "missing"):
            with self.subTest(invalid=invalid):
                self.assertIsNone(scraper._capture_cleanup_profile(invalid))
        with tempfile.TemporaryDirectory(prefix="chrome-user-offline-", dir="/private/tmp") as external:
            other_profile = Path(external) / "Default"
            other_profile.mkdir()
            linked_profile = self.profile.parent / "linked-profile"
            linked_profile.symlink_to(other_profile, target_is_directory=True)
            self.assertIsNone(scraper._capture_cleanup_profile(other_profile))
            self.assertIsNone(scraper._capture_cleanup_profile(linked_profile))
            row = f"61001 61001 {scraper.DEFAULT_CHROME} --user-data-dir={other_profile}"
            self.assertEqual(scraper._private_chrome_groups(row, other_profile, scraper.DEFAULT_CHROME), set())


class CaptureProcessCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_cleanup_targets_only_private_process_group_and_reaps_child(self) -> None:
        child = process(b"")
        child.returncode = None
        events = MagicMock()
        with patch.object(scraper.os, "killpg") as killpg:
            events.attach_mock(killpg, "killpg")
            events.attach_mock(child.wait, "wait")
            await scraper._stop_capture_process(child)
        self.assertEqual([entry[0] for entry in events.mock_calls], ["killpg", "wait", "killpg"])
        self.assertEqual(killpg.call_args_list[0].args, (child.pid, scraper.signal.SIGTERM))
        self.assertEqual(killpg.call_args_list[-1].args, (child.pid, scraper.signal.SIGKILL))
        child.wait.assert_awaited_once()

    async def test_cleanup_timeout_escalates_same_group_and_still_reaps(self) -> None:
        child = process(b"")
        child.returncode = None
        child.wait.side_effect = [asyncio.TimeoutError(), 0]
        with patch.object(scraper.os, "killpg") as killpg:
            await scraper._stop_capture_process(child)
        self.assertEqual(child.wait.await_count, 2)
        self.assertEqual(killpg.call_args_list[0].args, (child.pid, scraper.signal.SIGTERM))
        self.assertTrue(all(entry.args == (child.pid, scraper.signal.SIGKILL)
                            for entry in killpg.call_args_list[1:]))

    async def test_already_exited_process_group_does_not_prevent_reaping(self) -> None:
        child = process(b"")
        with patch.object(scraper.os, "killpg", side_effect=ProcessLookupError):
            await scraper._stop_capture_process(child)
        child.wait.assert_awaited_once()

    async def test_detached_chrome_is_cleaned_even_after_node_exit_without_touching_other_chrome(self) -> None:
        child = process(b"")
        with tempfile.TemporaryDirectory(prefix="shopees-ugreen-profile-", dir="/private/tmp") as directory:
            profile = Path(directory) / "base"
            profile.mkdir()
            executable = scraper.DEFAULT_CHROME.resolve()
            table = "\n".join((
                f"64001 64001 {executable} --user-data-dir={profile}",
                f"64002 64002 {executable} --user-data-dir=/Users/fixture/Chrome/Default",
                f"64003 64003 {executable} --user-data-dir={profile}-other",
            ))
            with (
                patch.object(scraper, "_capture_process_table", new=AsyncMock(return_value=table)) as scan,
                patch.object(scraper, "_wait_capture_groups", new=AsyncMock(return_value=set())) as wait_groups,
                patch.object(scraper.os, "killpg") as killpg,
            ):
                await scraper._stop_capture_process(
                    child, user_data_dir=profile, chrome_executable=executable
                )
            self.assertEqual(scan.await_count, 2)
            self.assertEqual({entry.args for entry in killpg.call_args_list}, {
                (child.pid, scraper.signal.SIGTERM), (child.pid, scraper.signal.SIGKILL),
                (64001, scraper.signal.SIGTERM), (64001, scraper.signal.SIGKILL),
            })
            self.assertTrue(all(entry.args[0] == {64001} for entry in wait_groups.await_args_list))
            child.wait.assert_awaited_once()

    async def test_second_scan_prevents_force_killing_a_reused_unrelated_chrome_group(self) -> None:
        child = process(b"")
        with tempfile.TemporaryDirectory(prefix="shopees-ugreen-profile-", dir="/private/tmp") as directory:
            profile = Path(directory) / "base"
            profile.mkdir()
            executable = scraper.DEFAULT_CHROME.resolve()
            tables = [
                f"65001 65001 {executable} --user-data-dir={profile}",
                f"65001 65001 {executable} --user-data-dir=/Users/fixture/Chrome/Default",
            ]
            with (
                patch.object(scraper, "_capture_process_table", new=AsyncMock(side_effect=tables)),
                patch.object(scraper, "_wait_capture_groups", new=AsyncMock(return_value=set())),
                patch.object(scraper.os, "killpg") as killpg,
            ):
                await scraper._stop_capture_process(
                    child, user_data_dir=profile, chrome_executable=executable
                )
            chrome_calls = [entry.args for entry in killpg.call_args_list if entry.args[0] == 65001]
            self.assertEqual(chrome_calls, [(65001, scraper.signal.SIGTERM)])

    async def test_failed_process_scan_stops_reuse_without_exposing_process_table(self) -> None:
        child = process(b"")
        with tempfile.TemporaryDirectory(prefix="shopees-ugreen-profile-", dir="/private/tmp") as directory:
            profile = Path(directory) / "base"
            profile.mkdir()
            with (
                patch.object(scraper, "_capture_process_table", new=AsyncMock(side_effect=scraper.ScrapeError(PRIVATE_MARKER))),
                patch.object(scraper, "_wait_capture_groups", new=AsyncMock(return_value=set())),
                patch.object(scraper.os, "killpg") as killpg,
            ):
                with self.assertRaises(scraper.CaptureCleanupError) as raised:
                    await scraper._stop_capture_process(
                        child, user_data_dir=profile, chrome_executable=scraper.DEFAULT_CHROME
                    )
            self.assertNotIn(PRIVATE_MARKER, str(raised.exception))
            self.assertTrue(all(entry.args[0] == child.pid for entry in killpg.call_args_list))
            child.wait.assert_awaited_once()

    async def test_unreapable_node_has_bounded_waits_and_raises(self) -> None:
        child = process(b"")
        child.returncode = None
        child.wait.side_effect = asyncio.TimeoutError
        with (
            patch.object(scraper.os, "killpg"),
            patch.object(scraper.asyncio, "wait_for", wraps=asyncio.wait_for) as wait_for,
        ):
            with self.assertRaises(scraper.CaptureCleanupError):
                await scraper._stop_capture_process(child)
        self.assertEqual(child.wait.await_count, 2)
        self.assertEqual([entry.kwargs["timeout"] for entry in wait_for.call_args_list], [5, 2])


class ProcessTableReadTests(unittest.IsolatedAsyncioTestCase):
    async def test_process_table_is_read_only_and_never_printed(self) -> None:
        child = process(PRIVATE_MARKER.encode())
        public_stdout, public_stderr = io.StringIO(), io.StringIO()
        with (
            patch.object(scraper.asyncio, "create_subprocess_exec", new=AsyncMock(return_value=child)) as launch,
            redirect_stdout(public_stdout), redirect_stderr(public_stderr),
        ):
            table = await scraper._capture_process_table()
        self.assertEqual(table, PRIVATE_MARKER)
        self.assertEqual(launch.await_args.args, ("/bin/ps", "-ww", "-axo", "pid=,pgid=,command="))
        self.assertEqual(launch.await_args.kwargs["stderr"], asyncio.subprocess.DEVNULL)
        self.assertEqual(public_stdout.getvalue() + public_stderr.getvalue(), "")

    async def test_process_table_timeout_kills_and_reaps_only_its_own_ps(self) -> None:
        child = process(b"")
        child.returncode = None
        child.communicate.side_effect = asyncio.TimeoutError
        child.kill = MagicMock()
        with (
            patch.object(scraper.asyncio, "create_subprocess_exec", new=AsyncMock(return_value=child)),
            patch.object(scraper.asyncio, "wait_for", wraps=asyncio.wait_for) as wait_for,
        ):
            with self.assertRaises(scraper.ScrapeError):
                await scraper._capture_process_table()
        child.kill.assert_called_once()
        child.wait.assert_awaited_once()
        self.assertEqual([entry.kwargs["timeout"] for entry in wait_for.call_args_list], [3, 1])


class NodeSnapshotValidationTests(unittest.IsolatedAsyncioTestCase):
    async def test_attempt_parses_once_and_never_launches_legacy_context_or_cleans_profile(self) -> None:
        captured = snapshot()
        payload = parsed_payload()
        parser = MagicMock(return_value=payload)
        config = scraper.BrowserConfig(browser_profile="windows-intel", chrome_version=FIXTURE_VERSION, region=US_REGION)
        profile = Path("/unused-fixture-profile")
        progress = MagicMock()
        with (
            patch.dict(sys.modules, {"list_html": SimpleNamespace(parse_list_html=parser)}),
            patch.object(scraper, "_capture_node_list_snapshot", new=AsyncMock(return_value=captured)) as capture,
            patch.object(scraper, "_launch_context", new_callable=AsyncMock) as legacy_launch,
            patch.object(scraper, "_clean_profile_transients") as clean,
            patch.object(Path, "write_text") as write_text,
            patch.object(Path, "write_bytes") as write_bytes,
        ):
            result = await scraper._capture_list_page_attempt(profile, 0, config, 1, progress=progress)
        capture.assert_awaited_once_with(profile, 0, config)
        parser.assert_called_once_with(
            captured["html"], final_url=captured["final_url"], expected_shop_id=scraper.SHOP_ID, page_index=0
        )
        self.assertIs(result, payload)
        self.assertIs(result["stealth_probe"], captured["stealth_probe"])
        self.assertEqual(result["total"], 1)
        self.assertNotIn("html", result)
        self.assertNotIn(PRIVATE_MARKER, repr(progress.call_args_list))
        legacy_launch.assert_not_awaited()
        clean.assert_not_called()
        write_text.assert_not_called()
        write_bytes.assert_not_called()

    async def test_node_metadata_cannot_bypass_http_login_challenge_or_probe_checks(self) -> None:
        cases = (
            ({"http_status": 429}, {}, scraper.AccessChallengeError),
            ({"http_status": 404}, {}, scraper.ScrapeError),
            ({"final_url": "https://shopee.ph/verify/traffic"}, {}, scraper.AccessChallengeError),
            ({"final_url": "https://shopee.ph/buyer/login"}, {}, scraper.AccessChallengeError),
            ({"access_error": "商品接口拒绝访问：HTTP 429"}, {}, scraper.AccessChallengeError),
            ({"stealth_probe": {**probe(), "plugin_count": 0}}, {}, scraper.ScrapeError),
            ({}, {"challenge": True}, scraper.AccessChallengeError),
        )
        for metadata_change, payload_change, error_type in cases:
            with self.subTest(metadata=metadata_change, payload=payload_change):
                parser = MagicMock(return_value={**parsed_payload(), **payload_change})
                captured = {**snapshot(), **metadata_change}
                with (
                    patch.dict(sys.modules, {"list_html": SimpleNamespace(parse_list_html=parser)}),
                    patch.object(scraper, "_capture_node_list_snapshot", new=AsyncMock(return_value=captured)),
                ):
                    with self.assertRaises(error_type):
                        await scraper._capture_list_page_attempt(
                            Path("/unused-fixture-profile"), 0, scraper.BrowserConfig(browser_profile="windows-intel", chrome_version=FIXTURE_VERSION, region=US_REGION), 1
                        )

    async def test_parsed_snapshot_keeps_pagination_card_count_and_terminal_validation(self) -> None:
        cases = (
            {"final_url": "https://example.invalid/ugreen.ph?page=0&sortBy=sales&tab=0"},
            {"current_values": ["2"]},
            {"total_values": ["0"]},
            {"total_values": ["1", "2"]},
            {"result_view_count": 2},
            {"cards": []},
            {"scoped_anchor_count": 2},
            {"next_button_count": 0},
            {"next_disabled": False},
            {"next_url": "https://shopee.ph/next"},
            {"errors": ["conflicting monthly sales"]},
            {"total_values": ["2"], "next_disabled": False,
             "next_url": scraper.STORE_PAGE_URL_TEMPLATE.format(page=1)},
        )
        for change in cases:
            with self.subTest(change=change):
                parser = MagicMock(return_value={**parsed_payload(), **change})
                with (
                    patch.dict(sys.modules, {"list_html": SimpleNamespace(parse_list_html=parser)}),
                    patch.object(scraper, "_capture_node_list_snapshot", new=AsyncMock(return_value=snapshot())),
                ):
                    with self.assertRaises(scraper.ScrapeError):
                        await scraper._capture_list_page_attempt(
                            Path("/unused-fixture-profile"), 0, scraper.BrowserConfig(browser_profile="windows-intel", chrome_version=FIXTURE_VERSION, region=US_REGION), None
                        )

    async def test_parsed_cards_still_reject_foreign_identity_price_and_monthly_data(self) -> None:
        for change in (
            {"shop_id": "999"},
            {"product_url": f"https://example.invalid/product/{scraper.SHOP_ID}/100"},
            {"price_text": "-1"},
            {"monthly_sales_display": "-1"},
        ):
            with self.subTest(change=change):
                payload = parsed_payload()
                payload["cards"][0].update(change)
                parser = MagicMock(return_value=payload)
                with (
                    patch.dict(sys.modules, {"list_html": SimpleNamespace(parse_list_html=parser)}),
                    patch.object(scraper, "_capture_node_list_snapshot", new=AsyncMock(return_value=snapshot())),
                ):
                    with self.assertRaises(scraper.ScrapeError):
                        await scraper._capture_list_page_attempt(
                            Path("/unused-fixture-profile"), 0, scraper.BrowserConfig(browser_profile="windows-intel", chrome_version=FIXTURE_VERSION, region=US_REGION), 1
                        )

    async def test_parser_exception_does_not_expose_html_in_error_or_progress(self) -> None:
        parser = MagicMock(side_effect=ValueError(PRIVATE_MARKER))
        progress = MagicMock()
        with (
            patch.dict(sys.modules, {"list_html": SimpleNamespace(parse_list_html=parser)}),
            patch.object(scraper, "_capture_node_list_snapshot", new=AsyncMock(return_value=snapshot())),
        ):
            with self.assertRaises(scraper.ScrapeError) as raised:
                await scraper._capture_list_page_attempt(
                    Path("/unused-fixture-profile"), 0, scraper.BrowserConfig(browser_profile="windows-intel", chrome_version=FIXTURE_VERSION, region=US_REGION), None, progress=progress
                )
        self.assertNotIn(PRIVATE_MARKER, str(raised.exception))
        self.assertNotIn(PRIVATE_MARKER, repr(progress.call_args_list))


class FatalCleanupPropagationTests(unittest.IsolatedAsyncioTestCase):
    async def test_fatal_cleanup_is_not_retried_and_verification_does_not_visit_details(self) -> None:
        profile_path = Path("/unused-fixture-profile")
        profile = MagicMock()
        profile.__enter__.return_value = profile_path
        profile.__exit__.return_value = False
        config = scraper.BrowserConfig(browser_profile="windows-intel", chrome_version=FIXTURE_VERSION, region=US_REGION, chrome_executable=Path(__file__), retries=3)
        fatal = scraper.CaptureCleanupError("无法确认本次私有浏览器已退出")
        with (
            patch.object(scraper, "_capture_list_page_attempt", new=AsyncMock(side_effect=fatal)) as attempt,
            patch.object(scraper, "_select_verification_targets", return_value=[]),
            patch.object(scraper, "_temporary_chrome_profile_base", return_value=profile),
            patch.object(scraper, "_launch_context", new_callable=AsyncMock) as launch,
            patch.object(scraper, "_visit_detail", new_callable=AsyncMock) as visit,
            patch.object(scraper.asyncio, "sleep", new_callable=AsyncMock) as sleep,
        ):
            with self.assertRaises(scraper.CaptureCleanupError):
                await scraper.verify_access(config, Path("/unused-fixture-reference.xlsx"))
        attempt.assert_awaited_once()
        launch.assert_not_awaited()
        visit.assert_not_awaited()
        sleep.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
