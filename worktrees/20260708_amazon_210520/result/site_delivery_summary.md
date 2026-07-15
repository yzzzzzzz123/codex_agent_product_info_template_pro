# Stage4 站点交付摘要: amazon.com

## 基本信息

- **input_site**: amazon.com
- **effective_origin**: https://www.amazon.com
- **commerce_origin**: https://www.amazon.com
- **scope_reason**: 用户站点 amazon.com 的有效电商详情页位于 www.amazon.com；官方 sitemap 探测不可用，最终交付保持在同一 Amazon origin，并使用可复现的搜索/榜单列表页抽取。
- **coverage**: partial
- **observed_count**: 54

## Sitemap

https://www.amazon.com/s?k=wireless+mouse

## Companion: list_custom_code

```python
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
```

## 样本详情页

1. [https://www.amazon.com/dp/B004YAVF8I](https://www.amazon.com/dp/B004YAVF8I)
   - 原因: 样本详情页来自当前任务种子 PDP，Stage3 live checker 已验证标题、价格、图片、评价和 SKU 字段。
2. [https://www.amazon.com/dp/B07CMS5Q6P](https://www.amazon.com/dp/B07CMS5Q6P)
   - 原因: 样本详情页来自搜索列表页抽取，URL 包含标准 /dp/ASIN 详情页结构。
3. [https://www.amazon.com/dp/B0H15XJ51B](https://www.amazon.com/dp/B0H15XJ51B)
   - 原因: 样本详情页来自搜索列表页抽取，URL 包含标准 /dp/ASIN 详情页结构。
4. [https://www.amazon.com/dp/B087Z5WDJ2](https://www.amazon.com/dp/B087Z5WDJ2)
   - 原因: 样本详情页来自搜索列表页抽取，URL 包含标准 /dp/ASIN 详情页结构。
5. [https://www.amazon.com/dp/B0F5HPCLGB](https://www.amazon.com/dp/B0F5HPCLGB)
   - 原因: 样本详情页来自搜索列表页抽取，URL 包含标准 /dp/ASIN 详情页结构。

## 流程说明

- 第一波探测 robots.txt 成功，但 robots 未声明 sitemap；/sitemap.xml 与 /sitemap_index.xml 返回 HTML/500，未得到可直接递归的官方产品 sitemap。
- 列表页抓取验证了 https://www.amazon.com/s?k=wireless+mouse 和 https://www.amazon.com/Best-Sellers/zgbs 均能返回真实 /dp/ASIN 详情页链接。
- list_custom_code 编译通过，并在 authoring-time 执行测试中返回 54 个去重详情页 URL。
- Stage3 对种子详情页执行 live checker，验证商品标题、价格、币种、图片、属性、SKU、评分和评论数均通过 schema 校验。
- 第二波与第三波未触发：首轮已发现真实详情页 URL，但官方 sitemap 不可用，所以覆盖标记为 partial。

## 验证结果

- sitemap: 通过
- companion: list_custom_code 编译通过
- sample_urls: 通过
- runtime_evidence: live checker 与列表代码执行均通过
