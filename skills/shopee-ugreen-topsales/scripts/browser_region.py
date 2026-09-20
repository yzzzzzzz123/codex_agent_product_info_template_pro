"""按查询域观测到的系统代理出口选择本轮浏览器地区，不改变代理或硬件配置。

检测使用空白私有 Chrome profile，不读取真实会话。ipwho.is 的观测仅适用于该
查询域；系统代理/PAC/规则分流可能让 Shopee 使用不同出口，不能据此证明其出口、
站点地区判定或账号状态。国家到语言的映射是明确的默认配置，不代表用户母语。
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from playwright.async_api import async_playwright


LOOKUP_URL = "https://ipwho.is/?fields=success,country_code,timezone.id"
LOOKUP_TIMEOUT_SECONDS = 20
CLEANUP_TIMEOUT_SECONDS = 5
MAX_RESPONSE_BYTES = 64 * 1024
COUNTRY_LOCALES = {
    "US": "en-US", "SG": "en-SG", "PH": "en-PH",
    "GB": "en-GB", "CA": "en-CA", "AU": "en-AU", "NZ": "en-NZ",
    "IE": "en-IE", "IN": "en-IN",
    "DE": "de-DE", "FR": "fr-FR", "NL": "nl-NL", "ES": "es-ES",
    "IT": "it-IT", "PL": "pl-PL", "SE": "sv-SE", "CH": "de-CH",
    "JP": "ja-JP", "KR": "ko-KR", "CN": "zh-CN", "TW": "zh-TW",
    "HK": "zh-HK", "ID": "id-ID", "MY": "ms-MY", "TH": "th-TH",
    "VN": "vi-VN", "BR": "pt-BR", "MX": "es-MX", "TR": "tr-TR",
    "AE": "ar-AE", "SA": "ar-SA", "ZA": "en-ZA",
}
_TIMEZONE_PATTERN = re.compile(r"[A-Za-z0-9_+.-]+(?:/[A-Za-z0-9_+.-]+)*")
_NORMALIZE_TIMEZONE = """timezone =>
    Intl.DateTimeFormat('en-US', {timeZone: timezone}).resolvedOptions().timeZone
"""


class _RegionError(ValueError):
    """只包含固定诊断信息，不包含查询响应、IP、Cookie 或底层异常正文。"""


@dataclass(frozen=True)
class BrowserRegion:
    country_code: str
    locale: str
    languages: tuple[str, ...]
    timezone_id: str

    def validate(self) -> None:
        if not isinstance(self.country_code, str) or self.country_code not in COUNTRY_LOCALES:
            raise _RegionError("出口国家不在已审阅地区映射内；不猜测浏览器地区")
        expected_locale = COUNTRY_LOCALES[self.country_code]
        if self.locale != expected_locale:
            raise _RegionError("浏览器 locale 与国家映射不一致")
        expected_languages = (expected_locale, expected_locale.split("-", 1)[0])
        if not isinstance(self.languages, tuple) or self.languages != expected_languages:
            raise _RegionError("浏览器 languages 与国家映射不一致")
        if (not isinstance(self.timezone_id, str) or not self.timezone_id
                or len(self.timezone_id) > 128
                or _TIMEZONE_PATTERN.fullmatch(self.timezone_id) is None):
            raise _RegionError("出口时区不是有效的 IANA 时区")
        try:
            ZoneInfo(self.timezone_id)
        except (ZoneInfoNotFoundError, ValueError):
            raise _RegionError("出口时区不是可识别的 IANA 时区") from None

    def to_dict(self) -> dict[str, object]:
        self.validate()
        return {
            "country_code": self.country_code,
            "locale": self.locale,
            "languages": list(self.languages),
            "timezone_id": self.timezone_id,
        }


def region_from_payload(payload: object) -> BrowserRegion:
    """只读取 success、country_code、timezone.id；失败或未知国家不静默回退。"""
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise _RegionError("出口地区查询未明确成功")
    country = payload.get("country_code")
    if not isinstance(country, str) or country not in COUNTRY_LOCALES:
        raise _RegionError("出口国家不在已审阅地区映射内；不猜测浏览器地区")
    timezone = payload.get("timezone")
    if not isinstance(timezone, dict):
        raise _RegionError("出口地区查询缺少 IANA 时区")
    locale = COUNTRY_LOCALES[country]
    region = BrowserRegion(country, locale, (locale, locale.split("-", 1)[0]), timezone.get("id"))
    region.validate()
    return region


def _same_lookup_origin(url: object) -> bool:
    if not isinstance(url, str):
        return False
    try:
        parsed = urlsplit(url)
        return (parsed.scheme == "https" and parsed.hostname == "ipwho.is"
                and parsed.port in (None, 443)
                and parsed.username is None and parsed.password is None)
    except ValueError:
        return False


async def detect_browser_region(chrome_executable: Path, headless: bool = False) -> BrowserRegion:
    """仅查询固定域的出口地区；不能保证 Shopee 的分流出口相同。

    查询/启动/读取共用 20 秒预算；退出时分别最多等 5 秒关闭 context 和 Playwright，
    即使查询失败也尝试两项清理。全程不输出原始响应或底层异常，不复用真实 profile。
    """
    if not isinstance(chrome_executable, Path) or not chrome_executable.is_file():
        raise _RegionError("找不到已安装的系统 Chrome；不下载浏览器")
    if type(headless) is not bool:
        raise _RegionError("地区检测的 headless 参数必须为布尔值")
    executable = str(chrome_executable.resolve())
    environment = {
        key: value for key, value in os.environ.items()
        if key.lower() not in {"http_proxy", "https_proxy", "all_proxy"}
    }
    with tempfile.TemporaryDirectory(prefix="ugreen-region-") as temporary:
        profile = Path(temporary) / "profile"
        profile.mkdir(mode=0o700)
        playwright = None
        context = None

        async def lookup() -> BrowserRegion:
            nonlocal playwright, context
            playwright = await async_playwright().start()
            context = await playwright.chromium.launch_persistent_context(
                str(profile), executable_path=executable, headless=headless,
                ignore_https_errors=False, timeout=LOOKUP_TIMEOUT_SECONDS * 1000,
                env=environment,
            )

            async def restrict_request(route) -> None:
                request = route.request
                if request.method == "GET" and request.url == LOOKUP_URL:
                    await route.continue_()
                else:
                    await route.abort()

            await context.route("**/*", restrict_request)
            page = await context.new_page()
            response = await page.goto(
                LOOKUP_URL, wait_until="commit", timeout=LOOKUP_TIMEOUT_SECONDS * 1000,
            )
            if response is None or response.status != 200:
                raise _RegionError("出口地区查询未返回 HTTP 200")
            if not _same_lookup_origin(response.url) or not _same_lookup_origin(page.url):
                raise _RegionError("出口地区查询跳转到非预期来源")
            headers = await response.all_headers()
            content_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if content_type not in {"application/json", "text/json"}:
                raise _RegionError("出口地区查询未返回 JSON 内容类型")
            content_length = headers.get("content-length")
            if content_length is not None:
                if not re.fullmatch(r"[0-9]{1,20}", content_length.strip()):
                    raise _RegionError("出口地区查询响应长度无效")
                if int(content_length) > MAX_RESPONSE_BYTES:
                    raise _RegionError("出口地区查询响应超过大小上限")
            body = await response.body()
            if not isinstance(body, bytes) or len(body) > MAX_RESPONSE_BYTES:
                raise _RegionError("出口地区查询响应超过大小上限")
            try:
                payload = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise _RegionError("出口地区查询返回无效 JSON") from None
            region = region_from_payload(payload)
            # Chrome/ICU 可能返回 IANA 别名，例如 Asia/Kolkata -> Asia/Calcutta。
            # 使用同一浏览器规范化值，避免随后页面探针与有效时区别名误判不一致。
            normalized_timezone = await page.evaluate(_NORMALIZE_TIMEZONE, region.timezone_id)
            region = replace(region, timezone_id=normalized_timezone)
            region.validate()
            return region

        result = None
        failure = None
        cleanup_failed = False
        try:
            result = await asyncio.wait_for(lookup(), timeout=LOOKUP_TIMEOUT_SECONDS)
        except asyncio.CancelledError as exc:
            failure = exc
        except asyncio.TimeoutError:
            failure = _RegionError("出口地区查询超过 20 秒；未采用地区结果")
        except _RegionError as exc:
            failure = exc
        except Exception:
            failure = _RegionError("出口地区查询失败；未采用地区结果")
        finally:
            for resource in (context, playwright):
                if resource is None:
                    continue
                try:
                    close = resource.close if resource is context else resource.stop
                    await asyncio.wait_for(close(), timeout=CLEANUP_TIMEOUT_SECONDS)
                except asyncio.CancelledError as exc:
                    failure = failure or exc
                    cleanup_failed = True
                except Exception:
                    cleanup_failed = True
        if failure is not None:
            raise failure from None
        if cleanup_failed:
            raise _RegionError("出口地区查询临时浏览器未能确认正常关闭；未采用地区结果")
        if result is None:
            raise _RegionError("出口地区查询没有有效结果")
        return result
