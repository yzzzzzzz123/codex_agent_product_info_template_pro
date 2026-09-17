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
- 不并发运行两个完整抓取；主项目与每日 worktree 有用户改动时停止。
- 不自动删除 `result/` 中的未知文件。
- 不把 Cookie、浏览器配置、账号、代理或其他秘密写入源码、日志或结果文件；只允许
  runner 在受限临时 profile 内复制必要会话状态并在退出时删除。
- 每次使用独立临时 Chrome profile；只复制本机 profile 的必要会话状态，不直接启动或
  修改原 profile。环境指纹只由 `stealth_init.js` 注入。
- 不配置项目代理或代理凭据，也不加绕过系统代理的启动参数；Chrome 正常继承 macOS
  系统代理。
- 验证、身份、分页、PDP 完整性或 Excel 审计失败时，不覆盖已有有效结果。

## 固定范围与输出

- 只抓取 `https://shopee.ph/ugreen.ph?page=0&sortBy=sales&tab=0` 的全部 Top Sales。
- 每个唯一商品都必须实际访问 PDP；不得抽样或静默跳过。
- 唯一发布文件是主项目的 `result/ugreen_topsales.xlsx`。
- 不生成 HTML、JSON、截图、trace、响应、manifest 或其他持久化中间产物。
- 月销未展示时保持空值；店铺、商品和 SKU ID 均按文本处理。

## 长任务沟通

抓取持续执行时，约每五分钟用中文汇报一次完整任务清单、当前列表页/PDP 进度、
刚完成的结果和下一步。任务完成、暂停等待必要输入或已经交还用户后停止空转提醒。
