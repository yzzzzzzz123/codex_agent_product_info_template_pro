# Discovery Playbook

本 playbook 描述 `seed_agent` 在为站点发现 detail page / PDP / SPU URL 时使用的策略与边界。

## 目标

- 为每个站点发现至少 5 个真实可用的 SPU / detail page URL
- 覆盖多个 category / template family
- 优先选择带复杂 SKU 的 PDP（含 swatch / radio / select / option / variant_picker）
- 输出可直接写入 `input/dataset_url_template.json` 的 seed URL 集合

## 发现顺序

1. 首页 HTML
2. `robots.txt`
3. `sitemap.xml` 及 sitemap index / robots 声明的 sitemap
4. 首页抽取的 detail links
5. 导航 / category 页面抽取的 detail links
6. SPA / Next.js / Shopify / Headless 站点：解析 inline JSON、JSON-LD、next data、hydration payload
7. 备用：对 `/products` / `/shop` 等路径进行 template diversity scan

## URL 规范化

### 输入

- 1 个 canonical URL
- 去除 utm_* / gclid / fbclid 等追踪参数
- 去除 fragment
- SPU 候选必须为绝对 http(s) URL

### 输出

- 1 个 canonical PDP URL
- 多个 variant URL
- 多个 category URL
- 多个 template URL

### 模板签名

- 通过 path pattern 识别 category / template family
- 例如：`/products/smoothies/511/foo` -> category=`smoothies`
- 通过 `template_signature` 识别 PDP 模板家族

## 站点类型

- Shopify / Headless / VTEX 等：需识别真实 storefront
- Next.js / SPA：解析 `__NEXT_DATA__` / hydration route
- 复杂 SKU：必须命中 `swatch` / `radio` / `select` / `option` / `variant_picker` 等信号

## 输出契约

最终 discovery report 必须包含：

- `discovered_patterns`
- `selected_patterns`
- `selected_categories`
- `known_but_unselected_categories`
- `diversity_status`: `pass` / `warn` / `fail`
- `complex_sku_candidate_count`
- `selected_complex_sku_count`
- `complex_sku_status`: `pass` / `fail`

每个 category 至少 1 个 seed；若存在多个 category / template family：`len(seeds) >= 5`

## 角色

### `seed_agent`

- seed discover 负责人：
- 从首页 URL 开始，发现真实 PDP / category / route family 候选
- 验证候选是否为真实 PDP
- 抽取复杂 SKU PDP，若存在则 seed 中至少 1 个复杂 SKU PDP；否则在 report 中说明

### `orchestrator_agent`

- 接收 seed_agent 的 report，并写入 `input/dataset_url_template.json`

## 输入

- 站点域名或首页 URL，例如：`https://example.com`
- 目标 seed 数量（默认 5）
- 模式：`replace-all` 或 `merge`
- 输出：`input/dataset_url_template.json`

## 输出

- 状态：`ok` / `shortfall` / `fail`
- 若 `shortfall` 且 `< 5`，需说明原因
- 若 `fail`，需说明具体原因

## 验收标准

1. 至少 5 个真实可用的 SPU URL
2. 写入 `input/dataset_url_template.json`
3. 通过 diversity review

### 多 category / 多 template family

- 若存在多个 category，seed 必须覆盖多个 category
- 若存在多个 PDP template signature，seed 必须覆盖多个 template family
- 若为 Next.js / SPA 站点，解析 `__NEXT_DATA__` / hydration route，识别 page route，例如：`/products/babyblends/[id]/[name]` 与 `/products/smoothies/[id]/[name]` 视为不同 template

### 复杂 SKU 候选

- 若候选 PDP 页面包含 `swatch` / `radio` / `select` / `option` / `variant_picker` 信号，视为复杂 SKU 候选
- 若存在复杂 SKU 候选，seed 中至少 1 个复杂 SKU PDP，否则 Stage2/Stage3 可能无法抽取 SKU

### 平台识别

- BigCommerce / Shopify / WooCommerce / Headless 站点，优先识别真实 storefront，再抽取 PDP，最后作为 seed，否则 discovery 可能失败

## 处理流程

1. 若无法直接获取 detail URL，先尝试：
2. `robots.txt`
3. `sitemap.xml` 及 sitemap index / robots 声明的 sitemap
4. 首页抽取的 detail links
5. 导航 / category 页面抽取的 detail links
6. SPA / Next.js / Shopify / Headless 站点：解析 inline JSON、JSON-LD、next data、hydration payload
7. 备用：对 `/products` / `/shop` 等路径进行 template diversity scan

## 参考

- `skills/site-seed-discovery/references/discovery_playbook.md`
- `skills/site-seed-discovery/scripts/discover_seed_urls.py`
- `skills/site-seed-discovery/scripts/update_dataset_template.py`

## 输出模式

- 默认：`replace-all`，覆盖整个 dataset
- `merge`：与现有 `input/dataset_url_template.json` 合并

### `replace-all`

- 推荐：当前 batch 全量覆盖
- 不推荐：保留旧 seed，仅追加新 seed

### `merge`

- 推荐：保留旧 seed，仅追加新 seed
- 不推荐：当前 batch 全量覆盖

## 常见问题

- 若 `shortfall` 且 `< 5`，需说明原因
- 若 `fail`，需说明具体原因
- 若 diversity review 失败，需说明具体原因
