"""SKU/SPU ID generation utilities.

Provides functions to generate deterministic SKU and SPU identifiers
from URLs and SKU properties, with support for language/region prefix
normalization across international e-commerce sites.
"""

from __future__ import annotations

import hashlib
import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse, urlunparse


SUPPORTED_LANGS: List[str] = [
    "en", "fr", "de", "es", "pt", "it", "nl", "ru", "ja", "ko", "zh",
]

SUPPORTED_REGIONS: List[str] = [
    "us", "ca", "uk", "au", "de", "fr", "es", "it", "nl", "be", "ch",
    "jp", "kr", "cn", "br", "mx", "in", "sg", "hk",
]


def _md5_hex(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def remove_url_lang_region(url: str) -> str:
    """Remove language/region prefixes from the URL path.

    Handles patterns like:
      - /en-us/product/...
      - /fr/ca/product/...
      - /de-de/p/...
      - /ja/jp/item/...
    """
    if not url:
        return url
    parsed = urlparse(url)
    path = parsed.path or "/"
    parts = [p for p in path.split("/") if p]
    if not parts:
        return url

    def _is_lang(s: str) -> bool:
        return s.lower() in SUPPORTED_LANGS

    def _is_region(s: str) -> bool:
        return s.lower() in SUPPORTED_REGIONS

    def _is_lang_region(s: str) -> bool:
        if "-" in s:
            left, right = s.split("-", 1)
            return _is_lang(left) and _is_region(right)
        if "_" in s:
            left, right = s.split("_", 1)
            return _is_lang(left) and _is_region(right)
        return False

    idx = 0
    if idx < len(parts) and (_is_lang(parts[idx]) or _is_lang_region(parts[idx])):
        idx += 1
    if idx < len(parts) and _is_region(parts[idx]):
        idx += 1

    if idx > 0:
        new_path = "/" + "/".join(parts[idx:])
        if path.endswith("/") and not new_path.endswith("/") and len(parts[idx:]) > 0:
            new_path += "/"
        parsed = parsed._replace(path=new_path)
    return urlunparse(parsed)


def get_source_spu_id(url: str, *, ignore_lang_region: bool = True) -> str:
    """Generate a deterministic SPU ID from the product URL.

    Args:
        url: The product detail page URL.
        ignore_lang_region: If True, strip language/region prefixes first.

    Returns:
        MD5 hex string representing the SPU.
    """
    if not url:
        return ""
    normalized = url.strip()
    if ignore_lang_region:
        normalized = remove_url_lang_region(normalized)
    return _md5_hex(normalized)


def get_source_sku_id(
    url: str,
    sku_props: Optional[Dict[str, str]] = None,
    *,
    ignore_lang_region: bool = True,
) -> str:
    """Generate a deterministic SKU ID from URL and SKU properties.

    Args:
        url: The product detail page URL.
        sku_props: Dictionary of SKU variant properties (e.g. color, size).
        ignore_lang_region: If True, strip language/region prefixes first.

    Returns:
        MD5 hex string representing the SKU.
    """
    if not url:
        return ""
    normalized_url = url.strip()
    if ignore_lang_region:
        normalized_url = remove_url_lang_region(normalized_url)

    if not sku_props:
        return _md5_hex(normalized_url)

    sorted_items = sorted(sku_props.items(), key=lambda kv: kv[0].lower())
    prop_parts = [f"{k}={v}" for k, v in sorted_items if v is not None]
    prop_str = "&".join(prop_parts)
    combined = f"{normalized_url}#{prop_str}"
    return _md5_hex(combined)


class LangRegionIgnoreIDGenerator:
    """ID generator that normalizes away language/region URL prefixes.

    This class provides a reusable interface for generating SKU/SPU IDs
    with consistent language/region handling.
    """

    def __init__(self, *, ignore_lang_region: bool = True) -> None:
        self._ignore_lang_region = ignore_lang_region

    @property
    def ignore_lang_region(self) -> bool:
        return self._ignore_lang_region

    def normalize_url(self, url: str) -> str:
        if self._ignore_lang_region:
            return remove_url_lang_region(url)
        return url

    def spu_id(self, url: str) -> str:
        return get_source_spu_id(url, ignore_lang_region=self._ignore_lang_region)

    def sku_id(self, url: str, sku_props: Optional[Dict[str, str]] = None) -> str:
        return get_source_sku_id(url, sku_props, ignore_lang_region=self._ignore_lang_region)

    def pair(self, url: str, sku_props: Optional[Dict[str, str]] = None) -> Tuple[str, str]:
        return self.spu_id(url), self.sku_id(url, sku_props)


if __name__ == "__main__":
    import sys
    import json

    if len(sys.argv) < 2:
        print("Usage: get_sku_id_spu_id.py <url> [sku_props_json]")
        sys.exit(1)

    url_arg = sys.argv[1]
    sku_props_arg = json.loads(sys.argv[2]) if len(sys.argv) > 2 else None

    gen = LangRegionIgnoreIDGenerator()
    spu = gen.spu_id(url_arg)
    sku = gen.sku_id(url_arg, sku_props_arg)

    print(json.dumps({
        "url": url_arg,
        "normalized_url": gen.normalize_url(url_arg),
        "source_spu_id": spu,
        "source_sku_id": sku,
    }, indent=2, ensure_ascii=False))
