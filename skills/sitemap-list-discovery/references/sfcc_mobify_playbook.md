# Salesforce Commerce Cloud / Mobify PWA Playbook

## Recognition Signals

Some Salesforce Commerce Cloud sites are rendered through Mobify / PWA Kit and look partial if only HTML links or embedded first-page state are used.

Recognition signals:

- bundle paths like `/mobify/bundle/{build}/main.js`
- embedded JSON script like `id="mobify-data"`
- config values such as:
  - `organizationId`
  - `siteId`
  - `clientId`
- product list state such as `productSearchResult.hits`, `limit`, `offset`, and `total`
- PDP URLs containing separators like `productID`, e.g. `...?pid=...`

## Coverage Rule

Do not stop at `productSearchResult.hits` embedded in the first page when `total > len(hits)`.

Path-derived fallback only when verified against at least one successful category fetch.

## SLAS Guest PKCE Outline

```python
import base64

session = requests.Session(impersonate="chrome124", timeout=45)
verifier = "..."  # generate a secure random verifier
challenge = base64.urlsafe_b64encode(
    hashlib.sha256(verifier.encode("utf-8")).digest()
).decode("utf-8").rstrip("=")

# 1. authorize
# 2. exchange code for token
# 3. use guest token to call shopper-search

query = {}
code = (query.get("code") or [""])[0]
usid = (query.get("usid") or [""])[0]

token_payload = {
    "code_verifier": verifier,
    "client_id": CLIENT_ID,
    "channel_id": SITE_ID,
    "redirect_uri": REDIRECT_URI,
    "grant_type": "authorization_code",
    "code": code,
    "usid": usid,
}
```

## Pagination

```python
offset = 0
limit = 24
total = None
detail_uris = []
while True:
    url = f"{API_BASE}/product-search?siteId={SITE_ID}&offset={offset}&limit={limit}"
    rsp = common_request("get", url, headers=headers, timeout=40)
    data = rsp.json()
    hits = data.get("hits", [])
    for hit in hits:
        pid = hit.get("productId")
        if pid:
            detail_uris.append(f"https://www.example.com/product/{pid}")
    if total is None:
        total = data.get("total", 0)
    offset += limit
    if total and offset >= total:
        break
```

## Important Boundaries

- Do not hardcode observed `refresh_token` values; they rotate and quickly become invalid.
- Do not reuse one-time `code` / `usid`.
- Do not treat `ocapi_bearer` from localStorage as a stable source for final code.
