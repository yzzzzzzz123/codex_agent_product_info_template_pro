# shopees_ugreen_topsales_scraper

由中文 Codex Skill 驱动的专用采集项目：按 Shopee Philippines UGREEN 店铺 Top Sales
顺序读取全部列表页，逐个进入商品详情页，提取链接、价格、月销、SKU、主图和副图，
最后只发布 `worktrees/YYYYMMDD_ugreen_topsales/result/ugreen_topsales.xlsx`。

AI 负责判断任务、调用脚本、监控、解释异常及后续 Excel 分析；浏览器操作、字段解析、
完整性校验和 Excel 原子发布由 Skill 内代码执行。默认单路慢抓，稳定性优先。

## 使用

在 Codex 中调用：

```text
使用 $shopee-ugreen-topsales 先复测访问，通过后慢速抓取今天全店 Top Sales；遇到验证保留窗口让我处理，我确认后再接管。
```

也可以只验证或只分析：

```text
使用 $shopee-ugreen-topsales 复现历史成功链路，跨列表页抽查详情，不发布 Excel。
使用 $shopee-ugreen-topsales 分析现有 Excel 的价格和月销分布，不重新抓取。
```

完整工作流见 [`SKILL.md`](skills/shopee-ugreen-topsales/SKILL.md)。

## 环境与访问复测

需要 Python 3.10+、macOS Google Chrome 和可访问 Shopee Philippines 的系统网络。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
PLAYWRIGHT_NODEJS_PATH=/opt/homebrew/bin/node \
  .venv/bin/python skills/shopee-ugreen-topsales/scripts/run_scrape.py \
  --project-root "$PWD" --verify-access --manual-access
```

以上命令在主项目根目录运行；临时使用已安装的系统 Node 26.5 对齐昨日运行方式，
列表从现有 Python Playwright 的 `driver/package` 加载 core 1.63，不更换浏览器、Playwright
或 Node；新增解析依赖 `lxml==6.1.3` 已装入项目 `.venv`。PDP 继续 Python Playwright。
复测可在有开发改动的工作树运行，不创建 worktree、不写
Excel。默认从不晚于启动日的最近已有日期 worktree 工作簿取不同来源列表页的首、中、末
商品 URL/ID，再实时读取详情；均不存在时，才只读回退主项目历史
`result/ugreen_topsales.xlsx`。可用
`--reference-workbook "/绝对路径/ugreen_topsales.xlsx"` 指定参考表。旧表的价格、SKU
和图片不参与本次数据填充。退出 `0` 为列表和详情抽查通过，`2` 为部分验证/访问阻断，
`1` 为运行错误；通过复测不等于完成全店刷新。

本轮使用 `--manual-access` 和可交互终端：正常页自动验收继续，验证/无效页保持原窗口、
标签和临时 profile，用户处理并确认后 agent 向原终端发送 `resume`。未通过继续暂停，
不自动刷新、重开或关窗，不自动解验证码；取消时发送 `abort`。列表和详情完整性验收不变。

`--historical-list-preflight` 仅用于用户另行要求的历史顺序诊断，不与人工接管同时启用：在同一临时 profile 先严校验
`page=1`（可见第 2 页），通过后至少等 10 秒，再从 `page=0` 正常运行。它只复现昨日
日志中确有证据的访问顺序，尚未实时验证成功，不能认定预访问是昨日成功原因。预访问
失败则本轮不进入正常列表，复测仍独立诊断 PDP；预访问卡不计最终出现次数、排名或 PDP 集合。

每次使用独立临时 profile，复制真实 Chrome 的必要会话状态，不直接启动或修改原
profile，退出时清理临时副本。浏览器使用本机 Google Chrome 与系统代理；本轮按用户最新
要求恢复昨日成功配置：context `en-PH`、`Asia/Manila`、固定 Windows Chrome 122 UA、
`1366×768`，完整原始 JS 包含 `en-US/en/zh-CN`、`Win32`，4,847 字节且哈希与原始一致。
原始 API 覆写及其已知局限仍在，未经用户许可不得删减或替换。Node/HTML/lxml 路径已经
完成两轮早期失败复测；后续 2026-09-18 11:41 的人工处理后复测已取得列表首屏 30 卡、
显示 28 页，以及详情 3/3 通过。此为访问验证，不是完整全店刷新；不能据此认定
整个运行环境与昨日相同或人工验证是所有错误的唯一原因。
不安装另一套浏览器，不恢复旧代理账号或项目代理配置。

2026-09-17 原始流程曾完成 28 页、812 个唯一商品及 2,312 个 SKU；原始会话在 13:59
记录列表完成、14:45 记录全部详情完成。当天 15:09 后的改写测试已出现列表验证页，
后续正式入口复测仅详情抽查通过。不能把后续复测失败误写成当天从未完整成功。
参数、证据范围和排障说明见
[`verified_access.md`](skills/shopee-ugreen-topsales/references/verified_access.md)。

列表由 Node 内部采集模块经历史 preload 兼容层建立 persistent context，沿用该轮真实
profile 副本及默认标签/采集标签生命周期；不再由 Python 的额外标签 helper 采集。
导航至 `domcontentloaded`（上限 120 秒），完整等待 15 秒后单次 `page.content()`；HTML
仅经管道回传，Python/lxml 离线解析并严格验收，不落盘、不滚动或反复采样。
人工接管模式在浏览器打开时完成验收，失败则保留窗口等待人工处理，用户确认后重新读取。
未启用人工模式时，每轮每个列表页失败（含验证页）最多尝试三次，每次重启 Node/浏览器、沿用同一临时 profile，
保留 10/20 秒退避；耗尽返回本轮失败。用户明确要求继续可另开诊断轮，三次不是整个任务
上限；不无限自动重试。人工模式 PDP 挑战保留同页等待用户，其他模式仍停止。
临时会话数据库日志与 WAL/SHM 保留。按用户指示，仅忽略列表 `get_shop_tab` 的
`90309999`；HTTP 拒绝、登录/验证页和全部数据完整性校验仍生效。昨日的两份成功测试
临时 profile 均已清理，今日只复现方法，不能声称复用了昨日成功会话状态。

## 慢速每日 worktree

完整日更从上海时区的 `worktrees/YYYYMMDD_ugreen_topsales` 执行。主工作树与当日
worktree 必须干净且同一已提交 `HEAD`；项目不自动 commit、stash、reset、clean 或删除
worktree。运行开始固定上海日期，跨午夜完成仍在同一日 worktree 写入并校验结果。开发修改由用户
审阅提交后再进入正式日更。

默认一个详情采集通道，列表页间与商品间都至少等待 10 秒，可通过
`--list-interval-seconds 20 --detail-interval-seconds 20` 加长。全量列表仍逐页遍历，
“隔页”只用于复测跨页抽查。详情身份匹配后等待 300 毫秒读取，验收后离开页面再慢等；
15 秒是身份等待上限，不是在每个详情页固定停留的时间。

完整流程先验证访问，再准备/复用当日 worktree，运行、校验、发布：

```bash
.venv/bin/python skills/shopee-ugreen-topsales/scripts/prepare_daily_worktree.py
```

准备脚本返回 `python`、`runner`、`project_root`、`worktree`、`output` 绝对路径；
`output` 固定为该日期 worktree 内的 `result/ugreen_topsales.xlsx`。将这些字段分别赋给
`PYTHON`、`RUNNER`、`PROJECT_ROOT`、`WORKTREE`、`OUTPUT` 后执行：

```bash
PLAYWRIGHT_NODEJS_PATH=/opt/homebrew/bin/node \
  "$PYTHON" "$RUNNER" --project-root "$PROJECT_ROOT" --manual-access
"$PYTHON" "$WORKTREE/skills/shopee-ugreen-topsales/scripts/validate_result.py" \
  --project-root "$PROJECT_ROOT" --worktree "$WORKTREE"
```

最终只原子发布到 `OUTPUT`，不回写主项目 `result/`；验收只检查明确指定日期的
worktree，找不到文件即失败，不回退其他旧表。访问阻断、任何商品失败或审计不通过
均不覆盖该日期已有有效结果，其他日期工作簿保留。

用户明确接受旧清单并确认无新增时，另可显式选用 `--refresh-known-products` 模式，
只刷新全部已知详情，列表排名、列表价格及月销标为未采集；不作为实时列表失败的自动回退。
具体命令和来源审计见 Skill，当前全流程使用实时列表模式。

## 输出

工作簿固定为 `商品汇总`、`SKU明细`、`图片明细`、`抓取核验` 四张表，所有 ID 按文本
写入。月销未展示留空并标记未知，不推断为 `0`。每个唯一商品必须实际访问详情页，
不得用抽样或旧数据冒充完整结果。

每个日期 worktree 的 `result/` 只允许规范 Excel。不生成 HTML、JSON、截图、响应、
证据包或其他持久化中间文件，也不把 Cookie、账号、代理凭据写入源码、日志或结果。

只分析默认读取不晚于当前上海日期的最近已有日期 worktree 工作簿，也可指定日期或
文件；没有可用日期结果时如实说明，不自动把主项目历史表当成今日结果。主项目已有
`result/ugreen_topsales.xlsx` 保持原样，不自动移动、复制、删除或更新。
