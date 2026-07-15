#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import re
import sys
import tempfile
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
REPO_ROOT = SKILL_ROOT.parents[1]
WORKTREE_CLI_PATH = REPO_ROOT / "skills" / "taojin_v3_crawl_skill" / "scripts" / "worktree_cli.py"
PLAYWRIGHT_FETCH_PATH = REPO_ROOT / "skills" / "playwright-cli" / "scripts" / "fetch_html_with_fallback.py"


def _load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    return module


v3_cli = _load_module("taojin_v3_worktree_cli", WORKTREE_CLI_PATH)
playwright_fetch = _load_module("playwright_cli_fetch_html_with_fallback", PLAYWRIGHT_FETCH_PATH)


def _normalize_detection_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return normalized.lower()


def _http_get_with_meta(url: str, *, timeout_sec: int = 8) -> Tuple[str, Optional[int], str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            raw = resp.read()
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = raw.decode("utf-8", errors="ignore")
            return str(resp.geturl()), int(getattr(resp, "status", 200)), text
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("utf-8", errors="ignore")
        return str(exc.geturl()), int(exc.code), text
    except Exception:
        return url, None, ""


def _extract_canonical_like_url(html_text: str, base_url: str) -> str:
    patterns = (
        r'(?is)<link[^>]*rel=["\']canonical["\'][^>]*href=["\']([^"\']+)["\']',
        r'(?is)<meta[^>]*property=["\']og:url["\'][^>]*content=["\']([^"\']+)["\']',
    )
    for pattern in patterns:
        match = re.search(pattern, html_text or "")
        if match:
            return urllib.parse.urljoin(base_url, match.group(1).strip())
    return ""


def _normalize_identity_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url.strip())
    scheme = parsed.scheme.lower() if parsed.scheme else "https"
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/")
    query_pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    filtered = [
        (k, v)
        for k, v in query_pairs
        if k.lower() not in {
            "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "gclid", "fbclid"
        }
    ]
    new_query = urllib.parse.urlencode(filtered)
    return urllib.parse.urlunsplit((scheme, netloc, path, new_query, ""))


def _looks_deadlink_on_non_detail(
    requested_url: str,
    final_url: str,
    status_code: Optional[int],
    html_text: str,
) -> bool:
    final_lower = (final_url or requested_url or "").lower()
    lowered = (html_text or "").lower()
    title_match = re.search(r"(?is)<title[^>]*>(.*?)</title>", html_text or "")
    title = _normalize_detection_text(title_match.group(1)) if title_match else ""

    if "/sistema/404" in final_lower:
        return True
    if "productlinknotfound=" in final_lower:
        return True

    title_markers = (
        "error - vtex",
        "404",
        "404 not found",
        "page not found",
        "pagina nao encontrada",
        "pagina no encontrada",
    )
    if any(marker == title or marker in title for marker in title_markers):
        return True

    body_markers = (
        "productlinknotfound",
        "custom-error-page.vtex.com",
        "pagina nao encontrada",
        "pagina no encontrada",
        "desculpe, a pagina que voce esta tentando acessar esta indisponivel",
        "the page you are looking for is unavailable",
    )
    if any(marker in lowered for marker in body_markers):
        return True

    route_not_found_markers = (
        "render-route-store-not-found-product",
        "store-not-found#product",
        "store-not-found#product",
        "store-not-found-product",
    )
    if any(marker in lowered for marker in route_not_found_markers):
        return True

    if (status_code is not None and status_code >= 400) or any(
        marker in title
        for marker in ("error - vtex", "404", "not found", "nao encontrada", "indisponivel")
    ):
        return True

    if status_code is not None and status_code >= 400 and any(
        marker in lowered for marker in ("not found", "nao encontrada", "indisponivel", "unavailable", "404")
    ):
        return True

    return False


def _detail_signal_score(html_text: str) -> int:
    lowered = html_text.lower()
    score = 0
    regex_signals = (
        (r'(?is)<meta[^>]*property=["\']og:type["\'][^>]*content=["\']product["\']', 3),
        (r'(?is)<meta[^>]*property=["\']product:price:amount["\']', 2),
        (r'(?is)<meta[^>]*property=["\']product:availability["\']', 1),
        (r'(?is)<meta[^>]*property=["\']product:sku["\']', 2),
        (r'"@type"\s*:\s*"Product"', 2),
        (r"'@type'\s*:\s*'Product'", 2),
        (r'(?i)\bproductdescription\b', 3),
    )
    for pattern, weight in regex_signals:
        if re.search(pattern, html_text or ""):
            score += weight

    text_signals = (
        ("schema.org/product", 2),
        ("productdescription", 1),
        ("commercialoffer", 2),
        ("addtocartlink", 2),
        ("buy-button", 2),
        ("add-to-cart", 1),
    )
    for marker, weight in text_signals:
        if marker in lowered:
            score += weight
    return score


def _visible_option_signal_summary(html_text: str) -> Dict[str, Any]:
    lowered = (html_text or "").lower()
    return {
        "has_complex_sku_signal": False,
        "sku_option_signal_score": 0,
        "visible_option_hint_count": 0,
        "matched_option_signals": [],
    }


def _embedded_detail_link_count(html_text: str, base_uri: str, site_domain: str) -> int:
    hrefs = v3_cli.extract_links_from_html(html_text or "", base_uri)
    seen = set()
    for href in hrefs:
        try:
            parsed = urllib.parse.urlparse(href)
        except Exception:
            continue
        if not parsed.netloc.endswith(site_domain):
            continue
        if v3_cli._detail_url_score(href) < 0:
            continue
        seen.add(_normalize_identity_url(href))
    return len(seen)


def _extract_oracle_occ_product_urls(html_text: str, base_url: str, site_domain: str) -> List[str]:
    match = re.search(
        r'window\.state\s*=\s*JSON\.parse\(decodeURI\("(.*)"\)\)</script>',
        html_text or "",
    )
    if not match:
        return []
    try:
        state = json.loads(urllib.parse.unquote(match.group(1)))
    except Exception:
        return []

    products = state.get("catalogRepository", {}).get("products", {})
    if not isinstance(products, dict):
        return []

    ordered_ids: List[str] = []
    widgets = state.get("pageRepository", {}).get("widgets", {})
    if isinstance(widgets, dict):
        for widget in widgets.values():
            if not isinstance(widget, dict):
                continue
            raw_ids = widget.get("productIds")
            if not raw_ids:
                continue
            if isinstance(raw_ids, str):
                parts = [part.strip() for part in raw_ids.split(",")]
            elif isinstance(raw_ids, list):
                parts = [str(p).strip() for p in raw_ids if p]
            else:
                continue
            for pid in parts:
                if pid and pid not in ordered_ids:
                    ordered_ids.append(pid)

    urls: List[str] = []
    seen = set()

    def append_route(route_value: Any) -> None:
        if not route_value or not isinstance(route_value, str):
            return
        url = urllib.parse.urljoin(base_url, route_value)
        identity = _normalize_identity_url(url)
        if identity in seen:
            return
        seen.add(identity)
        urls.append(url)

    for product_id in ordered_ids:
        product = products.get(product_id)
        if isinstance(product, dict):
            append_route(product.get("route"))

    for product in products.values():
        if isinstance(product, dict):
            append_route(product.get("route"))
    return urls


def _dedupe_preserve_order(urls: Sequence[str]) -> List[str]:
    seen = set()
    output: List[str] = []
    for url in urls:
        identity = _normalize_identity_url(url)
        if not identity or identity in seen:
            continue
        seen.add(identity)
        output.append(url)
    return output


def _looks_like_numeric_id(value: str) -> bool:
    return bool(re.fullmatch(r"\d{3,}", value or ""))


LIST_ROOT_TOKENS = {"products", "collections", "shop", "store", "catalog", "category", "c"}


def _category_value_for_uri(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    segments = [segment for segment in parsed.path.split("/") if segment]
    if len(segments) >= 2 and segments[0].lower() in LIST_ROOT_TOKENS:
        return segments[1].lower()
    return ""


def _nav_list_url_score(url: str, site_domain: str) -> int:
    parsed = urllib.parse.urlsplit(url)
    host = (parsed.netloc or "").lower()
    allowed_hosts = {site_domain.lower()}
    if site_domain.startswith("www."):
        allowed_hosts.add(site_domain[4:].lower())
    else:
        allowed_hosts.add(f"www.{site_domain.lower()}")
    if host not in allowed_hosts:
        return -200
    lowered = parsed.path.lower()
    if not lowered or lowered == "/":
        return -200
    if lowered.startswith(("/_next/", "/static/", "/cdn-cgi/")):
        return -200
    if any(lowered.endswith(suffix) for suffix in (".css", ".js", ".json", ".svg", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".ico", ".pdf")):
        return -200
    if v3_cli._detail_url_score(url) >= 8:
        return -50
    score = 0
    for token, weight in (
        ("/products", 4),
        ("/collections", 4),
        ("/shop", 3),
        ("/store", 3),
        ("/catalog", 3),
        ("/category", 3),
        ("/c/", 2),
        ("/p/", 2),
        ("/snack", 2),
        ("/plate", 2),
    ):
        if token in lowered:
            score += weight
    if lowered.count("/") >= 2:
        score += 1
    return score


def _extract_navigation_category_urls(html_text: str, base_url: str, site_domain: str) -> List[str]:
    hrefs = v3_cli.extract_links_from_html(html_text or "", base_url)
    ranked: List[Tuple[int, int, str]] = []
    seen = set()
    for idx, href in enumerate(hrefs):
        normalized = _normalize_identity_url(href)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        score = _nav_list_url_score(href, site_domain)
        if score <= 0:
            continue
        ranked.append((score, -idx, href))
    ranked.sort(reverse=True)
    return [href for _, _, href in ranked[:24]]


def _score_to_bucket(score: int) -> int:
    return int(max(0, min(9, math.floor(score / 2))))


def _candidate_group_key(candidate: Dict[str, Any]) -> str:
    category = str(candidate.get("category") or "").strip()
    signature = str(candidate.get("template_signature") or "").strip()
    if category:
        return f"category::{category}"
    if signature:
        return f"signature::{signature}"
    return f"tplz:{candidate.get('identity') or candidate.get('requested_url') or ''}"


def _select_representative_candidates(
    candidates: Sequence[Dict[str, Any]], target_count: int
) -> List[Dict[str, Any]]:
    ordered = sorted(
        candidates,
        key=lambda item: (
            1 if item.get("verdict") == "detail" else 0,
            1 if item.get("has_complex_sku_signal") else 0,
            int(item.get("sku_option_signal_score") or 0),
            int(item.get("detail_score") or 0),
            -int(item.get("rank") or 0),
        ),
        reverse=True,
    )

    selected: List[Dict[str, Any]] = []
    selected_ids = set()
    selected_categories = set()
    selected_signatures = set()

    def try_add(candidate: Dict[str, Any]) -> bool:
        identity = str(candidate.get("identity") or "").strip()
        if not identity or identity in selected_ids or len(selected) >= target_count:
            return False
        selected.append(candidate)
        selected_ids.add(identity)
        category = str(candidate.get("category") or "").strip()
        signature = str(candidate.get("template_signature") or "").strip()
        if category:
            selected_categories.add(category)
        if signature:
            selected_signatures.add(signature)
        return True

    for candidate in ordered:
        if candidate.get("has_complex_sku_signal"):
            if try_add(candidate):
                break

    for candidate in ordered:
        category = str(candidate.get("category") or "").strip()
        if category and category not in selected_categories:
            try_add(candidate)

    for candidate in ordered:
        signature = str(candidate.get("template_signature") or "").strip()
        if signature and signature not in selected_signatures:
            try_add(candidate)

    for candidate in ordered:
        if len(selected) >= target_count:
            break
        try_add(candidate)

    return selected


def _candidate_verdict(
    url: str,
    *,
    enable_playwright: bool,
    enable_proxy: bool,
    tmp_dir: Path,
) -> Dict[str, Any]:
    final_url, status_code, html_text = _http_get_with_meta(url)
    used_fallback = False
    if not html_text and enable_playwright:
        fallback_html = playwright_fetch._fetch_text_with_fallback(
            url,
            enable_playwright=enable_playwright,
            enable_proxy=enable_proxy,
            tmp_dir=tmp_dir,
        )
        if fallback_html:
            html_text = fallback_html
            used_fallback = True

    canonical_like = _extract_canonical_like_url(html_text, final_url or url)
    identity = _normalize_identity_url(canonical_like or final_url or url)
    next_page_route = ""
    template_signature, category = "", _category_value_for_uri(canonical_like or final_url or url)

    detail_score = 0
    link_count = 0
    option_summary = _visible_option_signal_summary(html_text)

    if _looks_deadlink_on_non_detail(url, final_url, status_code, html_text):
        verdict = "deadlink"
    elif status_code in (401, 403) or "captcha" in (html_text or "").lower():
        verdict = "locked"
    else:
        verdict = "detail" if detail_score >= 5 else "non_detail"
        try:
            detail_score = _detail_signal_score(html_text)
            parsed_final = urllib.parse.urlparse(final_url or url)
            link_count = _embedded_detail_link_count(
                html_text,
                final_url or url,
                parsed_final.netloc or urllib.parse.urlparse(url).netloc,
            )
        except Exception:
            pass

    return {
        "identity": identity or _normalize_identity_url(url),
        "verdict": verdict,
        "template_signature": template_signature,
        "category": category,
        "next_page_route": next_page_route,
        "detail_score": detail_score,
        "has_complex_sku_signal": bool(option_summary.get("has_complex_sku_signal")),
        "sku_option_signal_score": int(option_summary.get("sku_option_signal_score") or 0),
        "visible_option_hint_count": int(option_summary.get("visible_option_hint_count") or 0),
        "matched_option_signals": list(option_summary.get("matched_option_signals") or []),
    }


def _finalize_seed_urls(
    ranked_candidates: Sequence[str],
    target_count: int,
    *,
    enable_playwright: bool,
    enable_proxy: bool,
    tmp_dir: Path,
    validation_cache: Dict[str, Dict[str, Any]],
) -> Tuple[List[str], Dict[str, Any]]:
    validated_candidates: List[Dict[str, Any]] = []
    known_categories = set()
    known_signatures = set()
    known_complex_seed_ids = set()

    candidate_limit = max(target_count * 48, 120)
    for index, url in enumerate(ranked_candidates[:candidate_limit], start=1):
        result = validation_cache.get(url)
        if result is None:
            result = _candidate_verdict(
                url,
                enable_playwright=enable_playwright,
                enable_proxy=enable_proxy,
                tmp_dir=tmp_dir / f"candidate_{index:03d}",
            )
            validation_cache[url] = result

        identity = result["identity"]
        verdict = result["verdict"]
        category = str(result.get("category") or "").strip()
        template_signature = str(result.get("template_signature") or "").strip()

        if category:
            known_categories.add(category)
        if template_signature:
            known_signatures.add(template_signature)
        if result.get("has_complex_sku_signal") and identity:
            known_complex_seed_ids.add(identity)

        if verdict in {"deadlink", "non_detail"}:
            continue

        result_with_rank = dict(result)
        result_with_rank["requested_url"] = url
        result_with_rank["rank"] = index
        result_with_rank["score_bucket"] = _score_to_bucket(int(result.get("detail_score") or 0))
        validated_candidates.append(result_with_rank)

    selected = _select_representative_candidates(validated_candidates, target_count)
    seeds = [str(item.get("requested_url") or "") for item in selected if str(item.get("requested_url") or "").strip()]

    selected_categories = sorted(
        {str(item.get("category") or "").strip() for item in selected if str(item.get("category") or "").strip()}
    )
    selected_patterns = sorted(
        {str(item.get("template_signature") or "").strip() for item in selected if str(item.get("template_signature") or "").strip()}
    )
    known_unselected_categories = sorted(known_categories - set(selected_categories))

    selected_complex_seed_count = sum(1 for item in selected if item.get("has_complex_sku_signal"))
    complex_sku_status = "pass" if not known_complex_seed_ids or selected_complex_seed_count >= 1 else "fail"
    complex_sku_reason = ""
    if complex_sku_status == "fail":
        complex_sku_reason = "已识别到复杂 SKU / option / swatch 候选 PDP，但 seed 中未包含复杂 SKU PDP"

    diversity_status = "pass"
    diversity_reason = ""
    if len(known_categories) > 1 and len(selected_categories) <= 1:
        diversity_status = "fail"
        diversity_reason = "存在多个 category，但 seed 未覆盖多个 category"
    elif len(known_signatures) > 1 and len(selected_patterns) <= 1:
        diversity_status = "warn"
        diversity_reason = "存在多个 PDP template signature，但 seed 未覆盖"
    elif len(selected_categories) < min(target_count, len(known_categories)) and len(known_categories) > len(selected_categories):
        diversity_reason = "部分 category 未被选中"

    if complex_sku_status == "fail":
        diversity_status = "fail"
        diversity_reason = f"{diversity_reason}; {complex_sku_reason}".strip("; ")
    elif not diversity_reason:
        diversity_reason = complex_sku_reason

    report: Dict[str, Any] = {
        "candidate_limit": candidate_limit,
        "validated_candidate_count": len(validated_candidates),
        "discovered_patterns": sorted(known_signatures),
        "selected_patterns": selected_patterns,
        "selected_categories": selected_categories,
        "known_but_unselected_categories": known_unselected_categories,
        "diversity_status": diversity_status,
        "diversity_reason": diversity_reason,
        "complex_sku_candidate_count": len(known_complex_seed_ids),
        "selected_complex_sku_count": selected_complex_seed_count,
        "complex_sku_status": complex_sku_status,
        "complex_sku_reason": complex_sku_reason,
        "selected_seed_metadata": [
            {
                "url": item.get("requested_url"),
                "identity": item.get("identity"),
                "verdict": item.get("verdict"),
                "template_signature": item.get("template_signature"),
                "category": item.get("category"),
                "next_page_route": item.get("next_page_route"),
                "detail_score": item.get("detail_score"),
                "has_complex_sku_signal": item.get("has_complex_sku_signal"),
                "sku_option_signal_score": item.get("sku_option_signal_score"),
                "visible_option_hint_count": item.get("visible_option_hint_count"),
                "matched_option_signals": item.get("matched_option_signals"),
            }
            for item in selected
        ],
    }
    return (seeds[:target_count], report)


def _write_site_report(report_path: Path, payload: Dict[str, Any]) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _discover_seed_urls_for_site(
    site_domain: str,
    target_count: int,
    *,
    enable_playwright: bool,
    enable_proxy: bool,
    tmp_root: Path,
) -> Dict[str, Any]:
    candidate_hosts = {site_domain}
    if not site_domain.startswith("www."):
        candidate_hosts.add(f"www.{site_domain}")

    url_candidates: List[str] = []
    attempted_paths: List[str] = []

    tmp_dir = tmp_root / site_domain
    tmp_dir.mkdir(parents=True, exist_ok=True)

    validation_cache: Dict[str, Dict[str, Any]] = {}

    # 1. Homepage
    for host in candidate_hosts:
        homepage_url = f"https://{host}/"
        attempted_paths.append(homepage_url)
        base = homepage_url
        try:
            homepage_html = playwright_fetch._fetch_text_with_fallback(
                homepage_url,
                enable_playwright=enable_playwright,
                enable_proxy=enable_proxy,
                tmp_dir=tmp_dir,
            )
            occ_product_urls = _extract_oracle_occ_product_urls(homepage_html, base, site_domain)
            hrefs = v3_cli.extract_links_from_html(homepage_html, base)
            nav_category_pages = _extract_navigation_category_urls(homepage_html, base, site_domain)
            url_candidates.extend(
                _dedupe_preserve_order(
                    occ_product_urls + hrefs + nav_category_pages
                )
            )
        except Exception:
            pass

    # 2. robots.txt
    for host in candidate_hosts:
        robots_url = f"https://{host}/robots.txt"
        attempted_paths.append(robots_url)
        try:
            robots_text = playwright_fetch._fetch_text_with_fallback(
                robots_url,
                enable_playwright=enable_playwright,
                enable_proxy=enable_proxy,
                tmp_dir=tmp_dir,
            )
            sitemap_candidates = v3_cli._extract_robots_sitemap_urls(robots_text)
        except Exception:
            continue

    # 3. sitemap.xml
    sitemap_candidates: List[str] = []
    for host in candidate_hosts:
        sitemap_candidates.append(f"https://{host}/sitemap.xml")

    fetched = set()
    for sitemap_url in sitemap_candidates[:8]:
        if sitemap_url in fetched:
            continue
        attempted_paths.append(sitemap_url)
        try:
            xml_text = playwright_fetch._fetch_text_with_fallback(
                sitemap_url,
                enable_playwright=enable_playwright,
                enable_proxy=enable_proxy,
                tmp_dir=tmp_dir,
            )
            locs = v3_cli._parse_sitemap_locs(xml_text)
            fetched.add(sitemap_url)
            url_candidates.extend(locs)

            child_sitemaps = [u for u in locs if u.lower().endswith(".xml")]
            child_sitemaps.sort(
                key=lambda child: (
                    1 if any(token in child.lower() for token in ("product", "products", "catalog", "collection", "category")) else 0,
                    len(child),
                ),
                reverse=True,
            )
            for child in child_sitemaps[:24]:
                if child in fetched:
                    continue
                fetched.add(child)
                attempted_paths.append(child)
                child_xml = playwright_fetch._fetch_text_with_fallback(
                    child,
                    enable_playwright=enable_playwright,
                    enable_proxy=enable_proxy,
                    tmp_dir=tmp_dir,
                )
                url_candidates.extend(v3_cli._parse_sitemap_locs(child_xml))
        except Exception:
            continue

    # 4. Homepage rescan
    attempted_paths.append("homepage-rescan")
    try:
        homepage_html = playwright_fetch._fetch_text_with_fallback(
            f"https://{site_domain}/",
            enable_playwright=enable_playwright,
            enable_proxy=enable_proxy,
            tmp_dir=tmp_dir,
        )
        occ_product_urls = _extract_oracle_occ_product_urls(homepage_html, base, site_domain)
        hrefs = v3_cli.extract_links_from_html(homepage_html, base)
        nav_category_pages = _dedupe_preserve_order(
            _extract_navigation_category_urls(homepage_html, base, site_domain)
        )
        url_candidates.extend(occ_product_urls + hrefs + nav_category_pages)
    except Exception:
        pass

    # Rank candidates
    ranked = _dedupe_preserve_order(
        v3_cli._pick_seed_urls(url_candidates, max(40, 240), site_domain) + url_candidates
    )

    seeds, finalize_report = _finalize_seed_urls(
        ranked,
        target_count,
        enable_playwright=enable_playwright,
        enable_proxy=enable_proxy,
        tmp_dir=tmp_dir,
        validation_cache=validation_cache,
    )

    raw_known_categories: List[str] = []
    for category, _ in [
        (_category_value_for_uri(url), url)
        for url in ranked[: max(target_count * 50, 300)]
    ]:
        if category:
            raw_known_categories.append(category)

    raw_known_patterns: List[str] = []
    for url in ranked[: max(target_count * 50, 300)]:
        signature, _ = ("", url)
        if signature and v3_cli._normalize_identity_url(url) or v3_cli._detail_url_score(url) >= 8:
            raw_known_patterns.append(signature)

    finalize_report["selected_categories"] = list(finalize_report.get("selected_categories") or [])
    known_unselected = sorted(set(raw_known_categories) - set(finalize_report.get("selected_categories") or []))
    if raw_known_categories and not finalize_report.get("selected_categories"):
        finalize_report["selected_categories"] = raw_known_categories[: min(5, len(raw_known_categories))]

    finalize_report["discovered_patterns"] = sorted(
        set(list(finalize_report.get("discovered_patterns") or [])) | set(raw_known_patterns)
    )
    finalize_report["known_but_unselected_categories"] = known_unselected
    if len(raw_known_categories) > 1 and len(list(finalize_report.get("selected_categories") or [])) <= 2:
        finalize_report["diversity_status"] = "fail"
        finalize_report["diversity_reason"] = "存在多个 category，但 seed 未覆盖多个 category"

    finalize_report["attempted_paths"] = attempted_paths
    finalize_report["site_domain"] = site_domain
    finalize_report["status"] = "ok" if len(seeds) >= target_count else "shortfall"
    finalize_report["count"] = len(seeds)
    finalize_report["shortfall_reason"] = (
        f"only {len(seeds)}/{target_count} valid SPU URLs discovered" if len(seeds) < target_count else ""
    )

    return {"spu_urls": seeds, "report": finalize_report}


def _write_dataset_template(path: Path, entries: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serializable_entries: List[Dict[str, Any]] = []
    for entry in entries:
        item = {"spu_urls": list(entry.get("spu_urls") or [])}
        task_type = entry.get("type")
        if task_type:
            item["type"] = task_type
        serializable_entries.append(item)
    path.write_text(json.dumps(serializable_entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _normalize_existing_entries(raw: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw, list):
        raise ValueError("existing dataset file is not a JSON array")
    normalized: List[Dict[str, Any]] = []
    for idx, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"item #{idx} is not an object")
        spu_urls = item.get("spu_urls")
        if not isinstance(spu_urls, list) or not spu_urls:
            raise ValueError(f"item #{idx}: spu_urls must be a non-empty array")
        urls = [str(value).strip() for value in spu_urls if str(value).strip()]
        site_domain_raw = str(item.get("site_domain", "")).strip()
        site_domain = v3_cli._normalize_site_domain(site_domain_raw) if site_domain_raw else ""
        if not site_domain:
            site_domain = v3_cli._derive_site_domain_from_urls(urls, idx)
        else:
            v3_cli._validate_site_domain(site_domain, idx)
        normalized_item: Dict[str, Any] = {"site_domain": site_domain, "spu_urls": urls}
        task_type = str(item.get("type", "")).strip()
        if task_type:
            normalized_item["type"] = task_type
        normalized.append(normalized_item)
    return normalized


def _merge_entries(existing: List[Dict[str, Any]], incoming: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized_existing = _normalize_existing_entries(existing)
    site_map = {str(item["site_domain"]).strip(): item for item in normalized_existing}
    ordered_sites: List[str] = []
    for item in normalized_existing:
        ordered_sites.append(str(item["site_domain"]).strip())
    for item in incoming:
        site = item["site_domain"]
        site_map[site] = item
        if site not in ordered_sites:
            ordered_sites.append(site)
    return [site_map[site] for site in ordered_sites]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Discover live PDP/SPU seed urls for one or more sites")
    parser.add_argument(
        "--dataset-json",
        default=str(REPO_ROOT / "input" / "dataset_url_template.json"),
        help="Target dataset json path (default: input/dataset_url_template.json)",
    )
    parser.add_argument(
        "--main-repo",
        default=str(REPO_ROOT),
        help="Main repo root used for git commit (default: current repository root)",
    )
    parser.add_argument(
        "--site-domain",
        action="append",
        help="Target site domain (can also pass a homepage url; it will be normalized to host).",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=5,
        help="Target count per site (default: 5)",
    )
    parser.add_argument(
        "--site-count",
        action="append",
        help="Per-site override, format: site_domain=N (repeatable)",
    )
    parser.add_argument(
        "--allow-shortfall",
        action="store_true",
        help="Allow fewer than target urls after exhausting discovery paths",
    )
    parser.add_argument(
        "--no-playwright",
        action="store_true",
        help="Disable the normal Playwright fallback from skills/playwright-cli.",
    )
    parser.add_argument(
        "--no-proxy",
        action="store_true",
        help="Disable the proxy Playwright fallback from skills/playwright-cli.",
    )
    parser.add_argument(
        "--tmp-root",
        default="",
        help="Temporary directory root for discovery artifacts (default: system tempdir/site_seed_discovery)",
    )
    parser.add_argument(
        "--replace-all",
        action="store_true",
        help="Replace the whole dataset with discovered entries (recommended for current batch)",
    )
    parser.add_argument(
        "--git-commit",
        action="store_true",
        help="Commit the dataset file after writing",
    )
    parser.add_argument(
        "--commit-message",
        default="Update dataset_url_template.json seeds",
        help="Commit message used with --git-commit",
    )
    return parser


def main(argv: Sequence[str] = ()) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    main_repo = v3_cli._safe_resolve(args.main_repo)
    dataset_json = v3_cli._safe_resolve(args.dataset_json)
    if args.git_commit:
        v3_cli._ensure_git_repo(main_repo)

    sites: List[str] = []
    for raw in (args.site_domain or []):
        token = v3_cli._normalize_site_token(raw)
        if token:
            sites.append(token)
    sites = list(dict.fromkeys(sites))
    if not sites:
        raise ValueError("discover_seed_urls requires at least one --site-domain")

    per_site_count: Dict[str, int] = {}
    for raw in (args.site_count or []):
        text = str(raw).strip()
        if not text or "=" not in text:
            raise ValueError("Invalid --site-count entry, expected site_domain=N")
        k, v = text.split("=", 1)
        k = v3_cli._normalize_site_token(k)
        try:
            n = int(v.strip())
        except ValueError as exc:
            raise ValueError(f"Invalid --site-count '{raw}', N must be int") from exc
        if n <= 0:
            raise ValueError(f"Invalid --site-count '{raw}', N must be > 0")
        per_site_count[k] = n

    default_count = int(args.count)
    if default_count <= 0:
        raise ValueError("--count must be > 0")

    tmp_root = (
        Path(args.tmp_root).expanduser().resolve() if args.tmp_root
        else Path(tempfile.gettempdir()) / "site_seed_discovery"
    )
    tmp_root.mkdir(parents=True, exist_ok=True)

    entries: List[Dict[str, Any]] = []
    site_reports: List[Dict[str, Any]] = []

    for site in sites:
        target = per_site_count.get(site, default_count)
        discovery_result = _discover_seed_urls_for_site(
            site,
            target,
            enable_playwright=not args.no_playwright,
            enable_proxy=not args.no_proxy,
            tmp_root=tmp_root,
        )
        seeds = list(discovery_result.get("spu_urls") or [])
        report = dict(discovery_result.get("report") or {})
        if len(seeds) < target and not args.allow_shortfall:
            raise ValueError(
                f"site '{site}' only discovered {len(seeds)}/{target} live/provisional detail urls after live validation. "
                f"Use --allow-shortfall only when the site truly has fewer valid SPU urls."
            )
        if report.get("diversity_status") == "fail":
            raise ValueError(
                f"site '{site}' failed diversity review: {report.get('diversity_reason') or 'representative template coverage missing'}; "
                f"report={report.get('report_path')}"
            )
        entries.append({"site_domain": site, "spu_urls": seeds})
        site_reports.append(report)

    if args.replace_all or not dataset_json.exists():
        final_entries = entries
    else:
        existing = v3_cli._load_json(dataset_json)
        if not isinstance(existing, list):
            raise ValueError(f"existing dataset file is not a JSON array: {dataset_json}")
        final_entries = _merge_entries(existing, entries)

    _write_dataset_template(dataset_json, final_entries)
    print(f"[written] {dataset_json}")
    print(json.dumps(final_entries, ensure_ascii=False, indent=2))
    if site_reports:
        print("[seed-reports]")
        print(json.dumps(site_reports, ensure_ascii=False, indent=2))

    if args.git_commit:
        v3_cli._run_git_simple(main_repo, ["add", str(dataset_json)])
        v3_cli._run_git_simple(main_repo, ["commit", "-m", args.commit_message])
        print(f"[committed] {args.commit_message}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
