# Web Analysis Playbook (taojin v3)

## 1. 概述

本手册定义了网页分析的标准方法、工具和最佳实践，用于从电商网站提取产品信息。

参考图片：IMG_5365-IMG_5370

---

## 2. DOM 分析方法

### 2.1 分析工具链

| 方法 | 适用场景 | 工具 |
|------|----------|------|
| XPath | 复杂层级、文本匹配 | `lxml` / `parsel` |
| CSS Selector | 类名、ID、属性选择 | `beautifulsoup4` / `Playwright` |
| Regex | 内联 JSON、脚本提取 | Python `re` 模块 |
| JSON Path | API 响应、内联 state | `jsonpath-ng` / 手动遍历 |
| API | XHR/Fetch 接口 | `curl_cffi.requests` / Playwright 网络拦截 |

### 2.2 分析优先级

1. **API / XHR**：优先寻找产品数据接口，最稳定
2. **内联 JSON**：`__NEXT_DATA__` / `__NUXT__` / `window.__PRELOADED_STATE__`
3. **JSON-LD**：`application/ld+json` 中的 schema.org 数据
4. **DOM 选择器**：CSS / XPath 提取可见元素
5. **Regex**：从脚本或 HTML 中提取结构化数据

### 2.3 分析输出

所有分析结论记录在 `dom_analysis.md` 中，包含：
- 每个字段的提取方法（XPath / CSS selector / regex / JSON path / API）
- 字段映射关系
- 冲突解决规则
- fallback 策略

---

## 3. 常见数据信号

### 3.1 Title 信号

```
- <title> 标签
- <h1> 产品标题
- <meta property="og:title">
- <meta name="twitter:title">
- JSON-LD: Product.name
- 内联 state: product.title / product.name
```

### 3.2 Product 信号

```
- 主容器: .product / #product / .product-detail / .pdp
- Buybox: .buy-box / .product-buybox / .add-to-cart-area
- 价格区块: .price / .product-price / .price-box
- 图片画廊: .gallery / .carousel / .swiper / .product-images
- 描述区: .description / .details / .accordion / .tab-content
```

### 3.3 Price 信号

**命名模式：**
- 原价：`old` / `was` / `original` / `list` / `regular` / `max` / `compare-at`
- 现价：`current` / `sale` / `price` / `value` / `selling` / `offer`

**DOM 模式：**
```
- .list + .sales (list price + sale price)
- .strike-through + .sales (删除线 + 现价)
- .was + .now
- .regular_price + .sale_price
- compare_at_price > selling_price 模式
```

**折扣验证：**
- `discount_percent` badge sanity check
- `(origin - activity) / origin ≈ discount%`

### 3.4 Variant / SKU 信号

**识别标志：**
- `swatch` / `radio` / `select` / `variant picker`
- `data-product-option-change`
- `variations_form` (WooCommerce)
- `form.variations_form` + `data-product_id`
- `select[name*="attribute"]` + swatch

**SKU 拓扑类型：**
- `variant_sku`：主变体 SKU（进入 skus[]）
- `component_sku`：组件 SKU
- `add_on_sku`：附加 SKU（不进入主 skus[]）
- `recommendation_sku`：推荐 SKU（不进入主 skus[]）
- `hidden_candidate`：隐藏候选 SKU

### 3.5 Gallery / Image 信号

```
- 主图区: .product-gallery / .images / .media
- 轮播: .carousel / .swiper / .slider
- 缩略图: .thumbnails / .thumbs
- 放大图: data-zoom-image / data-src / data-url
- 响应式: srcset
- SKU 图片映射: data-id / data-image-id / data-variant-id / data-color / data_pic
```

**图片处理规则：**
- 优先使用高分辨率版本（500px+）
- 相对路径转绝对 URL
- CDN URL 标准化
- SKU 级图片分组：`variant_images` / `variation_gallery_images`

### 3.6 Description 信号

```
- .description / .product-description
- .details / .product-details
- .accordion / .tabs (tab 内容)
- <meta name="description"> (fallback)
- bullet list / comparison table 保留结构
```

**保留规则：**
- 保留可见块结构（rich text / bullet list / table）
- 使用 `itertext()` 或 `get_text(" ")` 提取
- meta description 仅作 fallback

### 3.7 Schema.org 信号

```html
<script type="application/ld+json">
{
  "@type": "Product",
  "name": "...",
  "image": "...",
  "description": "...",
  "offers": {
    "@type": "Offer",
    "price": "...",
    "priceCurrency": "..."
  },
  "aggregateRating": {
    "@type": "AggregateRating",
    "ratingValue": "...",
    "reviewCount": "..."
  }
}
</script>
```

**用途：**
- fallback 数据源
- 字段验证参考
- review stats 的最后 fallback

---

## 4. Playwright 使用技巧

### 4.1 等待策略

| 等待类型 | 适用场景 | 代码示例 |
|----------|----------|----------|
| `networkidle` | 静态页面、资源加载完成 | `page.wait_for_load_state('networkidle')` |
| `domcontentloaded` | DOM 解析完成即可 | `page.wait_for_load_state('domcontentloaded')` |
| 选择器等待 | 关键元素出现 | `page.wait_for_selector('.product-price')` |
| 自定义等待 | 特定条件 | `page.wait_for_function(() => ...)` |

### 4.2 滚动与懒加载

```python
# 滚动到底部触发懒加载
page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
page.wait_for_timeout(1000)

# 渐进式滚动
for i in range(5):
    page.evaluate(f"window.scrollTo(0, {i * 500})")
    page.wait_for_timeout(500)
```

### 4.3 点击交互

**常见需要点击的元素：**
- 颜色/尺寸 swatch（触发 SKU 切换）
- "Show more" / "Read more"（展开描述）
- 图片缩略图（切换主图）
- Tab 切换（显示不同内容区）
- Cookie banner / GDPR 弹窗关闭

**注意事项：**
- 点击前确保元素可见
- 点击后等待内容加载
- 记录交互前后的数据变化

### 4.4 反爬绕过

**常见反爬信号：**
- 403 / 429 状态码
- "Just a moment..." / "Please wait"
- Cloudflare / Akamai / PerimeterX
- captcha / 验证码

**处理策略：**
- 参考 `skills/playwright-cli/references/proxy_toolkit_quickstart.md`
- 使用 `scripts/proxy-access.js`
- `curl_cffi.requests` 模拟浏览器指纹
- Headless / headed 模式切换

---

## 5. Review Stats 分析

### 5.1 Review Provider 识别

| Provider | 识别信号 |
|----------|----------|
| **Bazaarvoice** | `data-bv-product-id`, `bazaarvoice.com`, `api.bazaarvoice.com`, `bv.js`, BV config |
| **PowerReviews** | `pr-snippet-*`, `pwr`, `pr_`, `powerreviews`, `ui.powerreviews.com`, `display.powerreviews.com` |
| **Yotpo** | `yotpo`, `api.yotpo.com`, `data-yotpo-product-id` |
| **Judge.me** | `judgeme`, `jdgm` |
| **Loox** | `loox` |
| **Shopper Approved** | `shopperapproved.com/widgets`, `saLoadScript`, `ShopperApproved`, `SA__`, `tempReviews`, `merchantfallback` |
| **JSON-LD** | `application/ld+json` 中的 `aggregateRating` |
| **DOM** | 页面直接渲染的评分/评论数 |

### 5.2 Review Product ID 查找优先级

**Bazaarvoice：**
1. `data-bv-product-id` / widget 配置的 id
2. `masterId` / family id
3. `gtmData.id` / `gtmGA4Data.item_id`
4. URL 中的 pid / SKU / variant id
5. URL 路径 + DOM / widget id 推断

**PowerReviews：**
1. 网络请求中的 `merchant_id` / `apikey` / `page_id` / `locale`
2. 页面脚本中的配置
3. URL 中的 page id

**Shopper Approved：**
1. widget URL 中的参数
2. product-only / pagination URL（`page=1`, `merchantfallback=0`）

### 5.3 Widget Aggregate vs Product-only Stats

**重要区别：**
- **Widget aggregate**：商家整体或聚合数据（可能包含多个产品）
- **Product-only stats**：当前产品的真实数据

**优先级规则：**
1. product-only stats（产品专属数据）
2. widget aggregate（聚合数据，fallback）
3. JSON-LD `aggregateRating`（最后 fallback）

**冲突解决：**
- 如 widget aggregate 与 product-only stats 不一致，**以 product-only 为准**
- 记录在 `context/review_field_mapping.md` 中
- `score_count_same_provider` 标记是否来自同一 provider

### 5.4 Review Count 提取

**来源优先级：**
1. API 响应：`pagination.total` / `tempReviews.total` / `reviews.total` / `meta.total`
2. Widget 显示："N Reviews" 文本
3. JSON-LD：`aggregateRating.reviewCount`

**零评论处理：**
- `review.count = 0` / `comments = 0` / "No reviews" → `source_cmms = 0`
- `source_score` 规则：
  - 如 provider 明确返回 0 → `source_score = 0.0`
  - 如无明确分数 → `source_score = None`
  - 记录在 `zero_review_score_rule` 中

### 5.5 证据文件

必须保存以下证据：
- `raw_html/review_provider_discovery.json`：provider 发现过程
- `raw_html/review_stats_request.json`：请求 URL / method / params / body
- `raw_html/review_stats_response.json`：响应数据
- `context/review_field_mapping.md`：字段映射与 fallback 说明

---

## 6. 价格语义分析

### 6.1 价格字段命名模式

| 类型 | 常见命名 |
|------|----------|
| 原价 | `old_price`, `was_price`, `original_price`, `list_price`, `regular_price`, `max_price`, `compare_at_price`, `strikethrough_price` |
| 现价 | `current_price`, `sale_price`, `selling_price`, `price`, `value`, `offer_price`, `final_price`, `active_price` |

### 6.2 DOM 可见价格 vs Payload 价格

**冲突场景：**
- DOM 显示的价格与 API/JSON 中的价格不一致
- list/was + sale/current 模式识别

**解决策略：**
1. DOM buybox 可见价格优先（用户看到的价格）
2. payload / JSON-LD / API 作为验证和 fallback
3. 记录 `payload_price_conflict` 和 `chosen_rule`

### 6.3 特殊价格处理

**价格区间 (priceRange)：**
- 信号：`priceRange` / `hasPriceRange` / `min-max price`
- 处理：`priceRange.lower` 作为 SKU 级别价格
- 优先级：SKU exact price > configured variation API price > product price > priceRange lower fallback

**金融/月付价格：**
- 信号：`installments`, `paymentFrequency`, `monthly`, `per month`, `+ plan`
- 处理：拒绝融资价格，使用 `list_price` / `regular_price` / `full_price`
- 记录在 `financing_monthly_price_reject_bucket`

**Free / $0 价格：**
- "Free" / "$0" / "0" → 标准化为 `0`
- payload 中 `price = 0` / `0.0` 且无真实 SKU → `status = 0`

### 6.4 货币推断

**来源优先级：**
1. API / 内联 JSON 中的 `currency` / `country` / `locale` / `market`
2. Cookie / Header 中的 locale / currency
3. URL 路径 / 查询参数
4. buybox 价格符号（$ / € / £）
5. 站点域名 TLD 推断

**记录字段：**
- `source_price_currency`：3 位大写货币代码（USD / CNY / EUR 等）
- `currency_rule`：货币推断规则
- `market_lock_rule`：市场锁定规则

---

## 7. SKU 变体分析

### 7.1 SKU PDP 识别

**多 SKU PDP 特征：**
- 存在 swatch / radio / select / variant picker
- `data-product-option-change` 事件
- `variations_form` (WooCommerce)
- 价格区间显示
- 图片随选项变化

**单 SKU 折叠规则：**
- 单 SKU PDP 如只有一个空 props 的 SKU，应折叠到 SPU 层
- `props = {}` 且 `skus.length = 1` 且 `skus[0].sku_props` 为空 → 折叠

### 7.2 Swatch 类型

**Navigation Swatch：**
- 点击 swatch 跳转 URL（path / slug / handle / canonical 变化）
- 通过路由 / server action 改变产品标识
- 每个 swatch 对应独立 URL
- 需额外请求获取 SKU 级数据（price / status / pics）

**Matrix Swatch：**
- 同页面内选项矩阵
- 选择组合后动态更新价格/库存/图片
- 数据通常在 inline state / API 中
- 直接从 payload 提取所有 SKU

### 7.3 兄弟产品 (Sibling) 处理

**识别信号：**
- `product.siblings[]`
- color swatch href 指向 sibling PDP
- group / YGroup tag
- `color_*` tags

**处理策略：**
- sibling 作为 SKU 的颜色维度
- URL-split 方式处理
- 记录 sibling URL 和映射关系
- `dom_analysis.md` 中记录 sibling 策略

### 7.4 SKU 状态判断

**可见不可用 (visible_unavailable)：**
- selector / button / dropdown / condition row 显示不可用
- `add-to-cart` / `buy-now` CTA disabled
- "out of stock" / "sold out" / "unavailable" 文本
- → `status = 0`

**深度缺货 (deep_oos)：**
- `deep_oos` / `unavailable` / `sold out` / `incoming` / `notify me`
- payload 中 `available = false` / `quantity = 0`
- → `status = 0`

**证据优先级：**
DOM 选择器（disabled/灰化）> 文本提示（"Out of stock"）> JSON-LD / Schema > payload 数据

---

## 8. Commerce Origin 识别

### 8.1 Origin 类型

- `input_site`：输入的站点域名
- `effective_origin`：实际生效的站点 origin（重定向后）
- `commerce_origin`：电商平台 origin（如 Shopify storefront）

### 8.2 识别方法

**Shopify 识别：**
- `shop.*` 子域名
- `myshopify.com` 域名
- `/products/{handle}.js` 可用
- `window.Shopify` 对象
- `cdn.shopify.com` 资源

**BigCommerce / WooCommerce / Headless：**
- 平台特征 API 路径
- 典型 DOM 结构
- 平台特定脚本和样式

---

## 9. Stage1 → Stage2 迁移

### 9.1 数据延续

- Stage1 发现的字段映射在 Stage2 验证和修正
- Stage1 的 `dom_analysis.md` 在 Stage2 更新
- Stage1 的 raw / gt JSON 作为 Stage2 的基线

### 9.2 Stage2 补充

- 浏览器渲染后的完整 DOM
- 运行时 API / XHR 数据
- 动态加载的内容
- 交互触发的数据变化
