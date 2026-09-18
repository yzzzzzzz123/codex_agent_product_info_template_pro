"""历史列表 HTML 解析契约：纯内存 fixture，不联网、启动浏览器或读取 profile。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "skills/shopee-ugreen-topsales/scripts"
sys.path.insert(0, str(SCRIPTS))
from list_html import MIN_HTML_BYTES, parse_list_html  # noqa: E402


SHOP_ID = "64922227"
URL = f"https://shopee.ph/ugreen.ph?page=0&shop={SHOP_ID}&sortBy=sales&tab=0"
PRICE = '<span class="truncate text-base/5 font-medium">1,234.50</span>'


def card(
    item_id: str = "100", *, href: str | None = None,
    images: str = '<img alt="custom-overlay"><img alt=" 离线   商品 ">',
    price: str = PRICE, monthly: str = '<span>1.2K+ Sold/Month</span>',
) -> str:
    href = f"/product/{SHOP_ID}/{item_id}" if href is None else href
    return f'<a class="other contents" href="{href}">{images}{price}{monthly}</a>'


def document(
    cards: str | None = None, *, current: str = "1", total: str = "2",
    next_link: str = '<link rel="alternate next" href="?page=1&amp;sortBy=sales&amp;tab=0">',
    button: str = '<button class="shopee-mini-page-controller__next-btn"></button>',
    head: str = "", body: str = "", views: int = 1, pad: bool = True,
) -> str:
    products = card() if cards is None else cards
    html = (
        '<!doctype html><html><head><title>离线店铺</title>' + next_link + head + '</head><body>'
        f'<span class="shopee-mini-page-controller__current">{current}</span>'
        f'<span class="shopee-mini-page-controller__total">{total}</span>'
        + ''.join(f'<div class="shop-search-result-view">{products}</div>' for _ in range(views))
        + button + body + '</body></html>'
    )
    # 足够大的合成注释只存在内存，不保存真实页面或任何 fixture 中间文件。
    if pad:
        html += '<!--' + 'x' * MIN_HTML_BYTES + '-->'
    return html


def parse(html: str, *, final_url: str = URL, page_index: int = 0) -> dict:
    return parse_list_html(html, final_url=final_url, expected_shop_id=SHOP_ID, page_index=page_index)


class ListHtmlTests(unittest.TestCase):
    def test_react_comment_nodes_do_not_crash_challenge_detection(self) -> None:
        payload = parse(document(
            ''.join(card(str(i)) for i in range(100, 130)),
            body='<!-- React marker --><div><!--$--><span>normal</span><!--/$--></div>',
        ))
        self.assertFalse(payload['challenge'])
        self.assertEqual(payload['errors'], [])
        self.assertEqual(len(payload['cards']), 30)

    def test_normal_page_payload_keeps_field_contract_and_order(self) -> None:
        payload = parse(document(''.join(card(str(i)) for i in range(100, 130))))
        self.assertEqual(payload['errors'], [])
        self.assertFalse(payload['challenge'])
        self.assertEqual(payload['title'], '离线店铺')
        self.assertEqual(payload['current_values'], ['1'])
        self.assertEqual(payload['total_values'], ['2'])
        self.assertEqual(payload['result_view_count'], 1)
        self.assertEqual(payload['scoped_anchor_count'], 30)
        self.assertEqual(payload['next_button_count'], 1)
        self.assertFalse(payload['next_disabled'])
        self.assertEqual(payload['next_url'], 'https://shopee.ph/ugreen.ph?page=1&sortBy=sales&tab=0')
        self.assertEqual([row['item_id'] for row in payload['cards']], [str(i) for i in range(100, 130)])
        self.assertEqual(payload['cards'][0], {
            'shop_id': SHOP_ID, 'item_id': '100', 'title': '离线 商品',
            'product_url': f'https://shopee.ph/product/{SHOP_ID}/100',
            'price_text': '1,234.50', 'monthly_sales_display': '1.2K+',
            'monthly_sales_text': '1.2K+ Sold/Month',
        })
        self.assertEqual(set(payload), {
            'challenge', 'final_url', 'title', 'current_values', 'total_values',
            'result_view_count', 'scoped_anchor_count', 'next_url', 'next_button_count',
            'next_disabled', 'errors', 'cards',
        })

    def test_last_page_does_not_hardcode_historical_total_or_card_count(self) -> None:
        payload = parse(document(
            card(), current='7', total='7', next_link='',
            button='<button class="shopee-mini-page-controller__next-btn" disabled></button>',
        ), final_url=URL.replace('page=0', 'page=6'), page_index=6)
        self.assertEqual(payload['errors'], [])
        self.assertEqual(len(payload['cards']), 1)
        self.assertEqual(payload['total_values'], ['7'])
        self.assertIsNone(payload['next_url'])
        self.assertTrue(payload['next_disabled'])

    def test_only_contents_anchors_in_unique_results_view_are_cards(self) -> None:
        payload = parse(document(card(), body=card('101') + '<a href="/bad">Other</a>'))
        self.assertEqual(payload['scoped_anchor_count'], 1)
        self.assertEqual(len(payload['cards']), 1)
        for views in (0, 2):
            with self.subTest(views=views):
                payload = parse(document(views=views))
                self.assertEqual(payload['result_view_count'], views)
                self.assertTrue(payload['errors'])
                self.assertEqual(payload['cards'], [])

    def test_card_urls_keep_strict_host_protocol_path_and_shop_identity(self) -> None:
        for href in (
            f'https://shopee.ph/product/{SHOP_ID}/00100?from=list',
            f'/UGREEN-item-i.{SHOP_ID}.100/', f'/i.{SHOP_ID}.100',
            f'/product/{SHOP_ID}/%31%30%30',
        ):
            with self.subTest(href=href):
                self.assertEqual(parse(document(card(href=href)))['cards'][0]['item_id'], '100')
        for href in (
            '', '/not-a-product', f'/product/222/100',
            f'http://shopee.ph/product/{SHOP_ID}/100',
            f'https://sub.shopee.ph/product/{SHOP_ID}/100',
            f'https://shopee.ph.evil.example/product/{SHOP_ID}/100',
            f'https://shopee.ph@evil.example/product/{SHOP_ID}/100',
            f'https://other.example/product/{SHOP_ID}/100',
            f'/product/{SHOP_ID}/100/extra', 'https://[invalid',
        ):
            with self.subTest(href=href):
                payload = parse(document(card(href=href)))
                self.assertTrue(payload['errors'])
                self.assertEqual(payload['cards'], [])

    def test_duplicate_or_unrecognised_scoped_anchor_is_not_silently_ignored(self) -> None:
        payload = parse(document(card() + card(href=f'/Name-i.{SHOP_ID}.100') + card('101', href='/unknown')))
        self.assertEqual(payload['scoped_anchor_count'], 3)
        self.assertEqual(len(payload['cards']), 1)
        self.assertEqual(len(payload['errors']), 2)
        self.assertTrue(any('重复' in error for error in payload['errors']))
        self.assertTrue(any('URL' in error for error in payload['errors']))

    def test_first_valid_image_alt_is_title_and_overlay_alts_are_ignored(self) -> None:
        payload = parse(document(card(images=(
            '<img alt=""><img alt="CUSTOM-overlay"><img alt="flag-label">'
            '<img alt="rating-star"><img alt="商品 A"><img alt="商品 B">'
        ))))
        self.assertEqual(payload['cards'][0]['title'], '商品 A')
        payload = parse(document(card(images='<img alt="custom-overlay"><img src="fixture">')))
        self.assertEqual(payload['cards'], [])
        self.assertTrue(any('标题' in error for error in payload['errors']))

    def test_price_requires_exact_classes_numeric_text_and_one_matching_node(self) -> None:
        for price in ('', PRICE + PRICE, PRICE + PRICE.replace('1,234.50', '900'),
                      PRICE.replace('font-medium', 'font-mediumish'), PRICE.replace('1,234.50', '₱123')):
            with self.subTest(price=price):
                payload = parse(document(card(price=price)))
                self.assertEqual(payload['cards'], [])
                self.assertTrue(any('价格' in error for error in payload['errors']))
        payload = parse(document(card(price=PRICE + '<span class="truncate text-base/5 font-medium">PHP</span>')))
        self.assertEqual(payload['cards'][0]['price_text'], '1,234.50')

    def test_monthly_absence_and_zero_remain_distinct(self) -> None:
        for text, display in (('', None), ('0 Sold/Month', '0'), ('1,234 Sold/Month', '1,234'),
                              ('1.5M+ Sold/Month', '1.5M+'), ('2k Sold/Month', '2k')):
            with self.subTest(text=text):
                payload = parse(document(card(monthly=f'<span>{text}</span>')))
                self.assertEqual(payload['errors'], [])
                self.assertEqual(payload['cards'][0]['monthly_sales_display'], display)
                self.assertEqual(payload['cards'][0]['monthly_sales_text'], text or None)

    def test_monthly_uses_own_node_text_without_descendants_tails_or_script_style(self) -> None:
        for monthly in (
            '<span>Rating 4.9 <b>1</b> Sold/Month</span>',
            '<span><b>1.2K+</b> Sold/Month</span>',
            '<span><b>Rating</b>1.2K+ Sold/Month</span>',
            '<script>1.2K+ Sold/Month</script><style>2K Sold/Month</style>',
            '<span>1.2K+ Sold/Month extra</span>',
        ):
            with self.subTest(monthly=monthly):
                payload = parse(document(card(monthly=monthly)))
                self.assertIsNone(payload['cards'][0]['monthly_sales_display'])
        payload = parse(document(card(monthly='<div>Rating 4.9<span>  1.2K+   Sold/Month </span></div>')))
        self.assertEqual(payload['cards'][0]['monthly_sales_display'], '1.2K+')

    def test_monthly_identical_labels_deduplicate_but_conflicting_values_fail(self) -> None:
        same = '<span>1K Sold/Month</span>'
        payload = parse(document(card(monthly=same + same)))
        self.assertEqual(payload['errors'], [])
        self.assertEqual(payload['cards'][0]['monthly_sales_display'], '1K')
        payload = parse(document(card(monthly=same + '<span>2K Sold/Month</span>')))
        self.assertEqual(payload['cards'], [])
        self.assertTrue(any('月销' in error for error in payload['errors']))

    def test_card_errors_accumulate_for_title_price_and_monthly(self) -> None:
        payload = parse(document(card(images='', price='', monthly='<span>1 Sold/Month</span><span>2 Sold/Month</span>')))
        self.assertEqual(len(payload['errors']), 3)
        self.assertEqual(payload['cards'], [])

    def test_pager_values_are_unique_numeric_strings(self) -> None:
        payload = parse(document(body=(
            '<span class="shopee-mini-page-controller__current"> 1 </span>'
            '<span class="shopee-mini-page-controller__total">2</span>'
        )))
        self.assertEqual(payload['current_values'], ['1'])
        self.assertEqual(payload['total_values'], ['2'])
        self.assertEqual(payload['errors'], [])
        for field in ('current', 'total'):
            for value in ('', 'unknown', '1/2'):
                with self.subTest(field=field, value=value):
                    self.assertTrue(parse(document(**{field: value}))['errors'])
        payload = parse(document(body='<span class="shopee-mini-page-controller__current">2</span>'))
        self.assertEqual(payload['current_values'], ['1', '2'])
        self.assertTrue(payload['errors'])

    def test_next_button_state_requires_actual_unique_button(self) -> None:
        for attribute in ('disabled', 'disabled="false"', 'class="disabled shopee-mini-page-controller__next-btn"'):
            button = f'<button {attribute}' + ('' if attribute.startswith('class=') else ' class="shopee-mini-page-controller__next-btn"') + '></button>'
            self.assertTrue(parse(document(button=button))['next_disabled'])
        for button, count in (
            ('<div class="shopee-mini-page-controller__next-btn disabled"></div>', 0),
            ('<button class="shopee-mini-page-controller__next-btn"></button>' * 2, 2),
        ):
            with self.subTest(count=count):
                payload = parse(document(button=button))
                self.assertEqual(payload['next_button_count'], count)
                self.assertIsNone(payload['next_disabled'])
        self.assertTrue(parse(document(next_link='<link rel="next" href="?page=1">' * 2))['errors'])

    def test_final_url_challenges_cover_verify_captcha_traffic_and_encoded_path(self) -> None:
        for path in ('/verify', '/verify/captcha', '/captcha?next=foo', '/traffic/error', '/%76erify/traffic'):
            with self.subTest(path=path):
                self.assertTrue(parse(document(), final_url='https://shopee.ph' + path)['challenge'])

    def test_visible_title_and_raw_historical_challenge_markers_are_detected(self) -> None:
        for marker in ('Verify to Continue', 'Page Unavailable', 'Please Try Again Later',
                       'Please log in and try again', 'One More Step', 'Security Check', 'Traffic Error'):
            with self.subTest(marker=marker):
                self.assertTrue(parse(document(body=f'<div>{marker.upper()}</div>'))['challenge'])
                self.assertTrue(parse(document().replace('离线店铺', marker))['challenge'])
        for marker in ('/verify/traffic', 'verify/traffic/error', 'one more step', 'just a moment', 'security check'):
            with self.subTest(raw_marker=marker):
                self.assertTrue(parse(document(head=f'<script>"{marker}"</script>'))['challenge'])
        # 非历史 raw 标志必须出现在 title/body 可见文本，不能命中普通脚本字符串。
        payload = parse(document(head='<script>"Page Unavailable"</script><style>"Traffic Error"</style>'))
        self.assertFalse(payload['challenge'])

    def test_challenge_nodes_and_iframes_are_detected(self) -> None:
        for element in ('<div class="captcha-box"></div>', '<div id="CAPTCHA"></div>',
                        '<div class="traffic-error"></div>', '<div id="traffic-error"></div>',
                        '<iframe src="/captcha"></iframe>', '<iframe src="/verify"></iframe>',
                        '<iframe src="/traffic/error"></iframe>'):
            with self.subTest(element=element):
                self.assertTrue(parse(document(body=element))['challenge'])

    def test_embedded_search_page_keeps_historical_membership_contract(self) -> None:
        for embedded, mismatch in ((None, False), ('0', False), ('1', True), ('0},"searchParams":{"page":9', False)):
            with self.subTest(embedded=embedded):
                head = '' if embedded is None else '<script>{"searchParams":{"page":' + embedded + '}}</script>'
                payload = parse(document(head=head))
                self.assertEqual(any('searchParams.page' in error for error in payload['errors']), mismatch)

    def test_html_size_gate_uses_utf8_bytes_and_exact_threshold(self) -> None:
        minimal = document(pad=False)
        self.assertTrue(any('过小' in error for error in parse(minimal)['errors']))
        padding = MIN_HTML_BYTES - len(minimal.encode('utf-8')) - len('<!-- -->')
        exact = minimal + '<!--' + 'x' * padding + ' -->'
        self.assertEqual(len(exact.encode('utf-8')), MIN_HTML_BYTES)
        self.assertEqual(parse(exact)['errors'], [])
        unicode_padding = minimal + '<!--' + '汉' * 34_000 + '-->'
        self.assertLess(len(unicode_padding), MIN_HTML_BYTES)
        self.assertEqual(parse(unicode_padding)['errors'], [])

    def test_unparseable_html_or_invalid_arguments_fail_without_echoing_html(self) -> None:
        for html in ('', '   ', None, '\ud800'):
            with self.subTest(html=repr(html)):
                with self.assertRaises(ValueError):
                    parse(html)
        for page_index in (-1, True, '0'):
            with self.subTest(page_index=page_index):
                with self.assertRaises(ValueError):
                    parse(document(), page_index=page_index)


if __name__ == '__main__':
    unittest.main()
