# Runtime Compatibility

## Network Requests

Final Goldrush code should:

- prefer `common_request(...)` over raw `requests.get(...)` / `requests.post(...)`
- prefer byte-based XML/HTML parsing
- avoid browser-only logic
- avoid known failure patterns

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

Files, debug logs, or convenience utilities that exist only during authoring must not be referenced from final runtime code.

## XML Parsing

Sitemap responses may be gzip-compressed; decode bytes before XML parsing.

```python
import gzip

raw = getattr(rsp, "content", None) or b""
if not raw:
    raw = (getattr(rsp, "text", "") or "").encode("utf-8", "ignore")
```

Then parse with `fromstring(raw)` or `etree.fromstring(raw)`.

Handle malformed XML:

- malformed XML
- mixed HTML/XML that still contains `<loc>...</loc>`
- fake sitemap placeholders such as `ERROR`, `Invalid parameter`, or other non-XML text with `200 OK`

Preferred robust pattern:

```python
def _xml_urls(url):
    rsp = _fetch(url)
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
```

## Browser Verification

Some sites expose real sitemap XML only after a browser verification step.

- during authoring / investigation, you may use the sibling skill `skills/playwright-cli`
- use it only to recover the true sitemap content, confirm URL patterns, or inspect the page behind
- then distill the final Goldrush code back onto plain `common_request(...)` logic if that is still feasible

Hard boundary:

- browser-based recovery is for authoring only
- final Goldrush code must not depend on browser runtime
- do not hardcode `sample_list_url` as if it is always present

## URL Hygiene

All generated URLs should be clean strings:

- no backticks
- no leading/trailing spaces
- no Markdown formatting
- no pasted code-fence markers
- no quoted Markdown artifacts copied from chat answers

## Runtime Symbol Assumptions

Do not assume Goldrush injects one specific list-page variable name into `list_custom_code`.

Hard rules:

- do not hardcode `sample_list_url` as if it is always present
- when code needs the active list URL, probe known runtime surfaces carefully
- prefer a defensive resolver that checks:
  - `rsp.url`
  - `list_url`
  - `url`
- and fail explicitly if no usable source exists

Final `list_custom_code` must not contain:

- `list_custom_code:` labels
- JSON wrappers
- surrounding quotes
- bullet prefixes
- explanation text

After HTML report copy/paste, do not rely on Markdown rendering or a rich-text wrapper to reconstruct code semantics.

## Code Inclusion Checks

`list_custom_code` must not include:

- extra wrapper objects
- report-only metadata inside `script_res`
- helper debug output as final runtime output

Compile is only the first gate. Authoring-time validation must also dry-run the code logic against failure-like runtime shapes.

Minimum dry-run matrix:

1. `common_request(...)` returns a normal productive sitemap or list response
2. `common_request(...)` raises an exception on the root source
3. one child sitemap fetch fails while other child sitemaps still succeed
4. the fetched body is HTML challenge content rather than XML
5. the fetched body is empty or placeholder text

Expected contract:

- root fetch failure should fail explicitly and degrade clearly, not silently fake success
- child-sitemap loops must skip per child and keep processing siblings
- HTML challenge content must not be mistaken for a valid sitemap corpus

## Bytes Literal Hygiene

Avoid fragile bytes literals such as:

```python
b"\x1F\x8b"
```

Reason:

- HTML embedding, copy/paste chains, or Markdown rendering can corrupt these literals

Use:

```python
bytes([31, 139])
```

or an equivalent explicit construction.

## Failure Patterns To Avoid

Avoid generating code with these failure patterns:

1. `fromstring(rsp.text or "")` on XML-like content
2. using normal `requests.get(...)` or `requests.post(...)` instead of `common_request(...)` or an explicitly verified `curl_cffi` exception
3. using `random()` when it is not guaranteed in runtime
4. assuming `rsp.url` exists on every runtime response object
5. hardcoding a child sitemap as the first choice when the official root sitemap is available
6. returning zero usable PDP URLs when a stable category/list entry works
7. insisting on an official sitemap endpoint that is known to return placeholders, text, compressed garbage, or zero usable PDP URLs
8. assuming code that is theoretically correct but likely to yield empty `detail_uris` in the downstream checker
9. emitting non-list `detail_uris`
10. over-broad sitemap extraction that includes category / account / search / institutional URLs
11. weak keyword filtering that pollutes the narrowed target
12. generating browser-only code for final Goldrush runtime
13. adding Markdown backticks into URLs
14. assuming `rsp.url` exists on every runtime response object
15. hardcoding a child sitemap as the first choice when the official root sitemap is available
16. insisting on an official sitemap endpoint that is known to return placeholder text, compressed garbage, or zero usable PDP URLs when a stable category/list entry works
