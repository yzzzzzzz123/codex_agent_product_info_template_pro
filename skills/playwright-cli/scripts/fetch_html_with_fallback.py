#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import subprocess
import urllib.request
from pathlib import Path
from typing import Dict

SKILL_ROOT = Path(__file__).resolve().parent.parent
PROXY_SCRIPT = SKILL_ROOT / "scripts" / "proxy-access.js"
DEFAULT_VIEWPORT = {"width": 1366, "height": 768}
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


def http_get_text(url: str, *, timeout_sec: int = 20) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "*/*",
    }
    try:
        import curl_cffi.requests as creq  # type: ignore

        resp = creq.get(url, headers=headers, timeout=timeout_sec, impersonate="chrome120")
        resp.raise_for_status()
        return resp.text
    except Exception:
        pass

    try:
        import requests  # type: ignore

        resp = requests.get(url, headers=headers, timeout=timeout_sec)
        resp.raise_for_status()
        return resp.text
    except Exception:
        pass

    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
        raw = resp.read()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("utf-8", errors="ignore")


def _extract_html_title(html: str) -> str:
    m = re.search(r"(?is)<title[^>]*>(.*?)</title>", html)
    if not m:
        return ""
    return re.sub(r"\s+", " ", m.group(1)).strip()


def _looks_blocked(text: str) -> bool:
    if not text:
        return True
    lowered = text.lower()
    title = _extract_html_title(text).lower()
    if len(text) < 800:
        if any(
            k in lowered
            for k in (
                "captcha",
                "access denied",
                "just a moment",
                "security check",
                "please wait",
                "attention required",
            )
        ):
            return True
        if any(
            k in title
            for k in (
                "just a moment",
                "access denied",
                "security check",
                "please wait",
                "attention required",
            )
        ):
            return True
    if "cf-browser-verification" in lowered:
        return True
    if "cloudflare" in lowered and any(
        k in lowered
        for k in ("just a moment", "attention required", "enable cookies", "verify you are human")
    ):
        return True
    if any(k in title for k in ("page not available",)):
        return True
    if any(
        k in lowered
        for k in (
            "error code 451",
            "this page is not available in your location",
            "esta página no está disponible en tu ubicación",
        )
    ):
        return True
    return False


def _parse_bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _default_headless() -> bool:
    system = platform.system().lower()
    if system in {"windows", "darwin"}:
        return False
    return not bool(os.environ.get("DISPLAY"))


def _stealth_init_script(viewport: Dict[str, int]) -> str:
    width = int(viewport.get("width") or DEFAULT_VIEWPORT["width"])
    height = int(viewport.get("height") or DEFAULT_VIEWPORT["height"])
    return f"""
Object.defineProperty(navigator, 'webdriver', {{
  get: () => undefined,
  configurable: false
}});

const originalGetOwnPropertyNames = Object.getOwnPropertyNames;
Object.getOwnPropertyNames = new Proxy(originalGetOwnPropertyNames, {{
  apply: (target, thisArg, args) => {{
    const result = target.apply(thisArg, args);
    return result.filter(
      (name) => !name.startsWith('cdc_') && !name.startsWith('__playwright') && !name.startsWith('__pw')
    );
  }}
}});

for (const key of Object.keys(window)) {{
  if (key.startsWith('__playwright') || key.startsWith('__pw') || key.startsWith('cdc_')) {{
    try {{ delete window[key]; }} catch (e) {{}}
  }}
}}

window.chrome = {{
  runtime: {{
    onInstalled: {{ addListener: () => {{}}, removeListener: () => {{}} }},
    sendMessage: () => {{}},
    connect: () => ({{}}),
    getManifest: () => ({{ version: '122.0.0.0' }})
  }},
  loadTimes: () => ({{
    requestTime: Date.now() / 1000,
    startLoadTime: Date.now() / 1000,
    commitLoadTime: Date.now() / 1000,
    finishDocumentLoadTime: Date.now() / 1000,
    finishLoadTime: Date.now() / 1000,
    firstPaintTime: Date.now() / 1000 + 0.1,
    firstContentfulPaintTime: Date.now() / 1000 + 0.12,
    domContentLoadedEventEnd: Date.now() / 1000 + 0.2,
    loadEventEnd: Date.now() / 1000 + 0.3
  }}),
  csi: () => ({{
    startE: Date.now(),
    onloadT: Date.now() + 300,
    pageT: 300,
    tran: 150,
    dns: 20,
    conn: 50,
    resp: 80
  }}),
  app: {{
    isInstalled: false,
    getDetails: () => {{}},
    getIsInstalled: () => false
  }},
  webstore: {{
    onInstallStageChanged: {{ addListener: () => {{}} }},
    onDownloadProgress: {{ addListener: () => {{}} }}
  }}
}};

const originalPermissionQuery = window.navigator.permissions &&
  typeof window.navigator.permissions.query === 'function'
  ? window.navigator.permissions.query.bind(window.navigator.permissions)
  : null;

if (originalPermissionQuery) {{
  window.navigator.permissions.query = (parameters) => {{
    return parameters && parameters.name === 'notifications'
      ? Promise.resolve({{ state: Notification.permission }})
      : originalPermissionQuery(parameters);
  }};
}}

Object.defineProperty(navigator, 'plugins', {{
  get: () => [
    {{ name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' }},
    {{ name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefghlsjai', description: 'Portable Document Format' }},
    {{ name: 'Native Client', filename: 'internal-nacl-plugin', description: 'Native Client' }},
    {{ name: 'Widevine Content Decryption Module', filename: 'widevinecdm', description: 'Enables Widevine licenses for playback of HTML audio/video content.' }},
    {{ name: 'WebRTC Desktop Sharing', filename: 'webrtc-desktop-sharing', description: 'WebRTC Desktop Sharing' }}
  ]
}});

Object.defineProperty(navigator, 'languages', {{
  get: () => ['en-US', 'en', 'zh-CN'],
  configurable: false
}});

Object.defineProperty(navigator, 'language', {{
  get: () => 'en-US',
  configurable: false
}});

Object.defineProperty(navigator, 'platform', {{
  get: () => 'Win32',
  configurable: false
}});

Object.defineProperty(navigator, 'hardwareConcurrency', {{
  get: () => 8,
  configurable: false
}});

Object.defineProperty(navigator, 'deviceMemory', {{
  get: () => 8,
  configurable: false
}});

Object.defineProperty(window.screen, 'availWidth', {{ get: () => window.innerWidth }});
Object.defineProperty(window.screen, 'availHeight', {{ get: () => window.innerHeight }});
Object.defineProperty(window.screen, 'width', {{ get: () => {width} }});
Object.defineProperty(window.screen, 'height', {{ get: () => {height} }});
Object.defineProperty(window, 'outerWidth', {{ get: () => {width} }});
Object.defineProperty(window, 'outerHeight', {{ get: () => {height} }});
"""


def _playwright_get_html(url: str, *, timeout_ms: int = 60000) -> str:
    """普通 Playwright fallback with the same init JS used by the proxy path."""
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception as exc:
        raise RuntimeError("Playwright is not available in the current Python environment") from exc

    headless = _parse_bool_env("HEADLESS", _default_headless())
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        try:
            context = browser.new_context(
                ignore_https_errors=True,
                user_agent=DEFAULT_USER_AGENT,
                locale="en-US",
                timezone_id="America/New_York",
                viewport=DEFAULT_VIEWPORT,
                screen=DEFAULT_VIEWPORT,
            )
            context.add_init_script(_stealth_init_script(DEFAULT_VIEWPORT))
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            return page.content()
        finally:
            browser.close()


def _proxy_get_html(url: str, *, output_dir: Path) -> str:
    """Proxy Playwright fallback. Uses the bundled Node script."""
    output_dir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["node", str(PROXY_SCRIPT), url, str(output_dir)],
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        stdout = (proc.stdout or "").strip()
        raise RuntimeError(
            f"proxy-access.js failed (exit={proc.returncode}).\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}"
        )

    rendered = output_dir / "rendered_page.html"
    if not rendered.is_file():
        raise FileNotFoundError(f"proxy-access.js did not produce rendered_page.html under: {output_dir}")
    return rendered.read_text(encoding="utf-8", errors="ignore")


def fetch_text_with_fallback(
    url: str,
    *,
    enable_playwright: bool,
    enable_proxy: bool,
    tmp_dir: Path,
) -> str:
    """
    Strict fallback chain:
    1) direct fetch
    2) Python Playwright
    3) Proxy Playwright (node script)
    """
    try:
        text = http_get_text(url)
        if not _looks_blocked(text):
            return text
    except Exception:
        text = ""

    if enable_playwright:
        try:
            pw_html = _playwright_get_html(url)
            if pw_html and not _looks_blocked(pw_html):
                return pw_html
        except Exception:
            pass

    if enable_proxy:
        h = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
        out_dir = tmp_dir / f"proxy_{h}"
        proxy_html = _proxy_get_html(url, output_dir=out_dir)
        if proxy_html and not _looks_blocked(proxy_html):
            return proxy_html

    return text
