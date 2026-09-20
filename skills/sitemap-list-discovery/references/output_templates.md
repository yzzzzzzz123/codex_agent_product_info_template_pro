# Output Templates

## Default Output Discipline

This file now describes only the single-site Stage4 output shapes used by `taojin_v3_crawl_skill`.

When the parent Stage4 flow asks for list-side output:

- by default, return one primary answer only
- `sitemap` + `Detail_url_pattern(pattern/regex/xpath/raw_st)` when the chosen sitemap source already exposes or can cleanly isolate PDP URLs
- otherwise `sitemap` + `list_custom_code`
- only when the primary answer is insufficient may the answer also include one lower-priority `extra`
- if `extra` exists, it must be clearly labeled and ranked after the primary answer
- by default, return them as separate UI-ready fields, not as one JSON object

Hard rules:

- do not wrap output in JSON unless the user explicitly asks for a config block
- do not prepend long theory unless requested
- do not create temp files or extra artifacts
- do not use `/products/*` or `/products/{slug}` as final `Detail_url_pattern`; final delivery must be a real plain string such as `https://example.com/products/*`

## Output Fields

Minimum per-site output:

- `input_site`
- `effective_origin`
- `commerce_origin`
- `scope_reason`
- `sitemap`
- `Detail_url_pattern` or `list_custom_code`
- `sample_detail_uris`
- `process_notes`
- `coverage`
- `coverage_note` (optional)
- `observed_count`

When uncertainty remains after a re-think pass, the concise answer may also append:

- `extra`

Example `Detail_url_pattern`:

- `Detail_url_pattern(pattern/regex/xpath/raw_st): xpath .//*[local-name()="url"]/*[local-name()="loc"][contains(text(), "/products/")]/text()`

## Parent-Owned Stage4 Report Compatibility

If the parent Stage4 flow later renders a site summary or batch report, preserve the same list-skill field contract inside each site panel:

- one primary `input_site`
- one primary `sitemap`
- one primary companion field (`Detail_url_pattern` or `list_custom_code`)
- concise evidence notes

## Canonical Templates

### Direct Product Sitemap

```python
import re
import urllib.parse

def _fetch(url):
    headers = get_newest_common_headers()
    return common_request("get", url, headers=headers, timeout=40)

def _xml_urls(url):
    try:
        rsp = _fetch(url)
    except Exception:
        urls = []
    raw = getattr(rsp, "content", None) or b""
    if not raw:
        raw = (getattr(rsp, "text", "") or "").encode("utf-8", "ignore")
    try:
        from lxml import etree
        tree = etree.fromstring(raw)
        urls = [loc.text.strip() for loc in tree.xpath("//*[local-name()='loc']") if loc.text and loc.text.strip().startswith("http")]
    except Exception:
        urls = []
    if not urls and raw:
        urls = [u.strip() for u in re.findall(r"<loc>(.*?)</loc>", raw, flags=re.IGNORECASE | re.S) if u and u.strip().startswith("http")]
    return urls

detail_uris = []
seen = set()
for u in _xml_urls("https://example.com/sitemap_products_1.xml"):
    if u in seen:
        continue
    seen.add(u)
    detail_uris.append(u)

script_res = {"detail_uris": detail_uris}
```

### Homepage / Category Fallback

```python
import re
import urllib.parse

BASE = "https://example.com"

def _abs(url):
    return urllib.parse.urljoin(BASE, url)

def _category_uris(text):
    out = []
    seen = set()
    for u in re.findall(r"/Product/Category/List/\d+", text, flags=re.IGNORECASE):
        abs_u = _abs(u.strip())
        if abs_u in seen:
            continue
        seen.add(abs_u)
        out.append(abs_u)
    return out

def _pdp_uris(text):
    out = []
    seen = set()
    for u in re.findall(r"/Product/Detail/\d+", text, flags=re.IGNORECASE):
        abs_u = _abs(u.strip())
        if abs_u in seen:
            continue
        seen.add(abs_u)
        out.append(abs_u)
    return out

detail_uris = []
seen = set()
headers = get_newest_common_headers()
rsp = common_request("get", BASE, headers=headers, timeout=40)
text = getattr(rsp, "text", "") or ""
for cat_url in _category_uris(text):
    try:
        cat_rsp = common_request("get", cat_url, headers=headers, timeout=40)
        cat_text = getattr(cat_rsp, "text", "") or ""
        for u in _pdp_uris(cat_text):
            if u in seen:
                continue
            seen.add(u)
            detail_uris.append(u)
    except Exception:
        continue

script_res = {"detail_uris": detail_uris}
```

### Common Request Helper

```python
headers = get_newest_common_headers()
rsp = common_request("get", url, headers=headers, timeout=40)
```

For POST-based sitemap-adjacent APIs:

```python
headers = get_newest_common_headers()
rsp = common_request("post", url, headers=headers, json=payload, timeout=40)
```

Do not depend on `rsp.text` alone; always fall back to `rsp.content` when the response is binary or compressed.

If a pure Python API path is proven with `curl_cffi` browser impersonation, `curl_cffi` may be used in the final generated code as a safe fallback.
