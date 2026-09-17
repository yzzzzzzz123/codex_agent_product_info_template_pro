"""Deterministic browser helper for the UGREEN Top Sales Codex skill.

All page data stays in memory.  The browser opens every product-detail URL and
the caller receives structured records; this module never writes HTML, JSON,
screenshots, manifests, or other crawl artefacts.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Iterator, Sequence
from urllib.parse import unquote, urlsplit

from playwright.async_api import BrowserContext, Page, async_playwright


SHOP_ID = "64922227"
STORE_URL_TEMPLATE = "https://shopee.ph/ugreen.ph?page={page}&sortBy=sales&tab=0"
STORE_URL = STORE_URL_TEMPLATE.format(page=0)
DEFAULT_CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
DEFAULT_CHROME_DATA = Path.home() / "Library/Application Support/Google/Chrome"
IDENTITY_PATTERNS = (
    re.compile(r"(?:-i\.|/i\.)(\d+)\.(\d+)(?:/)?$", re.I),
    re.compile(r"/product/(\d+)/(\d+)(?:/)?$", re.I),
)


class ScrapeError(RuntimeError):
    """Raised when a page cannot be proven to belong to the requested scope."""


@dataclass(slots=True)
class BrowserConfig:
    """Runtime controls.  Defaults reproduce the successful browser route."""

    headless: bool = False
    detail_workers: int = 4
    navigation_timeout_ms: int = 120_000
    page_ready_timeout_ms: int = 35_000
    retries: int = 3
    chrome_executable: Path = DEFAULT_CHROME

    def validate(self) -> None:
        if self.detail_workers < 1:
            raise ValueError("detail_workers must be at least 1")
        if self.navigation_timeout_ms < 1 or self.page_ready_timeout_ms < 1:
            raise ValueError("browser timeouts must be positive")
        if self.retries < 1:
            raise ValueError("retries must be at least 1")
        if not self.chrome_executable.is_file():
            raise FileNotFoundError(f"Chrome executable not found: {self.chrome_executable}")


@dataclass(slots=True)
class ProductCard:
    source_page: int
    source_position: int
    shop_id: str
    item_id: str
    title: str
    product_url: str
    price_php: int | float
    monthly_sales_display: str | None
    monthly_sales_text: str | None
    monthly_sales_count_lower_bound: int | None
    monthly_sales_observation: str


@dataclass(slots=True)
class SkuRecord:
    model_id: str
    sku_props: dict[str, str]
    sku_image_url: str | None


@dataclass(slots=True)
class ProductRecord:
    global_rank: int
    source_page: int
    source_position: int
    shop_id: str
    item_id: str
    title: str
    product_url: str
    price_php: int | float
    monthly_sales_text: str | None
    monthly_sales_count_lower_bound: int | None
    monthly_sales_observation: str
    skus: list[SkuRecord]
    main_image_url: str
    secondary_image_urls: list[str]


@dataclass(slots=True)
class ScrapeAudit:
    list_page_count: int
    list_input_product_occurrences: int
    list_duplicate_occurrence_count: int
    listed_product_count: int
    detail_success_count: int
    detail_failure_count: int
    products_without_monthly_sales_display: int


@dataclass(slots=True)
class ScrapeResult:
    store_url: str
    captured_at: datetime
    products: list[ProductRecord]
    audit: ScrapeAudit


Progress = Callable[[str], None]


LIST_PAGE_SCRIPT = r"""
(options) => {
  const clean = (value) => String(value || '').replace(/\s+/g, ' ').trim();
  const identityFromUrl = (raw) => {
    try {
      const url = new URL(String(raw), location.href);
      const path = decodeURIComponent(url.pathname);
      let match = path.match(/(?:-i\.|\/i\.)(\d+)\.(\d+)(?:\/)?$/i);
      if (!match) match = path.match(/\/product\/(\d+)\/(\d+)(?:\/)?$/i);
      return match ? {shop_id: match[1], item_id: match[2]} : null;
    } catch (_) {
      return null;
    }
  };
  const visible = clean(document.body ? document.body.innerText : '');
  const challengeMarkers = [
    'Verify to Continue', 'Page Unavailable', 'Please Try Again Later',
    'Please log in and try again', 'One More Step', 'Security Check'
  ];
  const lowerUrl = location.href.toLowerCase();
  const challenge =
    /\/(?:verify|captcha)(?:\/|[?#]|$)/.test(lowerUrl) ||
    Boolean(document.querySelector('[class*="captcha"], [id*="captcha"], iframe[src*="captcha"]')) ||
    challengeMarkers.some((marker) => visible.toLowerCase().includes(marker.toLowerCase()));

  const uniqueText = (selector) => Array.from(new Set(
    Array.from(document.querySelectorAll(selector)).map((node) => clean(node.textContent)).filter(Boolean)
  ));
  const currentValues = uniqueText('.shopee-mini-page-controller__current');
  const totalValues = uniqueText('.shopee-mini-page-controller__total');
  const viewCount = document.querySelectorAll('.shop-search-result-view').length;
  const anchors = Array.from(document.querySelectorAll('.shop-search-result-view a.contents'));
  const errors = [];
  const cards = [];
  const seen = new Set();
  const monthlyPattern = /^((?:\d+(?:\.\d+)?[KM]\+?)|(?:\d[\d,]*))\s+Sold\/Month$/i;
  const pricePattern = /^\d[\d,]*(?:\.\d+)?$/;

  for (let anchorIndex = 0; anchorIndex < anchors.length; anchorIndex += 1) {
    const anchor = anchors[anchorIndex];
    const href = anchor.href || anchor.getAttribute('href') || '';
    const identity = identityFromUrl(href);
    if (!identity) {
      errors.push(`unrecognised product URL in card ${anchorIndex + 1}`);
      continue;
    }
    if (identity.shop_id !== options.expected_shop_id) {
      errors.push(`unexpected shop id ${identity.shop_id} in card ${anchorIndex + 1}`);
      continue;
    }
    const key = identity.shop_id + ':' + identity.item_id;
    if (seen.has(key)) {
      errors.push(`duplicate product identity ${key} in one page`);
      continue;
    }
    seen.add(key);

    let title = null;
    for (const image of anchor.querySelectorAll('img[alt]')) {
      const alt = clean(image.getAttribute('alt'));
      if (!alt || ['custom-overlay', 'flag-label', 'rating-star'].includes(alt.toLowerCase())) continue;
      title = alt;
      break;
    }

    const priceValues = Array.from(anchor.querySelectorAll('span'))
      .filter((node) => node.classList.contains('truncate') &&
        node.classList.contains('text-base/5') && node.classList.contains('font-medium'))
      .map((node) => clean(node.textContent))
      .filter((value) => pricePattern.test(value));

    const monthlyMatches = [];
    for (const node of anchor.querySelectorAll('*')) {
      const ownText = clean(Array.from(node.childNodes)
        .filter((child) => child.nodeType === Node.TEXT_NODE)
        .map((child) => child.nodeValue || '').join(' '));
      const match = ownText.match(monthlyPattern);
      if (match && !monthlyMatches.some((row) => row.text === ownText)) {
        monthlyMatches.push({display: match[1], text: ownText});
      }
    }

    if (!title) errors.push(`missing title for item ${identity.item_id}`);
    if (priceValues.length !== 1) {
      errors.push(`expected one price for item ${identity.item_id}, found ${priceValues.length}`);
    }
    if (monthlyMatches.length > 1) {
      errors.push(`conflicting monthly sales for item ${identity.item_id}`);
    }
    if (!title || priceValues.length !== 1 || monthlyMatches.length > 1) continue;

    const monthly = monthlyMatches.length === 1 ? monthlyMatches[0] : null;
    cards.push({
      shop_id: identity.shop_id,
      item_id: identity.item_id,
      title,
      product_url: href,
      price_text: priceValues[0],
      monthly_sales_display: monthly ? monthly.display : null,
      monthly_sales_text: monthly ? monthly.text : null,
    });
  }

  const nextNode = document.querySelector('link[rel~="next"]');
  const nextButtons = Array.from(
    document.querySelectorAll('button.shopee-mini-page-controller__next-btn')
  );
  const nextButton = nextButtons.length === 1 ? nextButtons[0] : null;
  return {
    challenge,
    final_url: location.href,
    title: document.title,
    current_values: currentValues,
    total_values: totalValues,
    result_view_count: viewCount,
    scoped_anchor_count: anchors.length,
    next_url: nextNode ? nextNode.href : null,
    next_button_count: nextButtons.length,
    next_disabled: nextButton ? (
      nextButton.disabled || nextButton.hasAttribute('disabled') ||
      nextButton.classList.contains('disabled')
    ) : null,
    stealth_probe: {
      webdriver_is_undefined: navigator.webdriver === undefined,
      user_agent: navigator.userAgent,
      language: navigator.language,
      languages: Array.from(navigator.languages || []),
      platform: navigator.platform,
      vendor: navigator.vendor,
      plugin_count: navigator.plugins ? navigator.plugins.length : null,
      hardware_concurrency: navigator.hardwareConcurrency,
      device_memory: navigator.deviceMemory === undefined ? null : navigator.deviceMemory,
      chrome_runtime_present: Boolean(window.chrome && window.chrome.runtime),
      time_zone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      screen_width: window.screen.width,
      screen_height: window.screen.height,
    },
    errors,
    cards,
  };
}
"""


DETAIL_PAGE_SCRIPT = r"""
(options) => {
  const textId = (value) => {
    if (value === undefined || value === null) return null;
    const text = String(value);
    return /^\d+$/.test(text) ? text : null;
  };
  const identityFromUrl = (raw) => {
    if (!raw) return null;
    try {
      const url = new URL(String(raw), location.href);
      if (url.protocol !== 'https:' || !/(^|\.)shopee\.ph$/i.test(url.hostname)) return null;
      const path = decodeURIComponent(url.pathname);
      let match = path.match(/\/product\/(\d+)\/(\d+)(?:\/|$)/i);
      if (!match) match = path.match(/-i\.(\d+)\.(\d+)(?:[/?]|$)/i);
      return match ? {shop_id: match[1], item_id: match[2], url: url.href} : null;
    } catch (_) {
      return null;
    }
  };

  const canonicalNode = document.querySelector('link[rel~="canonical"]');
  const ogNode = document.querySelector('meta[property="og:url"]');
  const locationIdentity = identityFromUrl(location.href);
  const canonicalIdentity = identityFromUrl(canonicalNode && canonicalNode.href);
  const ogIdentity = identityFromUrl(ogNode && ogNode.content);
  const expectedKey = options.shop_id + ':' + options.item_id;
  const scripts = Array.from(document.querySelectorAll('script[type="text/mfe-initial-data"]'));
  const candidates = [];
  let parseErrors = 0;
  let currentKeyDeclared = false;
  let currentKeySeen = false;

  for (let scriptIndex = 0; scriptIndex < scripts.length; scriptIndex += 1) {
    let payload;
    try { payload = JSON.parse(scripts[scriptIndex].textContent || ''); }
    catch (_) { parseErrors += 1; continue; }
    const store = payload && payload.initialState && payload.initialState.DOMAIN_PDP &&
      payload.initialState.DOMAIN_PDP.data && payload.initialState.DOMAIN_PDP.data.PDP_BFF_DATA;
    const cachedMap = store && store.cachedMap;
    if (!cachedMap || typeof cachedMap !== 'object') continue;
    const currentKey = store.currentKey;
    if (currentKey !== undefined && currentKey !== null) currentKeyDeclared = true;
    const ordered = [];
    if (currentKey !== undefined && currentKey !== null &&
        Object.prototype.hasOwnProperty.call(cachedMap, currentKey)) {
      currentKeySeen = true;
      ordered.push({key: String(currentKey), value: cachedMap[currentKey], is_current: true});
    }
    for (const key of Object.keys(cachedMap)) {
      if (currentKey !== undefined && currentKey !== null && String(currentKey) === key) continue;
      ordered.push({key, value: cachedMap[key], is_current: false});
    }
    for (const entry of ordered) {
      const item = entry.value && entry.value.item;
      if (!item || typeof item !== 'object') continue;
      const shopId = textId(item.shop_id !== undefined ? item.shop_id : item.shopid);
      const itemId = textId(item.item_id !== undefined ? item.item_id : item.itemid);
      if (!shopId || !itemId) continue;
      candidates.push({
        shop_id: shopId,
        item_id: itemId,
        key: shopId + ':' + itemId,
        is_current: entry.is_current,
        cache_key: entry.key,
        script_index: scriptIndex,
        bff: entry.value,
      });
    }
  }

  let selected = null;
  if (currentKeyDeclared) {
    const current = candidates.filter((value) => value.is_current);
    const identities = new Set(current.map((value) => value.key));
    if (currentKeySeen && identities.size === 1 && identities.has(expectedKey)) {
      selected = current.find((value) => value.key === expectedKey) || null;
    }
  } else {
    const identities = new Set(candidates.map((value) => value.key));
    if (identities.size === 1 && identities.has(expectedKey)) {
      selected = candidates.find((value) => value.key === expectedKey) || null;
    }
  }

  const visible = String(document.body ? document.body.innerText : '').replace(/\s+/g, ' ').trim();
  const lowerUrl = location.href.toLowerCase();
  const challengeMarkers = [
    'Verify to Continue', 'Page Unavailable', 'Please Try Again Later',
    'Please log in and try again', 'One More Step', 'Security Check'
  ];
  const challenge =
    /\/(?:verify|captcha)(?:\/|[?#]|$)/.test(lowerUrl) ||
    Boolean(document.querySelector('[class*="captcha"], [id*="captcha"], iframe[src*="captcha"]')) ||
    challengeMarkers.some((marker) => visible.toLowerCase().includes(marker.toLowerCase()));

  return {
    challenge,
    final_url: location.href,
    location_identity: locationIdentity,
    canonical_present: Boolean(canonicalNode),
    canonical_url: canonicalNode ? canonicalNode.href : null,
    canonical_identity: canonicalIdentity,
    og_present: Boolean(ogNode),
    og_url: ogNode ? ogNode.content : null,
    og_identity: ogIdentity,
    current_key_declared: currentKeyDeclared,
    current_key_seen: currentKeySeen,
    mfe_script_count: scripts.length,
    mfe_parse_errors: parseErrors,
    candidates: candidates.map((value) => ({
      shop_id: value.shop_id, item_id: value.item_id,
      is_current: value.is_current, cache_key: value.cache_key,
      script_index: value.script_index,
    })),
    selection: selected ? (selected.is_current ? 'currentKey' : 'uniqueIdentityFallback') : null,
    bff: selected ? selected.bff : null,
    stealth_probe: {
      webdriver_is_undefined: navigator.webdriver === undefined,
      user_agent: navigator.userAgent,
      language: navigator.language,
      languages: Array.from(navigator.languages || []),
      platform: navigator.platform,
      vendor: navigator.vendor,
      plugin_count: navigator.plugins ? navigator.plugins.length : null,
      hardware_concurrency: navigator.hardwareConcurrency,
      device_memory: navigator.deviceMemory === undefined ? null : navigator.deviceMemory,
      chrome_runtime_present: Boolean(window.chrome && window.chrome.runtime),
      time_zone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      screen_width: window.screen.width,
      screen_height: window.screen.height,
    },
  };
}
"""


def _emit(progress: Progress | None, message: str) -> None:
    if progress is not None:
        progress(message)


def _url_identity(value: str) -> tuple[str, str] | None:
    try:
        path = unquote(urlsplit(value).path)
    except (TypeError, ValueError):
        return None
    for pattern in IDENTITY_PATTERNS:
        match = pattern.search(path)
        if match:
            return str(int(match.group(1))), str(int(match.group(2)))
    return None


def _number(value: str) -> int | float:
    try:
        number = Decimal(value.replace(",", ""))
    except InvalidOperation as exc:
        raise ScrapeError(f"invalid numeric value: {value!r}") from exc
    if not number.is_finite() or number < 0:
        raise ScrapeError(f"invalid numeric value: {value!r}")
    return int(number) if number == number.to_integral_value() else float(number)


def _monthly_lower_bound(value: str | None) -> int | None:
    if value is None:
        return None
    normalized = value.upper().replace(",", "")
    if normalized.endswith("+"):
        normalized = normalized[:-1]
    multiplier = 1
    if normalized.endswith("K"):
        normalized = normalized[:-1]
        multiplier = 1_000
    elif normalized.endswith("M"):
        normalized = normalized[:-1]
        multiplier = 1_000_000
    number = Decimal(normalized) * multiplier
    if not number.is_finite() or number < 0 or number != number.to_integral_value():
        raise ScrapeError(f"invalid monthly-sales value: {value!r}")
    return int(number)


def _detect_profile_name(user_data: Path) -> str:
    profile = "Default"
    state_path = user_data / "Local State"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        candidate = state.get("profile", {}).get("last_used")
        if isinstance(candidate, str) and candidate:
            profile = candidate
    except (OSError, ValueError, TypeError):
        pass
    if Path(profile).name != profile or profile in {".", ".."}:
        raise ValueError(f"invalid Chrome profile name: {profile!r}")
    if not (user_data / profile).is_dir():
        raise FileNotFoundError(f"Chrome profile not found: {user_data / profile}")
    return profile


def _copy_regular_files(source: Path, target: Path, *, max_size: int = 64 << 20) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for entry in source.iterdir():
        try:
            is_file = entry.is_file() and not entry.is_symlink()
            size = entry.stat().st_size if is_file else 0
        except OSError:
            continue
        if not is_file or size > max_size:
            continue
        if entry.name in {"LOCK", "LOG", "LOG.old", "DevToolsActivePort"}:
            continue
        if entry.name.endswith(("-journal", "-wal", "-shm")):
            continue
        shutil.copy2(entry, target / entry.name)


def _copy_state_directory(source: Path, target: Path) -> None:
    if not source.is_dir() or source.is_symlink():
        return

    def ignore(directory: str, names: list[str]) -> set[str]:
        ignored: set[str] = set()
        for name in names:
            path = Path(directory) / name
            if path.is_symlink() or name in {"LOCK", "LOG", "LOG.old"}:
                ignored.add(name)
            elif name.endswith(("-journal", "-wal", "-shm")):
                ignored.add(name)
        return ignored

    shutil.copytree(source, target, ignore=ignore, dirs_exist_ok=True)


@contextmanager
def _temporary_chrome_profile() -> Iterator[Path]:
    temp_parent = Path("/private/tmp")
    root = Path(
        tempfile.mkdtemp(
            prefix="shopees-ugreen-profile-",
            dir=temp_parent if temp_parent.is_dir() else None,
        )
    )
    os.chmod(root, 0o700)
    try:
        source_root = DEFAULT_CHROME_DATA.resolve()
        if not source_root.is_dir():
            raise FileNotFoundError(f"Chrome user-data directory not found: {source_root}")
        profile = _detect_profile_name(source_root)
        source_profile = source_root / profile
        _copy_regular_files(source_root, root)
        target_profile = root / profile
        _copy_regular_files(source_profile, target_profile)
        for directory in (
            "Local Storage",
            "Session Storage",
            "WebStorage",
            "Storage",
            "Sessions",
            "Network",
        ):
            _copy_state_directory(
                source_profile / directory,
                target_profile / directory,
            )
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _stealth_script() -> str:
    path = Path(__file__).with_name("stealth_init.js")
    script = path.read_text(encoding="utf-8")
    if not script.strip():
        raise ScrapeError(f"stealth init script is empty: {path}")
    return script


async def _launch_context(config: BrowserConfig, user_data_dir: Path) -> BrowserContext:
    playwright = await async_playwright().start()
    context: BrowserContext | None = None
    try:
        context = await playwright.chromium.launch_persistent_context(
            str(user_data_dir),
            executable_path=str(config.chrome_executable),
            headless=config.headless,
            ignore_default_args=["--use-mock-keychain", "--password-store=basic"],
        )
        await context.add_init_script(script=_stealth_script())
        for page in list(context.pages):
            await page.close()
        setattr(context, "_ugreen_playwright", playwright)
        return context
    except BaseException:
        if context is not None:
            try:
                await context.close()
            except Exception:
                pass
        await playwright.stop()
        raise


async def _close_context(context: BrowserContext) -> None:
    playwright = getattr(context, "_ugreen_playwright", None)
    try:
        await context.close()
    finally:
        if playwright is not None:
            await playwright.stop()


def _valid_stealth_probe(probe: Any) -> bool:
    return isinstance(probe, dict) and all(
        (
            probe.get("webdriver_is_undefined") is True,
            probe.get("user_agent")
            == (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            probe.get("language") == "en-US",
            probe.get("languages") == ["en-US", "en", "zh-CN"],
            probe.get("platform") == "Win32",
            probe.get("vendor") == "Google Inc.",
            probe.get("plugin_count") == 5,
            probe.get("hardware_concurrency") == 8,
            probe.get("device_memory") == 8,
            probe.get("chrome_runtime_present") is True,
            probe.get("time_zone") == "Asia/Manila",
            probe.get("screen_width") == 1366,
            probe.get("screen_height") == 768,
        )
    )


async def _load_list_page(
    page: Page,
    page_index: int,
    config: BrowserConfig,
    expected_total: int | None,
) -> dict[str, Any]:
    url = STORE_URL_TEMPLATE.format(page=page_index)
    last_error = "page did not become ready"
    for attempt in range(1, config.retries + 1):
        try:
            response = await page.goto(
                url, wait_until="domcontentloaded", timeout=config.navigation_timeout_ms
            )
            if response is not None and response.status >= 400:
                raise ScrapeError(f"HTTP {response.status}")
            deadline = asyncio.get_running_loop().time() + (
                config.page_ready_timeout_ms / 1000
            )
            previous_fingerprint: tuple[str, ...] | None = None
            stable_count = 0
            while asyncio.get_running_loop().time() < deadline:
                payload = await page.evaluate(
                    LIST_PAGE_SCRIPT, {"expected_shop_id": SHOP_ID}
                )
                if payload.get("challenge"):
                    raise ScrapeError("Shopee verification page detected")
                current_values = payload.get("current_values") or []
                total_values = payload.get("total_values") or []
                cards = payload.get("cards") or []
                ready = (
                    payload.get("result_view_count") == 1
                    and current_values == [str(page_index + 1)]
                    and len(total_values) == 1
                    and str(total_values[0]).isdigit()
                    and not payload.get("errors")
                    and bool(cards)
                    and _valid_stealth_probe(payload.get("stealth_probe"))
                )
                if ready:
                    total = int(total_values[0])
                    if expected_total is not None and total != expected_total:
                        raise ScrapeError(
                            f"pager total changed from {expected_total} to {total}"
                        )
                    is_last = page_index + 1 == total
                    expected_count = 30 if not is_last else None
                    count_valid = (
                        len(cards) == expected_count
                        if expected_count is not None
                        else 1 <= len(cards) <= 30
                    )
                    terminal_valid = (
                        payload.get("next_button_count") == 1
                        and (
                            (is_last and not payload.get("next_url") and payload.get("next_disabled") is True)
                            or (
                                not is_last
                                and bool(payload.get("next_url"))
                                and payload.get("next_disabled") is False
                            )
                        )
                    )
                    anchors_complete = payload.get("scoped_anchor_count") == len(cards)
                    if count_valid and terminal_valid and anchors_complete:
                        fingerprint = tuple(str(card["item_id"]) for card in cards)
                        if fingerprint == previous_fingerprint:
                            stable_count += 1
                        else:
                            previous_fingerprint = fingerprint
                            stable_count = 1
                        required_stability = 4 if is_last else 2
                        if stable_count >= required_stability:
                            payload["total"] = total
                            return payload
                last_error = (
                    f"current={current_values}, total={total_values}, "
                    f"anchors={payload.get('scoped_anchor_count')}, cards={len(cards)}, "
                    f"next={payload.get('next_url')!r}, disabled={payload.get('next_disabled')!r}, "
                    f"errors={payload.get('errors') or []}"
                )
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(700)
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        if attempt < config.retries:
            await page.wait_for_timeout(1_000 * attempt)
    raise ScrapeError(
        f"list page {page_index + 1} failed after {config.retries} attempts: {last_error}"
    )


def _card_from_payload(value: dict[str, Any], page_index: int, position: int) -> ProductCard:
    identity = _url_identity(str(value.get("product_url") or ""))
    declared = str(value.get("shop_id")), str(value.get("item_id"))
    if identity != declared or declared[0] != SHOP_ID:
        raise ScrapeError(f"invalid product identity on list page: {declared!r}")
    monthly_display = value.get("monthly_sales_display")
    lower_bound = _monthly_lower_bound(monthly_display)
    return ProductCard(
        source_page=page_index,
        source_position=position,
        shop_id=declared[0],
        item_id=declared[1],
        title=str(value["title"]),
        product_url=str(value["product_url"]),
        price_php=_number(str(value["price_text"])),
        monthly_sales_display=str(monthly_display) if monthly_display else None,
        monthly_sales_text=(
            str(value["monthly_sales_text"])
            if value.get("monthly_sales_text")
            else None
        ),
        monthly_sales_count_lower_bound=lower_bound,
        monthly_sales_observation=(
            "not_displayed"
            if lower_bound is None
            else "displayed_zero" if lower_bound == 0 else "displayed"
        ),
    )


async def _collect_listing(
    page: Page,
    config: BrowserConfig,
    progress: Progress | None,
) -> tuple[list[ProductCard], int, int, int]:
    products: list[ProductCard] = []
    seen: set[tuple[str, str]] = set()
    total_pages: int | None = None
    page_index = 0
    occurrences = 0
    duplicates = 0
    previous_fingerprint: tuple[str, ...] | None = None

    while total_pages is None or page_index < total_pages:
        payload = await _load_list_page(page, page_index, config, total_pages)
        if total_pages is None:
            total_pages = int(payload["total"])
            if total_pages < 1:
                raise ScrapeError("Shopee pager reported no pages")
        raw_cards = payload["cards"]
        fingerprint = tuple(str(value["item_id"]) for value in raw_cards)
        if fingerprint == previous_fingerprint:
            raise ScrapeError(f"list page {page_index + 1} repeats the prior page")
        previous_fingerprint = fingerprint
        occurrences += len(raw_cards)
        for position, value in enumerate(raw_cards, 1):
            card = _card_from_payload(value, page_index, position)
            key = (card.shop_id, card.item_id)
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            products.append(card)
        _emit(
            progress,
            f"列表页 {page_index + 1}/{total_pages}：{len(raw_cards)} 个商品卡，累计 {len(products)} 个唯一商品",
        )
        page_index += 1

    captured_pages = page_index
    if total_pages is not None and captured_pages != total_pages:
        raise ScrapeError(
            f"list traversal stopped at {captured_pages}/{total_pages} pages"
        )
    if not products:
        raise ScrapeError("no products found in the Top Sales listing")
    return products, captured_pages, occurrences, duplicates


def _same_identity(value: Any, expected: tuple[str, str]) -> bool:
    return isinstance(value, dict) and (
        str(value.get("shop_id")), str(value.get("item_id"))
    ) == expected


def _validate_detail_payload(
    payload: dict[str, Any], expected: tuple[str, str]
) -> None:
    if payload.get("bff") is None:
        raise ScrapeError("matching PDP data is missing")
    if not _same_identity(payload.get("location_identity"), expected):
        raise ScrapeError("final page URL does not match the requested product")
    for label in ("canonical_identity", "og_identity"):
        identity = payload.get(label)
        present_key = "canonical_present" if label == "canonical_identity" else "og_present"
        if payload.get(present_key) and identity is None:
            raise ScrapeError(f"{label} exists but is not a valid Shopee PDP URL")
        if identity is not None and not _same_identity(identity, expected):
            raise ScrapeError(f"{label} does not match the requested product")
    if not _valid_stealth_probe(payload.get("stealth_probe")):
        raise ScrapeError("browser injection probe does not match the required values")


async def _wait_for_detail(
    page: Page, card: ProductCard, config: BrowserConfig
) -> dict[str, Any]:
    expected = (card.shop_id, card.item_id)
    deadline = asyncio.get_running_loop().time() + config.page_ready_timeout_ms / 1000
    last: dict[str, Any] | None = None
    while asyncio.get_running_loop().time() < deadline:
        payload = await page.evaluate(
            DETAIL_PAGE_SCRIPT,
            {"shop_id": card.shop_id, "item_id": card.item_id},
        )
        last = payload
        if payload.get("challenge"):
            raise ScrapeError("Shopee verification page detected")
        if payload.get("bff") is not None and _same_identity(
            payload.get("location_identity"), expected
        ):
            _validate_detail_payload(payload, expected)
            await page.wait_for_timeout(800)
            settled = await page.evaluate(
                DETAIL_PAGE_SCRIPT,
                {"shop_id": card.shop_id, "item_id": card.item_id},
            )
            if settled.get("challenge"):
                raise ScrapeError("Shopee verification page detected after settling")
            _validate_detail_payload(settled, expected)
            return settled
        await page.wait_for_timeout(350)
    candidates = (last or {}).get("candidates") or []
    raise ScrapeError(
        "timed out waiting for matching PDP data; candidates="
        + repr(candidates[:5])
    )


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _first(*values: Any) -> Any:
    return next((value for value in values if value is not None and value != ""), None)


def _asset_url(value: Any) -> str | None:
    if isinstance(value, dict):
        value = _first(
            value.get("image_id"), value.get("image"), value.get("url")
        )
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    if value.startswith("//"):
        return "https:" + value
    if value.startswith(("https://", "http://")):
        return value
    return f"https://down-ph.img.susercontent.com/file/{value.lstrip('/')}"


def _option_name(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        candidate = _first(value.get("name"), value.get("value"), value.get("option"))
        return str(candidate) if candidate is not None else None
    return None


def _parse_detail(card: ProductCard, payload: dict[str, Any], rank: int) -> ProductRecord:
    bff = _as_dict(payload.get("bff"))
    item = _as_dict(bff.get("item"))
    identity = (
        str(_first(item.get("shop_id"), item.get("shopid"))),
        str(_first(item.get("item_id"), item.get("itemid"))),
    )
    if identity != (card.shop_id, card.item_id):
        raise ScrapeError(
            f"embedded PDP identity {identity!r} does not match {card.shop_id}/{card.item_id}"
        )

    tiers = [_as_dict(value) for value in _as_list(item.get("tier_variations"))]
    models = _as_list(item.get("models"))
    if not models:
        raise ScrapeError(f"PDP {card.item_id} exposes no SKU models")
    sku_rows: list[SkuRecord] = []
    model_ids: set[str] = set()
    for raw_model in models:
        model = _as_dict(raw_model)
        model_id_value = _first(model.get("model_id"), model.get("modelid"))
        if model_id_value is None:
            raise ScrapeError(f"PDP {card.item_id} contains a model without an ID")
        model_id = str(model_id_value)
        if not model_id.isdigit() or model_id in model_ids:
            raise ScrapeError(f"PDP {card.item_id} contains an invalid/duplicate model ID")
        model_ids.add(model_id)
        extinfo = _as_dict(model.get("extinfo"))
        indices = _as_list(extinfo.get("tier_index") or model.get("tier_index"))
        props: dict[str, str] = {}
        valid_mapping = len(indices) == len(tiers)
        if valid_mapping:
            for tier_number, (tier, raw_index) in enumerate(zip(tiers, indices), 1):
                options = _as_list(tier.get("options"))
                if not isinstance(raw_index, int) or not 0 <= raw_index < len(options):
                    valid_mapping = False
                    break
                name = str(_first(tier.get("name"), f"Variation {tier_number}"))
                option = _option_name(options[raw_index])
                if option is None or name in props:
                    valid_mapping = False
                    break
                props[name] = option
        if not valid_mapping:
            props = {}
        if not props:
            props = {"SKU": model_id}

        image_candidates: list[Any] = [
            model.get("sku_image"),
            model.get("image"),
            model.get("image_id"),
            extinfo.get("sku_image"),
            extinfo.get("image"),
            extinfo.get("image_id"),
        ]
        for tier, raw_index in zip(tiers, indices):
            images = _as_list(tier.get("images"))
            if isinstance(raw_index, int) and 0 <= raw_index < len(images):
                image_candidates.append(images[raw_index])
        sku_image = next(
            (resolved for resolved in map(_asset_url, image_candidates) if resolved),
            None,
        )
        sku_rows.append(
            SkuRecord(
                model_id=model_id,
                sku_props=props,
                sku_image_url=sku_image,
            )
        )

    product_images = _as_dict(bff.get("product_images"))
    gallery_values = (
        _as_list(product_images.get("images"))
        or _as_list(item.get("images"))
        or [item.get("image")]
    )
    gallery: list[str] = []
    for value in gallery_values:
        resolved = _asset_url(value)
        if resolved and resolved not in gallery:
            gallery.append(resolved)
    if not gallery:
        raise ScrapeError(f"PDP {card.item_id} has no product gallery")
    for image_url in gallery:
        parts = urlsplit(image_url)
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            raise ScrapeError(f"PDP {card.item_id} has an invalid image URL")

    return ProductRecord(
        global_rank=rank,
        source_page=card.source_page,
        source_position=card.source_position,
        shop_id=card.shop_id,
        item_id=card.item_id,
        title=card.title or str(_first(item.get("title"), item.get("name"), "")),
        product_url=card.product_url,
        price_php=card.price_php,
        monthly_sales_text=card.monthly_sales_text,
        monthly_sales_count_lower_bound=card.monthly_sales_count_lower_bound,
        monthly_sales_observation=card.monthly_sales_observation,
        skus=sku_rows,
        main_image_url=gallery[0],
        secondary_image_urls=gallery[1:],
    )


async def _visit_detail(
    page: Page, card: ProductCard, rank: int, config: BrowserConfig
) -> ProductRecord:
    requested_identity = _url_identity(card.product_url)
    if requested_identity != (card.shop_id, card.item_id):
        raise ScrapeError(f"list URL identity changed for item {card.item_id}")
    last_error = "unknown error"
    for attempt in range(1, config.retries + 1):
        try:
            response = await page.goto(
                card.product_url,
                wait_until="domcontentloaded",
                timeout=config.navigation_timeout_ms,
            )
            if response is not None and response.status >= 400:
                raise ScrapeError(f"HTTP {response.status}")
            payload = await _wait_for_detail(page, card, config)
            return _parse_detail(card, payload, rank)
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < config.retries:
                try:
                    await page.goto("about:blank", wait_until="commit", timeout=10_000)
                except Exception:
                    pass
                await page.wait_for_timeout(1_000 * attempt)
    raise ScrapeError(
        f"detail {rank} ({card.shop_id}/{card.item_id}) failed after "
        f"{config.retries} attempts: {last_error}"
    )


async def _collect_details(
    context: BrowserContext,
    cards: Sequence[ProductCard],
    config: BrowserConfig,
    progress: Progress | None,
) -> list[ProductRecord]:
    queue: asyncio.Queue[tuple[int, ProductCard]] = asyncio.Queue()
    for rank, card in enumerate(cards, 1):
        queue.put_nowait((rank, card))
    results: list[ProductRecord | None] = [None] * len(cards)
    failures: list[str] = []
    completed = 0

    async def worker() -> None:
        nonlocal completed
        page = await context.new_page()
        try:
            while True:
                try:
                    rank, card = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                try:
                    results[rank - 1] = await _visit_detail(page, card, rank, config)
                except Exception as exc:
                    failures.append(str(exc))
                finally:
                    completed += 1
                    if completed == len(cards) or completed % 10 == 0:
                        _emit(
                            progress,
                            f"详情页 {completed}/{len(cards)}：成功 {completed - len(failures)}，失败 {len(failures)}",
                        )
                    queue.task_done()
        finally:
            await page.close()

    workers = min(config.detail_workers, len(cards))
    await asyncio.gather(*(worker() for _ in range(workers)))
    if failures:
        preview = "\n".join(failures[:10])
        raise ScrapeError(f"{len(failures)} product details failed:\n{preview}")
    completed_results = [value for value in results if value is not None]
    if len(completed_results) != len(cards):
        raise ScrapeError(
            f"detail completeness mismatch: {len(completed_results)}/{len(cards)}"
        )
    return completed_results


async def scrape_all(
    config: BrowserConfig | None = None,
    *,
    progress: Progress | None = None,
) -> ScrapeResult:
    """Scrape the complete fixed UGREEN Top Sales scope into memory."""

    config = config or BrowserConfig()
    config.validate()

    with _temporary_chrome_profile() as user_data_dir:
        context = await _launch_context(config, user_data_dir)
        try:
            list_page = await context.new_page()
            try:
                cards, page_count, occurrences, duplicates = await _collect_listing(
                    list_page,
                    config,
                    progress,
                )
            finally:
                await list_page.close()
            _emit(progress, f"开始逐个进入 {len(cards)} 个商品详情页")
            products = await _collect_details(context, cards, config, progress)
        finally:
            await _close_context(context)

    if any(product.global_rank != index for index, product in enumerate(products, 1)):
        raise ScrapeError("product rank/order validation failed")
    audit = ScrapeAudit(
        list_page_count=page_count,
        list_input_product_occurrences=occurrences,
        list_duplicate_occurrence_count=duplicates,
        listed_product_count=len(cards),
        detail_success_count=len(products),
        detail_failure_count=0,
        products_without_monthly_sales_display=sum(
            product.monthly_sales_observation == "not_displayed"
            for product in products
        ),
    )
    return ScrapeResult(
        store_url=STORE_URL,
        captured_at=datetime.now(timezone.utc),
        products=products,
        audit=audit,
    )
