import json
import re
import html
from urllib.parse import urljoin
from lxml.html import fromstring


def _clean(value):
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _node_text(node):
    try:
        return _clean(node.text_content())
    except Exception:
        return ""


def _texts(tree, xpath):
    out = []
    try:
        values = tree.xpath(xpath)
    except Exception:
        return out
    for value in values:
        if hasattr(value, "text_content"):
            text = _node_text(value)
        else:
            text = _clean(value)
        if text:
            out.append(text)
    return out


def _first_text(tree, xpaths):
    for xpath in xpaths:
        vals = _texts(tree, xpath)
        for val in vals:
            if val:
                return val
    return ""


def _abs(url, base_url):
    if not url:
        return None
    value = html.unescape(str(url).strip())
    if not value:
        return None
    if value.startswith("//"):
        return "https:" + value
    if value.startswith("http://") or value.startswith("https://"):
        return value
    return urljoin(base_url, value)


def _dedupe(values):
    seen = set()
    out = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _price_number(text):
    if text is None:
        return None
    value = html.unescape(str(text))
    if not value.strip():
        return None
    if re.search(r"\bfree\b", value, re.I):
        return 0.0
    money_patterns = [
        r"(?:US)?\$\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)",
        r"\bUSD\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)",
        r"([0-9][0-9,]*(?:\.[0-9]{1,2})?)\s*USD\b",
    ]
    for pattern in money_patterns:
        match = re.search(pattern, value, re.I)
        if match:
            try:
                return float(match.group(1).replace(",", ""))
            except Exception:
                return None
    fallback = re.search(r"([0-9][0-9,]*(?:\.[0-9]{1,2})?)", value)
    if fallback:
        try:
            return float(fallback.group(1).replace(",", ""))
        except Exception:
            return None
    return None


def _currency(text):
    value = str(text or "").upper()
    if "$" in value or "USD" in value:
        return "USD"
    if "€" in value or "EUR" in value:
        return "EUR"
    if "£" in value or "GBP" in value:
        return "GBP"
    if "¥" in value or "CNY" in value or "RMB" in value:
        return "CNY"
    return None


def _price_texts(tree, xpaths):
    values = []
    for xpath in xpaths:
        values.extend(_texts(tree, xpath))
    return _dedupe(values)


def _activity_price(tree):
    candidates = _price_texts(
        tree,
        [
            '//*[@id="apex-pricetopay-accessibility-label"]/text()',
            '//*[@id="corePrice_feature_div"]//*[contains(@class,"apex-pricetopay-value")]//*[contains(@class,"a-offscreen")]/text()',
            '//*[contains(@class,"priceToPay")]//*[contains(@class,"a-offscreen")]/text()',
            '//*[@id="corePrice_feature_div"]//*[contains(@class,"a-price")]//*[contains(@class,"a-offscreen")]/text()',
            '//*[@id="buybox"]//*[contains(@class,"a-price")]//*[contains(@class,"a-offscreen")]/text()',
            '//span[contains(@class,"a-price")]//span[contains(@class,"a-offscreen")]/text()',
        ],
    )
    for text in candidates:
        if "list price" in text.lower():
            continue
        number = _price_number(text)
        if number is not None:
            return number, text
    return None, ""


def _origin_price(tree, activity):
    candidates = _price_texts(
        tree,
        [
            '//*[contains(@class,"basisPrice") or contains(@class,"apex-basisprice")]//*[contains(@class,"a-offscreen")]/text()',
            '//*[contains(@class,"basisPrice") or contains(@class,"apex-basisprice")]//@data-basisprice-label',
            '//*[contains(@class,"a-text-price")]//*[contains(@class,"a-offscreen")]/text()',
        ],
    )
    for text in candidates:
        number = _price_number(text)
        if number is not None:
            return number, text
    return activity, ""


def _parse_dynamic_images(attr):
    if not attr:
        return []
    raw = html.unescape(str(attr))
    try:
        data = json.loads(raw)
    except Exception:
        return []
    if isinstance(data, dict):
        return list(data.keys())
    return []


def _images(tree, raw_html, base_url):
    urls = []
    for attr in tree.xpath('//*[@id="landingImage" or @id="imgBlkFront"]/@data-a-dynamic-image'):
        urls.extend(_parse_dynamic_images(attr))
    urls.extend(tree.xpath('//*[@id="landingImage" or @id="imgBlkFront"]/@src'))
    urls.extend(tree.xpath('//*[@id="imgTagWrapperId"]//img/@src'))
    if not urls:
        urls.extend(
            re.findall(
                r"https?://(?:m\.media-amazon|images-na\.ssl-images-amazon)\.com/images/I/[^\s\"'<>]+?\.(?:jpg|jpeg|png|webp)",
                raw_html,
                flags=re.I,
            )
        )
    normalized = []
    for url in urls:
        absolute = _abs(url, base_url)
        if not absolute:
            continue
        if ".svg" in absolute.lower() or "/S/sash/" in absolute:
            continue
        normalized.append(absolute)
    return _dedupe(normalized)[:12]


def _descriptions(tree):
    descriptions = []
    for text in _texts(tree, '//*[@id="feature-bullets"]//li//span[contains(@class,"a-list-item")]'):
        if not text:
            continue
        lower = text.lower()
        if "make sure this fits" in lower or lower == "about this item":
            continue
        descriptions.append(text)
    product_desc = _first_text(
        tree,
        [
            '//*[@id="productDescription"]',
            '//*[@id="aplus"]',
        ],
    )
    if product_desc and product_desc not in descriptions:
        descriptions.append(product_desc)
    return _dedupe(descriptions)


def _props_from_tables(tree):
    props = {}
    row_xpaths = [
        '//*[@id="productOverview_feature_div"]//tr',
        '//*[@id="prodDetails"]//tr',
        '//*[@id="detailBullets_feature_div"]//li',
    ]
    for xpath in row_xpaths:
        try:
            rows = tree.xpath(xpath)
        except Exception:
            rows = []
        for row in rows:
            cells = [_clean(cell.text_content()) for cell in row.xpath("./th|./td")]
            if len(cells) >= 2:
                key = cells[0].strip(" :")
                val = cells[1].strip()
            else:
                text = _node_text(row)
                if ":" not in text:
                    continue
                key, val = [part.strip() for part in text.split(":", 1)]
            if not key or not val:
                continue
            if key.lower() in {"customer reviews", "best sellers rank", "date first available"}:
                continue
            if len(key) > 80 or len(val) > 240:
                continue
            props.setdefault(key, val)
    return props


def _asin(detail_url, tree):
    match = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})", detail_url, re.I)
    if match:
        return match.group(1).upper()
    for value in tree.xpath('//*[@data-csa-c-asin]/@data-csa-c-asin'):
        value = _clean(value).upper()
        if re.match(r"^[A-Z0-9]{10}$", value):
            return value
    return ""


def _status(tree, title, activity):
    status_text = _first_text(
        tree,
        [
            '//*[@id="availability"]',
            '//*[@id="availabilityInsideBuyBox_feature_div"]',
            '//*[@id="buybox"]',
        ],
    ).lower()
    if re.search(r"currently unavailable|out of stock|temporarily out of stock|unavailable", status_text):
        return 0
    if "in stock" in status_text or "add to cart" in status_text or "buy now" in status_text:
        return 1
    if title and activity is not None:
        return 1
    return 0


def _review_stats(tree):
    score = None
    score_candidates = _price_texts(
        tree,
        [
            '//*[@id="acrPopover"]/@title',
            '//*[@id="acrPopover"]//*[contains(@class,"a-icon-alt")]/text()',
            '//*[@data-hook="rating-out-of-text"]/text()',
            '//*[@id="reviewsMedley"]//*[contains(@class,"a-icon-alt")]/text()',
        ],
    )
    for text in score_candidates:
        match = re.search(r"([0-5](?:\.\d+)?)\s+out\s+of\s+5", text, re.I)
        if match:
            try:
                score = float(match.group(1))
                break
            except Exception:
                pass

    cmms = None
    count_candidates = _price_texts(
        tree,
        [
            '//*[@id="acrCustomerReviewText"]/text()',
            '//*[@id="acrCustomerReviewLink"]',
            '//*[@data-hook="total-review-count"]/text()',
            '//*[@id="reviewsMedley"]',
        ],
    )
    for text in count_candidates:
        match = re.search(r"([0-9][0-9,]*)\s+(?:global\s+ratings|ratings|reviews)", text, re.I)
        if not match:
            match = re.search(r"\(([0-9][0-9,]*)\)", text)
        if match:
            try:
                cmms = int(match.group(1).replace(",", ""))
                break
            except Exception:
                pass
    return score, cmms


def _parse_product(detail_url, raw):
    if isinstance(raw, bytes):
        raw_text = raw.decode("utf-8", "ignore")
    else:
        raw_text = str(raw or "")
        raw = raw_text.encode("utf-8", "ignore")
    tree = fromstring(raw)

    title = _first_text(tree, ['//*[@id="productTitle"]', '//*[@id="title"]'])
    pics = _images(tree, raw_text, detail_url)
    descriptions = _descriptions(tree)
    props = _props_from_tables(tree)
    activity_price, activity_text = _activity_price(tree)
    origin_price, origin_text = _origin_price(tree, activity_price)
    currency = _currency(activity_text) or _currency(origin_text) or "USD"
    status = _status(tree, title, activity_price)
    asin = _asin(detail_url, tree)
    score, cmms = _review_stats(tree)

    sku_props = {}
    if asin:
        sku_props["ASIN"] = asin
    for key in ("Color", "Style Name", "Style", "Size"):
        if props.get(key):
            sku_props[key] = props[key]
    if not sku_props:
        sku_props["SKU"] = asin or title[:60] or "selected"

    if origin_price is None:
        origin_price = activity_price
    if activity_price is None:
        activity_price = origin_price

    return {
        "source_url": detail_url,
        "source_item_name": title,
        "source_pics": pics,
        "descriptions": descriptions,
        "source_origin_price": origin_price,
        "source_activity_price": activity_price,
        "source_price_currency": currency,
        "props": props,
        "skus": [
            {
                "sku_props": sku_props,
                "source_origin_price": origin_price,
                "source_activity_price": activity_price,
                "source_pics": pics[:6],
                "status": status,
            }
        ],
        "status": status,
        "source_score": score,
        "source_cmms": cmms,
        "not_detail": None,
    }


headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Upgrade-Insecure-Requests": "1",
}
rsp = common_request("get", detail_url, headers=headers, timeout=40)
raw = getattr(rsp, "content", None)
if not raw:
    raw = (getattr(rsp, "text", "") or "").encode("utf-8", "ignore")

script_res = _parse_product(detail_url, raw)
