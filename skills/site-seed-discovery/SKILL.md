---
name: site-seed-discovery
description: Discover live PDP/SPU seed URLs for one or more sites. Use when the user needs to find real product detail page URLs for a site, validate them, and write them into input/dataset_url_template.json for downstream taojin_v3_crawl_skill workflow.
---

# site-seed-discovery

本 skill 负责为站点发现真实可用的 detail page / PDP / SPU URL。

## 目标

1. 为每个站点发现至少 5 个真实可用的 SPU URL
2. 写入 `input/dataset_url_template.json`
3. 通过 diversity review

## 输入

- 站点域名或首页 URL
- 目标 seed 数量（默认 5）
- 模式：`replace-all` 或 `merge`
- 输出：`input/dataset_url_template.json`

## Quick Start

```bash
# 基本用法
python skills/site-seed-discovery/scripts/discover_seed_urls.py \
  --site-domain example.com \
  --count 5 \
  --replace-all
```

## 参考文件

- 发现策略与边界：`references/discovery_playbook.md`
- 发现脚本：`scripts/discover_seed_urls.py`
- 更新脚本：`scripts/update_dataset_template.py`

## Playwright fallback 支持

- `skills/playwright-cli/SKILL.md`
- `skills/playwright-cli/references/evidence-capture.md`
- `skills/playwright-cli/references/proxy-fallback.md`

## Navigation

- 详细发现策略：`references/discovery_playbook.md`
- 发现脚本：`scripts/discover_seed_urls.py`
- 更新脚本：`scripts/update_dataset_template.py`

## Output Contract

最终输出包含：

1. 至少 5 个真实可用的 SPU URL
2. 写入 `input/dataset_url_template.json`
3. 通过 diversity review

输出字段：

- 模式：`replace-all` 或 `merge`
- 输出：`input/dataset_url_template.json`
- 状态：`ok` / `shortfall` / `fail`
- `site_domain`
- `status`: `ok` / `shortfall` / `fail`
- `spu_urls`
- `count`
- `attempted_paths`
- `shortfall_reason`（若 `< 5`，需说明原因）
- `discovered_patterns`
- `selected_patterns`
- `selected_categories`
- `known_but_unselected_categories`
- `diversity_status`: `pass` / `warn` / `fail`
- `complex_sku_candidate_count`
- `selected_complex_sku_count`
- `complex_sku_status`: `pass` / `fail`

## 验收标准

- 至少 5 个真实可用的 SPU URL
- 若存在多个 category，seed 必须覆盖多个 category
- 若存在多个 PDP template signature，seed 必须覆盖多个 template family
- 若为 Next.js / SPA 站点，解析 `__NEXT_DATA__` / hydration route，识别 page route，例如：`/products/babyblends/[id]/[name]` 与 `/products/smoothies/[id]/[name]` 视为不同 template
- 复杂 SKU 候选必须命中：候选 PDP 页面包含 `swatch` / `radio` / `select` / `option` / `variant_picker` 信号，视为复杂 SKU 候选，若存在复杂 SKU 候选，seed 中至少 1 个复杂 SKU PDP，否则 Stage2/Stage3 可能无法抽取 SKU
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

## 输出模式

- 默认：`replace-all`，覆盖整个 dataset
- `merge`：与现有 `input/dataset_url_template.json` 合并

### `replace-all`

```bash
python skills/site-seed-discovery/scripts/discover_seed_urls.py \
  --site-domain example.com \
  --count 5 \
  --replace-all
```

- 推荐：当前 batch 全量覆盖
- 不推荐：保留旧 seed，仅追加新 seed

### `merge`

```bash
python skills/site-seed-discovery/scripts/discover_seed_urls.py \
  --site-domain example.com \
  --count 5
```

- 推荐：保留旧 seed，仅追加新 seed
- 不推荐：当前 batch 全量覆盖

## 示例

### A. 全量覆盖（推荐）

```bash
python skills/site-seed-discovery/scripts/discover_seed_urls.py \
  --site-domain example.com \
  --count 5 \
  --replace-all
```

### B. 合并（保留旧 seed）

```bash
python skills/site-seed-discovery/scripts/update_dataset_template.py \
  --dataset-json input/dataset_url_template.json \
  --entries-file /tmp/site_seed_entries.json \
  --replace-all
```

## 注意

- `/tmp/site_seed_entries.json` 可由其他工具生成，包含 `spu_urls` 字段
- 若 `--allow-shortfall` 允许少于 5 个 URL，仅在确认站点确实只有少量有效 SPU URL 时使用
- 若候选 URL 不是真实 detail URL，会被标记为 `non_detail`
- 若 URL 返回 401/403 或包含 captcha，会被标记为 `locked`
- 若 URL 返回 404 或包含 not found 标记，会被标记为 `deadlink`

## 输出文件

- `input/dataset_url_template.json` 包含 `spu_urls` 字段，每个站点对应一个对象
- 若 `spu_urls` 字段为空，说明该站点没有有效的 SPU URL
- 若 `site_domain` 字段为空，脚本会从 `spu_urls` 中推断
- 若 `spu_urls` 字段包含多个域名，脚本会报错

## 失败处理

- 若 discovery 失败 SKU PDP，但 seed 中未包含复杂 SKU PDP，会标记为 `complex_sku_status: fail`
- 若存在多个 category，但 seed 未覆盖多个 category，会标记为 `diversity_status: fail`
- 若 discovery 失败，会输出 `status: fail`，并说明具体原因

## 角色

- `seed_agent` 负责发现 seed
- `orchestrator_agent` 负责接收 report，并写入 `input/dataset_url_template.json`

## 示例输出

```json
{
  "site_domain": "example.com",
  "status": "ok",
  "count": "5",
  "spu_urls": [
    "https://example.com/products/1",
    "https://example.com/products/2",
    "https://example.com/products/3",
    "https://example.com/products/4",
    "https://example.com/products/5"
  ],
  "attempted_paths": "homepage, robots.txt, sitemap.xml",
  "shortfall_reason": "若少于 5 个 SPU URL，需说明原因"
}
```

## 失败示例

```json
{
  "site_domain": "example.com",
  "status": "fail",
  "count": "0",
  "spu_urls": [],
  "attempted_paths": "homepage, robots.txt, sitemap.xml",
  "shortfall_reason": "无法发现任何 SPU URL，请检查站点是否支持 sitemap"
}
```

## 复杂 SKU 示例

```json
{
  "site_domain": "example.com",
  "status": "ok",
  "count": "5",
  "spu_urls": [
    "https://example.com/products/1",
    "https://example.com/products/2",
    "https://example.com/products/3",
    "https://example.com/products/4",
    "https://example.com/products/5"
  ],
  "complex_sku_candidate_count": 3,
  "selected_complex_sku_count": 1,
  "complex_sku_status": "pass"
}
```

## 注意事项

- 若 discovery 发现 SKU PDP，但 seed 中未包含复杂 SKU PDP，会标记为 `complex_sku_status: fail`
- 若 discovery 发现多个 category，但 seed 未覆盖多个 category，会标记为 `diversity_status: fail`
- 若 discovery 失败，会输出 `status: fail`，并说明具体原因
- 若 discovery 成功，会输出 `status: ok`，并写入 `input/dataset_url_template.json`
- 若 discovery 成功，但 seed 中未包含复杂 SKU PDP，会标记为 `complex_sku_status: fail`
- 若 discovery 成功，但 seed 中未覆盖多个 category，会标记为 `diversity_status: fail`
- 若 discovery 成功，但 seed 中未覆盖多个 template family，会标记为 `diversity_status: warn`
