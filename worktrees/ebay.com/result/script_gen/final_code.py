#!/usr/bin/env python3
"""
eBay Product Information Extractor (ebay.com)
Final code - self-contained, no external file dependencies.

Stage3 final embedded code for taojin_v3_crawl_skill.
"""

import re
import json
import sys
from typing import Dict, List, Optional, Any

try:
    import requests
except ImportError:
    requests = None

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None


def _strip_html(text: str) -> str:
    """Remove HTML tags and normalize whitespace."""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _parse_price(price_str: Any) -> Optional[float]:
    """Parse price value to float."""
    if price_str is None:
        return None
    if isinstance(price_str, (int, float)):
        return float(price_str)
    try:
        cleaned = re.sub(r"[^0-9.]", "", str(price_str))
        return float(cleaned) if cleaned else None
    except (ValueError, TypeError):
        return None


def _fetch_html(url: str, timeout: int = 30) -> str:
    """Fetch HTML from URL with proper headers and cookie handling."""
    if requests is None:
        raise ImportError("requests library is required for fetching URLs")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    }

    session = requests.Session()

    # First visit homepage to get cookies
    session.get("https://www.ebay.com/", headers=headers, timeout=timeout, allow_redirects=True)

    # Then visit the product page
    response = session.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    response.raise_for_status()
    return response.text


def extract_product(html: str, url: str) -> Dict[str, Any]:
    """
    Extract product SPU/SKU information from eBay product page.

    Args:
        html: HTML content of the product detail page.
        url: URL of the product page.

    Returns:
        Dictionary with product data following the target schema.
    """
    script_res: Dict[str, Any] = {
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
    }

    # === Title ===
    title_match = re.search(r'class="vim x-item-title"[^>]*>([\s\S]*?)</div>', html)
    if title_match:
        script_res["source_item_name"] = _strip_html(title_match.group(1))

    # === Price ===
    price_match = re.search(
        r'class="vim x-price-section[^"]*"[^>]*>([\s\S]*?)</div>\s*</div>',
        html,
    )
    if price_match:
        price_text = _strip_html(price_match.group(1))
        us_price = re.search(r"US\s+\$([\d,]+\.?\d*)", price_text)
        if us_price:
            script_res["source_activity_price"] = _parse_price(us_price.group(1))
            script_res["source_price_currency"] = "USD"

    # === Images ===
    img_urls: set = set()
    img_regex = re.compile(r"https?://i\.ebayimg\.com/[^\"'\s<>)]+", re.IGNORECASE)
    for match in img_regex.finditer(html):
        img_url = match.group(0).rstrip(".")
        if "sprite" not in img_url and "icon" not in img_url:
            if any(
                size in img_url
                for size in ["s-l1600", "s-l400", "/images/g/"]
            ):
                img_urls.add(img_url)
    script_res["source_pics"] = list(img_urls)[:10]

    # === Props (Item specifics) ===
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
                    script_res["props"][dt] = dd

    # === Description ===
    desc_start = html.find("Item description from the seller")
    if desc_start > 0:
        desc_section = html[desc_start : desc_start + 8000]
        desc_text = _strip_html(desc_section)
        sentences = re.split(r"(?<=[.!?])\s+", desc_text)
        script_res["descriptions"] = [
            s.strip() for s in sentences if len(s.strip()) > 30
        ][:10]

    # === Review Stats ===
    ratings_start = html.find("Product ratings and reviews")
    if ratings_start > 0:
        ratings_section = html[ratings_start : ratings_start + 5000]
        ratings_text = _strip_html(ratings_section)
        score_match = re.search(
            r"([\d.]+)\s+out\s+of\s+5", ratings_text, re.IGNORECASE
        )
        if score_match:
            script_res["source_score"] = float(score_match.group(1))
        review_match = re.search(
            r"([\d,]+)\s+reviews?", ratings_text, re.IGNORECASE
        )
        if review_match:
            script_res["source_cmms"] = int(
                review_match.group(1).replace(",", "")
            )

    # === SKU ===
    sku: Dict[str, Any] = {
        "source_pics": (
            script_res["source_pics"][:1]
            if script_res["source_pics"]
            else []
        ),
        "status": 1,
        "source_activity_price": script_res["source_activity_price"],
        "source_origin_price": script_res["source_origin_price"],
        "source_price_currency": script_res["source_price_currency"],
        "sku_props": {},
    }

    item_id_match = re.search(r"itemId[\"'':\s]+(\d+)", html)
    if item_id_match:
        sku["sku_props"]["Item ID"] = item_id_match.group(1)

    script_res["skus"] = [sku]
    script_res["default_sku_index"] = 0
    script_res["effective_price"] = (
        script_res["source_activity_price"]
        or script_res["source_origin_price"]
    )

    return script_res


def main() -> None:
    """Main entry point for CLI usage."""
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python final_code.py <url>          # Fetch and extract from URL")
        print("  python final_code.py <html_file> <url>  # Extract from local HTML file")
        sys.exit(1)

    if len(sys.argv) == 2:
        url = sys.argv[1]
        html = _fetch_html(url)
    else:
        html_path = sys.argv[1]
        url = sys.argv[2]
        with open(html_path, "r", encoding="utf-8") as f:
            html = f.read()

    result = extract_product(html, url)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
