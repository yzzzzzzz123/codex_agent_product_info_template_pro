"""UGREEN Top Sales Codex Skill 的确定性浏览器抓取模块。

所有页面数据只保存在内存中。浏览器会打开每个商品详情页 URL，并向调用方返回
结构化记录；本模块不会写入 HTML、JSON、截图、清单或其他抓取产物。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import signal
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Iterator, Sequence
from urllib.parse import parse_qs, unquote, urlsplit

import playwright as playwright_package
from playwright.async_api import BrowserContext, Page, async_playwright


SHOP_ID = "64922227"
STORE_URL = (
    "https://shopee.ph/ugreen.ph?"
    "page=0&shop=64922227&sortBy=sales&tab=0"
)
STORE_PAGE_URL_TEMPLATE = (
    "https://shopee.ph/ugreen.ph?page={page}&shop=64922227&sortBy=sales&tab=0"
)
DEFAULT_CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
DEFAULT_CHROME_DATA = Path.home() / "Library/Application Support/Google/Chrome"
STEALTH_SHA256 = "0917c37fcfba7718f79bd6ec9d63996b7e07c23e88fe19f87e3b096799ef9128"
BROWSER_LOCALE = "en-PH"
BROWSER_LANGUAGES = ("en-US", "en", "zh-CN")
BROWSER_TIMEZONE = "Asia/Manila"
CHROME_USER_AGENT_TEMPLATE = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/{major}.0.0.0 Safari/537.36"
)
CHROME_USER_AGENT = CHROME_USER_AGENT_TEMPLATE.format(major="122")
IDENTITY_PATTERNS = (
    re.compile(r"(?:-i\.|/i\.)(\d+)\.(\d+)(?:/)?$", re.I),
    re.compile(r"/product/(\d+)/(\d+)(?:/)?$", re.I),
)
CHALLENGE_HTTP_STATUSES = {403, 418, 429, 503}


class ScrapeError(RuntimeError):
    """页面无法确认属于指定抓取范围时抛出。"""


class AccessChallengeError(ScrapeError):
    """Shopee 明确拦截或验证当前访问线路时抛出。"""


@dataclass(slots=True)
class BrowserConfig:
    """慢速浏览器参数；按用户要求复现昨日已验证的访问配置。"""

    headless: bool = False
    detail_shards: int = 1
    list_interval_ms: int = 10_000
    detail_interval_ms: int = 10_000
    list_navigation_timeout_ms: int = 120_000
    detail_navigation_timeout_ms: int = 60_000
    list_ready_timeout_ms: int = 35_000
    list_settle_ms: int = 15_000
    detail_identity_timeout_ms: int = 15_000
    detail_settle_ms: int = 300
    retries: int = 3
    retry_backoff_ms: int = 10_000
    chrome_executable: Path = DEFAULT_CHROME
    historical_list_preflight: bool = False
    manual_list_handoff: bool = False

    def validate(self) -> None:
        if self.manual_list_handoff and self.headless:
            raise ValueError("人工列表接管需要可见浏览器窗口")
        if self.manual_list_handoff and self.detail_shards != 1:
            raise ValueError("人工接管只允许单路浏览器采集")
        if self.detail_shards < 1:
            raise ValueError("detail_shards 必须至少为 1")
        if self.list_interval_ms < 10_000 or self.detail_interval_ms < 10_000:
            raise ValueError("稳定模式的列表和详情访问间隔均不得少于 10 秒")
        if (
            self.list_navigation_timeout_ms < 1
            or self.detail_navigation_timeout_ms < 1
            or self.list_ready_timeout_ms < 1
            or self.detail_identity_timeout_ms < 1
        ):
            raise ValueError("浏览器超时时间必须为正数")
        if self.retries < 1:
            raise ValueError("retries 必须至少为 1")
        if (
            self.retry_backoff_ms < 0
            or self.list_settle_ms < 0
            or self.detail_settle_ms < 0
        ):
            raise ValueError("浏览器等待时间不能为负数")
        if not self.chrome_executable.is_file():
            raise FileNotFoundError(f"找不到 Chrome 可执行文件：{self.chrome_executable}")


@dataclass(slots=True)
class ProductCard:
    source_page: int | None
    source_position: int | None
    shop_id: str
    item_id: str
    title: str
    product_url: str
    price_php: int | float | None
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
    global_rank: int | None
    source_page: int | None
    source_position: int | None
    shop_id: str
    item_id: str
    title: str
    product_url: str
    price_php: int | float | None
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
    collection_mode: str = "full_topsales"
    scope_metadata: dict[str, Any] = field(default_factory=dict)


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
    'Please log in and try again', 'One More Step', 'Security Check',
    'Traffic Error'
  ];
  const lowerUrl = location.href.toLowerCase();
  const challenge =
    /\/(?:verify|captcha)(?:\/|[?#]|$)/.test(lowerUrl) ||
    /\/traffic\/error(?:\/|[?#]|$)/.test(lowerUrl) ||
    Boolean(document.querySelector(
      '[class*="captcha"], [id*="captcha"], iframe[src*="captcha"], ' +
      '[class*="traffic-error"], [id*="traffic-error"], ' +
      'iframe[src*="/verify"], iframe[src*="/traffic/error"]'
    )) ||
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
      user_agent_data: navigator.userAgentData ? navigator.userAgentData.toJSON() : null,
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
    'Please log in and try again', 'One More Step', 'Security Check',
    'Traffic Error'
  ];
  const challenge =
    /\/(?:verify|captcha)(?:\/|[?#]|$)/.test(lowerUrl) ||
    /\/traffic\/error(?:\/|[?#]|$)/.test(lowerUrl) ||
    Boolean(document.querySelector(
      '[class*="captcha"], [id*="captcha"], iframe[src*="captcha"], ' +
      '[class*="traffic-error"], [id*="traffic-error"], ' +
      'iframe[src*="/verify"], iframe[src*="/traffic/error"]'
    )) ||
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
      user_agent_data: navigator.userAgentData ? navigator.userAgentData.toJSON() : null,
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
        parsed = urlsplit(value)
        if parsed.scheme != "https" or parsed.hostname != "shopee.ph":
            return None
        path = unquote(parsed.path)
    except (TypeError, ValueError):
        return None
    for pattern in IDENTITY_PATTERNS:
        match = pattern.search(path)
        if match:
            return str(int(match.group(1))), str(int(match.group(2)))
    return None


def _is_login_url(value: str) -> bool:
    return bool(re.search(r"/(?:buyer|account)/login(?:/|$)", urlsplit(value).path.lower()))


def _is_challenge_url(value: str) -> bool:
    try:
        path = unquote(urlsplit(value).path).lower()
    except (TypeError, ValueError):
        return False
    return bool(
        re.search(r"/(?:verify|captcha)(?:/|$)", path)
        or re.search(r"/traffic/error(?:/|$)", path)
        or _is_login_url(value)
    )


async def _wait_for_login(page: Page, config: BrowserConfig, target_url: str) -> bool:
    """本轮明确不做人工验证；登录页拒收，不等待或代填凭据。"""
    if not _is_login_url(page.url):
        return False
    raise AccessChallengeError("Shopee 要求登录；本轮不等待人工操作，不接受该页面")


def _valid_store_page_url(value: str, page_index: int) -> bool:
    """确认 Shopee 保持了指定店铺、页码与 Top Sales 排序。"""

    try:
        parsed = urlsplit(value)
        query = parse_qs(parsed.query, keep_blank_values=True)
    except (TypeError, ValueError):
        return False
    shop_values = query.get("shop")
    return bool(
        parsed.scheme.lower() == "https"
        and (parsed.hostname or "").lower() == "shopee.ph"
        and unquote(parsed.path).rstrip("/") == "/ugreen.ph"
        and query.get("page") == [str(page_index)]
        and query.get("sortBy") == ["sales"]
        and query.get("tab") == ["0"]
        and (shop_values is None or shop_values == [SHOP_ID])
    )


def _number(value: str) -> int | float:
    try:
        number = Decimal(value.replace(",", ""))
    except InvalidOperation as exc:
        raise ScrapeError(f"数值无效：{value!r}") from exc
    if not number.is_finite() or number < 0:
        raise ScrapeError(f"数值无效：{value!r}")
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
        raise ScrapeError(f"月销量数值无效：{value!r}")
    return int(number)


def _detect_profile_name(user_data: Path) -> str:
    """历史成功与复测均复制本机 Default，不自动切换到其他账号档案。"""
    profile = "Default"
    if not (user_data / profile).is_dir():
        raise FileNotFoundError(f"找不到 Chrome 档案：{user_data / profile}")
    return profile


CHROME_TRANSIENT_NAMES = {
    "LOCK",
    "DevToolsActivePort",
    "RunningChromeVersion",
    "SingletonCookie",
    "SingletonLock",
    "SingletonSocket",
}


def _copy_session_files(source: Path, target: Path, names: Sequence[str]) -> None:
    """只复制成功路线实际需要的文件，包括仍存在的 Cookie WAL/SHM。"""
    target.mkdir(parents=True, exist_ok=True)
    for name in names:
        entry = source / name
        if entry.is_file() and not entry.is_symlink():
            shutil.copy2(entry, target / name)


def _copy_state_directory(source: Path, target: Path) -> None:
    if not source.is_dir() or source.is_symlink():
        return

    def ignore(directory: str, names: list[str]) -> set[str]:
        ignored: set[str] = set()
        for name in names:
            path = Path(directory) / name
            if path.is_symlink() or name in CHROME_TRANSIENT_NAMES:
                ignored.add(name)
        return ignored

    shutil.copytree(source, target, ignore=ignore, dirs_exist_ok=True)


def _clean_profile_transients(root: Path) -> None:
    """清理 Chrome 进程锁和其他不可移植的运行时条目。"""

    for directory, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        parent = Path(directory)
        for name in list(dirnames):
            path = parent / name
            if path.is_symlink() or name in CHROME_TRANSIENT_NAMES:
                if path.is_symlink():
                    path.unlink(missing_ok=True)
                else:
                    shutil.rmtree(path, ignore_errors=True)
                dirnames.remove(name)
        for name in filenames:
            path = parent / name
            if (
                path.is_symlink()
                or not path.is_file()
                or name in CHROME_TRANSIENT_NAMES
            ):
                path.unlink(missing_ok=True)


def _clone_profile_tree(source: Path, target: Path) -> None:
    """将干净的临时基础档案克隆到独立 Chrome 用户数据目录。"""

    def ignore(directory: str, names: list[str]) -> set[str]:
        ignored: set[str] = set()
        for name in names:
            path = Path(directory) / name
            if (
                path.is_symlink()
                or (not path.is_dir() and not path.is_file())
                or name in CHROME_TRANSIENT_NAMES
            ):
                ignored.add(name)
        return ignored

    shutil.copytree(source, target, ignore=ignore)
    os.chmod(target, 0o700)


@contextmanager
def _temporary_chrome_profile_base() -> Iterator[Path]:
    """不启动原始档案，创建一个私有基础快照。"""

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
            raise FileNotFoundError(f"找不到 Chrome 用户数据目录：{source_root}")
        profile = _detect_profile_name(source_root)
        source_profile = source_root / profile
        base = root / "base"
        base.mkdir(mode=0o700)
        _copy_session_files(source_root, base, ("Local State",))
        target_profile = base / profile
        _copy_session_files(source_profile, target_profile, (
            "Preferences", "Secure Preferences", "Cookies", "Cookies-wal", "Cookies-shm",
        ))
        for directory in (
            "Local Storage",
            "Session Storage",
        ):
            _copy_state_directory(
                source_profile / directory,
                target_profile / directory,
            )
        yield base
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _clone_detail_profiles(base: Path, count: int) -> list[Path]:
    """将列表抓取后的基础状态克隆为独立详情页档案。"""

    if count < 1:
        raise ValueError("详情页档案数量必须至少为 1")
    _clean_profile_transients(base)
    shard_profiles: list[Path] = []
    for shard_index in range(count):
        shard = base.parent / f"shard-{shard_index + 1:02d}"
        _clone_profile_tree(base, shard)
        shard_profiles.append(shard)
    return shard_profiles


def _stealth_script() -> str:
    path = Path(__file__).with_name("proxy-access.js")
    script = path.read_bytes()
    if hashlib.sha256(script).hexdigest() != STEALTH_SHA256:
        raise ScrapeError("当前 JS 注入哈希不匹配；停止运行，请同步审阅脚本与版本校验")
    return script.decode("utf-8")


def _windows_chrome_user_agent(version: str) -> str:
    if not re.fullmatch(r"[1-9]\d*\.\d+\.\d+\.\d+", version):
        raise ScrapeError("无法识别本机 Chrome 版本；不回退到写死的 UA")
    return CHROME_USER_AGENT_TEMPLATE.format(major=version.split(".")[0])


async def _chrome_user_agent(executable: Path) -> str:
    """读取当前安装版本；不启动真实 profile、不修改浏览器或生成随机请求头。"""
    try:
        process = await asyncio.create_subprocess_exec(
            str(executable), "--version", stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError as error:
        raise ScrapeError("无法读取本机 Chrome 版本") from error
    try:
        output, _ = await asyncio.wait_for(process.communicate(), timeout=10)
    except BaseException as error:
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        await process.wait()
        if isinstance(error, asyncio.TimeoutError):
            raise ScrapeError("读取本机 Chrome 版本超过 10 秒；已终止版本查询") from error
        raise
    match = re.fullmatch(
        r"Google Chrome (\d+\.\d+\.\d+\.\d+)",
        output.decode("utf-8", errors="replace").strip(),
    )
    if process.returncode != 0 or match is None:
        raise ScrapeError("无法识别本机 Chrome 版本；不回退到写死的 UA")
    return _windows_chrome_user_agent(match[1])


async def _launch_context(config: BrowserConfig, user_data_dir: Path) -> BrowserContext:
    script = _stealth_script()
    playwright = await async_playwright().start()
    context: BrowserContext | None = None
    try:
        context = await playwright.chromium.launch_persistent_context(
            str(user_data_dir),
            executable_path=str(config.chrome_executable),
            headless=config.headless,
            ignore_https_errors=True,
            user_agent=CHROME_USER_AGENT,
            locale=BROWSER_LOCALE,
            timezone_id=BROWSER_TIMEZONE,
            viewport={"width": 1366, "height": 768},
            screen={"width": 1366, "height": 768},
            args=["--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--use-mock-keychain", "--password-store=basic"],
            env={key: value for key, value in os.environ.items()
                 if key.lower() not in {"http_proxy", "https_proxy", "all_proxy"}},
        )
        await context.add_init_script(script=script)
        # 历史成功链路保留 persistent context 自带的标签，随后另开采集页。
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


class _AccessWatch:
    """只记录本页公开商品接口的拒绝状态，不保留响应数据或凭据。"""

    def __init__(
        self,
        page: Page,
        *,
        ignore_shop_tab_90309999: bool = False,
    ) -> None:
        self.error: str | None = None
        self.tasks: set[asyncio.Task[None]] = set()
        self.ignore_shop_tab_90309999 = ignore_shop_tab_90309999
        page.on("response", self._received)
        page.on("close", self._closed)

    def _closed(self, *_: Any) -> None:
        for task in tuple(self.tasks):
            task.cancel()

    def _received(self, response: Any) -> None:
        parsed = urlsplit(response.url)
        if parsed.hostname != "shopee.ph" or not parsed.path.startswith((
            "/api/v4/shop/", "/api/v4/pdp/", "/api/v4/search/",
        )):
            return
        if response.status in CHALLENGE_HTTP_STATUSES:
            self.error = f"商品接口拒绝访问：{parsed.path}，HTTP {response.status}"
        task = asyncio.create_task(self._read_code(response, parsed.path))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def _read_code(self, response: Any, path: str) -> None:
        try:
            payload = await response.json()
        except Exception:
            return
        if isinstance(payload, dict) and any(
            str(payload.get(key)) == "90309999" for key in ("error", "error_code", "code")
        ):
            if (
                self.ignore_shop_tab_90309999
                and path == "/api/v4/shop/get_shop_tab"
            ):
                return
            if self.error is None:
                self.error = f"商品接口拒绝访问：{path}，业务错误码 90309999"

    async def check(self) -> None:
        if self.error:
            raise AccessChallengeError(self.error)
        # 只核对已到达的响应，不等待未来请求或 networkidle。
        pending = tuple(self.tasks)
        if pending:
            _, unfinished = await asyncio.wait(pending, timeout=2)
            if unfinished:
                raise ScrapeError("已收到的商品接口响应仍无法核对，停止接受本次快照")
        if self.error:
            raise AccessChallengeError(self.error)


def _watch_access(
    page: Page,
    *,
    ignore_shop_tab_90309999: bool = False,
) -> _AccessWatch:
    watch = getattr(page, "_ugreen_access_watch", None)
    if watch is None:
        watch = _AccessWatch(
            page,
            ignore_shop_tab_90309999=ignore_shop_tab_90309999,
        )
        setattr(page, "_ugreen_access_watch", watch)
    return watch


async def _check_access(page: Page) -> None:
    await _watch_access(page).check()
    if _is_challenge_url(page.url):
        raise AccessChallengeError(f"Shopee 进入验证页：{urlsplit(page.url).path}")


async def _park_and_wait(page: Page, interval_ms: int) -> None:
    """先验收已观察到的状态，再离开商品页做低频等待，不延迟详情读数。"""
    await _check_access(page)
    await page.goto("about:blank", wait_until="commit", timeout=10_000)
    await _check_access(page)
    await asyncio.sleep(interval_ms / 1000)
    await _check_access(page)


async def _launch_contexts(
    config: BrowserConfig, user_data_dirs: Sequence[Path]
) -> list[BrowserContext]:
    """启动独立持久化上下文，并在部分启动失败时完成清理。"""

    tasks = [
        asyncio.create_task(_launch_context(config, user_data_dir))
        for user_data_dir in user_data_dirs
    ]
    if not tasks:
        return []
    outcomes = await asyncio.gather(*tasks, return_exceptions=True)
    contexts = [value for value in outcomes if isinstance(value, BrowserContext)]
    failures = [value for value in outcomes if isinstance(value, BaseException)]
    if failures:
        await asyncio.gather(
            *(_close_context(context) for context in contexts),
            return_exceptions=True,
        )
        raise failures[0]
    return contexts


def _valid_stealth_probe(probe: Any) -> bool:
    if not isinstance(probe, dict):
        return False
    return all(
        (
            probe.get("webdriver_is_undefined") is True,
            probe.get("user_agent") == CHROME_USER_AGENT,
            probe.get("language") == "en-US",
            probe.get("languages") == list(BROWSER_LANGUAGES),
            probe.get("platform") == "Win32",
            probe.get("vendor") == "Google Inc.",
            probe.get("plugin_count") == 5,
            probe.get("hardware_concurrency") == 8,
            probe.get("device_memory") == 8,
            probe.get("chrome_runtime_present") is True,
            probe.get("time_zone") == BROWSER_TIMEZONE,
            probe.get("screen_width") == 1366,
            probe.get("screen_height") == 768,
        )
    )


def _validate_list_payload(
    payload: dict[str, Any], page_index: int, expected_total: int | None
) -> dict[str, Any]:
    """浏览器 DOM 与 Node HTML 路径共用的数据验收，不接受缺项或部分页面。"""
    if payload.get("challenge"):
        raise AccessChallengeError("Shopee 当前访问线路进入验证页")
    current_values = payload.get("current_values") or []
    total_values = payload.get("total_values") or []
    cards = payload.get("cards") or []
    ready = (
        payload.get("result_view_count") == 1
        and _valid_store_page_url(str(payload.get("final_url") or ""), page_index)
        and current_values == [str(page_index + 1)]
        and len(total_values) == 1
        and str(total_values[0]).isdigit()
        and not payload.get("errors")
        and bool(cards)
        and _valid_stealth_probe(payload.get("stealth_probe"))
    )
    if ready:
        total = int(total_values[0])
        if not 1 <= page_index + 1 <= total:
            raise ScrapeError("列表分页当前页超出总页数范围")
        if expected_total is not None and total != expected_total:
            raise ScrapeError(f"分页总数从 {expected_total} 变为 {total}")
        is_last = page_index + 1 == total
        count_valid = 1 <= len(cards) <= 30 if is_last else len(cards) == 30
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
        if count_valid and terminal_valid and payload.get("scoped_anchor_count") == len(cards):
            for position, card in enumerate(cards, 1):
                _card_from_payload(card, page_index, position)
            payload["total"] = total
            return payload
    raise ScrapeError(
        f"列表页 {page_index + 1} 单次快照未通过："
        f"当前页={current_values}, 总页数={total_values}, "
        f"链接数={payload.get('scoped_anchor_count')}, 商品卡数={len(cards)}, "
        f"下一页={payload.get('next_url')!r}, 禁用={payload.get('next_disabled')!r}, "
        f"错误={payload.get('errors') or []}"
    )


async def _load_list_page(
    page: Page,
    page_index: int,
    config: BrowserConfig,
    expected_total: int | None,
    *,
    ignore_shop_tab_90309999: bool = False,
) -> dict[str, Any]:
    """列表沿用历史时序：等满 15 秒后单次读取，不滚动或反复采样。"""
    url = STORE_PAGE_URL_TEMPLATE.format(page=page_index)
    _watch_access(
        page,
        ignore_shop_tab_90309999=ignore_shop_tab_90309999,
    )
    diagnostic: str | None = None
    try:
        response = await page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=config.list_navigation_timeout_ms,
        )
        await page.wait_for_timeout(config.list_settle_ms)
        payload = await page.evaluate(LIST_PAGE_SCRIPT, {"expected_shop_id": SHOP_ID})
        current_values = payload.get("current_values") or []
        total_values = payload.get("total_values") or []
        cards = payload.get("cards") or []
        probe_valid = _valid_stealth_probe(payload.get("stealth_probe"))
        diagnostic = (
            f"采集标签单次快照：路径={urlsplit(str(payload.get('final_url') or page.url)).path}，"
            f"商品卡={len(cards)}，结果区域={payload.get('result_view_count')}，"
            f"页面注入探针={'通过' if probe_valid else '未通过'}"
        )
        if response is not None and response.status in CHALLENGE_HTTP_STATUSES:
            raise AccessChallengeError(f"Shopee 拒绝当前访问线路：HTTP {response.status}")
        await _check_access(page)
        if payload.get("challenge"):
            raise AccessChallengeError("Shopee 当前访问线路进入验证页")
        if _is_login_url(page.url):
            raise AccessChallengeError("Shopee 当前访问线路进入登录页；本轮不等待人工操作")
        if response is not None and response.status >= 400:
            raise ScrapeError(f"HTTP {response.status}")
        payload = _validate_list_payload(payload, page_index, expected_total)
        await _check_access(page)
        return payload
    except ScrapeError as exc:
        exc.snapshot_diagnostic = diagnostic
        raise
    except Exception as exc:
        error = ScrapeError(f"列表页 {page_index + 1} 读取失败：{type(exc).__name__}: {exc}")
        error.snapshot_diagnostic = diagnostic
        raise error from exc


async def _load_list_page_with_extra_tab(
    context: BrowserContext,
    page_index: int,
    config: BrowserConfig,
    expected_total: int | None,
    *,
    progress: Progress | None = None,
) -> tuple[dict[str, Any], Page]:
    """保留浏览器启动默认标签，另开采集标签；只释放本函数创建的页面。"""

    pages: list[Page] = []
    accepted_page: Page | None = None
    listing_page: Page | None = None
    try:
        startup_count = len(context.pages)
        if startup_count == 0:
            pages.append(await context.new_page())
        listing_page = await context.new_page()
        pages.append(listing_page)
        _emit(
            progress,
            f"列表页 {page_index + 1}：保留 {startup_count} 个启动标签"
            + ("（另补一个空白标签）" if startup_count == 0 else "")
            + f"，另开采集标签；列表加载等待 {config.list_settle_ms / 1000:g} 秒；"
            "仅忽略 get_shop_tab 的 90309999",
        )
        payload = await _load_list_page(
            listing_page,
            page_index,
            config,
            expected_total,
            ignore_shop_tab_90309999=True,
        )
        accepted_page = listing_page
        return payload, accepted_page
    except Exception as exc:
        if progress is not None and listing_page is not None:
            _emit(
                progress,
                getattr(exc, "snapshot_diagnostic", None)
                or "未取得列表快照；保留原始访问错误，不重复读取页面",
            )
        raise
    finally:
        await asyncio.gather(
            *(page.close() for page in pages if page is not accepted_page),
            return_exceptions=True,
        )


def _card_from_payload(value: dict[str, Any], page_index: int, position: int) -> ProductCard:
    identity = _url_identity(str(value.get("product_url") or ""))
    declared = str(value.get("shop_id")), str(value.get("item_id"))
    if identity != declared or declared[0] != SHOP_ID:
        raise ScrapeError(f"列表页商品身份无效：{declared!r}")
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


class CaptureCleanupError(RuntimeError):
    """无法回收本轮浏览器时直接停止，不能进入列表重试并重用占用中的档案。"""


def _capture_cleanup_profile(user_data_dir: Path | None) -> Path | None:
    """清理只认本次任务临时根的真实后代，不扫描真实或未知 Chrome 档案。"""
    if user_data_dir is None:
        return None
    try:
        profile = user_data_dir.resolve(strict=True)
        if not profile.is_dir():
            return None
        for root in (Path("/private/tmp"), Path(tempfile.gettempdir())):
            try:
                relative = profile.relative_to(root.resolve(strict=True))
            except (OSError, ValueError):
                continue
            if (
                len(relative.parts) >= 2
                and relative.parts[0].startswith("shopees-ugreen-profile-")
                and relative.parts[0] != "shopees-ugreen-profile-"
            ):
                return profile
    except (OSError, ValueError):
        pass
    return None


def _private_chrome_groups(
    output: str, user_data_dir: Path, chrome_executable: Path
) -> set[int]:
    """解析仅在内存中的 ps 快照，精确匹配本轮 profile 的 Chrome 主进程组。"""
    import shlex

    profile = _capture_cleanup_profile(user_data_dir)
    if profile is None:
        return set()
    executable = str(chrome_executable.resolve())
    prefix = executable + " "
    groups: set[int] = set()
    for line in output.splitlines():
        fields = line.strip().split(None, 2)
        if len(fields) != 3:
            continue
        try:
            pid, group = int(fields[0]), int(fields[1])
        except ValueError:
            continue
        command = fields[2]
        if pid <= 1 or pid != group or not command.startswith(prefix):
            continue
        # ps 不为含空格的可执行文件名加引号；先消掉完整路径再解析开关。
        tail = command[len(prefix):]
        if not tail.startswith("--"):
            continue
        try:
            arguments = shlex.split(tail)
        except ValueError:
            continue
        profiles = [arg for arg in arguments if arg.startswith("--user-data-dir=")]
        if profiles != [f"--user-data-dir={profile}"]:
            continue
        if any(arg == "--type" or arg.startswith("--type=") for arg in arguments):
            continue
        groups.add(group)
    return groups


async def _capture_process_table() -> str:
    """有界读取进程参数；不打印或持久化其中的任何内容。"""
    command: asyncio.subprocess.Process | None = None
    try:
        command = await asyncio.create_subprocess_exec(
            "/bin/ps", "-ww", "-axo", "pid=,pgid=,command=",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        output, _ = await asyncio.wait_for(command.communicate(), timeout=3)
        if command.returncode != 0:
            raise ScrapeError("无法核对本次私有浏览器进程，停止重用会话")
        return output.decode("utf-8", errors="replace")
    except (OSError, asyncio.TimeoutError) as exc:
        if command is not None and command.returncode is None:
            try:
                command.kill()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(command.wait(), timeout=1)
            except asyncio.TimeoutError:
                pass
        raise ScrapeError("无法核对本次私有浏览器进程，停止重用会话") from exc


async def _wait_capture_groups(groups: set[int], deadline: float) -> set[int]:
    """仅观察已匹配进程组；等待始终受截止时间限制。"""
    remaining = set(groups)
    loop = asyncio.get_running_loop()
    while remaining:
        for group in tuple(remaining):
            try:
                os.killpg(group, 0)
            except ProcessLookupError:
                remaining.discard(group)
        if not remaining or loop.time() >= deadline:
            break
        await asyncio.sleep(min(0.1, max(0, deadline - loop.time())))
    return remaining


async def _stop_capture_process(
    process: asyncio.subprocess.Process,
    *,
    user_data_dir: Path | None = None,
    chrome_executable: Path | None = None,
) -> None:
    """有界回收本轮 Node 及精确匹配的 detached Chrome，绝不按名称批量终止。"""
    profile = _capture_cleanup_profile(user_data_dir)
    browser_groups: set[int] = set()
    scan_failed = False
    if profile is not None and chrome_executable is not None:
        try:
            browser_groups = _private_chrome_groups(
                await _capture_process_table(), profile, chrome_executable
            )
        except ScrapeError:
            scan_failed = True
    deadline = asyncio.get_running_loop().time() + 5
    for group in {process.pid, *browser_groups}:
        try:
            os.killpg(group, signal.SIGTERM)
        except ProcessLookupError:
            pass
    reaped = False
    try:
        await asyncio.wait_for(process.wait(), timeout=5)
        reaped = True
    except asyncio.TimeoutError:
        pass
    await _wait_capture_groups(browser_groups, deadline)
    # Chrome 是独立进程组；再次精确核对，避免只杀 Node 或沿用失效 PID。
    if profile is not None and chrome_executable is not None:
        try:
            browser_groups = _private_chrome_groups(
                await _capture_process_table(), profile, chrome_executable
            )
        except ScrapeError:
            browser_groups = set()
            scan_failed = True
    for group in {process.pid, *browser_groups}:
        try:
            os.killpg(group, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if not reaped:
        try:
            await asyncio.wait_for(process.wait(), timeout=2)
        except asyncio.TimeoutError as exc:
            raise CaptureCleanupError("本次 Node 进程未能在清理时限内退出，停止重用会话") from exc
    remaining = await _wait_capture_groups(
        browser_groups, asyncio.get_running_loop().time() + 2
    )
    if remaining or scan_failed:
        raise CaptureCleanupError("无法确认本次私有浏览器已退出，停止重用会话")


async def _capture_node_list_snapshot(
    user_data_dir: Path, page_index: int, config: BrowserConfig,
    *, expected_total: int | None = None, progress: Progress | None = None,
) -> dict[str, Any]:
    """沿用原 Node/preload 获取 HTML；HTML/metadata 仅通过内存管道传递。"""
    node = os.environ.get("PLAYWRIGHT_NODEJS_PATH") or shutil.which("node")
    if not node or not Path(node).is_file():
        raise ScrapeError("找不到已安装的系统 Node；不下载或切换运行时")
    worker = Path(__file__).with_name("capture_list_page.cjs")
    module = Path(playwright_package.__file__).resolve().parent / "driver" / "package"
    if not worker.is_file() or not (module / "package.json").is_file():
        raise ScrapeError("Node 列表获取模块或已安装的 Playwright 模块不存在")
    request = {
        "playwright_module": str(module),
        "user_data_dir": str(user_data_dir.resolve()),
        "chrome_executable": str(config.chrome_executable.resolve()),
        "headless": config.headless,
        "url": STORE_PAGE_URL_TEMPLATE.format(page=page_index),
        "navigation_timeout_ms": config.list_navigation_timeout_ms,
        "post_load_wait_ms": config.list_settle_ms,
        "init_script": _stealth_script(),
        "user_agent": CHROME_USER_AGENT,
        "locale": BROWSER_LOCALE,
        "timezone_id": BROWSER_TIMEZONE,
    }
    env = {key: value for key, value in os.environ.items()
           if key.lower() not in {"http_proxy", "https_proxy", "all_proxy"}}
    try:
        manual_options = {"limit": 64 * 1024 * 1024} if config.manual_list_handoff else {}
        process = await asyncio.create_subprocess_exec(
            str(Path(node).resolve()), str(worker),
            *(["--manual-handoff", "--capture-first"] if config.manual_list_handoff else []),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
            env=env,
            **manual_options,
        )
    except OSError as exc:
        raise ScrapeError("无法启动 Node 列表获取进程") from exc
    timeout = (config.list_navigation_timeout_ms + config.list_settle_ms + 45_000) / 1000
    try:
        if config.manual_list_handoff:
            return await _communicate_manual_capture(
                process, request, page_index, expected_total, timeout, progress,
            )
        stdout, _ = await asyncio.wait_for(
            process.communicate(json.dumps(request).encode("utf-8")), timeout=timeout
        )
    except asyncio.TimeoutError as exc:
        await _stop_capture_process(
            process, user_data_dir=user_data_dir, chrome_executable=config.chrome_executable
        )
        raise ScrapeError("Node 列表获取超时，已清理本次私有浏览器进程") from exc
    except asyncio.CancelledError:
        await asyncio.shield(_stop_capture_process(
            process, user_data_dir=user_data_dir, chrome_executable=config.chrome_executable
        ))
        raise
    except ScrapeError:
        await _stop_capture_process(
            process, user_data_dir=user_data_dir, chrome_executable=config.chrome_executable
        )
        raise
    except Exception as exc:
        await _stop_capture_process(
            process, user_data_dir=user_data_dir, chrome_executable=config.chrome_executable
        )
        raise ScrapeError("Node 列表获取通信失败") from exc
    try:
        try:
            snapshot = json.loads(stdout)
        except (ValueError, UnicodeDecodeError) as exc:
            raise ScrapeError("Node 列表获取未返回有效结构；不输出原始响应") from exc
        if not isinstance(snapshot, dict):
            raise ScrapeError("Node 列表获取返回的结构不是对象")
        if process.returncode != 0 or snapshot.get("error"):
            kinds = {"config": "配置", "runtime": "运行时", "navigation": "导航",
                     "timeout": "超时", "cleanup": "清理"}
            error_kind = snapshot.get("error_kind")
            kind = kinds.get(error_kind, "未知") if isinstance(error_kind, str) else "未知"
            raise ScrapeError(f"Node 列表获取失败（{kind}）；未输出页面或内部错误正文")
        if not isinstance(snapshot.get("html"), str) or not isinstance(snapshot.get("final_url"), str):
            raise ScrapeError("Node 列表快照缺少 HTML 或最终 URL")
        status = snapshot.get("http_status")
        if status is not None and type(status) is not int:
            raise ScrapeError("Node 列表快照的 HTTP 状态无效")
        if snapshot.get("access_error") is not None and not isinstance(snapshot["access_error"], str):
            raise ScrapeError("Node 列表快照的访问状态无效")
        if not isinstance(snapshot.get("stealth_probe"), dict):
            raise ScrapeError("Node 列表快照缺少页面注入探针")
    except ScrapeError:
        await _stop_capture_process(
            process, user_data_dir=user_data_dir, chrome_executable=config.chrome_executable
        )
        raise
    return snapshot


async def _wait_for_manual_resume(progress: Progress | None) -> None:
    """只读取终端控制词；不记录人工输入，不在等待期间自动操作页面。"""
    loop = asyncio.get_running_loop()
    ready: asyncio.Future[None] = loop.create_future()
    descriptor = sys.stdin.fileno()
    buffer = bytearray()

    def received() -> None:
        if ready.done():
            return
        try:
            chunk = os.read(descriptor, 1024)
            if not chunk:
                raise ScrapeError("人工接管控制终端已关闭")
            buffer.extend(chunk)
            while b"\n" in buffer:
                line, _, remaining = buffer.partition(b"\n")
                buffer[:] = remaining
                command = line.strip()
                if command == b"resume":
                    ready.set_result(None)
                    return
                if command == b"abort":
                    raise ScrapeError("用户取消人工接管；不继续访问其他页面")
                _emit(progress, "等待人工处理；仅接受 resume（检查当前页）或 abort（结束）")
            if len(buffer) > 1024:
                buffer.clear()
        except Exception as exc:
            ready.set_exception(exc)

    loop.add_reader(descriptor, received)
    try:
        await ready
    finally:
        loop.remove_reader(descriptor)


async def _communicate_manual_capture(
    process: asyncio.subprocess.Process, request: dict[str, Any], page_index: int,
    expected_total: int | None, timeout: float, progress: Progress | None,
) -> dict[str, Any]:
    """人工等待无自动超时；只在用户确认后验收，未通过就保持原窗口。"""
    if process.stdin is None or process.stdout is None or process.stderr is None:
        raise ScrapeError("人工接管缺少进程控制管道")

    async def send(value: dict[str, Any]) -> None:
        process.stdin.write((json.dumps(value) + "\n").encode("utf-8"))
        await process.stdin.drain()

    async def discard_stderr() -> None:
        while await process.stderr.read(65536):
            pass

    stderr_task = asyncio.create_task(discard_stderr())
    try:
        await send(request)
        while True:
            line = await asyncio.wait_for(process.stdout.readline(), timeout=timeout)
            if not line:
                raise ScrapeError("人工接管进程已退出，未接受列表数据")
            try:
                event = json.loads(line)
            except (ValueError, UnicodeDecodeError) as exc:
                raise ScrapeError("人工接管返回无效控制消息；不输出正文") from exc
            if not isinstance(event, dict):
                raise ScrapeError("人工接管返回无效控制消息")
            if event.get("event") == "manual_handoff_ready":
                known_paths = {"/ugreen.ph", "/verify/captcha", "/verify/traffic", "/verify/traffic/error", "/buyer/login"}
                page_path = event.get("page_path")
                if isinstance(page_path, str) and page_path in known_paths:
                    _emit(progress, f"人工接管当前页面：{page_path}")
                _emit(progress, f"人工接管：浏览器窗口保持打开；请处理验证并回到待采集的 Top Sales 第 {page_index + 1} 页。"
                      f"目标链接：{STORE_PAGE_URL_TEMPLATE.format(page=page_index)}。"
                      "确认后由控制终端发送 resume；等待期间不关闭、刷新或重试")
                control = asyncio.create_task(_wait_for_manual_resume(progress))
                exited = asyncio.create_task(process.wait())
                try:
                    done, _ = await asyncio.wait((control, exited), return_when=asyncio.FIRST_COMPLETED)
                    if exited in done:
                        raise ScrapeError("人工接管浏览器进程已退出")
                    await control
                finally:
                    control.cancel()
                    exited.cancel()
                    await asyncio.gather(control, exited, return_exceptions=True)
                await send({"command": "resume"})
            elif event.get("event") == "manual_snapshot":
                snapshot = event.get("snapshot")
                try:
                    _validate_list_snapshot(snapshot, page_index, expected_total, progress=progress)
                except (ScrapeError, ValueError, TypeError, KeyError):
                    _emit(progress, "当前页面尚未通过列表验收；保留同一窗口，继续等待人工处理，不自动重试")
                    await send({"command": "hold"})
                    continue
                except Exception as exc:
                    kind = type(exc).__name__
                    _emit(progress, f"当前页解析器内部异常（{kind}）；保留窗口，不输出页面正文")
                    await send({"command": "hold"})
                    continue
                await send({"command": "accept"})
                process.stdin.close()
                code = await asyncio.wait_for(process.wait(), timeout=15)
                if code != 0:
                    raise ScrapeError("人工接管列表已验收，但浏览器未正常结束")
                return snapshot
            elif event.get("event") == "manual_snapshot_error":
                stages = {"settle", "title", "content", "probe", "access_check", "metadata"}
                stage = event.get("stage")
                label = stage if isinstance(stage, str) and stage in stages else "unknown"
                _emit(progress, f"当前页读取异常（阶段 {label}）；窗口仍保留，等待下一次人工确认")
            else:
                kinds = {"config", "runtime", "navigation", "timeout", "cleanup", "manual"}
                kind = event.get("error_kind")
                label = kind if isinstance(kind, str) and kind in kinds else "unknown"
                raise ScrapeError(f"人工接管进程报告失败（{label}）；不输出内部正文")
    finally:
        stderr_task.cancel()
        await asyncio.gather(stderr_task, return_exceptions=True)


async def _capture_list_page_attempt(
    user_data_dir: Path,
    page_index: int,
    config: BrowserConfig,
    expected_total: int | None,
    *,
    progress: Progress | None = None,
) -> dict[str, Any]:
    """每次重启 Node 与私有 Chrome；在关闭后离线解析原始 HTML。"""
    _emit(progress, f"列表页 {page_index + 1}：Node/preload 读取 HTML，"
          f"加载后完整等待 {config.list_settle_ms / 1000:g} 秒；沿用本轮真实会话副本")
    if config.manual_list_handoff:
        snapshot = await _capture_node_list_snapshot(
            user_data_dir, page_index, config, expected_total=expected_total, progress=progress,
        )
    else:
        snapshot = await _capture_node_list_snapshot(user_data_dir, page_index, config)
    return _validate_list_snapshot(snapshot, page_index, expected_total, progress=progress)


def _validate_list_snapshot(
    snapshot: dict[str, Any], page_index: int, expected_total: int | None,
    *, progress: Progress | None = None,
) -> dict[str, Any]:
    from list_html import parse_list_html

    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("html"), str) \
            or not isinstance(snapshot.get("final_url"), str):
        raise ScrapeError("Node 列表快照缺少 HTML 或最终 URL")
    status = snapshot.get("http_status")
    if status is not None and type(status) is not int:
        raise ScrapeError("Node 列表快照的 HTTP 状态无效")
    if snapshot.get("access_error") is not None and not isinstance(snapshot["access_error"], str):
        raise ScrapeError("Node 列表快照的访问状态无效")
    try:
        payload = parse_list_html(
            snapshot["html"], final_url=snapshot["final_url"],
            expected_shop_id=SHOP_ID, page_index=page_index,
        )
    except (TypeError, ValueError) as exc:
        raise ScrapeError("Node 已读取 HTML，但无法离线解析列表") from exc
    payload["stealth_probe"] = snapshot.get("stealth_probe")
    probe_pass = _valid_stealth_probe(payload["stealth_probe"])
    _emit(progress, f"HTML 单次快照：路径={urlsplit(snapshot['final_url']).path}，"
          f"商品卡={len(payload.get('cards') or [])}，结果区域={payload.get('result_view_count')}，"
          f"页面注入探针={'通过' if probe_pass else '未通过'}")
    status = snapshot.get("http_status")
    if status in CHALLENGE_HTTP_STATUSES:
        raise AccessChallengeError(f"Shopee 拒绝当前访问线路：HTTP {status}")
    access_error = snapshot.get("access_error")
    if access_error:
        raise AccessChallengeError(str(access_error))
    if _is_challenge_url(snapshot["final_url"]):
        raise AccessChallengeError(f"Shopee 进入验证页：{urlsplit(snapshot['final_url']).path}")
    if _is_login_url(snapshot["final_url"]):
        raise AccessChallengeError("Shopee 进入登录页；本轮不等待人工操作")
    if isinstance(status, int) and status >= 400:
        raise ScrapeError(f"HTTP {status}")
    return _validate_list_payload(payload, page_index, expected_total)


async def _capture_list_page_with_profile(
    user_data_dir: Path,
    page_index: int,
    config: BrowserConfig,
    expected_total: int | None,
    *,
    progress: Progress | None = None,
) -> dict[str, Any]:
    """沿用昨日列表的有界重试：失败快照不接收，重启浏览器复用同一临时会话。"""

    attempt_config = replace(config, retries=1)
    max_attempts = 1 if config.manual_list_handoff else config.retries
    for attempt in range(1, max_attempts + 1):
        try:
            return await _capture_list_page_attempt(
                user_data_dir,
                page_index,
                attempt_config,
                expected_total,
                progress=progress,
            )
        except ScrapeError:
            if attempt == max_attempts:
                raise
            wait_ms = max(10_000, config.retry_backoff_ms) * 2 ** (attempt - 1)
            _emit(
                progress,
                f"列表页 {page_index + 1} 第 {attempt} 次未通过；"
                f"等待 {wait_ms / 1000:g} 秒后重启浏览器，沿用同一临时会话",
            )
            await asyncio.sleep(wait_ms / 1000)
    raise ScrapeError("列表尝试次数无效")


async def _historical_list_preflight(
    user_data_dir: Path,
    config: BrowserConfig,
    progress: Progress | None,
) -> int:
    """复现历史同 profile 先访问可见第 2 页；不把预访问卡片计入全量。"""
    _emit(progress, "历史顺序预访问：先读取第 2 页，再在同一临时会话从第 1 页开始")
    payload = await _capture_list_page_with_profile(
        user_data_dir, 1, config, None, progress=progress,
    )
    _emit(progress, f"历史顺序预访问通过：第 2/{payload['total']} 页，"
          f"{len(payload['cards'])} 个商品卡；仅用于复现会话顺序")
    await asyncio.sleep(config.list_interval_ms / 1000)
    return int(payload["total"])


async def _collect_listing(
    user_data_dir: Path,
    config: BrowserConfig,
    progress: Progress | None,
) -> tuple[list[ProductCard], int, int, int]:
    products: list[ProductCard] = []
    seen: set[tuple[str, str]] = set()
    total_pages: int | None = (
        await _historical_list_preflight(user_data_dir, config, progress)
        if config.historical_list_preflight else None
    )
    page_index = 0
    occurrences = 0
    duplicates = 0
    previous_fingerprint: tuple[str, ...] | None = None

    while total_pages is None or page_index < total_pages:
        payload = await _capture_list_page_with_profile(
            user_data_dir,
            page_index,
            config,
            total_pages,
            progress=progress,
        )
        if total_pages is None:
            total_pages = int(payload["total"])
            if total_pages < 1:
                raise ScrapeError("Shopee 分页器未返回任何页面")
        raw_cards = payload["cards"]
        fingerprint = tuple(str(value["item_id"]) for value in raw_cards)
        if fingerprint == previous_fingerprint:
            raise ScrapeError(f"列表页 {page_index + 1} 与上一页重复")
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
        if page_index < total_pages:
            await asyncio.sleep(config.list_interval_ms / 1000)

    captured_pages = page_index
    if total_pages is not None and captured_pages != total_pages:
        raise ScrapeError(
            f"列表翻页在 {captured_pages}/{total_pages} 页处停止"
        )
    if not products:
        raise ScrapeError("Top Sales 列表中未找到商品")
    return products, captured_pages, occurrences, duplicates


def _same_identity(value: Any, expected: tuple[str, str]) -> bool:
    return isinstance(value, dict) and (
        str(value.get("shop_id")), str(value.get("item_id"))
    ) == expected


def _validate_detail_payload(
    payload: dict[str, Any], expected: tuple[str, str]
) -> None:
    if payload.get("bff") is None:
        raise ScrapeError("缺少匹配的 PDP 数据")
    if not _same_identity(payload.get("location_identity"), expected):
        raise ScrapeError("最终页面 URL 与请求商品不匹配")
    for label in ("canonical_identity", "og_identity"):
        identity = payload.get(label)
        present_key = "canonical_present" if label == "canonical_identity" else "og_present"
        if payload.get(present_key) and identity is None:
            raise ScrapeError(f"{label} 存在，但不是有效的 Shopee PDP URL")
        if identity is not None and not _same_identity(identity, expected):
            raise ScrapeError(f"{label} 与请求商品不匹配")
    if not _valid_stealth_probe(payload.get("stealth_probe")):
        raise ScrapeError("浏览器 JS 注入探针与要求值不匹配")


async def _wait_for_detail(
    page: Page, card: ProductCard, config: BrowserConfig
) -> dict[str, Any]:
    expected = (card.shop_id, card.item_id)
    deadline = (
        asyncio.get_running_loop().time()
        + config.detail_identity_timeout_ms / 1000
    )
    last: dict[str, Any] | None = None
    while asyncio.get_running_loop().time() < deadline:
        if await _wait_for_login(page, config, card.product_url):
            deadline = asyncio.get_running_loop().time() + config.detail_identity_timeout_ms / 1000
        payload = await page.evaluate(
            DETAIL_PAGE_SCRIPT,
            {"shop_id": card.shop_id, "item_id": card.item_id},
        )
        last = payload
        if payload.get("challenge"):
            raise AccessChallengeError("Shopee 当前访问线路进入验证页")
        if payload.get("bff") is not None and _same_identity(
            payload.get("location_identity"), expected
        ):
            _validate_detail_payload(payload, expected)
            await page.wait_for_timeout(config.detail_settle_ms)
            settled = await page.evaluate(
                DETAIL_PAGE_SCRIPT,
                {"shop_id": card.shop_id, "item_id": card.item_id},
            )
            if settled.get("challenge"):
                raise AccessChallengeError("Shopee 当前访问线路在详情页进入验证页")
            _validate_detail_payload(settled, expected)
            return settled
        await page.wait_for_timeout(350)
    candidates = (last or {}).get("candidates") or []
    raise ScrapeError(
        "等待匹配的 PDP 数据超时；候选项="
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
            f"内嵌 PDP 身份 {identity!r} 与 {card.shop_id}/{card.item_id} 不匹配"
        )

    tiers = [_as_dict(value) for value in _as_list(item.get("tier_variations"))]
    models = _as_list(item.get("models"))
    if not models:
        raise ScrapeError(f"PDP {card.item_id} 未提供 SKU 型号")
    sku_rows: list[SkuRecord] = []
    model_ids: set[str] = set()
    for raw_model in models:
        model = _as_dict(raw_model)
        model_id_value = _first(model.get("model_id"), model.get("modelid"))
        if model_id_value is None:
            raise ScrapeError(f"PDP {card.item_id} 包含没有 ID 的型号")
        model_id = str(model_id_value)
        if not model_id.isdigit() or model_id in model_ids:
            raise ScrapeError(f"PDP {card.item_id} 包含无效或重复的型号 ID")
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
        raise ScrapeError(f"PDP {card.item_id} 没有商品图片集")
    for image_url in gallery:
        parts = urlsplit(image_url)
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            raise ScrapeError(f"PDP {card.item_id} 包含无效图片 URL")

    known_details = card.monthly_sales_observation == "not_collected"
    title = card.title or str(_first(item.get("title"), item.get("name"), ""))
    if known_details:
        fresh_title = _first(item.get("title"), item.get("name"))
        if not isinstance(fresh_title, str) or not fresh_title.strip():
            raise ScrapeError(f"PDP {card.item_id} 缺少本次读取的商品标题")
        title = fresh_title.strip()

    return ProductRecord(
        global_rank=None if known_details else rank,
        source_page=card.source_page,
        source_position=card.source_position,
        shop_id=card.shop_id,
        item_id=card.item_id,
        title=title,
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
    page: Page, card: ProductCard, rank: int, config: BrowserConfig,
    *, progress: Progress | None = None,
) -> ProductRecord:
    requested_identity = _url_identity(card.product_url)
    if requested_identity != (card.shop_id, card.item_id):
        raise ScrapeError(f"商品 {card.item_id} 的列表页 URL 身份已变化")
    _watch_access(page)
    document_watch = _watch_detail_document(page) if config.manual_list_handoff else None
    last_error = "未知错误"
    for attempt in range(1, config.retries + 1):
        try:
            generation = document_watch.generation if document_watch is not None else None
            response = await page.goto(
                card.product_url,
                wait_until="domcontentloaded",
                timeout=config.detail_navigation_timeout_ms,
            )
            if (document_watch is not None and document_watch.generation == generation
                    and response is not None):
                # goto 的返回响应属于主文档；正常 response 事件已记录时不能二次重置 API。
                document_watch.record(response.status)
            await _wait_for_login(page, config, card.product_url)
            if response is not None and response.status in CHALLENGE_HTTP_STATUSES:
                raise AccessChallengeError(
                    f"Shopee 拒绝当前访问线路：HTTP {response.status}"
                )
            if _is_challenge_url(page.url):
                raise AccessChallengeError(
                    f"Shopee 当前访问线路进入验证页：{urlsplit(page.url).path}"
                )
            if response is not None and response.status >= 400:
                raise ScrapeError(f"HTTP {response.status}")
            payload = await _wait_for_detail(page, card, config)
            record = _parse_detail(card, payload, rank)
            if config.manual_list_handoff:
                await _check_manual_detail_access(page)
            else:
                await _check_access(page)
            return record
        except AccessChallengeError:
            if config.manual_list_handoff:
                return await _resume_manual_detail(page, card, rank, config, progress)
            raise
        except Exception as exc:
            if config.manual_list_handoff:
                return await _resume_manual_detail(page, card, rank, config, progress)
            if _is_challenge_url(page.url):
                raise AccessChallengeError(
                    f"Shopee 当前访问线路进入验证页：{urlsplit(page.url).path}"
                ) from exc
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < config.retries:
                await _park_and_wait(page, config.retry_backoff_ms * (2 ** (attempt - 1)))
    raise ScrapeError(
        f"详情页 {rank}（{card.shop_id}/{card.item_id}）尝试 "
        f"{config.retries} 次后仍失败：{last_error}"
    )


def _replace_detail_access_watch(page: Page) -> None:
    """仅新主文档边界更换 API 观测代际；人工确认本身不能清除访问错误。"""
    previous = getattr(page, "_ugreen_access_watch", None)
    if previous is not None:
        page.remove_listener("response", previous._received)
        page.remove_listener("close", previous._closed)
        pending = tuple(previous.tasks)
        for task in pending:
            task.cancel()
    setattr(page, "_ugreen_access_watch", _AccessWatch(page))


class _DetailDocumentWatch:
    """人工模式下只记录当前主文档的 HTTP 状态，不保存 URL、响应正文或凭据。"""

    def __init__(self, page: Page) -> None:
        self.page = page
        self.status: int | None = None
        self.generation = 0
        page.on("response", self._received)

    def record(self, status: Any) -> None:
        self.status = status if type(status) is int else None
        self.generation += 1
        _replace_detail_access_watch(self.page)

    def _received(self, response: Any) -> None:
        try:
            request = response.request
            if not request.is_navigation_request() or request.frame != self.page.main_frame:
                return
            self.record(response.status)
        except Exception:
            # 非 frame 请求（例如 service worker）不应改变当前主文档状态。
            return


def _watch_detail_document(page: Page) -> _DetailDocumentWatch:
    watch = getattr(page, "_ugreen_detail_document_watch", None)
    if watch is None:
        watch = _DetailDocumentWatch(page)
        setattr(page, "_ugreen_detail_document_watch", watch)
    return watch


async def _check_manual_detail_access(page: Page) -> None:
    status = _watch_detail_document(page).status
    if status is None:
        raise ScrapeError("当前详情主文档 HTTP 状态尚未确认")
    if status in CHALLENGE_HTTP_STATUSES:
        raise AccessChallengeError(f"当前详情主文档仍拒绝访问：HTTP {status}")
    if status >= 400:
        raise ScrapeError(f"当前详情主文档仍为 HTTP {status}")
    await _check_access(page)


async def _resume_manual_detail(
    page: Page, card: ProductCard, rank: int, config: BrowserConfig,
    progress: Progress | None,
) -> ProductRecord:
    """同页等待用户处理；确认仅触发读取和严校验，不导航、刷新或解决验证码。"""
    public_url = f"https://shopee.ph/product/{card.shop_id}/{card.item_id}"
    while True:
        if page.is_closed():
            raise ScrapeError("详情人工接管页面已关闭，未接受该商品")
        _emit(progress, f"详情 {rank} 人工接管：当前浏览器窗口和会话保持打开。"
              f"请自行处理验证/登录或当前错误，并回到商品 {public_url}；"
              "确认后发送 resume 检查当前页，或 abort 结束；等待期间不自动刷新或跳转")
        # 控制终端关闭、用户取消及任务取消必须向上传播，不能吞掉后继续等待。
        await _wait_for_manual_resume(progress)
        if page.is_closed():
            raise ScrapeError("详情人工接管页面已关闭，未接受该商品")
        try:
            await _check_manual_detail_access(page)
            payload = await _wait_for_detail(page, card, config)
            record = _parse_detail(card, payload, rank)
            await _check_manual_detail_access(page)
            _emit(progress, f"详情 {rank} 人工确认后严校验通过："
                  f"{len(record.skus)} 个 SKU、{1 + len(record.secondary_image_urls)} 张图片")
            return record
        except Exception:
            if page.is_closed():
                raise ScrapeError("详情人工接管页面已关闭，未接受该商品") from None
            _emit(progress, f"详情 {rank} 当前页仍未通过身份、访问或数据完整性检查；"
                  "保留窗口，继续等待人工处理，不接受本次快照")


async def _visit_and_park_detail_with_manual_handoff(
    page: Page, card: ProductCard, rank: int, config: BrowserConfig,
    interval_ms: int, progress: Progress | None,
) -> ProductRecord:
    """详情快照与离页前检查作为整体验收；晚到的访问错误也先保留页面。"""
    record = await _visit_detail(page, card, rank, config, progress=progress)
    while True:
        try:
            await _check_manual_detail_access(page)
            await _park_and_wait(page, interval_ms)
            return record
        except Exception:
            # 不沿用挑战出现前的记录；用户处理后重新读取该商品全部公开数据。
            record = await _resume_manual_detail(page, card, rank, config, progress)


async def _collect_details(
    contexts: Sequence[BrowserContext],
    cards: Sequence[ProductCard],
    config: BrowserConfig,
    progress: Progress | None,
) -> list[ProductRecord]:
    if not contexts:
        raise ScrapeError("没有可用的详情页浏览器分片")
    shard_count = min(len(contexts), len(cards))
    base_size, remainder = divmod(len(cards), shard_count)
    shards: list[list[tuple[int, ProductCard]]] = []
    start = 0
    for shard_index in range(shard_count):
        size = base_size + (1 if shard_index < remainder else 0)
        stop = start + size
        shards.append(
            [(rank, cards[rank - 1]) for rank in range(start + 1, stop + 1)]
        )
        start = stop

    results: list[ProductRecord | None] = [None] * len(cards)
    completed = 0

    async def run_shard(
        shard_index: int,
        context: BrowserContext,
        work: Sequence[tuple[int, ProductCard]],
    ) -> None:
        nonlocal completed
        page = await context.new_page()
        first_rank = work[0][0]
        last_rank = work[-1][0]
        order_label = "清单序号" if work[0][1].monthly_sales_observation == "not_collected" else "排名"
        _emit(
            progress,
            f"详情分片 {shard_index + 1}/{shard_count} 开始：{order_label} {first_rank}-{last_rank}",
        )
        try:
            for rank, card in work:
                interval_ms = config.detail_interval_ms if rank != last_rank else 0
                if config.manual_list_handoff:
                    results[rank - 1] = await _visit_and_park_detail_with_manual_handoff(
                        page, card, rank, config, interval_ms, progress,
                    )
                else:
                    results[rank - 1] = await _visit_detail(page, card, rank, config)
                    await _park_and_wait(page, interval_ms)
                completed += 1
                if completed == len(cards) or completed % 10 == 0:
                    _emit(
                        progress,
                        f"详情页 {completed}/{len(cards)}：成功 {completed}，失败 0",
                    )
        finally:
            await page.close()

    tasks = [
        asyncio.create_task(run_shard(index, contexts[index], shards[index]))
        for index in range(shard_count)
    ]
    try:
        await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise

    completed_results = [value for value in results if value is not None]
    if len(completed_results) != len(cards):
        raise ScrapeError(
            f"详情页完整性校验失败：{len(completed_results)}/{len(cards)}"
        )
    return completed_results


def _select_verification_targets(reference_workbook: Path) -> list[ProductCard]:
    """旧表仅提供跨页 URL/ID；价格、月销和商品描述不进入本次数据。"""
    from openpyxl import load_workbook

    if not reference_workbook.is_file():
        raise FileNotFoundError(f"找不到用于选择复测链接的参考表：{reference_workbook}")
    workbook = load_workbook(reference_workbook, read_only=True, data_only=True)
    try:
        if "商品汇总" not in workbook.sheetnames:
            raise ValueError("参考表缺少商品汇总工作表")
        sheet = workbook["商品汇总"]
        headers = next(sheet.iter_rows(min_row=6, max_row=6, values_only=True))
        required = ("列表页", "店铺ID", "商品ID", "商品链接")
        if any(headers.count(name) != 1 for name in required):
            raise ValueError("参考表第 6 行的列表页、身份或链接表头缺失/重复")
        indices = {name: headers.index(name) for name in required}
        by_page: dict[int, list[ProductCard]] = {}
        seen: set[tuple[str, str]] = set()
        for row in sheet.iter_rows(min_row=7, values_only=True):
            if not any(value is not None for value in row):
                continue
            number = row[indices["列表页"]]
            identity = (str(row[indices["店铺ID"]]), str(row[indices["商品ID"]]))
            url = str(row[indices["商品链接"]] or "")
            if (not isinstance(number, int) or isinstance(number, bool) or number < 1
                    or identity[0] != SHOP_ID or _url_identity(url) != identity):
                raise ValueError("参考表包含无效的 UGREEN 商品身份、页码或链接")
            if identity in seen:
                continue
            seen.add(identity)
            # 此占位卡只送入详情解析；验证模式没有 ScrapeResult，也没有导出路径。
            card = ProductCard(number - 1, 0, *identity, "", url, 0, None, None, None,
                               "verification_only")
            by_page.setdefault(number, []).append(card)
        pages = sorted(by_page)
        if not pages:
            raise ValueError("参考表没有可验证的商品链接")
        selected_pages = sorted({pages[0], pages[len(pages) // 2], pages[-1]})
        return [by_page[number][-1 if number == pages[-1] else 0]
                for number in selected_pages]
    finally:
        workbook.close()


def _read_known_product_reference(
    reference_workbook: Path,
) -> tuple[list[ProductCard], dict[str, Any]]:
    """从同一次只读快照取全部唯一身份/链接；不接收任何历史商品数据。"""
    from openpyxl import load_workbook

    reference = reference_workbook.expanduser().resolve()
    if not reference.is_file():
        raise FileNotFoundError(f"找不到已知商品范围参考表：{reference}")
    snapshot = reference.read_bytes()
    workbook = load_workbook(BytesIO(snapshot), read_only=True, data_only=False)
    try:
        if "商品汇总" not in workbook.sheetnames:
            raise ValueError("参考表缺少商品汇总工作表")
        sheet = workbook["商品汇总"]
        captured_at = sheet["B3"].value
        if (sheet["A3"].value != "采集时间" or not isinstance(captured_at, str)
                or re.fullmatch(r"\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}", captured_at) is None):
            raise ValueError("参考表缺少可确认的采集时间；不得用文件修改时间代替")
        try:
            reference_date = datetime.strptime(captured_at, "%Y/%m/%d %H:%M:%S").date()
        except ValueError as exc:
            raise ValueError("参考表采集时间不是有效日期") from exc
        headers = next(sheet.iter_rows(min_row=6, max_row=6, values_only=True))
        required = ("店铺ID", "商品ID", "商品链接")
        if any(headers.count(name) != 1 for name in required):
            raise ValueError("参考表第 6 行的身份或链接表头缺失/重复")
        indices = {name: headers.index(name) for name in required}
        cards: list[ProductCard] = []
        seen: set[tuple[str, str]] = set()
        for row in sheet.iter_rows(min_row=7, values_only=True):
            if not any(value is not None for value in row):
                continue
            shop_id, item_id = (row[indices[name]] for name in required[:2])
            url = row[indices["商品链接"]]
            if (not isinstance(shop_id, str) or not isinstance(item_id, str)
                    or shop_id != SHOP_ID or not re.fullmatch(r"[1-9]\d*", item_id)
                    or not isinstance(url, str)
                    or _url_identity(url) != (shop_id, item_id)):
                raise ValueError("参考表包含无效的 UGREEN 商品身份或链接")
            parsed = urlsplit(url)
            if parsed.username is not None or parsed.password is not None or parsed.port not in (None, 443):
                raise ValueError("参考表商品链接包含用户信息或非标准端口")
            identity = (shop_id, item_id)
            if identity in seen:
                continue
            seen.add(identity)
            # 来源位置、价格、月销等全部未知；旧标题、SKU 和图片从未读取。
            cards.append(ProductCard(
                source_page=None, source_position=None, shop_id=shop_id, item_id=item_id,
                title="", product_url=url, price_php=None,
                monthly_sales_display=None, monthly_sales_text=None,
                monthly_sales_count_lower_bound=None, monthly_sales_observation="not_collected",
            ))
        if not cards:
            raise ValueError("参考表没有已知商品链接")
        identity_text = "\n".join(f"{card.shop_id}:{card.item_id}" for card in cards)
        metadata = {
            "reference_workbook": str(reference),
            "reference_sha256": hashlib.sha256(snapshot).hexdigest(),
            "reference_captured_at": captured_at,
            "reference_date": reference_date.isoformat(),
            "reference_unique_count": len(cards),
            "reference_identity_sha256": hashlib.sha256(identity_text.encode("utf-8")).hexdigest(),
        }
        return cards, metadata
    finally:
        workbook.close()


async def verify_access(
    config: BrowserConfig,
    reference_workbook: Path,
    *,
    details_only: bool = False,
    progress: Progress | None = None,
) -> dict[str, Any]:
    """复用正式实现做有限访问诊断；从不创建/刷新工作簿。"""
    config.validate()
    if config.detail_shards != 1:
        raise ValueError("访问复测只允许单并发")
    reference_metadata: dict[str, Any] = {}
    if details_only:
        known_cards, reference_metadata = _read_known_product_reference(reference_workbook)
        positions = sorted({0, len(known_cards) // 2, len(known_cards) - 1})
        targets = [known_cards[position] for position in positions]
    else:
        targets = _select_verification_targets(reference_workbook)
    _stealth_script()
    report: dict[str, Any] = {
        "mode": "verify_access", "list_pass": None if details_only else False,
        "details_only": details_only, "list_skipped": details_only, "list_pages_checked": 0,
        "list_error": None, "details": [], "detail_success_count": 0,
        "detail_attempted_count": 0, "detail_target_count": len(targets),
        "full_crawl_completed": False, "workbook_written": False,
        "historical_list_preflight": config.historical_list_preflight and not details_only,
        "preflight_pass": False if config.historical_list_preflight and not details_only else None,
        "injection_sha256": STEALTH_SHA256,
        "scope": ("仅已知商品清单首、中、末详情抽查；未访问列表，不验证全量详情完整性"
                  if details_only else
                  "仅列表首屏（可选历史第 2 页预访问）与跨页详情快照；不验证全店完整性或详情长驻稳定性"),
        "collection_mode": "known_product_details" if details_only else "full_topsales",
        "scope_metadata": reference_metadata,
    }
    with _temporary_chrome_profile_base() as base_profile:
        if details_only:
            _emit(progress, f"仅详情访问复测：已知清单 {len(known_cards)} 个商品，抽查 {len(targets)} 个，不访问列表或发布 Excel")
        else:
            _emit(progress, "访问复测：检查 Top Sales 列表首屏，不发布 Excel")
            try:
                expected_total = None
                if config.historical_list_preflight:
                    expected_total = await _historical_list_preflight(base_profile, config, progress)
                    report.update(preflight_pass=True, list_pages_checked=1)
                listing = await _capture_list_page_with_profile(
                    base_profile, 0, config, expected_total, progress=progress
                )
                report.update(list_pass=True, list_pages_checked=1 + int(config.historical_list_preflight),
                              observed_total_pages=listing["total"])
                _emit(progress, f"列表首屏通过：{len(listing['cards'])} 个商品卡")
            except CaptureCleanupError:
                raise
            except Exception as exc:
                if config.manual_list_handoff:
                    raise
                report["list_error"] = str(exc)
                _emit(progress, f"列表未通过：{exc}；仅继续独立详情诊断，不进入全量发布")
            await asyncio.sleep(config.list_interval_ms / 1000)
        context = await _launch_context(config, base_profile)
        try:
            page = await context.new_page()
            try:
                for index, target in enumerate(targets, 1):
                    outcome: dict[str, Any] = {
                        "shop_id": target.shop_id, "item_id": target.item_id,
                        "reference_source_page": (target.source_page + 1
                                                  if target.source_page is not None else None),
                        "passed": False,
                    }
                    report["details"].append(outcome)
                    report["detail_attempted_count"] += 1
                    source_label = (f"参考表第 {target.source_page + 1} 页"
                                    if target.source_page is not None else "已知清单")
                    _emit(progress, f"详情复测 {index}/{len(targets)}："
                                    f"{source_label}商品 {target.item_id}")
                    try:
                        interval_ms = config.detail_interval_ms if index < len(targets) else 0
                        if config.manual_list_handoff:
                            product = await _visit_and_park_detail_with_manual_handoff(
                                page, target, index, config, interval_ms, progress,
                            )
                        else:
                            product = await _visit_detail(page, target, index, config)
                            await _park_and_wait(page, interval_ms)
                        outcome.update(passed=True, title=product.title,
                                       sku_count=len(product.skus),
                                       gallery_count=1 + len(product.secondary_image_urls))
                        report["detail_success_count"] += 1
                        _emit(progress, f"详情快照通过：{len(product.skus)} 个 SKU、"
                                        f"{1 + len(product.secondary_image_urls)} 张图片")
                    except Exception as exc:
                        outcome["error"] = str(exc)
                        _emit(progress, f"详情复测停止：{exc}")
                        break
            finally:
                await page.close()
        finally:
            await _close_context(context)
    return report


async def scrape_known_details(
    config: BrowserConfig | None,
    reference_workbook: Path,
    *,
    no_new_products_confirmed: bool = False,
    progress: Progress | None = None,
) -> ScrapeResult:
    """以用户确认无新增的历史身份清单为边界，只刷新每个商品的当前 PDP。"""
    if no_new_products_confirmed is not True:
        raise ValueError("已知商品全量详情刷新需要用户明确确认本次没有新增商品")
    config = config or BrowserConfig()
    config.validate()
    if config.detail_shards != 1:
        raise ValueError("已知商品全量详情刷新只允许单路访问")
    cards, metadata = _read_known_product_reference(reference_workbook)
    metadata["user_confirmed_no_new_products"] = True
    _stealth_script()
    _emit(progress, f"已知商品全量详情刷新：参考 {metadata['reference_date']} 清单，"
                    f"共 {len(cards)} 个唯一商品；不访问列表，不复用历史价格、月销、SKU 或图片")
    with _temporary_chrome_profile_base() as base_profile:
        context = await _launch_context(config, base_profile)
        try:
            products = await _collect_details([context], cards, config, progress)
        finally:
            await _close_context(context)

    expected_identities = [(card.shop_id, card.item_id) for card in cards]
    actual_identities = [(product.shop_id, product.item_id) for product in products]
    if actual_identities != expected_identities:
        raise ScrapeError("已知商品详情完整性校验失败：结果必须与完整参考身份清单逐项一致")
    for product, card in zip(products, cards):
        if (_url_identity(product.product_url) != (card.shop_id, card.item_id)
                or not isinstance(product.title, str) or not product.title.strip()
                or product.global_rank is not None or product.source_page is not None
                or product.source_position is not None or product.price_php is not None
                or product.monthly_sales_text is not None
                or product.monthly_sales_count_lower_bound is not None
                or product.monthly_sales_observation != "not_collected"):
            raise ScrapeError("已知商品详情存在历史列表数据混入或缺少实时身份/标题")
    audit = ScrapeAudit(
        list_page_count=0,
        list_input_product_occurrences=0,
        list_duplicate_occurrence_count=0,
        listed_product_count=len(cards),
        detail_success_count=len(products),
        detail_failure_count=0,
        products_without_monthly_sales_display=0,
    )
    return ScrapeResult(
        store_url=STORE_URL,
        captured_at=datetime.now(timezone.utc),
        products=products,
        audit=audit,
        collection_mode="known_product_details",
        scope_metadata=metadata,
    )


async def scrape_all(
    config: BrowserConfig | None = None,
    *,
    progress: Progress | None = None,
) -> ScrapeResult:
    """将固定范围内完整的 UGREEN Top Sales 数据抓取到内存。"""

    config = config or BrowserConfig()
    config.validate()

    with _temporary_chrome_profile_base() as base_profile:
        cards, page_count, occurrences, duplicates = await _collect_listing(
            base_profile,
            config,
            progress,
        )
        user_data_dirs = _clone_detail_profiles(
            base_profile, config.detail_shards
        )
        _emit(
            progress,
            f"列表抓取完成；从列表会话克隆并启动 {config.detail_shards} 个"
            f"独立临时档案分片，逐个进入 {len(cards)} 个商品详情页",
        )
        contexts: list[BrowserContext] = []
        try:
            contexts = await _launch_contexts(config, user_data_dirs)
            products = await _collect_details(contexts, cards, config, progress)
        finally:
            await asyncio.gather(
                *(_close_context(context) for context in contexts),
                return_exceptions=True,
            )

    if any(product.global_rank != index for index, product in enumerate(products, 1)):
        raise ScrapeError("商品排名或顺序校验失败")
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
