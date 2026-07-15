# Agent 职责说明 (taojin v3)

## 概述

taojin_v3_crawl_skill 采用多 agent 协作架构，每个 agent 有明确的职责边界和优先级。

## Agent 列表与优先级

| Agent | 优先级 | 职责 |
|-------|--------|------|
| `orchestrator_agent` | `5.5xhigh` | 批处理调度、重试策略、工作树管理、全局协调 |
| `seed_agent` | `xhigh` | 种子 URL 发现 |
| `site_agent` | `xhigh` | 单站点爬取协调（Stage4 + Stage3） |
| `extract_agent` | `xhigh` | Stage2-3 SPU/SKU 提取 |
| `list_agent` | `xhigh` | Stage4 列表发现 |

**规则：**
- `orchestrator_agent` 优先级为 `5.5xhigh`，高于其他所有 agent
- 其他 agent 优先级均为 `xhigh`
- 每个 agent 拥有独立的工作树

## 各 Agent 详细职责

### 1. orchestrator_agent

**优先级：** `5.5xhigh`

**核心职责：**
- 批处理调度与重试波次管理
- 工作树（worktree）创建与管理
- 任务类型配置（`task_type` / `review_stats_required` / `list_discovery_required`）
- 全局资源协调与错误聚合
- 最终 HTML 报告组装

**具体工作：**
1. 从 `input/dataset_url_template.json` 读取站点列表
2. 调度 `seed_agent` 执行种子发现（如需要）
3. 为每个站点创建工作树并生成 `run_prompt.md`
4. 调度 `site_agent` 执行单站点爬取
5. 管理重试波次（第一波、第二波、第三波）
6. 组装最终 HTML 报告

**重试策略：**
- 第一波：运行所有站点一次
- 第二波：重试 `blocked` / `dead` / `amb` / `none` 状态的站点
- 第三波：再次重试仍未通过的站点
- 每波之间有冷却时间

---

### 2. seed_agent

**优先级：** `xhigh`

**核心职责：**
- 种子 URL 发现
- 向 `orchestrator_agent` 汇报结果

**具体工作：**
1. 接收 `orchestrator_agent` 的种子发现任务
2. 执行站点种子 URL 发现
3. 产出 `input/dataset_url_template.json`
4. 向 `orchestrator_agent` 汇报完成

**工作边界：**
- 每个 `seed_agent` 对应一个发现任务
- 产出归 `orchestrator_agent` 持有
- 仅负责种子发现，不负责后续爬取

---

### 3. site_agent

**优先级：** `xhigh`

**核心职责：**
- 单站点的 Stage 协调
- 向 `orchestrator_agent` 汇报

**具体工作：**
1. 接收 `orchestrator_agent` 分配的站点任务
2. 读取工作树中的 `result/prompt/run_prompt.md`
3. 协调 Stage4 列表发现（委派 `list_agent`）
4. 协调 Stage3 SPU/SKU 提取（委派 `extract_agent`）
5. 产出 `site_delivery_summary.md`
6. 向 `orchestrator_agent` 汇报站点结果

**工作边界：**
- 每个 `site_agent` 对应一个站点
- 每个站点一个独立工作树
- 工作树路径：`result/{site_domain}/`

---

### 4. extract_agent

**优先级：** `xhigh`

**核心职责：**
- Stage2 浏览器渲染与数据提取
- Stage3 代码嵌入与校验

**具体工作：**

**Stage2：**
1. 读取 Stage1 产出（`dom_analysis.md` / `stage1_raw_gt.json` / `stage1_gt.json`）
2. Playwright 浏览器渲染获取 `rendered_page.html`
3. SPU/SKU 字段提取（title / pics / descriptions / price / props / skus / status）
4. Review stats 提取（如 `with_review_stats = True`）
5. 产出 `stage2_script_res.json`
6. 运行 `stage2_self_test.py` 自检

**Stage3：**
1. 读取 Stage2 产出
2. 生成 `extract_{site_domain}.py`
3. 代码嵌入优化为 `final_code.py`
4. 运行 `final_code_check.py` 或 `final_code_check_offline.py`
5. 生成 `rendered_spu_skus_final.html`
6. 产出 `final_code_change.md` 记录变更

**工作边界：**
- 以 "v3" 模式执行 `run_prompt`
- Stage2-3 连续执行
- 不负责 Stage4 列表发现

---

### 5. list_agent

**优先级：** `xhigh`

**核心职责：**
- Stage4 列表发现
- 向 `site_agent` / `orchestrator_agent` 汇报

**具体工作：**
1. 接收站点域名作为输入
2. 发现 PDP URL 的 sitemap / 子 sitemap / 列表页 / API / JSON state
3. 产出 `sitemap` + `Detail_url_pattern` 或 `list_custom_code`
4. 产出 `sample_detail_uris`（3-5 个样本 PDP URL）
5. 产出 `process_notes` 记录发现路径
6. 标注 `coverage` 状态（ok / partial / none / blocked / dead / amb）
7. 统计 `observed_count`

**工作边界：**
- 仅当 `extra_tasks` 包含 `list_discovery` 时执行
- 参考 `skills/sitemap-list-discovery/SKILL.md`
- 产出供 Stage3 使用的 PDP URL 列表

---

## Stage 流转规则

### 整体流程

```
orchestrator_agent
    ↓ (调度)
seed_agent → 种子发现 → dataset_url_template.json
    ↓ (worktree setup)
site_agent (per site)
    ├─→ list_agent → Stage4 列表发现
    │       ↓
    └─→ extract_agent → Stage2-3 SPU/SKU 提取
            ↓
         final_code.py + script_res
```

### Stage 流转条件

**Stage1 → Stage2：**
- Stage1 产出 `stage1_raw_gt.json` 和 `stage1_gt.json`
- `dom_analysis.md` 完成
- 即使 Stage1 被阻挡，Stage2 也可基于 `offline_evidence` 继续

**Stage2 → Stage3：**
- Stage2 产出 `stage2_script_res.json`
- `stage2_self_test.py` 通过（或有明确的失败记录）
- 进入代码嵌入阶段

**Stage3 → Stage4：**
- Stage3 产出 `final_code.py`
- `final_code_check.py` 通过
- 仅当 `list_discovery_required = True` 时执行 Stage4
- Stage4 由 `list_agent` 独立执行

### 重试流转

- `coverage = blocked` / `dead` / `amb` / `none` 的站点进入下一波重试
- 每波重试后更新 `process_notes`
- 三波后仍未通过的站点保留最终状态

---

## 通信与汇报

- 下级 agent 向上级 agent 汇报结果
- `orchestrator_agent` 拥有全局视图
- 每个 agent 只负责自己的职责范围
- 工作树是 agent 间的数据传递边界
