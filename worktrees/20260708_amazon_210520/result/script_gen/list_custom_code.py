import re
import html
import urllib.parse

BASE = "https://www.amazon.com"
DEFAULT_SEEDS = [
    "https://www.amazon.com/s?k=wireless+mouse",
    "https://www.amazon.com/Best-Sellers/zgbs",
]


def _headers():
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }


def _response_text(rsp):
    raw = getattr(rsp, "content", None) or b""
    if raw:
        try:
            return raw.decode("utf-8", "ignore")
        except Exception:
            pass
    return getattr(rsp, "text", "") or ""


def _clean_url(url):
    value = html.unescape(str(url or "")).strip()
    if not value:
        return None
    value = urllib.parse.urljoin(BASE, value)
    parsed = urllib.parse.urlsplit(value)
    host = (parsed.hostname or "").lower()
    if host not in {"amazon.com", "www.amazon.com"}:
        return None
    match = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})", parsed.path, re.I)
    if not match:
        return None
    asin = match.group(1).upper()
    return "https://www.amazon.com/dp/" + asin


def _detail_uris_from_html(text):
    found = []
    patterns = [
        r'href=["\']([^"\']*/(?:dp|gp/product)/[A-Z0-9]{10}[^"\']*)["\']',
        r'["\'](https?://www\.amazon\.com/(?:[^"\']*/)?(?:dp|gp/product)/[A-Z0-9]{10}[^"\']*)["\']',
        r'/(?:dp|gp/product)/([A-Z0-9]{10})',
    ]
    for pattern in patterns[:2]:
        for match in re.finditer(pattern, text, re.I):
            url = _clean_url(match.group(1))
            if url:
                found.append(url)
    for match in re.finditer(patterns[2], text, re.I):
        url = "https://www.amazon.com/dp/" + match.group(1).upper()
        found.append(url)
    return found


def _runtime_seed_urls():
    seeds = []
    for name in ("list_url", "url"):
        try:
            value = globals().get(name)
        except Exception:
            value = None
        if isinstance(value, str) and value.startswith("http"):
            seeds.append(value)
    try:
        value = getattr(rsp, "url", None)
    except Exception:
        value = None
    if isinstance(value, str) and value.startswith("http"):
        seeds.append(value)
    seeds.extend(DEFAULT_SEEDS)
    out = []
    seen = set()
    for seed in seeds:
        if seed in seen:
            continue
        seen.add(seed)
        out.append(seed)
    return out


detail_uris = []
seen = set()
headers = _headers()

for seed in _runtime_seed_urls():
    try:
        page_rsp = common_request("get", seed, headers=headers, timeout=40)
        page_text = _response_text(page_rsp)
    except Exception:
        page_text = ""
    if not page_text or re.search(r"captcha|automated access|robot check", page_text, re.I):
        continue
    for uri in _detail_uris_from_html(page_text):
        if uri in seen:
            continue
        seen.add(uri)
        detail_uris.append(uri)
    if len(detail_uris) >= 80:
        break

script_res = {"detail_uris": detail_uris}
