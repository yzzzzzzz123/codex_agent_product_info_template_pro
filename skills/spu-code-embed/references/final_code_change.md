# final_code.py Change Guide

## Self-Contained Rule

`final_code.py` must be fully self-contained.

Direct or indirect dependency on any other local file is not allowed. Any required function, method, class, constant, configuration, or helper logic that would otherwise come from another file must be re-created explicitly within `final_code.py`.

Access through import, path-based lookup, dynamic module loading, file reads, or any other external-file mechanism is strictly forbidden.

## Allowed Imports

`final_code.py` must use only standard library plus:

- `requests`
- `curl_cffi.requests`
- `lxml`
- `json`
- `re`
- `urllib.parse`
- `html`
- `from lxml.html import fromstring`
- `fromstring`
- `etree`

## Forbidden Imports

`final_code.py` must not import:

- `Path`
- `os`
- or any other module that touches the filesystem

## Forbidden Globals

`final_code.py` must not reference:

- `random_va()`
- `gen_headers()`
- `static_simple_curl_cffi_req()`
- `save_rendered_spu_html()`
- or any other helper from the checker globals

## Forbidden File Operations

`final_code.py` must not read or write files such as:

- `raw_html/static_page.html`
- `rendered_page.html`
- `*_request.json`
- `*_response.json`
- `stage1_gt.json`
- `stage1_raw_gt.json`

## Runtime Symbols

`final_code.py` may assume only these runtime symbols:

- `detail_url`: the PDP URL string
- `rsp`: the response object from `common_request(...)`
- `common_request`: the Goldrush request function

Do not assume any other runtime variable names.

## script_res Contract

`final_code.py` must end with exactly one runtime contract output shape.

For detail-side:

```python
script_res = {
    "source_url": detail_url,
    "source_item_name": ...,
    "source_pics": [...],
    "descriptions": [...],
    "source_origin_price": ...,
    "source_activity_price": ...,
    "source_price_currency": ...,
    "props": {...},
    "skus": [
        {
            "sku_props": {...},
            "source_origin_price": ...,
            "source_activity_price": ...,
            "source_pics": [...],
            "status": 1
        }
    ],
    "status": 1
}
```

Missing fields must be `None`, not absent.

## Field Rules

- `source_origin_price` and `source_activity_price` must be numeric. If the site shows `Free`, `$0`, or similar, normalize to `0`.
- `source_price_currency` must be a 3-character upper-case string such as `USD` / `CNY` / `EUR`.
- `props` must be a dict. If the site has no SPU-level props, emit `{}`.
- `skus[].sku_props` must be a dict. If the site has no SKU-level props, emit `{"SKU": "<sku_id>"}` or similar.
- `descriptions` must be a list of strings or HTML strings. HTML strings are allowed; plain text is also allowed.
- `source_pics` must be a list of strings. Each string must be an absolute URL.
- `skus[].source_pics` must be a list of strings. Each string must be an absolute URL.
- `status` must be an integer. `1` means on-shelf, `0` means off-shelf.
- `source_score` and `source_cmms` are optional. If present, `source_score` must be a float and `source_cmms` must be an integer.
- `not_detail` is optional. If present, it must be a string such as `"yes"` or `"deadlink"`.

## Common Request Helper

```python
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
rsp = common_request("get", detail_url, headers=headers, timeout=40)
```

For POST-based APIs:

```python
rsp = common_request("post", api_url, headers=headers, json=payload, timeout=40)
```

Do not depend on `rsp.text` alone; always fall back to `rsp.content` when the response is binary or compressed.

## HTML Parsing

```python
from lxml.html import fromstring
raw = getattr(rsp, "content", None) or b""
if not raw:
    raw = (getattr(rsp, "text", "") or "").encode("utf-8", "ignore")
tree = fromstring(raw)
```

For JSON-LD extraction:

```python
import json
scripts = tree.xpath('//script[@type="application/ld+json"]//text()')
for s in scripts:
    try:
        data = json.loads(s)
    except Exception:
        continue
    if isinstance(data, dict) and data.get("@type") == "Product":
        ...
```

## Price Normalization

```python
import re

def _to_number(text):
    if text is None:
        return None
    s = str(text).strip()
    if not s:
        return None
    s = re.sub(r"[^\d\.,]", "", s)
    s = s.replace(",", "")
    try:
        return float(s)
    except Exception:
        return None
```

If the site shows `Free`, `$0`, or similar, normalize to `0`.

## Currency Extraction

```python
def _currency(text):
    if not text:
        return None
    s = str(text).strip().upper()
    mapping = {
        "$": "USD",
        "USD": "USD",
        "€": "EUR",
        "EUR": "EUR",
        "£": "GBP",
        "GBP": "GBP",
        "¥": "CNY",
        "CNY": "CNY",
        "RMB": "CNY",
    }
    for k, v in mapping.items():
        if k in s:
            return v
    return None
```

## Image URL Normalization

```python
from urllib.parse import urljoin

def _abs(url):
    if not url:
        return None
    s = str(url).strip()
    if s.startswith("//"):
        return "https:" + s
    if s.startswith("http"):
        return s
    return urljoin(detail_url, s)
```

## SKU Extraction Patterns

Common patterns:

- Shopify: `window.meta.product.variants`
- WooCommerce: `form.cart select option`
- Magento: `swatch-opt-...` or `#product_addtocart_form`
- SFCC: `productSearchResult.hits` or `window.__INITIAL_STATE__`
- Custom: look for `data-sku`, `data-variant-id`, or JSON-LD `offers`

## Validation Checklist

Before finalizing `final_code.py`:

1. `compile(code, "<site>", "exec")` passes
2. `final_code.py` is fully self-contained
3. `final_code.py` uses only allowed imports
4. `final_code.py` does not reference forbidden globals
5. `final_code.py` does not read or write files
6. `script_res` contains all required fields
7. Missing fields are `None`, not absent
8. Prices are numeric
9. Currency is a 3-character upper-case string
10. `props` and `skus[].sku_props` are dicts
11. `source_pics` and `skus[].source_pics` are lists of absolute URLs
12. `status` is an integer

## Common Failure Patterns

Avoid:

1. importing `os` or `pathlib`
2. referencing `random_va()` or `gen_headers()`
3. reading `stage1_gt.json` or `stage1_raw_gt.json`
4. assuming `rsp.text` is always present
5. emitting non-numeric prices
6. emitting non-list `source_pics`
7. emitting non-dict `props`
8. emitting non-dict `skus[].sku_props`
9. emitting relative image URLs
10. emitting missing fields as absent instead of `None`
