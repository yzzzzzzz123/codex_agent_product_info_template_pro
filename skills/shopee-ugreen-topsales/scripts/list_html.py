"""将 Node 单次读取的列表 HTML 在内存中按历史 lxml 契约解析。

本模块不访问浏览器、网络或文件；只返回现有 runner 的列表快照结构。错误页面仍返回
可诊断的字段及 errors，只有无法解析的输入抛出 ValueError。完整分页、卡数、页面 URL
和注入探针由 scraper 继续验收，不能将本模块返回 payload 视作页面已通过。
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote, urljoin, urlsplit

from lxml import etree
from lxml.html import HTMLParser, HtmlElement, fromstring


MIN_HTML_BYTES = 100_000
MONTHLY_RE = re.compile(
    r"^((?:\d+(?:\.\d+)?[KM]\+?)|(?:\d[\d,]*))\s+Sold/Month$", re.I
)
PRICE_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
ITEM_PATTERNS = (
    re.compile(r"(?:-i\.|/i\.)(\d+)\.(\d+)(?:/)?$", re.I),
    re.compile(r"/product/(\d+)/(\d+)(?:/)?$", re.I),
)
SEARCH_PAGE_RE = re.compile(r'"searchParams":\{"page":(\d+)')
CHALLENGE_MARKERS = (
    "verify to continue", "page unavailable", "please try again later",
    "please log in and try again", "one more step", "security check", "traffic error",
)
# 原 batch 对整个 HTML 的检查；这些标志在历史成功列表上没有触发。
RAW_CHALLENGE_MARKERS = (
    "/verify/traffic", "verify/traffic/error", "one more step", "just a moment",
    "security check",
)
IGNORED_IMAGE_ALTS = {"custom-overlay", "flag-label", "rating-star"}


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def _class_nodes(tree: HtmlElement, class_name: str) -> list[HtmlElement]:
    return tree.xpath(
        '//*[contains(concat(" ", normalize-space(@class), " "), $token)]',
        token=f" {class_name} ",
    )


def _unique_pager_values(
    tree: HtmlElement, class_name: str, errors: list[str]
) -> list[str]:
    values = list(dict.fromkeys(
        value for node in _class_nodes(tree, class_name)
        if (value := _clean(node.text_content()))
    ))
    if len(values) != 1 or not re.fullmatch(r"\d+", values[0]):
        errors.append(f"分页 {class_name} 必须恰有一个数字值")
    return values


def _identity(value: str) -> tuple[str, str] | None:
    try:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or parsed.hostname != "shopee.ph":
            return None
        path = unquote(parsed.path)
        for pattern in ITEM_PATTERNS:
            match = pattern.search(path)
            if match:
                return str(int(match.group(1))), str(int(match.group(2)))
    except (TypeError, ValueError):
        return None
    return None


def _challenge(tree: HtmlElement, raw: str, final_url: str, title: str) -> bool:
    try:
        path = unquote(urlsplit(final_url).path).lower()
    except (TypeError, ValueError):
        path = ""
    if re.search(r"/(?:verify|captcha)(?:/|$)|/traffic/error(?:/|$)", path):
        return True
    visible = _clean(" ".join(tree.xpath(
        '//body//text()[not(ancestor::script) and not(ancestor::style)]'
    ))).lower()
    if any(marker in visible or marker in title.lower() for marker in CHALLENGE_MARKERS):
        return True
    if any(marker in raw.lower() for marker in RAW_CHALLENGE_MARKERS):
        return True
    for node in tree.iter():
        # lxml comments/processing instructions are not elements; their get()
        # may return None even when a default is supplied.
        if not isinstance(node.tag, str):
            continue
        classes = node.get("class", "").lower()
        node_id = node.get("id", "").lower()
        if any(marker in classes or marker in node_id for marker in ("captcha", "traffic-error")):
            return True
        if node.tag == "iframe":
            source = node.get("src", "").lower()
            if any(marker in source for marker in ("captcha", "/verify", "/traffic/error")):
                return True
    return False


def parse_list_html(
    html: str, *, final_url: str, expected_shop_id: str, page_index: int
) -> dict[str, Any]:
    """解析一次 HTML 快照；不生成或保存 HTML、JSON、截图等中间文件。"""
    if not isinstance(html, str):
        raise ValueError("列表 HTML 必须为字符串")
    if not isinstance(page_index, int) or isinstance(page_index, bool) or page_index < 0:
        raise ValueError("列表 page_index 必须为非负整数")
    if not isinstance(final_url, str) or not isinstance(expected_shop_id, str):
        raise ValueError("列表 URL 与 shop ID 必须为字符串")
    try:
        raw = html.encode("utf-8")
        tree = fromstring(raw, parser=HTMLParser(encoding="utf-8", no_network=True))
    except (TypeError, ValueError, etree.ParserError) as exc:
        raise ValueError("列表 HTML 无法解析") from exc

    errors: list[str] = []
    if len(raw) < MIN_HTML_BYTES:
        errors.append(f"列表 HTML 过小：{len(raw)} 字节，至少需要 {MIN_HTML_BYTES} 字节")
    embedded_pages = {int(value) for value in SEARCH_PAGE_RE.findall(html)}
    if embedded_pages and page_index not in embedded_pages:
        errors.append(f"嵌入 searchParams.page 与请求页 {page_index} 不一致")

    title = _clean(tree.xpath("string(//title)"))
    current_values = _unique_pager_values(tree, "shopee-mini-page-controller__current", errors)
    total_values = _unique_pager_values(tree, "shopee-mini-page-controller__total", errors)
    views = _class_nodes(tree, "shop-search-result-view")
    anchors = tree.xpath(
        '//*[contains(concat(" ", normalize-space(@class), " "), " shop-search-result-view ")]'
        '//a[contains(concat(" ", normalize-space(@class), " "), " contents ")]'
    )
    cards: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    if len(views) != 1:
        errors.append(f"列表必须恰有一个 shop-search-result-view，实际 {len(views)} 个")
    for anchor_index, anchor in enumerate(anchors if len(views) == 1 else (), 1):
        try:
            href = urljoin(final_url, anchor.get("href") or "")
        except ValueError:
            href = ""
        identity = _identity(href)
        if identity is None:
            errors.append(f"第 {anchor_index} 个商品卡 URL 无法识别或不属于 https://shopee.ph")
            continue
        shop_id, item_id = identity
        if shop_id != expected_shop_id:
            errors.append(f"第 {anchor_index} 个商品卡店铺 ID 不匹配")
            continue
        if identity in seen:
            errors.append(f"同页商品身份重复：{shop_id}:{item_id}")
            continue
        seen.add(identity)
        card_title = next((
            alt for node in anchor.xpath('.//img[@alt]')
            if (alt := _clean(node.get("alt"))) and alt.lower() not in IGNORED_IMAGE_ALTS
        ), None)
        price_values = [
            text for node in anchor.xpath('.//span')
            if {"truncate", "text-base/5", "font-medium"}.issubset(node.get("class", "").split())
            and PRICE_RE.fullmatch(text := _clean(node.text_content()))
        ]
        monthly_matches: list[tuple[str, str]] = []
        for node in anchor.xpath('.//*[not(self::script) and not(self::style)]'):
            # 恢复昨日 lxml 的 own node.text：不拼接子节点内容或 tail 文本。
            own_text = _clean(node.text)
            match = MONTHLY_RE.fullmatch(own_text)
            if match and (row := (match.group(1), own_text)) not in monthly_matches:
                monthly_matches.append(row)
        if not card_title:
            errors.append(f"商品 {item_id} 缺少标题")
        if len(price_values) != 1:
            errors.append(f"商品 {item_id} 必须恰有一个列表价格，实际 {len(price_values)} 个")
        if len(monthly_matches) > 1:
            errors.append(f"商品 {item_id} 月销标签冲突")
        if not card_title or len(price_values) != 1 or len(monthly_matches) > 1:
            continue
        monthly = monthly_matches[0] if monthly_matches else None
        cards.append({
            "shop_id": shop_id,
            "item_id": item_id,
            "title": card_title,
            "product_url": href,
            "price_text": price_values[0],
            "monthly_sales_display": monthly[0] if monthly else None,
            "monthly_sales_text": monthly[1] if monthly else None,
        })

    next_links = tree.xpath('//link[contains(concat(" ", normalize-space(@rel), " "), " next ")]')
    if len(next_links) > 1:
        errors.append("列表下一页 link 不唯一")
    next_url = None
    if next_links:
        try:
            href = _clean(next_links[0].get("href"))
            next_url = urljoin(final_url, href) if href else None
        except ValueError:
            errors.append("列表下一页 URL 无法解析")
    next_buttons = [
        node for node in _class_nodes(tree, "shopee-mini-page-controller__next-btn")
        if node.tag == "button"
    ]
    next_button = next_buttons[0] if len(next_buttons) == 1 else None
    next_disabled = None if next_button is None else (
        next_button.get("disabled") is not None
        or "disabled" in next_button.get("class", "").split()
    )
    return {
        "challenge": _challenge(tree, html, final_url, title),
        "final_url": final_url,
        "title": title,
        "current_values": current_values,
        "total_values": total_values,
        "result_view_count": len(views),
        "scoped_anchor_count": len(anchors),
        "next_url": next_url,
        "next_button_count": len(next_buttons),
        "next_disabled": next_disabled,
        "errors": errors,
        "cards": cards,
    }
