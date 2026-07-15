import json
import re
import urllib.parse
from curl_cffi import requests as curl_requests
from lxml.html import fromstring


def _response_text(response):
    if response is None:
        return ""
    content = getattr(response, "content", None)
    if isinstance(content, bytes):
        return content.decode("utf-8", "ignore")
    if content:
        return str(content)
    return getattr(response, "text", "") or ""


def _response_ok(response):
    if response is None:
        return False
    status = getattr(response, "status_code", 200)
    return 200 <= int(status) < 300 and bool(_response_text(response))


def _live_get(url, headers):
    try:
        response = curl_requests.get(
            url,
            headers=headers,
            impersonate="chrome",
            timeout=45,
        )
        if _response_ok(response):
            return response
    except Exception:
        response = None
    response = common_request("get", url, headers=headers, timeout=45)
    return response


def _absolute_url(value):
    if not value:
        return None
    value = str(value).strip()
    if value.startswith("//"):
        return "https:" + value
    if value.startswith("http://") or value.startswith("https://"):
        return value
    return urllib.parse.urljoin(detail_url, value)


def _clean_text(node):
    return re.sub(r"\s+", " ", " ".join(node.itertext())).strip()


def _description_blocks(fragment):
    if not fragment:
        return []
    try:
        root = fromstring("<div>" + str(fragment) + "</div>")
    except Exception:
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(fragment))).strip()
        return [text] if text else []
    blocks = []
    pending_heading = None
    for child in root:
        tag = str(child.tag).lower() if isinstance(child.tag, str) else ""
        text = _clean_text(child)
        if not text:
            continue
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            if pending_heading:
                blocks.append(pending_heading)
            pending_heading = text
            continue
        if tag in ("ul", "ol"):
            rows = []
            for item in child.xpath(".//li"):
                item_text = _clean_text(item)
                if item_text:
                    rows.append("• " + item_text)
            text = "\n".join(rows)
        if pending_heading:
            text = pending_heading + "\n" + text
            pending_heading = None
        if text and "Learn more about Jackery Solar Generator 5000 Plus" not in text:
            blocks.append(text)
    if pending_heading:
        blocks.append(pending_heading)
    return blocks


def _selected_variant_index(url, tree, variants):
    parsed_query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    requested = parsed_query.get("variant", [None])[0]
    if requested:
        for index, variant in enumerate(variants):
            if str(variant.get("id")) == str(requested):
                return index
    if tree is not None:
        candidates = tree.xpath(
            '//input[@type="radio" and @name="Select Options" and @checked]/@data-id'
            ' | //input[contains(concat(" ", normalize-space(@class), " "), " product-variant-id ") and @name="id"]/@value'
        )
        for candidate in candidates:
            for index, variant in enumerate(variants):
                if str(variant.get("id")) == str(candidate):
                    return index
    return 0


def _selected_specs(tree, variant_id):
    if tree is None:
        return {}
    wanted = ("Capacity", "Cell Chemistry", "AC Total Output", "Warranty")
    props = {}
    nodes = tree.xpath(
        '//*[@variant_id="%s"]//*[contains(concat(" ", normalize-space(@class), " "), " specs-item ")]'
        % str(variant_id)
    )
    for node in nodes:
        keys = node.xpath('./*[contains(concat(" ", normalize-space(@class), " "), " key ")]')
        values = node.xpath('./*[contains(concat(" ", normalize-space(@class), " "), " value ")]')
        if not keys or not values:
            continue
        key = _clean_text(keys[0])
        value = _clean_text(values[0])
        if key in wanted and value and key not in props:
            props[key] = value
    return props


def _build_result():
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        page_response = rsp
    except NameError:
        page_response = None
    page_text = _response_text(page_response) if _response_ok(page_response) else ""
    if not page_text:
        page_response = _live_get(detail_url, headers)
        page_text = _response_text(page_response)
    try:
        tree = fromstring(page_text) if page_text else None
    except Exception:
        tree = None

    parsed = urllib.parse.urlsplit(detail_url)
    product_path = parsed.path.rstrip("/") + ".js"
    product_url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, product_path, "", ""))
    api_headers = dict(headers)
    api_headers["Accept"] = "application/json"
    api_headers["Referer"] = detail_url
    product_response = _live_get(product_url, api_headers)
    product_text = _response_text(product_response)
    product = json.loads(product_text)
    variants = product.get("variants") or []
    if not variants:
        raise ValueError("Shopify product endpoint returned no variants")

    selected_index = _selected_variant_index(detail_url, tree, variants)
    selected = variants[selected_index]
    options = product.get("options") or [{}]
    option_name = str(options[0].get("name") or "Option")

    currency_match = re.search(
        r'currency\s*:\s*\{\s*currency\s*:\s*["\']([A-Z]{3})',
        page_text,
    )
    currency = currency_match.group(1) if currency_match else "USD"

    pics = []
    for image_value in product.get("images") or []:
        normalized = _absolute_url(image_value)
        if normalized and normalized not in pics:
            pics.append(normalized)

    sku_rows = []
    for variant in variants:
        activity = float(variant.get("price")) / 100.0
        compare_at = variant.get("compare_at_price")
        origin = float(compare_at) / 100.0 if compare_at is not None else activity
        featured_image = variant.get("featured_image") or {}
        image_url = _absolute_url(featured_image.get("src"))
        sku_props = {
            option_name: str(variant.get("option1") or variant.get("title") or variant.get("id"))
        }
        if variant.get("sku"):
            sku_props["SKU"] = str(variant.get("sku"))
        sku_rows.append(
            {
                "sku_props": sku_props,
                "source_origin_price": origin,
                "source_activity_price": activity,
                "source_price_currency": currency,
                "source_pics": [image_url] if image_url else [],
                "status": 1 if variant.get("available") else 0,
            }
        )

    selected_row = sku_rows[selected_index]
    props = {
        "Brand": str(product.get("vendor") or "Jackery"),
        "Product ID": str(product.get("id")),
    }
    props.update(_selected_specs(tree, selected.get("id")))
    props.update(selected_row["sku_props"])

    return {
        "source_url": detail_url,
        "source_item_name": str(product.get("title") or "").strip(),
        "source_pics": pics,
        "descriptions": _description_blocks(product.get("description")),
        "source_origin_price": selected_row["source_origin_price"],
        "source_activity_price": selected_row["source_activity_price"],
        "source_price_currency": currency,
        "props": props,
        "status": selected_row["status"],
        "skus": sku_rows,
        "source_score": None,
        "source_cmms": None,
        "not_detail": None,
    }


script_res = _build_result()
