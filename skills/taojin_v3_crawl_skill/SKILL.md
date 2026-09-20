---
name: "taojin_v3_crawl_skill"
description: "A v2-derived, end-to-end crawler workflow for extracting product information from a single e-commerce website. v3 keeps v2's Stage1/Stage2 data contract, lets the parent execution unit own Stage1, delegates Stage2-3 to a dedicated downstream agent, delegates browser fallback to skills/playwright-cli, and enters an optional Stage4 that directly calls skills/sitemap-list-discovery for single-site List discovery when the current task enables list discovery."
---

# taojin_v3_crawl_skill

## Quick Start

### 单站点 (site_domain)

工作目录: `worktrees/taojin_v3_{site_count}sites_{MM-DD_HH-MM-SS}/`

- 单站点模式: 工作树路径为 `worktrees/{site_domain}/`
- 如发现种子 URL 不足，使用 `--allow-shortfall` 参数

### 相关文件

- `skills/taojin_v3_crawl_skill/assets/run_prompt_template.md`
- `skills/taojin_v3_crawl_skill/assets/self_test_config_template.jsonc`
- `skills/taojin_v3_crawl_skill/references/raw_product_schema.jsonc`
- `skills/taojin_v3_crawl_skill/references/target_product_schema.jsonc`
- `skills/taojin_v3_crawl_skill/references/stage2_anchor_schema.md`
- `skills/taojin_v3_crawl_skill/references/agent_responsibilities.md`
- `skills/taojin_v3_crawl_skill/references/web_analysis_playbook.md`
- `skills/playwright-cli/SKILL.md`
- `skills/playwright-cli/references/playwright_cli_quickstart.md`
- `skills/playwright-cli/references/proxy_toolkit_quickstart.md`
- `skills/taojin_v3_crawl_skill/references/human_operation_flow.md`

### Python 环境

- 默认使用 `./env/.venv/bin/python`
- 如使用其他 Python，通过 `--python-bin` 或 `PYTHONBIN` 环境变量指定

## 核心脚本

- Stage1 后处理: `scripts/postprocess_raw_product.py`
- Stage2 自检: `scripts/stage2_self_test.py`
- Stage3 嵌入: `skills/spu-code-embed/SKILL.md`
- Stage4 列表发现: `skills/sitemap-list-discovery/SKILL.md`
- (Stage3) 校验工具: `skills/spu-code-embed/scripts/final_code_check.py`, `skills/spu-code-embed/scripts/final_code_check_offline.py`, `skills/spu-code-embed/scripts/final_render_html.py`

## 人工审核

- 参考: `references/human_operation_flow.md`

## 工作流

1. **种子发现 (seed discover)**
   - 由 `seed_agent` 执行种子发现
   - `seed_agent` 向 `orchestrator_agent` 汇报，优先级 `xhigh`
   - `orchestrator_agent` 优先级 `5.5xhigh`，每个 agent 一个工作树
   - 产出: `input/dataset_url_template.json`，由 `orchestrator_agent` 持有

2. **工作树设置 (worktree setup)**
   - `orchestrator_agent` 执行 `worktree setup`
   - 基于 `input/dataset_url_template.json` 创建工作树并生成 `run_prompt.md`

3. **站点代理 (site_agent)**
   - `site_agent` 向 `orchestrator_agent` 汇报，优先级 `xhigh`
   - `orchestrator_agent` 优先级 `5.5xigh`，每个 `site_agent` 一个工作树
   - 工作树路径: `result/{site_domain}/prompt/run_prompt.md`
   - `site_agent` 负责单站点的 Stage 协调

4. **Agent 职责与 Stage 流转**
   - 详见 `references/agent_responsibilities.md`
   - Stage2-3 由 `extract_agent` 以 "v3" 模式执行 `run_prompt`
   - Stage3 参考 `skills/spu-code-embed/SKILL.md`
   - 如 `extra_tasks` 包含 `list_discovery`，Stage4 由 `list_agent` 执行
     - 参考 `skills/sitemap-list-discovery/SKILL.md`
     - 产出: `site_delivery_summary.md` + Stage4 HTML 报告
   - 模板: `assets/run_prompt_template.md` 的 "交付物 (Deliverables)" 部分

## 相关技能

- 种子发现: `skills/site-seed-discovery/SKILL.md`
- 列表发现: `skills/sitemap-list-discovery/SKILL.md`
- SPU 代码嵌入: `skills/spu-code-embed/SKILL.md`
- 浏览器回退: `skills/playwright-cli/SKILL.md`

## 输入数据

- 数据集模板: `input/dataset_url_template.json`

## 任务类型与字段规则

### 任务类型

- `type` / `task_type`: 控制是否启用 review stats
- `extra_tasks`: 控制是否启用 list_discovery
- `type = "with_review_stats"`: 启用 review stats
- `extra_tasks = ["list_discovery"]`: 启用列表发现，产出 `site_delivery_summary.md`

### SPU/SKU 字段规则

#### 通用规则

- `script_res` 中所有 key 必须存在，值为 `None` 表示缺失
- 缺失字段不能省略，必须显式设为 `None`
- 单 SKU 与多 SKU case 必须分别处理，不可混淆
- `props` 必须为 dict，SPU 无属性时为 `{}`
- `skus[].sku_props` 必须为 dict，SKU 无属性时至少包含 `SKU` 或 `Model` 等业务标识

#### 价格规则

- `source_origin_price` / `source_activity_price` 必须为数字
- 显示 `Free` / `$0` / `0` 时标准化为 `0`
- 价格字段为 `None` 而非空字符串
- `source_price_currency` 为 3 位大写货币代码 (USD/CNY/EUR 等)
- 货币从 market/currency/locale 推断，可来自 API/inline state/cookie/header

#### SKU 规则

- 单 SKU PDP 如只有一个空 props 的 SKU，应折叠到 SPU 层
- WooCommerce: `form.variations_form`, `data-product_id`, `select[name*="attribute"]` + swatch
- 礼品卡类: Value/Amount/Denomination + selector/swatch -> `sku_props`
- 图片映射: swatch/option 的 `data-id`/`data-image-id`/`data-variant-id`/`data-color`/`data_id` -> per-option gallery
- variant_images / variation_gallery_images 用于 SKU 图片分组
- `items` / `variants` / `offers` / `childSkus` -> `skus[]`
- 可见不可用 (visible_unavailable): selector/button/dropdown/condition row -> `status=0`
- deep_oos/unavailable/sold out/incoming/notify me -> `status=0`
- URL query / merchant sku / style code -> `props` / `sku_props`
- sibling swatch / ProductFlow redirect / plan builder / bundle builder -> `sku_props`
- Subscription / One-Time / Subscribe & Save -> `sku_props`
- Gift Card Design x Value 矩阵 -> `skus[]`
- payload/inline state/API 中价格为 `0`/`0.0` 且无真实 SKU -> `status=0`
- Stage1/Stage2 中已标注 `status=0` 的 SKU，Stage3 checker 应保持一致

#### Review Stats 规则

- `type = "with_review_stats"` 时必须提取 `source_score` / `source_cmms`
- `type != "with_review_stats"` 时 `source_score` / `source_cmms` 必须为 `None`
- Review provider 类型:
  - Bazaarvoice, PowerReviews, Yotpo, Judge.me, Loox, Shopper Approved 等
  - widget 嵌入 / API 调用 / JSON-LD aggregateRating
- 证据文件:
  - `raw_html/review_provider_discovery.json`
  - `raw_html/review_stats_request.json`
  - `raw_html/review_stats_response.json`
  - `context/review_field_mapping.md`
- `source_cmms` 从 review count / "N Reviews" / API total 字段提取
- `source_score` 从同一 provider/API 提取
- 如 widget aggregate 与 product-only stats 不一致，以 product-only 为准
- 无法获取时设为 `None`，记录 fallback 原因到 risks

## Stage 详细规则

### Stage1: 原始数据采集

- 使用 `curl_cffi.requests` 抓取静态 HTML
- 产出: `dom_analysis.md` (参考 `references/stage2_anchor_schema.md`)
- 产出: `stagel_raw_gt.json` (参考 `references/raw_product_schema.jsonc`)
  - raw PDP 数据，`_projection_props` 保留 SKU 级别属性
  - 多 SKU 时 raw 有 `skus[]`
  - SPU 级别字段: `source_origin_price` / `source_activity_price` / `source_price_currency` / `props` / `status`
- 后处理: `scripts/postprocess_raw_product.py` -> `stage1_gt.json`
  - 参考 `references/target_product_schema.jsonc`

### Stage2: 浏览器渲染与解析

- Playwright 渲染，产出 `rendered_page.html`
- 价格:
  - buybox / price block 识别 (strike-through / list / was / regular / compare-at + sales / current / sale / value)
  - `source_origin_price` / `source_activity_price` 映射
  - PDP DOM 中 badge / offers.price / salePrice / catalogSalePrice / compare_at_price 等信号
  - DOM 可见价格 vs offer/payload 价格不一致时的处理
  - "list + sales" 模式识别
- Review Stats:
  - JSON-LD aggregateRating 作为 fallback
  - widget + HTML 解析 + review API
  - Shopper Approved: `shopperapproved.com/widgets`, `saLoadScript`, `SA.`, `tempReviews`
  - merchant/company fallback vs product-only stats
  - widget "N Reviews" vs API `pagination total` / `tempReviews.total` / `reviews.total` / `meta.total`
- SKU:
  - `_projection_mode: "explicit_spu"` 时 SPU 有自己的价格/属性/状态
  - `_projection_props` 从 SKU 投影到 SPU
  - 价格字段命名: old/was/original/list/regular/max/compare-at + current/sale/price/value
  - sale_price / selling_price / compare_at_price / price / regular_price
  - compare_at_price > selling_price 时的 origin/activity 映射
  - discount_percent badge sanity check
- 货币:
  - market/currency/locale/country 从 API/inline state/cookie/header 推断
  - Shopify / headless / market-aware 场景
- SKU 状态:
  - `skus[]` 中可见 selector 为 disabled -> `status=0`
  - 单 SKU 折叠规则
- Description:
  - 保留可见块结构 (rich text / bullet list / table)
- Commerce Origin:
  - `shop.*` Shopify / storefront host 识别
  - `commerce_origin` 字段记录

### Stage3: 代码嵌入与校验

- 参考 `skills/spu-code-embed/SKILL.md`
- Live checker: `skills/spu-code-embed/scripts/final_code_check.py`
- Offline checker: `skills/spu-code-embed/scripts/final_code_check_offline.py`
- 渲染: `skills/spu-code-embed/scripts/final_render_html.py`
- blocked site 使用 offline checker + Stage1 evidence
- `final_code.py` 必须自包含，无外部文件依赖
- `script_res` 必须包含所有字段，缺失为 `None`
- Stage3 checker 中的 `script_res` 严格遵循 Stage2 target schema

### Stage4: 列表发现 (可选)

- 由 `list_agent` 执行，参考 `skills/sitemap-list-discovery/SKILL.md`
- 发现 PDP URL 的 sitemap / 子 sitemap / 列表页 / API / JSON state
- 产出: `list_custom_code` 或 `sitemap + Detail_url_pattern`
- 产出: `site_delivery_summary.md` + Stage4 batch HTML 报告

## 代理职责

- `orchestrator_agent`: 批处理调度、工作树管理、重试策略
- `seed_agent`: 种子 URL 发现
- `site_agent`: 单站点爬取协调 (Stage4 + Stage3)
- `extract_agent`: Stage2-3 SPU/SKU 提取
- `list_agent`: Stage4 列表发现

详见 `references/agent_responsibilities.md`

## 人工操作流程

参考 `references/human_operation_flow.md`

## 网页分析手册

参考 `references/web_analysis_playbook.md`

## 输出物

- Stage1: `raw_html/static_page.html`, `stagel_raw_gt.json`, `stage1_gt.json`
- Stage2: `raw_html/rendered_page.html`, `stage2_script_res.json`
- Stage3: `result/script_gen/final_code.py`, `rendered_spu_skus_final.html`
- Stage4: `site_delivery_summary.md`, Stage4 HTML 报告
