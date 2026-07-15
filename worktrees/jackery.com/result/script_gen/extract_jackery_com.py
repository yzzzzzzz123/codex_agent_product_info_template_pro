"""Live Stage2 extractor for Jackery Shopify product pages."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlsplit, urlunsplit

from curl_cffi import requests
from lxml.html import fromstring


DEFAULT_URL = "https://www.jackery.com/products/jackery-solar-generator-5000-plus"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def _absolute_url(value: Any) -> Optional[str]:
    if not value:
        return None
    value = str(value).strip()
    if value.startswith("//"):
        return "https:" + value
    if value.startswith("http://") or value.startswith("https://"):
        return value
    return None


def _clean_text(node: Any) -> str:
    return re.sub(r"\s+", " ", " ".join(node.itertext())).strip()


def _description_blocks(fragment: Any) -> List[str]:
    if not fragment:
        return []
    try:
        root = fromstring("<div>" + str(fragment) + "</div>")
    except Exception:
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(fragment))).strip()
        return [text] if text else []

    blocks: List[str] = []
    pending_heading: Optional[str] = None
    for child in root:
        tag = str(child.tag).lower() if isinstance(child.tag, str) else ""
        text = _clean_text(child)
        if not text:
            continue
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            if pending_heading:
                blocks.append(pending_heading)
            pending_heading = text
            continue
        if tag in {"ul", "ol"}:
            text = "\n".join(
                "• " + _clean_text(item)
                for item in child.xpath(".//li")
                if _clean_text(item)
            )
        if pending_heading:
            text = pending_heading + "\n" + text
            pending_heading = None
        if text and "Learn more about Jackery Solar Generator 5000 Plus" not in text:
            blocks.append(text)
    if pending_heading:
        blocks.append(pending_heading)
    return blocks


def _selected_variant_id(detail_url: str, tree: Any, variants: List[Dict[str, Any]]) -> str:
    requested = parse_qs(urlsplit(detail_url).query).get("variant", [None])[0]
    variant_ids = {str(variant.get("id")) for variant in variants}
    if requested and str(requested) in variant_ids:
        return str(requested)

    candidates = tree.xpath(
        '//input[@type="radio" and @name="Select Options" and @checked]/@data-id'
        ' | //input[contains(concat(" ", normalize-space(@class), " "), " product-variant-id ") and @name="id"]/@value'
    )
    for candidate in candidates:
        if str(candidate) in variant_ids:
            return str(candidate)
    return str(variants[0].get("id"))


def _selected_specs(tree: Any, variant_id: str) -> Dict[str, str]:
    wanted = {"Capacity", "Cell Chemistry", "AC Total Output", "Warranty"}
    props: Dict[str, str] = {}
    nodes = tree.xpath(
        '//*[@variant_id="%s"]//*[contains(concat(" ", normalize-space(@class), " "), " specs-item ")]'
        % variant_id
    )
    for node in nodes:
        keys = node.xpath(
            './*[contains(concat(" ", normalize-space(@class), " "), " key ")]'
        )
        values = node.xpath(
            './*[contains(concat(" ", normalize-space(@class), " "), " value ")]'
        )
        if not keys or not values:
            continue
        key = _clean_text(keys[0])
        value = _clean_text(values[0])
        if key in wanted and value and key not in props:
            props[key] = value
    return props


def extract(detail_url: str) -> Dict[str, Any]:
    page_response = requests.get(detail_url, headers=HEADERS, impersonate="chrome", timeout=45)
    page_response.raise_for_status()
    page_html = page_response.content.decode("utf-8", "ignore")
    tree = fromstring(page_html)

    parsed = urlsplit(detail_url)
    product_path = parsed.path.rstrip("/") + ".js"
    product_url = urlunsplit((parsed.scheme, parsed.netloc, product_path, "", ""))
    product_response = requests.get(
        product_url,
        headers={**HEADERS, "Accept": "application/json", "Referer": detail_url},
        impersonate="chrome",
        timeout=45,
    )
    product_response.raise_for_status()
    product = product_response.json()

    variants = product.get("variants") or []
    if not variants:
        raise ValueError("Shopify product endpoint returned no variants")
    selected_id = _selected_variant_id(detail_url, tree, variants)
    selected_index = next(
        (index for index, variant in enumerate(variants) if str(variant.get("id")) == selected_id),
        0,
    )
    selected = variants[selected_index]
    option_name = str((product.get("options") or [{}])[0].get("name") or "Option")

    pics = []
    for value in product.get("images") or []:
        normalized = _absolute_url(value)
        if normalized and normalized not in pics:
            pics.append(normalized)

    skus = []
    for variant in variants:
        activity = float(variant["price"]) / 100.0
        compare_at = variant.get("compare_at_price")
        origin = float(compare_at) / 100.0 if compare_at is not None else activity
        image = _absolute_url((variant.get("featured_image") or {}).get("src"))
        sku_props = {option_name: str(variant.get("option1") or variant.get("title") or variant.get("id"))}
        if variant.get("sku"):
            sku_props["SKU"] = str(variant["sku"])
        skus.append(
            {
                "sku_props": sku_props,
                "source_origin_price": origin,
                "source_activity_price": activity,
                "source_price_currency": "USD",
                "source_pics": [image] if image else [],
                "status": 1 if variant.get("available") else 0,
            }
        )

    props: Dict[str, str] = {
        "Brand": str(product.get("vendor") or "Jackery"),
        "Product ID": str(product.get("id")),
    }
    props.update(_selected_specs(tree, selected_id))
    props.update(skus[selected_index]["sku_props"])

    return {
        "source_url": detail_url,
        "source_item_name": str(product.get("title") or "").strip(),
        "source_pics": pics,
        "descriptions": _description_blocks(product.get("description")),
        "source_origin_price": skus[selected_index]["source_origin_price"],
        "source_activity_price": skus[selected_index]["source_activity_price"],
        "source_price_currency": "USD",
        "props": props,
        "status": skus[selected_index]["status"],
        "skus": skus,
        "source_score": None,
        "source_cmms": None,
        "not_detail": None,
        "default_sku_index": selected_index,
        "effective_price": skus[selected_index]["source_activity_price"],
        "_projection_mode": "all",
        "_projection_props": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--detail-url", default=DEFAULT_URL)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = extract(args.detail_url)
    Path(args.output).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
