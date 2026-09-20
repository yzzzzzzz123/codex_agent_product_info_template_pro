# Stage2 锚点 Schema (Stage2 Anchor Schema)

## 1. 概述

本文档定义了 Stage2（浏览器渲染与解析）的 DOM 分析锚点 schema，用于记录从 HTML 页面中提取各字段的方法、路径和验证规则。

参考图片：IMG_5345-IMG_5350

---

## 2. 基本信息字段

### 2.1 站点与 Origin

```yaml
input_site: ""                 # 输入的站点域名
effective_origin: ""           # 实际生效的 origin（重定向后）
commerce_origin: ""            # 电商平台 origin（如 Shopify storefront）
scope_reason: ""               # 最终交付范围选择的原因
source_from: "static_html|rendered_html"  # 数据来源
```

**字段说明：**
- `input_site`：规范化后的输入站点域名
- `effective_origin`：实际访问的站点 origin（考虑重定向）
- `commerce_origin`：电商平台的 origin（如 Shopify 的 storefront host）
- `scope_reason`：为什么最终交付范围选择在选定的 origin 上

---

## 3. 价格相关字段 (price_semantics)

### 3.1 可见价格字段

```yaml
price_semantics:
  visible_activity_price: ""    # 现价的 selector / payload path / value
  visible_origin_price: ""      # 原价的 selector / payload path / value
  visible_price_mode: ""        # 价格显示模式（list+sales / single-price 等）
```

### 3.2 Payload 价格字段

```yaml
  payload_fields:
    sale_price: ""              # payload 中的销售价字段路径
    selling_price: ""           # payload 中的售价字段路径
    compare_at_price: ""        # payload 中的比较价字段路径
```

### 3.3 价格规则

```yaml
  chosen_rule: ""               # 选择的价格规则说明
  currency_rule: ""             # 货币推断规则
  discount_sanity_check: ""     # 折扣百分比合理性验证结果
  price_priority_rule: ""       # 价格优先级规则
  price_scope_rule: ""          # 价格范围规则
  market_lock_rule: ""          # 市场锁定规则
  currency_consistency_check: "" # 价格值与 source_price_currency 的一致性检查
```

### 3.4 价格字段命名模式

**原价类（origin）：**
- `old` / `was` / `original` / `list` / `regular` / `max` / `compare-at`

**现价类（activity）：**
- `current` / `sale` / `price` / `value` / `selling` / `offer`

**常见组合：**
- `list + sales` 模式
- `.strike-through + .sales` 模式
- `origin = activity = 现价` 模式（无折扣）

---

## 4. 产品信息字段

```yaml
title: ""                      # 产品标题 selector / path
product: ""                    # 产品主容器 selector
category: ""                   # 分类
description: ""                # 描述 selector / path
rating: ""                     # 评分（1-10 分制等）
review_count: ""               # 评论数
```

---

## 5. SKU / 变体相关字段 (variant_handling)

### 5.1 SKU 拓扑

```yaml
variant_handling:
  sku_topology: "variant_sku|component_sku|add_on_sku|recommendation_sku|hidden_candidate"
```

**SKU 类型说明：**
- `variant_sku`：主变体 SKU，进入 `skus[]`
- `component_sku`：组件 SKU
- `add_on_sku`：附加 SKU，不进入主 `skus[]`
- `recommendation_sku`：推荐 SKU，不进入主 `skus[]`
- `hidden_candidate`：隐藏候选 SKU

### 5.2 选项配置

```yaml
  option_names_source: ""       # 选项名称来源
  option_values_source: ""      # 选项值来源
  option_kv_mapping_rule: ""    # option displayName -> displayValue 映射规则
  option_kv_examples: ""        # 示例：Color -> Red, Size -> M
  sku_map_source: ""            # SKU 映射来源
  sku_id_field: ""              # SKU ID 字段
```

### 5.3 SKU 字段规则

```yaml
  price_fields: "activity_price/origin_price"  # 价格字段（selector 或 payload path）
  stock_rule: ""                # 库存状态规则（status=0 的判定）
  sku_props_rule: ""            # SKU 属性规则（option displayName -> displayValue）
  visible_unavailable_rule: ""  # 可见不可用规则（selector/button/dropdown/condition row → status=0）
  deep_oos_rule: ""             # 深度缺货规则（deep_oos/unavailable/notify-me → status=0）
  business_code_as_prop_rule: "" # URL query / merchant sku / style code → props/sku_props
  placeholder_zero_price_rule: "" # payload price=0/0.0 的处理规则（Free/$0/0）
```

### 5.4 SKU 验证

```yaml
  visible_sku_selector_coverage_check: ""  # skus[] 与页面选择器的覆盖检查
  current_dimension_evidence: ""   # 当前维度证据（siblings[] / handle / swatch label / color tag / SKU RAF）
```

---

## 6. 图片处理字段

### 6.1 图片提取规则

```yaml
image_handling:
  main_gallery_selector: ""     # 主图库 selector
  thumbnail_selector: ""        # 缩略图 selector
  image_attr: "src|data-src|data-url|data-zoom-image"  # 图片 URL 属性
  image_size_min: 500           # 最小图片尺寸（px）
  use_srcset: true              # 是否使用 srcset
  srcset_priority: "2x|3x|1x"   # srcset 优先级
```

### 6.2 SKU 图片映射

```yaml
  variant_image_rule: ""        # 变体图片映射规则
  variant_image_source: ""      # 变体图片来源
  # data-id / data-image-id / data-variant-id / data-color / data_pic
  per_option_gallery: false     # 是否每个选项有独立图库
  variant_images_field: ""      # variant_images 字段路径
  variation_gallery_images_field: ""  # variation_gallery_images 字段路径
```

---

## 7. 可见性检查字段

```yaml
visible_field_check: ""         # 价格/状态/review/当前 props 等的可见性检查
                                 # （与 rendered DOM/text、screenshot 对比）
visible_field_conflict: ""      # JSON/JSON-LD/inline state 与可见内容的冲突
runtime_reconciliation_rule: "" # 运行时 XHR/API 的对账规则
```

---

## 8. Review Stats 字段

### 8.1 Provider 信息

```yaml
review_stats:                   # 仅当 with_review_stats 启用时
  provider: "bazaarvoice|yotpo|powerreviews|judgeme|loox|shopperapproved|json_ld|dom|none|other"
  provider_detection_source: ""  # selector / script URL / network request / inline config
```

### 8.2 Review Product ID

```yaml
  review_product_id: ""         # provider 侧的产品 id
  review_product_id_source: ""  # data-bv-product-id / masterId / telemetry / URL pid / etc.
  review_product_id_priority: "" # 各 id 来源的优先级
  provider_conflict_notes: ""   # 多 provider 冲突说明
```

### 8.3 前端选择器

```yaml
  frontend_score_selector: ""   # 前端评分 selector（无 API 时用，为 none 表示 score_source 是 endpoint/path）
  frontend_count_selector: ""   # 前端评论数 selector（无 API 时用，为 none 表示 count_source 是 endpoint/path）
```

### 8.4 Widget API

```yaml
  widget_endpoint: ""           # review widget / review API endpoint
  widget_params: ""             # merchant_id/page_id/apikey/locale 等参数
  score_source: ""              # provider response path / DOM selector / JSON-LD path
  count_source: ""              # provider response path / DOM selector / JSON-LD path
  score_count_same_provider: true  # 分数和评论数是否来自同一 provider
```

### 8.5 零评论处理

```yaml
  zero_review_score_rule: ""    # count=0 时 source_score 的处理（是否设 0/0.0 或 None）
```

### 8.6 Widget 可见数据

```yaml
  visible_widget_url: ""        # 可见 widget 的嵌入 URL（无则为 none）
  product_only_url: ""          # product-only / pagination 的 URL（merchantfallback=0 等）
  visible_widget_score: ""      # 可见 widget 显示的评分
  visible_widget_review_count: ""  # 可见 widget 显示的评论数
  product_only_score: ""        # product-only / pagination 的评分
  product_only_review_count: "" # product-only / pagination 的评论数
```

### 8.7 冲突解决

```yaml
  review_conflict_resolution: ""  # visible widget aggregate | product-only stats | json_ld fallback
                                  # 选择哪个作为最终结果
```

### 8.8 证据文件

```yaml
  request_file: "raw_html/review_stats_request.json"
  response_file: "raw_html/review_stats_response.json"
  summary_file: "raw_html/review_stats_summary.json"
  fallback_notes: ""            # fallback 到 JSON-LD 等的说明
```

---

## 9. 完整示例

```yaml
input_site: "example.com"
effective_origin: "https://www.example.com"
commerce_origin: "https://shop.example.com"
scope_reason: "主站展示产品，结账在 shop 子域名"
source_from: "rendered_html"

price_semantics:
  visible_activity_price: ".price-box .sale-price"
  visible_origin_price: ".price-box .old-price"
  visible_price_mode: "list+sales"
  payload_fields:
    sale_price: "product.price.sale"
    selling_price: "product.price.selling"
    compare_at_price: "product.price.compare_at"
  chosen_rule: "DOM buybox 可见价格优先，payload 作为验证"
  currency_rule: "从 __NEXT_DATA__.currency 推断为 USD"
  discount_sanity_check: "($50 - $35) / $50 = 30%，与 badge 显示的 30% OFF 一致"
  price_priority_rule: "SKU exact price > variation API price > product price > priceRange lower"
  price_scope_rule: "per-variant pricing"
  market_lock_rule: "country=US, currency=USD 锁定"
  currency_consistency_check: "价格值与 USD 符号一致"

variant_handling:
  sku_topology: "variant_sku"
  option_names_source: "product.options[].name"
  option_values_source: "product.options[].values"
  option_kv_mapping_rule: "option displayName -> displayValue"
  option_kv_examples: "Color -> Red, Size -> M"
  sku_map_source: "product.variants[]"
  sku_id_field: "id"
  price_fields: "price / compare_at_price"
  stock_rule: "available = false → status=0"
  sku_props_rule: "selectedOptions.name -> selectedOptions.value"
  visible_unavailable_rule: ".swatch.disabled → status=0"
  deep_oos_rule: "inventory_policy = deny + inventory_quantity = 0 → status=0"
  business_code_as_prop_rule: "URL ?variant= → sku_props.variant_id"
  placeholder_zero_price_rule: "price=0 且 unavailable → status=0，Free 商品 → price=0"
  visible_sku_selector_coverage_check: "6 个 swatch 对应 6 个 SKU"
  current_dimension_evidence: "current handle = red-tshirt, swatch label = Red"

image_handling:
  main_gallery_selector: ".product-gallery .gallery-image"
  thumbnail_selector: ".thumbnails img"
  image_attr: "data-zoom-image"
  image_size_min: 500
  use_srcset: true
  srcset_priority: "2x, 1x"
  variant_image_rule: "variant.image.src → per-SKU gallery"
  variant_image_source: "product.variants[].image"
  per_option_gallery: true
  variant_images_field: "variant_images"
  variation_gallery_images_field: "variation_gallery_images"

review_stats:
  provider: "bazaarvoice"
  provider_detection_source: "data-bv-product-id + bv.js script"
  review_product_id: "12345"
  review_product_id_source: "data-bv-product-id"
  review_product_id_priority: "data-bv-product-id > masterId > URL pid"
  provider_conflict_notes: "无冲突，仅 Bazaarvoice"
  frontend_score_selector: ".bv-rating"
  frontend_count_selector: ".bv-review-count"
  widget_endpoint: "https://api.bazaarvoice.com/data/statistics"
  widget_params: "passkey=xxx&productId=12345"
  score_source: "Results[0].ReviewStatistics.AverageOverallRating"
  count_source: "Results[0].ReviewStatistics.TotalReviewCount"
  score_count_same_provider: true
  zero_review_score_rule: "count=0 时 source_score=0.0"
  visible_widget_url: "https://display.bazaarvoice.com/..."
  product_only_url: "https://api.bazaarvoice.com/...?merchantfallback=0"
  visible_widget_score: "4.5"
  visible_widget_review_count: "128"
  product_only_score: "4.5"
  product_only_review_count: "128"
  review_conflict_resolution: "product-only stats，与 widget 显示一致"
  request_file: "raw_html/review_stats_request.json"
  response_file: "raw_html/review_stats_response.json"
  summary_file: "raw_html/review_stats_summary.json"
  fallback_notes: "无需 fallback"

visible_field_check: "价格/状态/评分与截图一致"
visible_field_conflict: "无冲突"
runtime_reconciliation_rule: "运行时 XHR 价格与 DOM 一致"
```
