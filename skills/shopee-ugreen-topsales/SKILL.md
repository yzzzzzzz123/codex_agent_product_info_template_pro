---
name: shopee-ugreen-topsales
description: 复测、全量刷新、校验或分析 Shopee Philippines UGREEN 店铺 Top Sales；用户确认无新增商品时可按明确历史清单刷新全部详情。适用于该店铺每日 worktree 慢速采集及 Excel 分析，不适用于其他店铺或通用 Shopee 抓取。
---

# Shopee UGREEN Top Sales

AI 负责理解请求、选择模式、运行和监控脚本、解释失败与分析 Excel；同目录 `scripts/`
是唯一的浏览器采集、数据校验和导出实现。提示词、进度、报错、结论和分析使用中文。
目标固定为 UGREEN Philippines 全店 Top Sales；以稳定性优先，不追求抓取速度。

## 模式与阅读入口

- **复测/排障：**先读 [已验证访问链路](references/verified_access.md)，执行下述
  `--verify-access`；只检查实时访问，不发布 Excel，不创建 worktree。
- **完整刷新：**先读 [抓取契约](references/extraction_contract.md)，按下方人工接管流程
  复测，再走每日 worktree；必须完整采集全部列表页和每个唯一 PDP。
- **已知商品详情刷新：**用户明确确认没有新增商品，并指定或接受历史清单时，阅读抓取
  契约的“已知商品详情刷新”，执行下方独立模式。该模式不访问列表，必须重抓清单中
  每个唯一 PDP；不自动把列表失败转成此模式。
- **只分析：**阅读抓取契约的工作簿 schema，使用可用的 spreadsheet Skill 只读分析
  不晚于当前上海日期的最近已有日期 worktree 工作簿，或用户指定日期/文件。没有可用
  日期结果时如实说明，不默认改读主项目历史表，不得擅自抓取、创建 worktree 或改表。
- **刷新后分析：**完整刷新、验证成功后，再分析本次发布的工作簿。

需要复现历史成功、修改浏览器参数、诊断访问错误或调整等待时机时，必须阅读
[已验证访问链路](references/verified_access.md)。它区分了局部成功、全店成功及未知原因。
不要因为旧工作簿存在就宣称今天成功，也不要把 PDP 抽查通过等同于列表可用。

## 环境与主项目

从本文件位置确定 `SKILL_DIR`，执行
`git -C "$SKILL_DIR" rev-parse --path-format=absolute --git-common-dir`；返回的 `.git`
目录的父目录是 `PROJECT_ROOT`。主项目解释器为 `.venv/bin/python`；不存在时在主项目执行：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

默认使用可见的本机 Google Chrome，每次复制必要会话状态到私有临时 profile；不直接
启动、修改或清理真实 profile。浏览器版本取自已安装 Chrome 的实际版本；旧固定 153、
美国地区和脚本哈希只属于历史记录。共享配置目录
`scripts/browser-profiles.json` 的八套配置是本地兼容性测试输入，不是真实跨 OS/硬件仿真，也不是
站点放行保证；原生 UA-CH 和原注入的八类已知 API 语义缺陷仍需如实说明。
启动地区检测仅查询不含真实会话的临时 Chrome 在 `ipwho.is` 的出口国家/时区，按映射
设置 locale/languages/timezone；失败停止，不默认美国。查询域与 Shopee 可能经不同
系统代理规则分流，GPU/设备型号也不代表国籍。同轮列表、详情、普通故障重试和人工
恢复保持相同配置，不能因验证失败自动换身份或代理。worktree 日期仍按 `Asia/Shanghai`。
人工处理验证时保留的仍是这份临时会话。
当前 `--browser-profile` 默认为 `auto`：每次新运行从八套目录中随机选择一次，允许
连续两轮恰好选中同一套，并非保证不重复的轮询。也可指定目录中的配置 ID 进行可复现
的本地兼容性测试；不是每页轮换，不因挑战重新抽取。八套 ID 见抓取契约的配置表。
列表、详情、人工恢复使用同一份冻结配置，输出摘要记录本轮配置 ID、真实版本和地区。
正常继承系统代理，不配置项目代理/凭据，不强制直连，不擅自下载或切换浏览器。

当前只适配 PH UGREEN 店铺 `64922227`、`PHP` 与 `down-ph` 图片域规则。地区查询为
`SG/en-SG/Asia/Singapore` 只证明该次查询成功，不证明 Shopee 可达，更不将该 Skill
转换成 SG 采集器。用户要求 SG 时先取得真实店铺 URL，再单独适配和验证；未完成前
明确报告不支持，不能静默继续用 PH 地址。新配置的本地测试不得写成新一轮抓取成功。

## 人工验证与接管闭环

用户已明确选择：遇到登录、验证码或访问挑战，先保持窗口，由用户手动完成，再由 agent
接管。复测和正式全量均加 `--manual-access`，使用可交互 PTY、可见 Chrome、单路采集。
不要等工具一次性返回而失去控制；保留运行中的终端 session ID，供用户回复后继续。

1. 正常页面由程序严格验收并自动继续；不要求用户逐页确认。列表首次导航后完整等待
   15 秒读取一次 HTML；不启用历史第 2 页预访问。
2. 页面无法通过时，保持**同一个窗口、标签和临时 profile**，暂停采集。告知用户当前
   待采页面/商品，让用户在该窗口完成验证并返回目标页面。等待期间不关窗、不清理
   profile、不自动刷新、重开或发送 `resume`，也不替用户解验证码。
3. 用户说“好了/继续”后，向保留的 PTY 输入 `resume\n`。这只是请求重新检查，不是
   将用户确认当作数据验收。列表重新等 15 秒读取；PDP 仍按身份匹配上限 15 秒、匹配后
   300 毫秒读取。检查当前 URL、HTTP/API、注入探针及全部字段/完整性。
4. 未通过就继续保留页面，报告状态并等待下一次人工确认；通过才继续当前任务。人工
   等待没有自动关闭时限，不进行无限自动重试。用户取消时输入 `abort\n`，结束后清理
   临时会话，不发布部分结果。浏览器被用户关闭或进程已退出则报告，不能假装会话还在。
5. 全量列表的各页沿用本轮临时 profile；详情使用同一 post-list 状态的临时副本，保持
   原有慢速间隔。当前页验收完成后的正常浏览器生命周期与整轮结束清理不属于验证中关窗。

2026-09-18 11:41 的实测已取得首屏 30 卡、分页显示 28 页，以及跨来源页详情 `3/3`；
这证明人工处理后的访问链路可用，不等于全店已完成，也不证明人工验证是所有错误的唯一原因。
详细记录见 [已验证访问链路](references/verified_access.md)。

## 已知商品详情刷新

这是用户明确选择历史范围时的可选模式，**不是当前全流程的默认模式**。2026-09-18 用户曾
确认无新增并接受昨日 812 个商品，随后恢复实时列表全流程。参考表可为
`<PROJECT_ROOT>/result/ugreen_topsales.xlsx`；数量从文件严格读取，不在代码
中写死。文件只提供完整 URL/身份集合及来源元数据，不复用旧标题、价格、月销、排名、
SKU 或图片；标题、规格、SKU、图库由本次每个 PDP 实际读取。

1. 先用相同入口进行仅详情复测，不要求列表恢复：

   ```bash
   PLAYWRIGHT_NODEJS_PATH=/opt/homebrew/bin/node \
     .venv/bin/python skills/shopee-ugreen-topsales/scripts/run_scrape.py \
     --project-root "$PROJECT_ROOT" --verify-access --refresh-known-products \
     --reference-workbook "$PROJECT_ROOT/result/ugreen_topsales.xlsx"
   ```

   仅抽取已知清单的首、中、末商品；`list_skipped=true`、`list_pass=null`，不是列表通过。
   全部抽查通过退出 `0` 也不代表 812 个已经采完。此模式允许 dirty 工作树，不发布 Excel。
2. 复测通过后，执行下方每日 worktree 准备步骤。正式发布仍要求主项目和当日 worktree
   干净且同一已提交 HEAD；用户确认无新增不等于授权 Git 提交。没有提交授权时先完成
   代码与访问验证，再请求必要授权，不能绕过此门槛。
3. 用准备步骤返回的 `PYTHON`、`RUNNER`、`PROJECT_ROOT` 执行：

   ```bash
   PLAYWRIGHT_NODEJS_PATH=/opt/homebrew/bin/node \
     "$PYTHON" "$RUNNER" --project-root "$PROJECT_ROOT" --refresh-known-products \
     --reference-workbook "$PROJECT_ROOT/result/ugreen_topsales.xlsx" \
     --confirm-no-new-products
   ```

   必须显式给参考表和确认开关；不加 `--historical-list-preflight`，不运行列表。每个唯一
   商品实际访问且身份集合、顺序与清单一致，单路且商品间至少 10 秒。任一 PDP 失败仍
   禁止部分发布，不因清单完整就声称详情完整。
4. 运行下方的当日 worktree 验收命令。结果应为 `collection_mode=known_product_details`，
   且 `audit_status=通过`。工作簿保留四表，序号仅表示采集顺序；列表页、页内排名、价格
   和月销留空并标明未采集，不冒充今日 Top Sales 指标。核验表记录来源日期、哈希、清单
   身份哈希、用户无新增确认及完整 PDP 数。只宣告“已知清单全部详情刷新”，不宣告
   “今日列表、排序和月销已刷新”。

## 实时列表模式：先复测访问

在主项目根目录运行已有入口，不另写临时抓取/登录脚本。本轮用临时环境变量指定已安装
的系统 Node 26.5；列表内部模块加载现有 Python Playwright 的 `driver/package`（core 1.63），
通过历史 preload 调用形状读取单次 HTML，Python/lxml 解析验收，PDP 继续 Python。
不更换浏览器、Playwright 或 Node；新增的解析依赖 `lxml==6.1.3` 已安装在项目 `.venv`：

```bash
PLAYWRIGHT_NODEJS_PATH=/opt/homebrew/bin/node \
  .venv/bin/python skills/shopee-ugreen-topsales/scripts/run_scrape.py \
  --project-root "$PROJECT_ROOT" --verify-access --manual-access
```

`--historical-list-preflight` 仅用于用户另行要求的历史顺序诊断，不与人工接管同时启用：同一临时 profile 先严校验
`page=1`（可见第 2 页），通过后至少等 10 秒，再检查 `page=0`。这仅复现日志已有证据
的顺序，尚未实时验证成功，不能认定预访问是昨日成功原因。预访问失败则本轮不进入
正常列表，`--verify-access` 仍继续独立 PDP 诊断。

默认按日期倒序选择不晚于启动日的最近已有
`worktrees/YYYYMMDD_ugreen_topsales/result/ugreen_topsales.xlsx`；均不存在时，才只读
回退主项目历史 `result/ugreen_topsales.xlsx`。用户指定历史工作簿时追加
`--reference-workbook "/绝对路径/ugreen_topsales.xlsx"`。明确汇报参考表路径与日期；
旧表只提供抽查 URL、商品 ID 和来源页，不使用旧价格、SKU、图片或其他旧数据填充
本次结果，也不把历史文件的存在当成本次生成成功。

复测先检查实时列表，再从参考表不同 `source_page` 的首、中、末位置选择商品，逐个
实际进入详情页。这是“隔页抽查”，不是跳页全量采集。若可用来源页不足，明确说明
覆盖不足，不能虚报跨页覆盖。开发工作树可以 dirty；此模式不准备 worktree、不写 Excel。

读取 stdout 摘要和退出码：`0` 为列表及详情抽查通过；`2` 为部分验证通过或访问阻断；
`1` 为运行错误。即使退出 `0`，也只能说访问复测通过，不能说全店已刷新。列表被阻断但
历史 URL 的详情可读时，如实分别汇报；不得拿旧表替代今天的完整列表继续发布。

## 每日 worktree 与实时列表全量刷新

1. 所选模式的访问复测通过后，在主项目根目录执行：

   ```bash
   .venv/bin/python skills/shopee-ugreen-topsales/scripts/prepare_daily_worktree.py
   ```

   解析 stdout 单个 JSON，将小写字段 `python`、`runner`、`project_root`、`worktree`、
   `output` 分别赋给示例中的 shell 变量 `PYTHON`、`RUNNER`、`PROJECT_ROOT`、`WORKTREE`、
   `OUTPUT`，使用
   返回的绝对路径执行；不要读取不存在的大写 JSON 字段。日期按 `Asia/Shanghai`，
   目录固定为 `worktrees/YYYYMMDD_ugreen_topsales`，`output` 必须是该 worktree 内的
   `result/ugreen_topsales.xlsx`。运行已开始后跨午夜，仍写入并校验启动日的 worktree；
   若准备后隔天才启动，须先重新执行准备步骤。
2. 准备报错即停止。主工作树与当日 worktree 必须干净且处于同一已提交 `HEAD`；
   不自动 commit、stash、reset、clean、prune、删除或调和 worktree。若本次任务还包含
   代码修改，开发验证可先完成，但正式日更须等用户审阅并提交修改。
3. 实时列表全量模式使用返回的路径运行当日 worktree 的 runner；已知商品模式使用上方
   带 `--refresh-known-products` 的命令：

   ```bash
   PLAYWRIGHT_NODEJS_PATH=/opt/homebrew/bin/node \
     "$PYTHON" "$RUNNER" --project-root "$PROJECT_ROOT" --manual-access
   ```

   runner 执行全量采集并在发布前验收。默认可见 Chrome、单路详情；只有用户明确要求
   才使用 `--headless`。不添加页数/商品数限制，不并发启动两个完整刷新。
4. 保持默认慢速：列表页之间、详情页之间均至少 10 秒。用户不着急或链路不稳定时，
   可追加 `--list-interval-seconds 20 --detail-interval-seconds 20` 或更长时间；不得
   自动提高并发、缩短到 10 秒以下。人工接管模式遇到无效页保留窗口，按上方闭环等待
   用户处理，不自动重启人工暂停的挑战页。本次配置扩充不改变非人工模式既有有界
   重试上限；耗尽结束，所有无效页面拒收，不因挑战切换配置或代理。
   列表由 Node 导航到 `domcontentloaded`（上限 120 秒），完整等待 15 秒后单次
   `page.content()`；HTML 仅经内存管道交给 Python/lxml 解析并验收全部字段，不落盘、
   不滚动或追加稳定采样。登录、验证和业务访问错误不能接受为数据，只能保留页面等
   人工处理；不通过密集重试、代理池或指纹轮换处理。
5. 完整列表从 `page=0` 逐页采到末页，不沿旧清单替代今日列表。每个唯一商品真实进入详情页；身份匹配上限
   为 15 秒，匹配后等待 300 毫秒再读取并复验。验收后先检查已观察到的挑战/业务错误，
   再离开到 `about:blank` 等待下一个商品的慢速间隔，不在商品页面固定停留 15 秒。
6. 跟踪列表页与 PDP 进度，约每五分钟中文汇报任务清单、当前事项、刚完成结果和下一步。
   系统要求更频繁时按更短间隔汇报；不要静默等待整个全店任务结束。
7. runner 成功退出后，再从当日 worktree 运行：

   ```bash
   "$PYTHON" "$WORKTREE/skills/shopee-ugreen-topsales/scripts/validate_result.py" \
     --project-root "$PROJECT_ROOT" --worktree "$WORKTREE"
   ```

8. 校验仅检查 `WORKTREE/result/ugreen_topsales.xlsx`，不存在或不通过就失败，不回退
   主项目历史表或其他日期结果。只有校验退出码为零、`audit_status` 为 `通过`，才能宣告
   本次全量刷新成功，汇报实际页数、唯一商品数、SKU 数、图片数及 `OUTPUT` 的完整路径。
   失败则明确“本次未刷新，已有工作簿未覆盖”，保留 worktree，不自动提交或删除。

同一诊断轮内，内部重试之外仅明显的一次性浏览器进程故障允许完整重启 runner 一次；
同类故障再次发生就返回本轮失败。本次配置扩充不增加重试次数，不把配置变化作为
追加尝试的理由。人工模式保持同一会话正常处理；无有效数据不得发布。
本轮使用人工接管模式。登录/验证页面仍不可接受为数据来源，不凭等待、用户确认或
注入探针通过宣称访问成功，也不将未经证实的 Cookie/代理推测写成原因。

## 分析与发布边界

- 本次唯一规范结果是
  `<主项目根目录>/worktrees/YYYYMMDD_ugreen_topsales/result/ugreen_topsales.xlsx`。
  从启动日 worktree 运行并原子发布到该 worktree；不回写主项目，不覆盖其他日期结果。
  主项目已有 `result/ugreen_topsales.xlsx` 是历史文件，保留原样，不自动移动、复制或删除。
- 工作簿保留四张来源表，所有 ID 按文本处理。月销空值且 `not_displayed` 为未知，
  不能当零；已知详情模式 `not_collected` 是未采集，也不能写成未展示或零。分析默认只
  在对话中输出。写回分析需用户明确要求并单独处理 schema 变更。
- 未经用户许可不得删除或替换原注入项；已证实问题逐项最小处理，不能以恢复原生 API
  为由整段删减。保留 Chrome 原生 Client Hints，不随机请求头、轮换身份或伪造登录状态；
  不恢复旧 Goldrush 代理配置，不使用 `--no-proxy-server`。
- 不持久化 Cookie/Storage、凭据或抓取中间产物；只允许运行中临时 profile，结束后清理。
  不生成 HTML、JSON、截图、trace、manifest、部分工作簿或其他 sidecar。
- 每个日期 worktree 的 `result/` 只允许规范 Excel；发现未知文件停止，不自动删除。
  分页、身份、SKU/图库、PDP 完整性或 Excel 审计失败都禁止发布，保留已有有效结果。
- 用户只要求运行时，若发现必须改代码才可继续，报告问题并请求方向，不擅自编辑或提交。
