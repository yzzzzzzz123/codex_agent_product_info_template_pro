# Worktree Operations (工作树操作说明)

## 1. 概述

taojin_v3_crawl_skill 使用 **worktree**（工作树）模式管理多站点并行爬取。每个站点拥有独立的工作树，实现隔离的工作环境，避免站点间相互干扰。

工作树基于 Git worktree 机制，每个站点有自己的分支和独立的目录。

---

## 2. 工作树目录结构

### 2.1 根目录

```
worktrees/
├── taojin_v3_{site_count}sites_{MM-DD_HH-MM-SS}/
│   ├── taojin_v3_{site_count}sites_{MM-DD_HH-MM-SS}.html  # 批量 HTML 报告
│   └── ...
└── {site_domain}/          # 单站点工作树
    ├── result/
    │   ├── prompt/
    │   │   └── run_prompt.md
    │   ├── raw_html/
    │   │   ├── static_page.html
    │   │   ├── rendered_page.html
    │   │   ├── review_provider_discovery.json
    │   │   ├── review_stats_request.json
    │   │   └── review_stats_response.json
    │   ├── script_gen/
    │   │   ├── extract_{site_domain}.py
    │   │   ├── final_code.py
    │   │   ├── final_code_change.md
    │   │   ├── final_code_check.py
    │   │   ├── final_code_check_offline.py
    │   │   ├── rendered_spu_skus_final.html
    │   │   └── self_test_config.json
    │   ├── context/
    │   │   ├── field_mapping.md
    │   │   ├── review_field_mapping.md
    │   │   └── evidence.log.md
    │   ├── dom_analysis.md
    │   ├── stage1_raw_gt.json
    │   ├── stage1_gt.json
    │   ├── stage2_script_res.json
    │   └── site_delivery_summary.md
    └── input/
        └── ...
```

### 2.2 单站点模式

单站点模式下，工作树路径为：
- `worktrees/{site_domain}/`

### 2.3 批量模式

批量模式下，工作树路径为：
- `worktrees/taojin_v3_{site_count}sites_{MM-DD_HH-MM-SS}/`

批量 HTML 报告与工作树同目录：
- `taojin_v3_{site_count}sites_{MM-DD_HH-MM-SS}.html`

---

## 3. Worktree CLI 操作

使用 `scripts/worktree_cli.py` 进行工作树管理。

### 3.1 种子发现

```bash
python scripts/worktree_cli.py seed discover \
  --site-domain example.com \
  --count 5 \
  --worktree-root worktrees
```

**输出：**
```json
{
  "site_domain": "example.com",
  "target_count": 5,
  "worktree_path": "worktrees/example.com",
  "spu_urls": [],
  "status": "placeholder",
  "note": "seed discover placeholder - delegates to site-seed-discovery skill"
}
```

### 3.2 工作树创建 (setup)

```bash
python scripts/worktree_cli.py worktree setup \
  --site example.com \
  --worktree-root worktrees \
  --branch worktree/example.com
```

**参数：**
- `--site`: 站点域名
- `--worktree-root`: 工作树根目录（可选，默认 `worktrees`）
- `--branch`: 分支名（可选，默认 `worktree/{site_domain}`）

**输出：**
```json
{
  "site_domain": "example.com",
  "worktree_path": "worktrees/example.com",
  "branch": "worktree/example.com",
  "status": "created"
}
```

**状态值：**
- `created`: 成功创建
- `exists`: 已存在
- `error`: 创建失败（带 `error` 字段）

### 3.3 工作树清理 (cleanup)

```bash
python scripts/worktree_cli.py worktree cleanup \
  --site example.com \
  --worktree-root worktrees \
  --remove-branch
```

**参数：**
- `--site`: 站点域名
- `--worktree-root`: 工作树根目录
- `--remove-branch`: 同时删除 Git 分支（可选）

### 3.4 工作树列表 (list)

```bash
python scripts/worktree_cli.py worktree list \
  --worktree-root worktrees
```

**输出：**
```json
[
  {
    "site_domain": "example.com",
    "path": "worktrees/example.com",
    "has_git": true
  }
]
```

### 3.5 Prompt 渲染 (render)

```bash
python scripts/worktree_cli.py prompt render \
  --site example.com \
  --worktree-root worktrees \
  --template skills/taojin_v3_crawl_skill/assets/run_prompt_template.md \
  --output worktrees/example.com/result/prompt/run_prompt.md
```

---

## 4. 工作树生命周期

### 4.1 创建流程

```
orchestrator_agent
    ↓
1. 读取 input/dataset_url_template.json
2. 为每个站点创建 worktree
3. 渲染 run_prompt.md 到工作树
4. 调度 site_agent 在工作树中工作
```

### 4.2 工作流程

```
工作树创建 → Stage4 列表发现 → Stage2-3 提取 → 产出 → （可选）清理
```

每个站点独立运行在自己的工作树中，互不干扰。

### 4.3 重试波次

- 第一波：所有站点首次运行
- 第二波：失败站点重试（在同一工作树中）
- 第三波：再次重试（在同一工作树中）

重试在同一工作树中进行，保留历史产出。

### 4.4 清理时机

- 批量任务全部完成后可清理
- 保留工作树用于调试和追溯
- 长期运行应定期清理过期工作树

---

## 5. 工作树产出文件

每个工作树的 `result/` 目录包含：

### 5.1 Stage1 产出

| 文件 | 说明 |
|------|------|
| `raw_html/static_page.html` | 静态抓取的 HTML |
| `dom_analysis.md` | DOM 分析记录（锚点 schema） |
| `stage1_raw_gt.json` | 原始提取数据（raw schema） |
| `stage1_gt.json` | 后处理后数据（target schema） |

### 5.2 Stage2 产出

| 文件 | 说明 |
|------|------|
| `raw_html/rendered_page.html` | Playwright 渲染的 HTML |
| `raw_html/review_*.json` | Review stats 证据 |
| `stage2_script_res.json` | Stage2 提取结果 |
| `context/` | 字段映射和证据日志 |

### 5.3 Stage3 产出

| 文件 | 说明 |
|------|------|
| `script_gen/extract_{site_domain}.py` | 初始提取脚本 |
| `script_gen/final_code.py` | 最终嵌入代码 |
| `script_gen/final_code_change.md` | 变更记录 |
| `script_gen/final_code_check.py` | 在线检查器 |
| `script_gen/final_code_check_offline.py` | 离线检查器 |
| `script_gen/rendered_spu_skus_final.html` | 渲染结果 HTML |
| `script_gen/self_test_config.json` | 自检配置 |

### 5.4 Stage4 产出

| 文件 | 说明 |
|------|------|
| `site_delivery_summary.md` | 站点交付总结 |

---

## 6. 工作树管理最佳实践

### 6.1 命名规范

- 工作树目录名 = 站点域名（小写，去协议，去尾斜杠）
- 分支名 = `worktree/{site_domain}`
- 批量目录 = `taojin_v3_{n}sites_{MM-DD_HH-MM-SS}`

### 6.2 隔离性

- 每个站点独立工作树，文件互不影响
- 每个 agent 操作自己的工作树
- 通过文件系统传递数据，而非内存

### 6.3 可追溯性

- 工作树保留完整产出历史
- `process_notes` 记录操作过程
- 人工标记存储在 localStorage（HTML 报告）

### 6.4 资源管理

- 定期清理已完成的工作树
- 保留失败站点的工作树用于调试
- 批量任务完成后统一归档

---

## 7. Git Worktree 原理（可选）

工作树底层使用 `git worktree` 命令：

```bash
# 创建分支
git branch worktree/example.com

# 添加工作树
git worktree add worktrees/example.com worktree/example.com

# 移除工作树
git worktree remove worktrees/example.com --force

# 删除分支
git branch -D worktree/example.com
```

**注意：** 如非 Git 仓库环境，工作树也可以普通目录模式运行，Git worktree 是增强特性。
