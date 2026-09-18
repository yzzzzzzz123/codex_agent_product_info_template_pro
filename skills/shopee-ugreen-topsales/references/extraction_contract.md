# 抓取与工作簿契约

运行、排障、修改抓取器或解释工作簿时阅读本文件。如果本文与 `scripts/` 实现不一致，
先确认差异；不以文档替代实测，也不因代码当前有缺陷而降低发布要求。

## 固定范围

- 用户入口：`https://shopee.ph/ugreen.ph?page=0&sortBy=sales&tab=0`
- 抓取与工作簿规范 URL：
  `https://shopee.ph/ugreen.ph?page=0&shop=64922227&sortBy=sales&tab=0`
- Shop ID：`64922227`
- 排序：Shopee 店铺 Top Sales 顺序。
- 商品身份：从 Shopee PDP URL 解析的 `(shop_id, item_id)`。
- 输出：
  `<主项目根目录>/worktrees/YYYYMMDD_ugreen_topsales/result/ugreen_topsales.xlsx`。
  日期固定为任务启动时的 `Asia/Shanghai` 日期，跨午夜仍写入该日期 worktree。

抓取器按全局身份去重，保留商品在列表中首次出现的顺序与排名，不发现或跟随该店铺
范围之外的商品。

## 已知商品详情刷新

用户于 2026-09-18 明确确认今天没有新增商品，并接受昨日已知商品清单。这个显式模式
曾用于调整当时任务范围；后续人工接管复测通过，用户现要求实时列表全流程。该模式仍可
显式选择，但不是当前默认流程，也不是自动回退。
运行 `--refresh-known-products --reference-workbook PATH --confirm-no-new-products`；参考
路径必须明确，正式发布必须有无新增确认，不与 `--historical-list-preflight` 合用。

- 读取一次参考文件快照，校验商品汇总中的同店文本 ID、HTTPS PDP URL、采集时间，按
  首次出现顺序去重成完整清单。只读取 URL/身份与来源元数据，禁止历史数据回填。
- `collection_mode=known_product_details`，记录参考文件名、参考采集时间/日期、文件
  SHA-256、去重目标数，以及顺序身份集合（每行 `shop_id:item_id`，以换行连接）的 SHA-256。
  用户无新增确认是范围依据，不应写成浏览器独立证明了今天没有新增。
- 不访问任何列表或预访问页，直接从真实会话临时副本启动同一已验证 PDP 路线；单路，
  商品之间至少 10 秒。812 是当前参考表的实际目标数，不是代码硬编码的通过阈值。
- 必须实际读取每个目标，返回身份序列与参考清单完全相同；缺失、额外、重复、错序或
  任一 PDP 身份、SKU、图库失败均禁止部分发布。原参考文件保持不变。
- 只导出当前 PDP 的标题、SKU/规格和图库。当前实现不从 PDP 提取价格/月销；价格、
  月销、列表页和页内排名留空，月销状态为 `未采集`（不是 `未展示` 或零）。采集序号
  仅为本次清单遍历顺序，不是今日 Top Sales 排名。不得把旧数值填入这些空位。
- 四表、列位置和既有格式保留，标题/表头/核验范围按模式区分。实时列表页数、商品卡
  出现次数和重复次数均为 0；另核验完整参考目标数=PDP 成功数=导出唯一商品数、失败数 0。
  独立验收应返回 `collection_mode=known_product_details`；“通过”只证明这份确认清单
  全部详情成功刷新，不证明今日实时排序、列表价格或月销。
- 加 `--verify-access` 时仅取全清单首、中、末 PDP 抽查，跳过列表，明确返回
  `details_only=true`、`list_skipped=true`、`list_pass=null`。抽查通过不代表全量完成。

每日 worktree、clean 同 HEAD、独占运行、原子发布和不覆盖历史表的门槛仍适用。
后续“列表页契约”仅用于 `full_topsales`；“PDP 契约”适用于两种模式。

## 浏览器路线与注入

确定性 runner 启动 macOS 已安装的 Google Chrome，每次在 `/private/tmp` 创建独立
私有临时 profile。它只从本机 Chrome 的 `Default` 档案复制必要配置、Cookie、Local
Storage 和 Session Storage 到临时副本，不自动切换其他档案；原 profile 绝不直接启动或修改。
`scripts/proxy-access.js` 在每个 document 的页面脚本执行前注入。当前已恢复用户提供的
完整 `buildStealthScript`：保留 webdriver、自动化标记清除及全局属性过滤、chrome 对象、
权限、插件、语言、平台、硬件/PDF、screen/outer 尺寸和 WebGL 全部原注入项。
脚本为 142 行、4,847 字节，与历史原始内容完全一致；语言列表为 `en-US/en/zh-CN`，
navigator language 为 `en-US`、platform 为 `Win32`。当前 SHA-256：
`0917c37fcfba7718f79bd6ec9d63996b7e07c23e88fe19f87e3b096799ef9128`。
未经用户许可不得删除或替换原注入项，
已证实的问题逐项最小处理。重复执行失败、插件普通数组、权限普通对象等原代码局限仍在，
本地测试记录这些局限，不代表已修复或保持了对应的原生 API。

Context 参数按用户最新要求恢复昨日配置：固定 Windows Chrome 122 UA、locale `en-PH`、
timezone `Asia/Manila`、viewport/screen `1366×768`、`ignore_https_errors=True`。
本机运行的是 macOS 系统 Chrome；保留 Chrome 原生 Client Hints，不叠加 UA/Intl 覆写，
不随机请求头或轮换身份。这些配置不代表完整 Windows 设备仿真，也不改变 IP 地区或登录状态。
原始脚本与历史成功配置见访问记录。Node/preload 与单次 HTML/lxml 路径已完成两轮实时
复测当时列表未成功；后续人工处理及解析修正后的复测首屏和详情均通过，见访问记录。
当前启用 `--manual-access`，保留原参数，不代表整个运行环境与昨日相同。
本轮复测及正式 runner 临时设置 `PLAYWRIGHT_NODEJS_PATH=/opt/homebrew/bin/node`，使用已安装
的系统 Node 26.5；列表加载现有 Python Playwright 的 `driver/package`（core 1.63），
PDP 继续 Python Playwright。Python Playwright 默认自带 Node 24.21。旧项目对应
依赖路径的成功安装记录也为 1.63.0，但没有成功进程内的版本读数；证据见访问记录。
不因此更换浏览器、Playwright 或 Node；本轮新增解析依赖 `lxml==6.1.3` 已装入项目 `.venv`。

列表页和每个 PDP 校验关键注入值；注入验证成功不等于站点一定允许访问。项目不设置
代理服务器、proxy fallback 或代理凭据，也不强制直连；Chrome 正常继承系统代理。
保留所需 `--disable-blink-features=AutomationControlled`，忽略
`--use-mock-keychain`、`--password-store=basic` 默认参数以复制原会话行为。
不加历史曾导致资源访问问题的额外 DNT/Upgrade 请求头。退出时清理临时 profile，
本机原 profile 保持不变。完整证据与限制见 [verified_access.md](verified_access.md)。

## 列表页契约

既有 Python runner 调用内部 `capture_list_page.cjs`，每次重新启动 Node/浏览器，复用
同轮真实 Chrome 会话的临时副本。进程内 preload 兼容层将 `launch → newContext` 转接为
`launchPersistentContext`，移除显式 proxy/extraHTTPHeaders，保留默认标签并建立采集 Page；
没有默认标签时才补一个空白标签。不再走 Python 的额外标签或 DOM 列表采样 helper。
列表导航等待 `domcontentloaded`，上限 120 秒，之后完整等待 15 秒，单次 `page.content()`。
HTML 与必要元数据只经 stdin/stdout 管道传递；由 `list_html.py` 使用 lxml
在内存中离线解析，既有 Python 验收器检查 HTTP/API、最终 URL、注入探针及下述全部条件。
人工接管模式在浏览器仍开着时验收，合格后才关闭本页 context；不合格则保留窗口供用户
手动处理。HTML 注释/处理指令不作为元素访问其 class/id，避免解析器对注释抛 AttributeError。
注入探针仍单独读取，商品列表不再由 `LIST_PAGE_SCRIPT` 提取；不落 HTML、JSON 或截图文件。
不在等待前提前判定、不滚动、不追加稳定采样，失败诊断使用本次解析结果。
采集标签只忽略
`/api/v4/shop/get_shop_tab` 的业务码 `90309999`；HTTP 拒绝、登录/验证页面仍会失败。
未启用人工模式时，按原 batch 对 Node 非零退出及 HTML 校验异常（含 `challenge marker found`）的处理，
每轮每个列表页失败最多尝试三次，保留 10/20 秒退避；每次仍严格拒收挑战页面，耗尽返回
本轮失败。用户明确要求继续可另开诊断轮，三次不是整个任务上限；不无限自动重试或等待
人工验证。启用人工模式后的暂停与恢复见下节。列表每次关闭 context 后不额外清理
会话文件，保留 LOG、journal、WAL/SHM 等临时状态。默认列表页间仍至少等待 10 秒。
全量列表完成后，才从该 post-list 会话副本建立详情会话；默认一个详情通道。

`BrowserConfig.historical_list_preflight` 默认 `false`；仅用户要求复现历史顺序时传入
`--historical-list-preflight`，不与人工接管同时启用。开启后在同一临时 profile 先对 `page=1` 严格执行上述采集
与全部验收，通过后按列表间隔等待至少 10 秒，再从 `page=0` 正常开始，并核对总页数。
预访问卡不进入最终 occurrences、排名或 PDP 集合；全量仍逐页采集 `0 → 末页`，包括正式
第 2 页。预访问失败则本轮不进入正常列表，复测可继续独立 PDP 诊断。这是历史访问顺序的
复现选项，尚未实时验证成功，不代表已证明预访问带来成功；正式发布仍要求 clean、同 HEAD。

- 从 page index `0` 开始，读取页面实时 mini-pager 总页数。
- 逐页遍历到最后一页，不隔页跳过。“隔页复测”只指不同历史来源页的详情抽查，不改变
  全量分页要求。
- 必须恰有一个 `.shop-search-result-view`，商品卡来自其 `a.contents`。
- pager 当前页必须等于请求页，总页数在遍历期间必须保持一致。
- 每个非末页必须有 30 张卡；末页必须有 1–30 张卡。
- 每个作用域内的 anchor 都必须成功解析。同页身份重复、标题缺失、价格缺失或不唯一、
  月销标签冲突都会使该页失败。
- 非末页必须有可用的 next link/button；末页必须没有 next link，且 next button 已禁用。
- 使用本次单次快照的卡片身份序列；相邻两页指纹相同视为失败，不另设稳定采样次数门槛。
- 价格取自列表卡。月销只识别可见的 `N Sold/Month` 标签，支持逗号、`K`、`M` 和
  可选的 `+`。
- 页面不展示月销时，文字和数值留空，状态写 `not_displayed`，绝不推断为零；页面明确
  展示零时状态写 `displayed_zero`。

## 人工接管契约

`--manual-access`（兼容旧名 `--manual-list-handoff`）适用于复测和完整刷新，要求可见
窗口、单路和交互终端。正常页自动验收继续；失败快照绝不接收，当前 Page/profile 保持打开。

- 列表内部使用 `--manual-handoff --capture-first`：第一次快照利用原加载后 15 秒等待与
  API 观察器；不额外等待、不提前清空本次错误。Python 合格发 `accept`；不合格发 `hold`。
- `hold` 返回人工就绪事件，agent 告知用户处理并等待其确认，随后才向 PTY 发 `resume`。
  无人工等待超时，不自动刷新、跳页、换 profile 或重试；`abort`/终端结束才取消清理。
- 主 frame 新 document 导航时更新 API 观察区间与主文档 HTTP 状态；`resume` 不清除当前
  document 已收到的拒绝。列表确认后等待 15 秒再读取，旧验证文档错误不污染新页面，
  但只说“好了”不能清除当前页错误。当前错误和全部列表验收仍生效。
- PDP 直接重读用户处理后的当前商品页，不自动导航；按原身份匹配和 300 毫秒时序，再
  验证 URL/canonical/OG/BFF、注入、SKU 和图库。旧的失败快照不能沿用，离开前发现挑战
  也须暂停并重验后才计为成功。等待失败继续保留页面，不静默跳过商品。
- 解析/读取异常与站点挑战分开报告；仍有活页面时尽可能保留窗口，不以异常或人工确认
  作为放宽数据验收的理由。页面或进程已经关闭时如实停止，不假称保留。

## PDP 契约

浏览器必须访问每个全局唯一商品 URL。请求 URL、最终 URL、可选 canonical URL、
可选 `og:url` 与页面嵌入数据都必须解析为预期 `(shop_id, item_id)`。

详情页继续使用 Python Playwright，默认一个临时 profile/persistent context，复用一个 Page 串行访问全部
商品；不自动增加并发。人工模式按上方闭环保留验证页；否则登录页立即拒收并报错，不进入
原 60 秒人工等待。其他读取时序不变。
默认参数为 60 秒导航、最多 15 秒等待身份匹配，匹配后等待
300 毫秒读取并复验。15 秒不是固定页面停留时间；数据验收后检查已观察挑战或业务
访问错误，离开到 `about:blank`，再等待至少 10 秒访问下一个商品。允许加长商品间隔。

普通暂时故障总计最多三次尝试，退避从至少 10 秒起步并递增。明确登录/访问挑战、
CAPTCHA 或业务访问错误不重复冲击，不通过增加并发、轮换代理或指纹消除错误。

商品数据选择路径：

```text
script[type="text/mfe-initial-data"]
  -> initialState.DOMAIN_PDP.data.PDP_BFF_DATA
  -> cachedMap[currentKey]
```

只有页面没有声明 `currentKey`，且所有可用 cache candidate 恰好只有一个身份并等于
预期身份时，才允许 fallback。已声明但缺失、存在歧义或不匹配的 current key 必须
失败。页面稳定后要再次校验身份。

每个 PDP 至少要有一个唯一的纯数字 model ID。SKU 标签来自 tier variation index；
无法建立可靠映射时，用数字 model ID 保底作为 SKU 标签。Shopee 整数价格单位除以
100,000。SKU 图片按 model、extinfo、tier image 字段依次解析。

商品图库优先取 PDP BFF product images，其次 item images，最后 item image。图片 URL
按页面顺序规范化、去重；第一张是主图，剩余是副图。图库为空或 URL 无效时该商品失败。

任一 PDP 在 runner 有界重试后仍失败，则整个任务失败，禁止导出部分商品集。

## 访问复测契约

`run_scrape.py --verify-access` 不创建 worktree，不发布工作簿，允许开发 dirty 工作树。
本轮附加 `--manual-access`，正常首屏严格验收，挑战则人工暂停；
正常首屏未通过不能用 PDP 抽查通过替代。
默认参考不晚于启动日的最近已有日期 worktree 工作簿；均不存在时，才只读回退主项目
历史 `result/ugreen_topsales.xlsx`，也可用 `--reference-workbook` 显式指定。只读取旧表来源页、URL 和
商品身份，选择不同来源页的首、中、末位置代表商品；价格、月销、SKU、图库不得从旧表
带入本次采集数据。每个选中 PDP 都实际打开并使用上述实时解析路径。

列表与详情结果分开报告：全部访问验证通过退出 `0`，部分验证/阻断退出 `2`，运行错误
退出 `1`。抽查只证明这些 URL 在当时可读，不证明分页完整、今天全店数据完整或长期
稳定。列表失败但详情可读，不得自动转为“沿旧表 URL 抓完整店铺”的正式发布；只有用户
明确接受完整已知清单并确认无新增后，才选择上方带来源审计的独立详情刷新模式。

## 工作簿 schema

工作簿必须恰有四张来源表，且不含公式单元格。以下是实时列表模式；已知详情模式按
上方规则保留表/列位置并区分标题、未采集字段和审计：

1. `商品汇总`：每个唯一商品一行，含排名、来源列表页/页内位置、ID、标题、列表价、
   月销观察、SKU 数、主图、副图数和 PDP 链接。
2. `SKU明细`：每个 PDP model 一行，含商品身份、model ID、规格文字、SKU 图片和
   PDP 链接。
3. `图片明细`：每张主图或副图一行，保持商品顺序和图库顺序。
4. `抓取核验`：记录范围、列表/PDP 完整性、重复、月销、SKU/图片、URL 和最终审计；
   可发布的工作簿中 `完整性结论` 必须为 `通过`。

Shop、item 和 model ID 均使用 Excel 文本格式。导出器先写临时 `.xlsx`，检查 ZIP 包，
重新打开并验证 sheet 名、表头、ID、链接、行数、公式和审计结果，然后原子替换固定
工作簿。替换前的任何失败都会保留该日期已有有效工作簿；每个日期 worktree 的
`result/` 不留下临时文件或伴随文件，其他日期结果保留。

## 输出定位与验收

- `prepare_daily_worktree.py` 的 `output` 指向当日 worktree 内的固定 Excel。
- `run_scrape.py --project-root` 仍接收主项目根目录，但正式运行只发布到启动日
  worktree 的 `result/ugreen_topsales.xlsx`，不发布回主项目。
- `validate_result.py --project-root MAIN --worktree DAILY` 两个路径都必须传入；
  只验收指定日期 worktree 的文件，不存在即失败，不回退主项目历史表或其他日期结果。
  跨午夜验收仍传本次启动日的 worktree。
- 只分析默认使用不晚于当前上海日期的最近已有日期 worktree 工作簿，或用户指定的
  日期/文件；没有可用日期结果时明确说明，不把主项目历史表自动当成今日结果。
- 主项目已有 `result/ugreen_topsales.xlsx` 保持原样，不自动移动、复制、删除或更新。
  它仅可作为复测的只读 fallback，或用户明确指定的历史分析输入。

## 强制停止条件

- 人工模式遇到验证/CAPTCHA、登录拦截或访问错误先暂停保留窗口；未获真实有效数据不能
  发布。未启用人工模式时 PDP 挑战停止；列表在本轮单页最多三次有界尝试后仍失败，
  或有界重试后仍有 HTTP 错误。任何单次验证页面都不得被接受为有效结果。
- 分页缺失、不连续、发生变化，卡片异常或相邻页重复。
- 任一 URL、canonical、OG、BFF 或店铺身份不匹配。
- 任一 PDP、SKU model 集合或商品图库缺失。
- PDP 失败数非零或商品数不一致。
- 目标日期 worktree 的 `result/` 出现未知文件、每日任务并发或工作簿/审计不通过。
