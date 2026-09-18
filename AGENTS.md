# AGENTS.md

## 唯一工作流

- 本项目只有一个任务型 Skill：`skills/shopee-ugreen-topsales/SKILL.md`。
- 遇到 UGREEN Top Sales 抓取、固定 Excel 校验或分析任务时，必须先完整读取该
  `SKILL.md`，再按其模式路由和步骤执行。
- 不恢复旧的通用抓取 Skills、HTML 报告、多阶段流水线、代理配置或 CLI 入口。
- Skill 目录中的 `scripts/` 是唯一运行时实现，不另建第二套抓取代码。
- 面向用户的提示词、进度、错误、结论和 Excel 分析统一使用中文。

## 安全边界

- 不自动 `git add/commit/stash/reset/clean/push/pull/fetch`，不删除 worktree 或分支。
- 不并发运行两个完整抓取；正式日更要求主项目和当日 worktree 干净且同 HEAD。
  `--verify-access` 是不发布文件的开发/排障入口，可在 dirty 工作树运行，不创建 worktree。
- 不自动删除任何日期 worktree 的 `result/` 中的未知文件。
- 不把 Cookie、浏览器配置、账号、代理或其他秘密写入源码、日志或结果文件；只允许
  runner 在受限临时 profile 内复制必要会话状态并在退出时删除。
- 每次使用独立临时 Chrome profile；只复制本机 profile 的必要会话状态，不直接启动或
  修改原 profile。保留完整 `proxy-access.js` 原注入项，未经用户许可不得删除或替换；
  已证实的问题逐项最小处理。本轮按用户最新要求复现昨日配置：context `en-PH`、
  `Asia/Manila`、固定 Windows Chrome 122 UA；完整 JS 包含 `en-US/en/zh-CN`、`Win32`。
  本轮运行临时设置 `PLAYWRIGHT_NODEJS_PATH=/opt/homebrew/bin/node`，使用已安装的系统
  Node 26.5；列表加载现有 Python Playwright 的 `driver/package`（core 1.63），按历史
  preload 调用形状启动真实会话副本。完整等待 15 秒后单次 `page.content()`，HTML 仅经
  内存管道交给 Python/lxml 解析验收，不落盘；PDP 继续 Python。不更换浏览器、Playwright
  或 Node；本轮新增的解析依赖 `lxml==6.1.3` 已安装在项目 `.venv`。
  当前脚本与历史成功配置的区别详见
  `skills/shopee-ugreen-topsales/references/verified_access.md`。
- 不配置项目代理或代理凭据，也不加绕过系统代理的启动参数；Chrome 正常继承 macOS
  系统代理。
- 验证、身份、分页、PDP 完整性或 Excel 审计失败时，不覆盖已有有效结果。

## 固定范围与输出

- 范围仅为 `https://shopee.ph/ugreen.ph?page=0&sortBy=sales&tab=0` 的 UGREEN 商品。
  默认实时列表模式仍抓完整 Top Sales；用户明确确认无新增并接受历史清单时，可以
  显式使用 `--refresh-known-products --reference-workbook PATH --confirm-no-new-products`
  刷新清单中全部详情。此模式不访问列表，也不自动作为列表失败的回退。
  2026-09-18 用户在人工处理验证后的访问复测通过后，已改回实时列表完整流程；历史清单
  模式保留为显式可选项，不自动回退。
- 已知详情模式只复用 URL/IDs 与来源元数据，不复用旧标题、价格、月销、SKU 或图片。
  所有详情实时读取；排名、列表页/页内排名、价格、月销不声称今日已采集，未采集字段
  保持空值。核验范围明确为已确认清单，不能宣称今日 Top Sales 排序、月销已更新。
- 每个唯一商品都必须实际访问 PDP；不得抽样或静默跳过。
- 以稳定性优先：默认单路，列表页间和详情页间至少等待 10 秒，允许加长，不自动提速。
  “隔页复测”指从不同历史列表页抽取详情，不代表全量抓取可以跳过列表页。
- 实时列表模式可按历史证据使用 `--historical-list-preflight`：同一临时 profile 先严校验 `page=1`
  （可见第 2 页），通过后至少等 10 秒，再从 `page=0` 正常采集。预访问卡不计最终出现
  次数、排名或 PDP 集合；失败则本轮不进入正常列表，复测仍可独立诊断 PDP。此开关默认
  关闭，不与人工接管同时启用；尚无实时成功验证，不把预访问当成已证实的成功原因。
- PDP 匹配身份后等待 300 毫秒读取数据，验收后离开页面再执行慢速间隔；不要改为在
  商品页面固定停留 15 秒。15 秒是身份匹配上限，不是稳定等待时长。
- 每次唯一发布文件是主项目的
  `worktrees/YYYYMMDD_ugreen_topsales/result/ugreen_topsales.xlsx`；日期固定为任务启动时的
  上海日期，跨午夜仍写该 worktree。各日期结果分别保留，不回写主项目 `result/`。
- 主项目已有 `result/ugreen_topsales.xlsx` 仅保留为历史表，不自动移动、复制、删除或更新。
  复测默认先选不晚于启动日的最近已有日期 worktree 工作簿，仅在均无时只读回退历史表；
  只分析默认使用最近已有日期 worktree 工作簿或用户指定日期，不把主项目历史表当今日结果。
- 正式验收必须明确指定主项目和本次 worktree，仅检查该日期结果，不回退其他旧表。
- 不生成 HTML、JSON、截图、trace、响应、manifest 或其他持久化中间产物。
- 月销未展示时保持空值；店铺、商品和 SKU ID 均按文本处理。
- 本轮使用 `--manual-access`：正常页面严格验收后自动继续，验证/登录/无效页面保持原
  窗口、标签和临时 profile，用户手动处理并在对话确认后才向保留的 PTY 输入 `resume`。
  不自动解验证码，不在等待期间刷新、重启、关闭或清理。重新验收失败继续人工暂停；
  用户取消或进程结束才清理，不发布部分数据。PDP 同样保留当前商品页并重新完整验收。
- 一次 PDP 抽查通过不代表全店列表可访问或完整日更已完成。未启用人工模式时，每个列表页（含验证页
  失败）最多尝试三次，每次拒收无效页面，沿用同一临时 profile 重启 Node/浏览器，保留
  10/20 秒退避；耗尽返回本轮失败。用户明确要求继续时可另开诊断轮，三次不是整个任务
  上限；不无限自动重试。未启用人工模式的 PDP 登录/验证/业务访问错误仍停止。
  只报告证据，不将某个 Cookie 缺失或代理推测写成已确认原因。

## 长任务沟通

抓取持续执行时，约每五分钟用中文汇报一次完整任务清单、当前列表页/PDP 进度、
刚完成的结果和下一步。任务完成、暂停等待必要输入或已经交还用户后停止空转提醒。
