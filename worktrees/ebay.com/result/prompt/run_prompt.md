# Run Prompt Template (taojin v3)

> **站点**: `ebay.com`
> **工作树**: `/Users/yuzhizheng/Desktop/codex/codex_agent_product_info_template_pro/worktrees/20260709`
> **任务类型**: `{task_type}`
> **额外任务**: `{extra_tasks}`

---

## 1. 目标说明 (Objective)

从指定电商站点提取产品 SPU/SKU 信息，生成可运行的 Python 提取代码。

根据任务配置，可能包含：
- 产品信息提取（SPU/SKU）
- Review stats 提取（如启用）
- 列表发现（如启用）

---

## 2. 参考资料列表 (References)

### 2.1 核心参考

- `skills/taojin_v3_crawl_skill/references/agent_responsibilities.md` — Agent 职责说明
- `skills/taojin_v3_crawl_skill/references/stage2_anchor_schema.md` — Stage2 锚点 schema
- `skills/taojin_v3_crawl_skill/references/web_analysis_playbook.md` — 网页分析手册
- `skills/taojin_v3_crawl_skill/references/raw_product_schema.jsonc` — 原始产品 schema
- `skills/taojin_v3_crawl_skill/references/target_product_schema.jsonc` — 目标产品 schema
- `skills/taojin_v3_crawl_skill/references/human_operation_flow.md` — 人工操作流程
- `skills/taojin_v3_crawl_skill/references/worktree_operations.md` — 工作树操作说明

### 2.2 Playwright 相关

- `skills/playwright-cli/SKILL.md`
- `skills/playwright-cli/references/playwright_cli_quickstart.md`
- `skills/playwright-cli/references/proxy_toolkit_quickstart.md`
- `skills/playwright-cli/scripts/proxy-access.js`

### 2.3 SPU 代码嵌入

- `skills/spu-code-embed/SKILL.md`
- `skills/spu-code-embed/references/code_embed_skill.md`
- `skills/spu-code-embed/references/final_code_change.md`
- `skills/spu-code-embed/scripts/final_code_check.py`
- `skills/spu-code-embed/scripts/final_code_check_offline.py`
- `skills/spu-code-embed/scripts/final_render_html.py`

### 2.4 列表发现

- `skills/sitemap-list-discovery/SKILL.md`
- `skills/sitemap-list-discovery/references/discovery_playbook.md`
- `skills/sitemap-list-discovery/references/detail_url_pattern_rules.md`
- `skills/sitemap-list-discovery/references/html_report_contract.md`
- `skills/sitemap-list-discovery/references/html_report_template.html`
- `skills/sitemap-list-discovery/references/runtime_compatibility.md`

### 2.5 工具脚本

- `skills/taojin_v3_crawl_skill/scripts/postprocess_raw_product.py`
- `skills/taojin_v3_crawl_skill/scripts/stage2_self_test.py`
- `skills/taojin_v3_crawl_skill/assets/self_test_config_template.jsonc`

---

## 3. 任务类型说明 (Task Type)

### 3.1 type / task_type

控制是否启用 review stats 提取。

| 值 | 说明 |
|----|------|
| `with_review_stats` | 启用 review stats，必须提取 `source_score` / `source_cmms` |
| 其他 | 不启用，`source_score` / `source_cmms` 必须为 `None` |

### 3.2 extra_tasks

控制是否启用额外任务。

| 值 | 说明 |
|----|------|
| `["list_discovery"]` | 启用列表发现，执行 Stage4，产出 `site_delivery_summary.md` + HTML 报告 |
| `[]` | 不启用列表发现，仅执行 Stage2-3 |

### 3.3 任务类型说明 ({task_type_notes})

{task_type_notes}

---

## 4. 运行环境 (Environment)

### 4.1 工作目录

所有产出文件写入当前工作树的 `result/` 目录。

工作目录结构：
```
result/
├── prompt/
│   └── run_prompt.md
├── raw_html/
│   ├── static_page.html
│   ├── rendered_page.html
│   ├── *_request.json
│   └── *_response.json
├── context/
│   ├── field_mapping.md
│   └── review_field_mapping.md
├── dom_analysis.md
├── stage1_raw_gt.json
├── stage1_gt.json
├── stage2_script_res.json
└── script_gen/
    ├── extract_ebay.com.py
    ├── final_code.py
    ├── final_code_change.md
    ├── final_code_check.py
    ├── final_code_check_offline.py
    ├── rendered_spu_skus_final.html
    └── self_test_config.json
```

---

## 5. Agent 协作与 Stage 流转 (Agent Orchestration)

### 5.1 角色总览

本任务涉及以下 agent，各有明确职责边界：

- `orchestrator_agent`: 批处理调度、重试策略、工作树管理（优先级 5.5xhigh）
- `seed_agent`: 种子 URL 发现（优先级 xhigh）
- `site_agent`: 单站点爬取协调（优先级 xhigh）
- `extract_agent`: Stage2-3 SPU/SKU 提取（优先级 xhigh）
- `list_agent`: Stage4 列表发现（优先级 xhigh）

详见 `references/agent_responsibilities.md`。

### 5.2 种子发现

由 `seed_agent` 执行种子发现：
1. `seed_agent` 向 `orchestrator_agent` 汇报，优先级 `xhigh`
2. `orchestrator_agent` 优先级 `5.5xhigh`，每个 `seed_agent` 一个工作树
3. 产出 `input/dataset_url_template.json`，由 `orchestrator_agent` 持有
4. `orchestrator_agent` 执行 `worktree setup` 并生成 `run_prompt.md`

### 5.3 站点代理

`site_agent` 负责单站点的 Stage 协调：
1. `site_agent` 向 `orchestrator_agent` 汇报，优先级 `xhigh`
2. `orchestrator_agent` 优先级 `5.5xhigh`，每个 `site_agent` 一个工作树
3. 工作树路径: `result/prompt/run_prompt.md`
4. `orchestrator_agent` 调度 `site_agent`，协调各站点的执行

### 5.4 Stage 流转

- Stage2-3 由 `extract_agent` 以 "v3" 模式执行
- Stage4 由 `list_agent` 执行（当 `extra_tasks` 包含 `list_discovery` 时）
- 详见 `references/agent_responsibilities.md`

### 5.5 工作树管理

由 `orchestrator_agent` 统一管理工作树的创建、调度和清理：

1. MUST: 各 agent 职责遵循 `references/agent_responsibilities.md`
2. MUST: `orchestrator_agent` / `seed_agent` / `site_agent` / `extract_agent` / `list_agent` 优先级均为 `xhigh`
   - 例外：`orchestrator_agent` 为 `5.5xhigh`，高于其他 agent
3. MUST: `orchestrator_agent` 拥有批处理视图，负责调度 + 重试 + 工作树管理 + 产出汇总
4. MUST: 每个站点一个工作树，`worktrees/*` 下可见
5. SHOULD: `orchestrator_agent` 负责任务类型配置传递（task_type / review_stats_required / list_discovery_required）
6. MUST: 每个 agent 只操作自己的工作树，不跨站修改

---

## 6. Stage1: 原始数据采集 (Raw GT)

### 6.1 概述

使用 `curl_cffi.requests` 抓取静态 HTML，提取原始产品数据。

**入口 PDP URL**: `{product_url}`

### 6.2 多 SKU 识别

首先判断是否为多 SKU PDP：
- 信号：swatch / radio / select / variant picker / `data-product-option-change` / `variations_form` 等
- 如确认是多 SKU PDP，在 Stage2/Stage3 完整提取 SKU 矩阵
- 在 `dom_analysis.md` / `final_code_change.md` 中标注 "多 SKU PDP"

### 6.3 Stage1 步骤

1. 参考 `references/web_analysis_playbook.md` 进行 DOM 分析
2. 使用 `curl_cffi.requests` 抓取静态 HTML，保存到 `raw_html/static_page.html`
   - 如遇 403/429/"Just a moment..."/captcha 等反爬，参考 `skills/playwright-cli/references/proxy_toolkit_quickstart.md` 使用代理绕过
3. MUST (SPU 级别): 提取 title / pics / descriptions / props / status，以及 JSON-LD / inline state / API payload 中的 media 等 SPU 级别字段
4. MUST: 保留 `source_spu_id` 字段（如可获取）

### 6.4 Pretty URL + Inner Detail Endpoint 模式

**MUST**: 对于 "outer pretty URL + inner detail endpoint/API" 架构：
- Stage1 先抓 outer pretty URL HTML，确认是否为 PDP
- 通过 pretty HTML 中的 `data-product` / `productName` / `dw.ac.capture` / `canonical` / `data-pid` / `data-productid` 等信号定位 inner detail endpoint/API
- 如果 inner endpoint 存在，且 pretty HTML 已经包含 title / pics / descriptions / props / status / sku 等字段，也要记录
- MUST: price / status / currency 等字段要验证（来自 commerce state / analytics telemetry / weak signal 等），并在 `dom_analysis.md` 中记录
- MUST: 如果 inner detail endpoint/API 存在，保存对应的 `raw_html/*_request.json` / `raw_html/*_response.json`
- MUST: 如果 pretty URL 返回 404/500/not found shell 等，但通过 path/query 参数或 inner product API/fragment endpoint 仍能获取 payload，标记为 "outer page degraded, inner product still alive"，不标记为 deadlink

### 6.5 Stage1 输出

1. 生成 `dom_analysis.md`，参考 `references/stage2_anchor_schema.md`
2. 生成 `stage1_raw_gt.json`，参考 `references/raw_product_schema.jsonc`
   - raw PDP 数据，`_projection_props` 保留 SKU 级别属性
   - 多 SKU 时 raw 有 `skus[]`
   - `_projection_mode: "explicit_spu"` 时 SPU 有自己的价格/属性/状态
3. 运行 `scripts/postprocess_raw_product.py` 生成 `stage1_gt.json`，参考 `references/target_product_schema.jsonc`

### 6.6 Review Stats (如启用)

MUST (如 review_stats_required != True): `source_score` / `source_cmms` 设为 None

- 如 `review_stats_required = True`，Stage1 探索 review provider 类型（review widget / review API / JSON-LD `aggregateRating` fallback）
- 保存证据：`raw_html/review_provider_discovery.json` / `raw_html/review_stats_request.json` / `raw_html/review_stats_response.json` / `context/review_field_mapping.md`
- Provider 包括：Bazaarvoice, Yotpo, PowerReviews, Judge.me, Loox, Shopper Approved 等

**MUST (Provider 优先级)**: DOM/widget > widget API > JSON-LD fallback

**Bazaarvoice review product id 查找**:
1. `data-bv-product-id` / widget 配置 id
2. `masterId` / family id
3. `gtmData.id` / `gtmGA4Data.item_id`
4. URL 中的 pid / SKU / variant id
5. URL path + DOM/widget id 推断

**PowerReviews 识别**:
- `pr-snippet-*`, `powerreviews.com`, `display.powerreviews.com/n/{merchant_id}/1/{locale}/product/{page_id}/snippet`
- 从 network 请求提取 `merchant_id`, `apikey`, `page_id`, `locale` 参数

**Shopper Approved 识别**:
- `shopperapproved.com/widgets`, `saLoadScript`, `SA.`, `tempReviews`
- 区分 widget aggregate 和 product-only / pagination 数据

**规则**:
- `source_cmms` 和 `source_score` 必须来自同一 provider/API
- 如不一致，记录在 `context/review_field_mapping.md` 的 `score_count_same_provider`
- 零评论时：`source_cmms = 0`，`source_score` 根据 provider 规则设为 0.0 或 None

### 6.7 价格与状态

MUST (可见性验证): price / status / source_score / source_cmms / 当前 props 等字段要验证，与 Stage2 渲染后的 `rendered_page.html` / Playwright text snapshot / screenshot 对比

- JSON/JSON-LD/inline state 中的字段要记录来源和映射
- 运行时 XHR/fetch/API 也需要追踪
- 在 `dom_analysis.md` / `context/field_mapping.md` 中记录 1-2 个 "DOM vs payload vs API" 的对比点

### 6.8 Commerce Origin

MUST (commerce origin 识别): 从 discovery/Stage1 的 `input_site` 出发，识别 PDP / buybox / storefront 的 `commerce_origin`，在 Stage2/Stage3 保持一致的 commerce surface

---

## 7. Stage1 补充规则

### 7.1 SKU 相关

- **Sibling swatch 处理**: 如 PDP 有 sibling swatch / similar item / variant thumbnail 等，通过 URL-split 处理
  - `product.siblings[]`, color swatch href, handle, group/YGroup tag, `color_*` tags 等信号
  - sibling 作为颜色维度加入 `skus[].props`
- **Swatch 类型**: 区分 `navigation_swatch`（跳转 URL）和 `matrix_swatch`（同页选项矩阵）
- **变体图片**: swatch/option 的 `data-id` / `data-image-id` / `data-variant-id` / `data-color` / `data_pic` / 图片索引 → per-option gallery
- **SKU 状态**: 
  - 可见不可用 (visible_unavailable): selector/button/dropdown/condition row → `status=0`
  - deep_oos/unavailable/sold out/incoming/notify me → `status=0`
- **业务编码作属性**: URL query / merchant sku / style code → `props` / `sku_props`
- **零价格占位**: payload 中 price=0/0.0 且无真实 SKU → `status=0`；Free/$0 商品 → 价格为 0

### 7.2 价格语义

- **命名模式**: old/was/original/list/regular/max/compare-at + current/sale/price/value
- **list + sales 模式**: DOM buybox 中 list/was + sale/current 模式识别
- **priceRange 处理**: 精确 SKU 价格 > 配置好的 variation API 价格 > 产品价格 > priceRange lower fallback
- **金融/月付价格**: 拒绝融资价格，使用 list/regular/full_price
- **货币推断**: 从 API/inline JSON/cookie/header 中的 currency/country/locale/market 推断

### 7.3 描述处理

- 保留可见块结构（rich text / bullet list / table）
- meta description 仅作 fallback

---

## 8. Stage2: 浏览器渲染与解析

### 8.1 输入输出

**输入**: Stage1 产出（`dom_analysis.md` / `stage1_raw_gt.json` / `stage1_gt.json`）

**输出**:
- `result/script_gen/extract_ebay.com.py`
- `stage2_script_res.json`（v2 target schema）
- `stage2_self_test.py` 自检通过

### 8.2 Stage2 路径

优先级：`live_html → live_api → offline_evidence`

- **live_html**: 当前 PDP HTML / Playwright 渲染后的完整 HTML
- **live_api**: 从 PDP HTML 中发现的可用 API 接口，用 requests + API 调用
- **offline_evidence**: 如 Live HTML / Live API 都失败，用 Stage1 的 `raw_html/*` 和证据文件

### 8.3 核心要求

1. 验证 Stage1 的字段映射，更新 `dom_analysis.md`
2. 浏览器渲染补充动态加载内容
3. 修正 Stage1 的错误
4. 运行 `scripts/stage2_self_test.py` 自检
5. MUST: Stage2 不改变 Stage1 的核心结构（如 SKU 数量级变化需记录原因）

### 8.4 Blocked Site 处理

如遇 403/429 + Cloudflare "Just a moment..." 等阻挡：
- Stage2 尽力而为
- 使用 Stage1 的证据文件作为 offline_evidence
- 记录在 `process_notes` 中

---

## 9. Stage3: 代码嵌入与校验

### 9.1 目标

将 Stage2 的提取逻辑封装为自包含的 `final_code.py`，可独立运行。

### 9.2 步骤

1. 参考 `skills/spu-code-embed/SKILL.md` 和相关文档
2. 从 `result/script_gen/extract_ebay.com.py` 优化为 `final_code.py`
3. 复制检查脚本和渲染脚本到 `result/script_gen/`
4. 运行 `final_code_check.py` 或 `final_code_check_offline.py` 验证
5. 生成 `final_code_change.md` 记录变更

### 9.3 final_code.py 要求

- MUST: 自包含，无外部文件依赖
- MUST: `script_res` 包含所有字段，缺失为 `None`
- MUST: 严格遵循 target schema
- MUST: `final_code.py` 可通过 `compile(...)`

### 9.4 Blocked Site 离线检查

被阻挡站点使用 offline checker + Stage1 evidence：
- `final_code_check_offline.py`
- 基于 `stage1_gt.json` 和样本 URL

---

## 10. Stage4: 列表发现 (可选)

### 10.1 触发条件

仅当 `list_discovery_required = True` 时执行 Stage4。

### 10.2 职责

由 `list_agent` 执行 Stage4 列表发现：
- 发现 PDP URL 的 sitemap / 子 sitemap / 列表页 / API / JSON state
- 产出 `sitemap` + `Detail_url_pattern` 或 `list_custom_code`
- 产出 `sample_detail_uris`（3-5 个样本）
- 产出 `process_notes` 和 `coverage`
- 参考 `skills/sitemap-list-discovery/SKILL.md`

### 10.3 覆盖状态

| 状态 | 说明 |
|------|------|
| `ok` | 有真实 PDP URL 且成功发现 |
| `partial` | 有部分 PDP URL 但覆盖不完整 |
| `none` | 站点可达但未找到真实 PDP URL |
| `blocked` | 被反爬阻挡，无绕过方法 |
| `dead` | 站点停放、过期、永久不可达 |
| `amb` | 站点可达但有效电商表面不明确 |

### 10.4 交付物

当 `list_discovery_required = True` 时，额外产出：

- `site_delivery_summary.md`
- `worktrees/taojin_v3_{site_count}sites_{MM-DD_HH-MM-SS}/taojin_v3_{site_count}sites_{MM-DD_HH-MM-SS}.html`

---

## 11. SPU/SKU 字段规则

### 11.1 通用规则

- MUST: `script_res` 中所有 key 必须存在，值为 `None` 表示缺失
- MUST: 缺失字段不能省略，必须显式设为 `None`
- MUST: 单 SKU 与多 SKU case 必须分别处理，不可混淆
- MUST: `props` 必须为 dict，SPU 无属性时为 `{}`
- MUST: `skus[].sku_props` 必须为 dict，SKU 无属性时至少包含 SKU/Model 等业务标识

### 11.2 价格规则

- `source_origin_price` / `source_activity_price` 必须为数字
- 显示 `Free` / `$0` / `0` 时标准化为 `0`
- 价格字段为 `None` 而非空字符串
- `source_price_currency` 为 3 位大写货币代码 (USD/CNY/EUR 等)
- 货币从 market/currency/locale 推断，可来自 API/inline state/cookie/header

### 11.3 SKU 规则

- 单 SKU PDP 如只有一个空 props 的 SKU，应折叠到 SPU 层
- WooCommerce: `form.variations_form`, `data-product_id`, `select[name*="attribute"]` + swatch
- 礼品卡类: Value/Amount/Denomination + selector/swatch → `sku_props`
- 图片映射: swatch/option 的 `data-id`/`data-image-id`/`data-variant-id`/`data-color`/`data_id` → per-option gallery
- `variant_images` / `variation_gallery_images` 用于 SKU 图片分组
- `items` / `variants` / `offers` / `childSkus` → `skus[]`
- 可见不可用 → `status=0`
- deep_oos/unavailable/sold out/incoming/notify me → `status=0`
- URL query / merchant sku / style code → `props` / `sku_props`
- sibling swatch / ProductFlow redirect / plan builder / bundle builder → `sku_props`
- Subscription / One-Time / Subscribe & Save → `sku_props`
- Gift Card Design x Value 矩阵 → `skus[]`
- payload/inline state/API 中价格为 `0`/`0.0` 且无真实 SKU → `status=0`
- Stage1/Stage2 中已标注 `status=0` 的 SKU，Stage3 checker 应保持一致

### 11.4 Review Stats 规则

- `type = "with_review_stats"` 时必须提取 `source_score` / `source_cmms`
- `type != "with_review_stats"` 时必须为 `None`
- Review provider 类型: Bazaarvoice, PowerReviews, Yotpo, Judge.me, Loox, Shopper Approved 等
- 证据文件必须保存
- `source_cmms` 从 review count / "N Reviews" / API total 字段提取
- `source_score` 从同一 provider/API 提取
- 如 widget aggregate 与 product-only stats 不一致，以 product-only 为准
- 无法获取时设为 `None`，记录 fallback 原因到 risks

---

## 12. 交付物 (Deliverables)

### 12.1 标准交付（Stage2-3）

| 文件 | 说明 |
|------|------|
| `result/dom_analysis.md` | DOM 分析与锚点记录 |
| `result/stage1_raw_gt.json` | Stage1 原始提取数据 |
| `result/stage1_gt.json` | Stage1 后处理数据 |
| `result/stage2_script_res.json` | Stage2 提取结果 |
| `result/raw_html/static_page.html` | 静态 HTML |
| `result/raw_html/rendered_page.html` | 渲染后 HTML |
| `result/script_gen/final_code.py` | 最终可运行代码 |
| `result/script_gen/final_code_change.md` | 代码变更记录 |
| `result/script_gen/rendered_spu_skus_final.html` | 渲染验证 HTML |

### 12.2 Stage4 交付（如启用）

| 文件 | 说明 |
|------|------|
| `result/site_delivery_summary.md` | 站点交付总结 |
| `output/per_site/{site}.json` | 站点 Stage4 结果 |
| `output/stage4_report.html` | 批量 HTML 报告 |

---

## 13. 自检 (Self-Test)

运行 Stage2 自检：
```bash
python skills/taojin_v3_crawl_skill/scripts/stage2_self_test.py \
  --config result/script_gen/self_test_config.json
```

运行 Stage3 检查：
```bash
python result/script_gen/final_code_check.py \
  --detail-url-file input/ebay.com_uris.txt \
  --clear_rendered_html \
  --continue_on_error
```

---

**开始执行。**
