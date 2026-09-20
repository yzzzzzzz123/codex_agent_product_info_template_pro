# codex_agent_product_info_template_pro

从截图还原的 Codex Agent 商品信息采集模板项目。

## 项目结构

```text
codex_agent_product_info_template_pro/
├── docs/environment_setup.md             # 环境搭建指南
├── input/dataset_url_template.json       # 数据集URL模板
├── pyproject.toml
├── AGENTS.md                             # Agent架构文档
├── README.md
└── skills/
    ├── playwright-cli/                   # 浏览器自动化 skill
    │   ├── SKILL.md
    │   ├── scripts/
    │   │   ├── proxy-access.js
    │   │   └── fetch_html_with_fallback.py
    │   └── references/
    ├── site-seed-discovery/              # 种子URL发现 skill
    │   ├── SKILL.md
    │   ├── scripts/
    │   │   ├── discover_seed_urls.py
    │   │   └── update_dataset_template.py
    │   └── references/
    ├── sitemap-list-discovery/           # Stage4 列表发现 skill
    │   ├── SKILL.md
    │   └── references/
    ├── spu-code-embed/                   # Stage3 SPU代码嵌入 skill
    │   ├── SKILL.md
    │   ├── scripts/
    │   │   ├── final_code_check.py
    │   │   ├── final_code_check_offline.py
    │   │   └── final_render_html.py
    │   └── references/
    └── taojin_v3_crawl_skill/            # 主爬取 skill (v3)
        ├── SKILL.md
        ├── assets/
        │   ├── run_prompt_template.md
        │   └── self_test_config_template.jsonc
        ├── scripts/
        │   ├── worktree_cli.py
        │   ├── postprocess_raw_product.py
        │   ├── stage2_self_test.py
        │   ├── get_sku_id_spu_id.py
        │   ├── eval_spu_extraction.py
        │   ├── loose_eval_spu_extraction.py
        │   ├── render_stage4_site_summary.py
        │   ├── render_stage4_batch_report.py
        │   ├── assemble_html_report.py
        │   └── run_batch.py
        └── references/
            ├── agent_responsibilities.md
            ├── web_analysis_playbook.md
            ├── human_operation_flow.md
            ├── stage2_anchor_schema.md
            ├── stage4_html_report_template.html
            ├── raw_product_schema.jsonc
            ├── target_product_schema.jsonc
            ├── extraction_result_schema.json
            ├── extraction_result_example.jsonc
            ├── eval_output_schema.json
            ├── worktree_operations.md
            └── ...
```

## single_spu_task

### 入门: taojin v3 (推荐)

`skills/taojin_v3_crawl_skill` 是 v2 派生的端到端爬取工作流（Stage1 采集、Stage2 解析、Stage3 嵌入，可选 Stage4 列表发现）。保持 v2 的 Stage1/Stage2 数据契约，将 Stage2-3 委托给下游代理，浏览器回退委托给 `skills/playwright-cli`，当任务启用列表发现时进入可选的 Stage4，直接调用 `skills/sitemap-list-discovery` 进行单站点列表发现。

- 技能入口: `skills/taojin_v3_crawl_skill/SKILL.md`
- 工作树操作参考: `skills/taojin_v3_crawl_skill/references/worktree_operations.md`
- worktree CLI: `./env/.venv/bin/python skills/taojin_v3_crawl_skill/scripts/worktree_cli.py --help`
- Stage4 站点摘要: `./env/.venv/bin/python skills/taojin_v3_crawl_skill/scripts/render_stage4_site_summary.py ...`
- Stage4 批量报告: `./env/.venv/bin/python skills/taojin_v3_crawl_skill/scripts/render_stage4_batch_report.py ...`

### 环境搭建

详见 [docs/environment_setup.md](docs/environment_setup.md)。

- Node.js / npm (推荐使用 nvm 管理版本)
- Codex CLI
- ripgrep
- playwright-cli skill
- xvfb (Linux 服务器环境)
- `env/` 目录（Python 虚拟环境、Node 环境、Playwright 浏览器）

`playwright-cli` skill 需要 Python 3.8+ 和 Playwright Python 库，安装在 `env/.venv`；Node 环境的 Playwright 安装在 `env/node`。

### Batch Input

数据集在 `input/dataset_url_template.json` 中按站点配置（数组格式）。

每个条目包含：

- `site_domain`: 站点域名（如 "www.example.com"）
- `spu_uris`: SPU URL 列表
- `type`: 任务类型，如 `"with_review_stats"`（启用时提取 `source_score` 和 `source_cmms`）
- `extra_tasks`: 额外任务，如 `["list_discovery"]`（启用时调用列表发现，产出 `site_delivery_summary.md`）

组合模式:

- 基础模式: 默认（无 review stats，无 list discovery）
- 仅 review: `type: "with_review_stats"`
- 仅 list discovery: `extra_tasks: ["list_discovery"]`
- 全量模式: `type: "with_review_stats"` + `extra_tasks: ["list_discovery"]`

## 环境搭建

详见 [docs/environment_setup.md](docs/environment_setup.md)。

## 提取说明

本项目代码从截图中 OCR/视觉提取还原。

## 快速验收

```bash
node --check skills/playwright-cli/scripts/proxy-access.js
./env/.venv/bin/python skills/playwright-cli/scripts/fetch_html_with_fallback.py  # 需先搭建 env
./env/.venv/bin/python skills/taojin_v3_crawl_skill/scripts/worktree_cli.py --help
```
