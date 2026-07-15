#!/usr/bin/env python3
"""
Extract product information from eBay product pages.

Site: ebay.com
Stage: Stage2
"""

import re
import json
from typing import Dict, List, Optional, Any
from urllib.parse import urljoin


def _strip_html(text: str) -> str:
    """Remove HTML tags and normalize whitespace."""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _parse_price(price_str: Any) -> Optional[float]:
    """Parse price string to float."""
    if price_str is None:
        return None
    if isinstance(price_str, (int, float)):
        return float(price_str)
    try:
        cleaned = re.sub(r"[^0-9.]", "", str(price_str))
        return float(cleaned) if cleaned else None
    except (ValueError, TypeError):
        return None


def extract_product(html: str, url: str) -> Dict[str, Any]:
    """Extract product information from eBay PDP HTML.

    Args:
        html: The HTML content of the product page.
        url: The URL of the product page.

    Returns:
        A dictionary containing extracted product data.
    """
    result = {
        "source_url": url,
        "source_item_name": None,
        "source_pics": [],
        "descriptions": [],
        "props": {},
        "source_origin_price": None,
        "source_activity_price": None,
        "source_price_currency": "USD",
        "status": 1,
        "skus": [],
        "default_sku_index": 0,
        "effective_price": None,
        "source_score": None,
        "source_cmms": None,
        "not_detail": None,
        "_projection_mode": "all",
        "_projection_props": [],
    }

    # Extract title
    title_match = re.search(r'class="vim x-item-title"[^>]*>([\s\S]*?)</div>', html)
    if title_match:
        result["source_item_name"] = _strip_html(title_match.group(1))

    # Extract price
    price_match = re.search(
        r'class="vim x-price-section[^"]*"[^>]*>([\s\S]*?)</div>\s*</div>',
        html,
    )
    if price_match:
        price_text = _strip_html(price_match.group(1))
        us_price = re.search(r"US\s+\$([\d,]+\.?\d*)", price_text)
        if us_price:
            result["source_activity_price"] = _parse_price(us_price.group(1))
            result["source_price_currency"] = "USD"

    # Extract images
    img_urls = set()
    img_regex = re.compile(r"https?://i\.ebayimg\.com/[^\"'\s<>)]+", re.IGNORECASE)
    for match in img_regex.finditer(html):
        img_url = match.group(0)
        img_url = img_url.rstrip(".")
        if "sprite" not in img_url and "icon" not in img_url:
            if any(size in img_url for size in ["s-l1600", "s-l400", "/images/g/"]):
                img_urls.add(img_url)
    result["source_pics"] = list(img_urls)[:10]

    # Extract item specifics (props)
    specifics_start = html.find("Item specifics")
    if specifics_start > 0:
        section = html[specifics_start : specifics_start + 5000]
        dt_pattern = re.compile(r"<dt[^>]*>([\s\S]*?)</dt>", re.IGNORECASE)
        dd_pattern = re.compile(r"<dd[^>]*>([\s\S]*?)</dd>", re.IGNORECASE)
        dts = [_strip_html(m.group(1)) for m in dt_pattern.finditer(section)]
        dds = [_strip_html(m.group(1)) for m in dd_pattern.finditer(section)]
        if len(dts) == len(dds):
            for dt, dd in zip(dts, dds):
                if dt and dd:
                    result["props"][dt] = dd

    # Extract description
    desc_start = html.find("Item description from the seller")
    if desc_start > 0:
        desc_section = html[desc_start : desc_start + 8000]
        desc_text = _strip_html(desc_section)
        sentences = re.split(r"(?<=[.!?])\s+", desc_text)
        result["descriptions"] = [s.strip() for s in sentences if len(s.strip()) > 30][:10]

    # Extract ratings
    ratings_start = html.find("Product ratings and reviews")
    if ratings_start > 0:
        ratings_section = html[ratings_start : ratings_start + 5000]
        ratings_text = _strip_html(ratings_section)
        score_match = re.search(r"([\d.]+)\s+out\s+of\s+5", ratings_text, re.IGNORECASE)
        if score_match:
            result["source_score"] = float(score_match.group(1))
        review_match = re.search(r"([\d,]+)\s+reviews?", ratings_text, re.IGNORECASE)
        if review_match:
            result["source_cmms"] = int(review_match.group(1).replace(",", ""))

    # Build SKU
    sku = {
        "source_pics": result["source_pics"][:1] if result["source_pics"] else [],
        "status": 1,
        "source_activity_price": result["source_activity_price"],
        "source_origin_price": result["source_origin_price"],
        "source_price_currency": result["source_price_currency"],
        "sku_props": {},
    }

    # Extract item ID for SKU prop
    item_id_match = re.search(r"itemId[\"'':\s]+(\d+)", html)
    if item_id_match:
        sku["sku_props"]["Item ID"] = item_id_match.group(1)

    result["skus"] = [sku]
    result["default_sku_index"] = 0
    result["effective_price"] = result["source_activity_price"] or result["source_origin_price"]

    return result


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("Usage: python extract_ebay.com.py <html_file> <url>")
        sys.exit(1)

    html_path = sys.argv[1]
    url = sys.argv[2]

    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    result = extract_product(html, url)
    print(json.dumps(result, indent=2, ensure_ascii=False))
