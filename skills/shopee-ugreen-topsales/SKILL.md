---
name: shopee-ugreen-topsales
description: 刷新、校验或分析 Shopee Philippines UGREEN 店铺 Top Sales 的规范 Excel。适用于该店铺每日全量抓取、固定 result/ugreen_topsales.xlsx 输出或对该工作簿的提问；不适用于其他店铺或通用 Shopee 抓取。
---

# Shopee UGREEN Top Sales

把本 Skill 作为 AI 编排边界，把同目录 `scripts/` 作为唯一的抓取与导出实现。目标固定为
Shopee Philippines UGREEN 店铺的 Top Sales，禁止扩展成通用爬虫。面向用户的进度、
结论、报错和 Excel 分析全部使用中文；脚本 JSON 的机器字段名保持不变。

## 先判断任务模式

- **只刷新：**执行完整每日流程，最后汇报校验后的数量。
- **只分析：**用 spreadsheet Skill 只读分析现有固定工作簿，在对话中回答；不得抓取、
  创建 worktree 或修改工作簿。
- **刷新后分析：**先完成并校验刷新，再分析刚发布的工作簿。

用户只要求分析时，不得擅自刷新。当前工作簿 schema 固定为四张抓取来源表，因此分析
只在对话中输出，不写回工作簿，也不另建第二份分析文件。如果用户将来明确要求把分析
写入 Excel，先把它作为一次独立 schema 变更处理，并同步修改导出与校验代码。

## 执行完整刷新

1. 阅读 [references/extraction_contract.md](references/extraction_contract.md)。
2. 从本文件位置确定 `SKILL_DIR`，再执行
   `git -C "$SKILL_DIR" rev-parse --path-format=absolute --git-common-dir`；返回的
   `.git` 目录的父目录就是主项目根目录。
3. 确认主项目存在 `.venv/bin/python`。如果不存在，在主项目根目录执行：

   ```bash
   python3 -m venv .venv
   .venv/bin/python -m pip install -e .
   ```

   抓取器使用本机已安装的 Google Chrome，并为每次运行创建独立临时 profile；只把
   最近使用的本机 profile 中必要会话状态复制到临时副本，原 profile 绝不直接启动或
   修改。全部环境指纹只由 `stealth_init.js` 在 document 执行前注入。除非明确修改
   实现并重新验证，否则不要下载 Playwright 自带浏览器。
4. 在主项目根目录执行：

   ```bash
   .venv/bin/python skills/shopee-ugreen-topsales/scripts/prepare_daily_worktree.py
   ```

   解析 stdout 的单个 JSON 对象。其中包含按日 worktree、主项目 Python、runner、
   分支、Git heads 和固定输出路径。日期按 `Asia/Shanghai`，目录固定为
   `worktrees/YYYYMMDD_ugreen_topsales`。
5. 准备步骤只要报错就停止。禁止自动 commit、stash、reset、clean、删除、prune 或
   调和 worktree。主工作树和已存在的当日 worktree 必须都干净，并指向同一个已提交
   `HEAD`。
6. 使用 JSON 返回的绝对路径运行：

   ```bash
   "$PYTHON" "$RUNNER" --project-root "$PROJECT_ROOT"
   ```

   保持默认可见 Chrome。只有用户明确要求时才加 `--headless`。不得配置项目代理或
   代理凭据，也不得强制绕过系统代理；让 Chrome 按默认行为使用 macOS 系统网络/代理。
   禁止添加样例限制、页数限制或商品数限制。禁止并发启动两个刷新任务。
7. 持续观察脚本输出的列表页和 PDP 进度。长任务约每五分钟用中文主动汇报：完整任务
   清单、当前列表页/PDP 进度、刚完成的结果和下一步。
8. runner 成功退出后，从当日 worktree 执行：

   ```bash
   "$PYTHON" "$WORKTREE/skills/shopee-ugreen-topsales/scripts/validate_result.py" \
     --project-root "$PROJECT_ROOT"
   ```

9. 只有校验退出码为零且 `audit_status` 为 `通过`，才能说本次已成功刷新。如果抓取
   失败，要明确说明旧工作簿可能仍存在，但本次没有刷新。保留当日 worktree，不自动
   提交或删除。

runner 内部已有有界重试。如果 runner 之外出现明显的一次性浏览器进程故障，AI 最多
可以完整重启 runner 一次；同类故障再次发生就停止并汇报，禁止无限循环。

## 分析工作簿

使用 spreadsheet Skill 检查工作簿。规范路径始终是：

```text
<主项目根目录>/result/ugreen_topsales.xlsx
```

分析前阅读抓取契约中的工作簿 schema。所有 ID 按文本处理。月销为空且状态为
`not_displayed` 表示未知，绝不能当作零。除非用户明确要求修改工作簿，否则只读分析并
用中文在对话中返回结论。

## 不可破坏的边界

- 遍历页面报告的全部列表页，并访问每个唯一 PDP；禁止发布样例、抽样或静默跳过失败。
- 只使用随 Skill 提供的 `stealth_init.js` 初始化注入；不得读取、恢复或配置已删除的
  项目代理系统。Chrome 正常继承 macOS 系统代理，不加 `--no-proxy-server`。
- 本机 Chrome 状态只能复制到每次运行的临时 profile，并在退出时删除；不得直接启动或
  修改原 profile。Cookie/Storage 是会话状态，不作为环境指纹实现。
- 不使用 Playwright context 的 UA、locale、timezone、viewport、screen 指纹覆盖。
- 抓取数据仅驻留内存。不得写 HTML、JSON、截图、trace、响应、manifest、证据、
  prompt、部分工作簿或其他 sidecar。
- `result/` 只能包含 `ugreen_topsales.xlsx`。出现未知文件必须停止，且不得自动删除。
- CAPTCHA/访问挑战、分页不一致、身份不匹配、PDP 不完整、SKU/图库缺失或工作簿校验
  失败，都必须中止发布，并保留上一份有效工作簿。
- 如果运行中发现需要改代码，而用户只要求运行，则汇报问题，不得擅自编辑或提交代码。
