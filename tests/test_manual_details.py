"""PDP 人工接管离线测试：不启动浏览器、不联网、不处理真实验证码。"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/shopee-ugreen-topsales/scripts"))
import scraper
from test_scraper import FIXTURE_VERSION, US_REGION, card, probe


def valid_payload(item_id="100"):
    return {
        "challenge": False,
        "location_identity": {"shop_id": scraper.SHOP_ID, "item_id": item_id},
        "canonical_present": False, "og_present": False, "stealth_probe": probe(),
        "bff": {"item": {"shop_id": scraper.SHOP_ID, "item_id": item_id,
                         "title": "本次详情", "models": [{"model_id": "123"}],
                         "images": ["main-current", "secondary-current"]}},
    }


class FakePage:
    def __init__(self):
        self.url = "https://shopee.ph/verify/captcha"
        self.closed = False
        self.main_frame = object()
        self.listeners = {}
        self.goto = AsyncMock(return_value=SimpleNamespace(status=403))
        self.evaluate = AsyncMock(return_value=valid_payload())
        self.wait_for_timeout = AsyncMock()
        self.close = AsyncMock()

    def on(self, event, callback):
        self.listeners.setdefault(event, []).append(callback)

    def remove_listener(self, event, callback):
        self.listeners[event].remove(callback)

    def is_closed(self):
        return self.closed

    def document_response(self, status, *, main=True, navigation=True):
        response = SimpleNamespace(
            url=self.url, status=status,
            request=SimpleNamespace(is_navigation_request=lambda: navigation,
                                    frame=self.main_frame if main else object()))
        for callback in tuple(self.listeners.get("response", ())):
            callback(response)


class ManualDetailsTests(unittest.IsolatedAsyncioTestCase):
    def config(self, **kwargs):
        return scraper.BrowserConfig(browser_profile="windows-intel", chrome_version=FIXTURE_VERSION, region=US_REGION, manual_list_handoff=True, **kwargs)

    async def test_handoff_keeps_same_page_until_resume_then_reads_without_renavigation(self):
        page, product = FakePage(), card()
        messages, permission, waiting = [], asyncio.Event(), asyncio.Event()
        old_watch = scraper._watch_access(page)
        old_watch.error = "旧业务拒绝，必须清除"

        async def resume(_):
            waiting.set()
            await permission.wait()
            page.url = product.product_url
            page.document_response(200)

        with patch.object(scraper, "_wait_for_manual_resume", new=resume):
            task = asyncio.create_task(scraper._visit_detail(
                page, product, 1, self.config(detail_navigation_timeout_ms=1), progress=messages.append))
            await waiting.wait()
            await asyncio.sleep(0.02)
            self.assertFalse(task.done())
            page.goto.assert_awaited_once()
            page.evaluate.assert_not_awaited()
            page.close.assert_not_awaited()
            permission.set()
            result = await task
        self.assertEqual(result.item_id, "100")
        self.assertEqual(len(result.skus), 1)
        self.assertEqual(len(result.secondary_image_urls), 1)
        page.goto.assert_awaited_once()
        self.assertEqual(page.evaluate.await_count, 2)
        self.assertIsNot(page._ugreen_access_watch, old_watch)
        self.assertEqual(len(page.listeners["response"]), 2)
        self.assertIn(product.product_url, "".join(messages))
        page.close.assert_not_awaited()

    async def test_rejected_current_challenge_never_accepts_embedded_old_data(self):
        page, product = FakePage(), card()
        blocked = {**valid_payload(), "challenge": True}
        page.evaluate.side_effect = [blocked, valid_payload(), valid_payload()]

        async def resume(_):
            page.url = product.product_url
            page.document_response(200)

        with patch.object(scraper, "_wait_for_manual_resume", new=AsyncMock(side_effect=resume)) as wait:
            result = await scraper._visit_detail(page, product, 1, self.config())
        self.assertEqual(wait.await_count, 2)
        self.assertEqual(result.item_id, "100")
        self.assertEqual(page.evaluate.await_count, 3)
        page.goto.assert_awaited_once()
        page.close.assert_not_awaited()

    async def test_remaining_login_or_challenge_url_holds_before_reading(self):
        for url in ("https://shopee.ph/buyer/login", "https://shopee.ph/verify/captcha"):
            with self.subTest(url=url):
                page, product, attempts = FakePage(), card(), 0

                async def resume(_):
                    nonlocal attempts
                    attempts += 1
                    page.url = url if attempts == 1 else product.product_url
                    page.document_response(200)

                with patch.object(scraper, "_wait_for_manual_resume", new=resume):
                    result = await scraper._visit_detail(page, product, 1, self.config())
                self.assertEqual(attempts, 2)
                self.assertEqual(result.item_id, "100")
                self.assertEqual(page.evaluate.await_count, 2)
                page.goto.assert_awaited_once()

    async def test_resume_still_requires_identity_probe_skus_and_gallery(self):
        changes = (
            lambda p: p.update(canonical_present=True, canonical_identity={"shop_id": scraper.SHOP_ID, "item_id": "999"}),
            lambda p: p["stealth_probe"].update(platform="wrong"),
            lambda p: p["bff"]["item"].update(item_id="999"),
            lambda p: p["bff"]["item"].update(models=[]),
            lambda p: p["bff"]["item"].update(images=[]),
        )
        for change in changes:
            with self.subTest(change=change):
                page, product, attempts = FakePage(), card(), 0
                invalid = deepcopy(valid_payload())
                change(invalid)

                async def resume(_):
                    nonlocal attempts
                    attempts += 1
                    page.url = product.product_url
                    page.document_response(200)
                    page.evaluate.return_value = invalid if attempts == 1 else valid_payload()

                with patch.object(scraper, "_wait_for_manual_resume", new=resume):
                    result = await scraper._visit_detail(page, product, 1, self.config())
                self.assertEqual(attempts, 2)
                self.assertEqual(result.item_id, "100")
                page.goto.assert_awaited_once()

    async def test_navigation_error_enters_hold_without_automatic_retry_or_error_body(self):
        page, product, messages = FakePage(), card(), []
        page.goto.side_effect = RuntimeError("private raw exception must not be emitted")

        async def resume(_):
            page.url = product.product_url
            page.document_response(200)

        with patch.object(scraper, "_wait_for_manual_resume", new=resume):
            result = await scraper._visit_detail(page, product, 1, self.config(), progress=messages.append)
        self.assertEqual(result.item_id, "100")
        page.goto.assert_awaited_once()
        self.assertNotIn("private raw", "".join(messages))

    async def test_new_api_denial_after_resume_is_not_ignored(self):
        page, product, attempts = FakePage(), card(), 0

        async def resume(_):
            nonlocal attempts
            attempts += 1
            page.url = product.product_url
            page.document_response(200)

        async def evaluate(*_):
            if attempts == 1:
                page._ugreen_access_watch.error = "新到达的接口拒绝"
            return valid_payload()

        page.evaluate.side_effect = evaluate
        with patch.object(scraper, "_wait_for_manual_resume", new=resume):
            result = await scraper._visit_detail(page, product, 1, self.config())
        self.assertEqual(attempts, 2)
        self.assertEqual(result.item_id, "100")
        page.goto.assert_awaited_once()

    async def test_old_http_403_cannot_be_cleared_by_resume_without_navigation(self):
        page, product, attempts = FakePage(), card(), 0
        page.url = product.product_url

        async def resume(_):
            nonlocal attempts
            attempts += 1
            page.evaluate.assert_not_awaited()
            if attempts == 2:
                page.document_response(200)

        with patch.object(scraper, "_wait_for_manual_resume", new=resume):
            result = await scraper._visit_detail(page, product, 1, self.config())
        self.assertEqual(attempts, 2)
        self.assertEqual(result.item_id, "100")
        self.assertEqual(page._ugreen_detail_document_watch.status, 200)
        page.goto.assert_awaited_once()

    async def test_current_document_api_denial_survives_repeated_resume(self):
        page, product, attempts = FakePage(), card(), 0

        async def resume(_):
            nonlocal attempts
            attempts += 1
            page.url = product.product_url
            page.evaluate.assert_not_awaited()
            if attempts == 1:
                page.document_response(200)
                page._ugreen_access_watch.error = "当前主文档商品接口 90309999"
            elif attempts == 3:
                page.document_response(200)

        with patch.object(scraper, "_wait_for_manual_resume", new=resume):
            result = await scraper._visit_detail(page, product, 1, self.config())
        self.assertEqual(attempts, 3)
        self.assertEqual(result.item_id, "100")
        page.goto.assert_awaited_once()

    async def test_subframe_or_non_navigation_response_cannot_clear_document_denial(self):
        page = FakePage()
        document = scraper._watch_detail_document(page)
        document.record(403)
        previous_api = page._ugreen_access_watch
        previous_api.error = "当前拒绝"
        page.document_response(200, main=False)
        page.document_response(200, navigation=False)
        self.assertEqual(document.status, 403)
        self.assertIs(page._ugreen_access_watch, previous_api)
        self.assertEqual(previous_api.error, "当前拒绝")

    async def test_goto_return_does_not_reset_current_document_api_twice(self):
        page, product = FakePage(), card()

        async def goto(*_, **__):
            page.url = product.product_url
            page.document_response(200)
            page._ugreen_access_watch.error = "主响应后 DOMContentLoaded 前已经拒绝"
            return SimpleNamespace(status=200)

        page.goto.side_effect = goto

        async def resume(_):
            self.assertIsNotNone(page._ugreen_access_watch.error)
            page.document_response(200)

        with patch.object(scraper, "_wait_for_manual_resume", new=AsyncMock(side_effect=resume)) as wait:
            result = await scraper._visit_detail(page, product, 1, self.config())
        wait.assert_awaited_once()
        self.assertEqual(result.item_id, "100")

    async def test_abort_and_cancel_propagate_without_retrying_or_closing_in_helper(self):
        for error in (scraper.ScrapeError("用户取消人工接管"), asyncio.CancelledError()):
            with self.subTest(error=type(error).__name__):
                page = FakePage()
                with patch.object(scraper, "_wait_for_manual_resume", new=AsyncMock(side_effect=error)) as wait:
                    with self.assertRaises(type(error)):
                        await scraper._visit_detail(page, card(), 1, self.config())
                wait.assert_awaited_once()
                page.goto.assert_awaited_once()
                page.evaluate.assert_not_awaited()
                page.close.assert_not_awaited()

    async def test_closed_page_is_not_accepted_or_waited_forever(self):
        page = FakePage()
        page.closed = True
        with patch.object(scraper, "_wait_for_manual_resume", new_callable=AsyncMock) as wait:
            with self.assertRaisesRegex(scraper.ScrapeError, "已关闭"):
                await scraper._resume_manual_detail(page, card(), 1, self.config(), None)
        wait.assert_not_awaited()

    async def test_success_without_challenge_does_not_request_manual_input(self):
        page, product = FakePage(), card()
        page.url = product.product_url
        page.goto.return_value = SimpleNamespace(status=200)
        with patch.object(scraper, "_wait_for_manual_resume", new_callable=AsyncMock) as wait:
            result = await scraper._visit_detail(page, product, 1, self.config())
        self.assertEqual(result.item_id, "100")
        wait.assert_not_awaited()

    async def test_non_manual_challenge_behavior_is_unchanged(self):
        page = FakePage()
        with patch.object(scraper, "_wait_for_manual_resume", new_callable=AsyncMock) as wait:
            with self.assertRaises(scraper.AccessChallengeError):
                await scraper._visit_detail(page, card(), 1, scraper.BrowserConfig(browser_profile="windows-intel", chrome_version=FIXTURE_VERSION, region=US_REGION))
        wait.assert_not_awaited()
        page.goto.assert_awaited_once()

    async def test_new_document_cancels_old_tasks_and_detaches_old_api_listeners(self):
        page = FakePage()
        document = scraper._watch_detail_document(page)
        previous = scraper._watch_access(page)
        previous.error = "旧失败"
        pending = asyncio.create_task(asyncio.Event().wait())
        previous.tasks.add(pending)
        page.document_response(200)
        await asyncio.sleep(0)
        self.assertTrue(pending.cancelled())
        current = page._ugreen_access_watch
        self.assertIsNot(current, previous)
        self.assertIsNone(current.error)
        self.assertEqual(page.listeners["response"], [document._received, current._received])
        self.assertEqual(page.listeners["close"], [current._closed])
        page.document_response(200)
        self.assertEqual(len(page.listeners["response"]), 2)
        self.assertEqual(len(page.listeners["close"]), 1)

    async def test_park_challenge_requires_new_full_record_before_counting_success(self):
        page, old, fresh, product = FakePage(), object(), object(), card()
        scraper._watch_detail_document(page).record(200)
        page.url = product.product_url
        with patch.object(scraper, "_visit_detail", new=AsyncMock(return_value=old)) as visit, \
                patch.object(scraper, "_park_and_wait", new=AsyncMock(side_effect=[scraper.AccessChallengeError("late challenge"), None])) as park, \
                patch.object(scraper, "_resume_manual_detail", new=AsyncMock(return_value=fresh)) as resume:
            result = await scraper._visit_and_park_detail_with_manual_handoff(
                page, product, 1, self.config(), 10_000, None)
        self.assertIs(result, fresh)
        self.assertEqual(park.await_count, 2)
        self.assertEqual([call.args[1] for call in park.await_args_list], [10_000, 10_000])
        visit.assert_awaited_once()
        resume.assert_awaited_once()
        page.goto.assert_not_awaited()
        page.close.assert_not_awaited()

    async def test_manual_collection_preserves_serial_order_and_slow_intervals(self):
        page = FakePage()
        context = SimpleNamespace(new_page=AsyncMock(return_value=page))
        cards, records = [card("100"), card("200")], [object(), object()]
        messages = []
        with patch.object(scraper, "_visit_and_park_detail_with_manual_handoff", new=AsyncMock(side_effect=records)) as visit, \
                patch.object(scraper, "_visit_detail", new_callable=AsyncMock) as default_visit:
            result = await scraper._collect_details([context], cards, self.config(), messages.append)
        self.assertEqual(result, records)
        self.assertEqual([call.args[1] for call in visit.await_args_list], cards)
        self.assertEqual([call.args[4] for call in visit.await_args_list], [10_000, 0])
        default_visit.assert_not_awaited()
        page.close.assert_awaited_once()

    async def test_late_watch_challenge_keeps_original_page_until_user_revalidation(self):
        page, product = FakePage(), card()
        page.url = product.product_url
        scraper._watch_detail_document(page).record(200)
        watcher = scraper._watch_access(page)
        watcher.error = "离页前才到达的业务错误"

        async def resume(_):
            page.goto.assert_not_awaited()
            page.close.assert_not_awaited()
            self.assertEqual(page.url, product.product_url)
            page.document_response(200)

        with patch.object(scraper, "_visit_detail", new=AsyncMock(return_value=object())), \
                patch.object(scraper, "_wait_for_manual_resume", new=resume), \
                patch.object(scraper.asyncio, "sleep", new_callable=AsyncMock) as sleep:
            result = await scraper._visit_and_park_detail_with_manual_handoff(
                page, product, 1, self.config(), 10_000, None)
        self.assertEqual(result.item_id, "100")
        page.goto.assert_awaited_once_with("about:blank", wait_until="commit", timeout=10_000)
        sleep.assert_awaited_once_with(10)

    async def test_manual_verification_uses_same_detail_handoff_and_does_not_publish(self):
        page, cards = FakePage(), [card("100"), card("200"), card("300")]
        context = SimpleNamespace(new_page=AsyncMock(return_value=page))
        profile = MagicMock()
        profile.__enter__.return_value = Path("/unused-test-profile")
        profile.__exit__.return_value = False
        products = [scraper._parse_detail(value, valid_payload(value.item_id), index)
                    for index, value in enumerate(cards, 1)]
        with patch.object(scraper, "_read_known_product_reference", return_value=(cards, {})), \
                patch.object(scraper, "_temporary_chrome_profile_base", return_value=profile), \
                patch.object(scraper, "_launch_context", new=AsyncMock(return_value=context)), \
                patch.object(scraper, "_close_context", new_callable=AsyncMock), \
                patch.object(scraper, "_visit_and_park_detail_with_manual_handoff", new=AsyncMock(side_effect=products)) as visit, \
                patch.object(scraper, "_visit_detail", new_callable=AsyncMock) as default_visit:
            report = await scraper.verify_access(
                self.config(chrome_executable=Path(__file__)), Path("/unused.xlsx"), details_only=True)
        self.assertEqual(report["detail_success_count"], 3)
        self.assertFalse(report["workbook_written"])
        self.assertEqual([call.args[4] for call in visit.await_args_list], [10_000, 10_000, 0])
        default_visit.assert_not_awaited()
        page.close.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
