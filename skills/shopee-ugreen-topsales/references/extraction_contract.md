# 抓取与工作簿契约

运行、排障、修改抓取器或解释工作簿时阅读本文件。如果本文与代码出现差异，以
`scripts/` 下的 Python/JavaScript 可执行实现为准。

## 固定范围

- 店铺：`https://shopee.ph/ugreen.ph?page=0&sortBy=sales&tab=0`
- Shop ID：`64922227`
- 排序：Shopee 店铺 Top Sales 顺序。
- 商品身份：从 Shopee PDP URL 解析的 `(shop_id, item_id)`。
- 输出：`<主项目根目录>/result/ugreen_topsales.xlsx`。

抓取器按全局身份去重，保留商品在列表中首次出现的顺序与排名，不发现或跟随该店铺
范围之外的商品。

## 浏览器路线与注入

确定性 runner 启动 macOS 已安装的 Google Chrome，每次在 `/private/tmp` 创建独立
私有临时 profile。它只把最近使用的本机 Chrome profile 中必要文件与 Cookie、Local
Storage、Session、Network 等会话状态复制到临时副本；原 profile 绝不直接启动或修改。
UA、语言、平台、插件、硬件并发、内存、时区、屏幕尺寸、WebGL 等环境指纹全部由
`scripts/stealth_init.js` 在每个 document 的页面脚本执行前注入；列表页和每个 PDP
都会校验关键注入值。Playwright context 不设置 UA、locale、timezone、viewport 或
screen 指纹覆盖。会话状态不承担指纹注入职责。

这段注入是旧浏览器流程中唯一复用并扩展的部分。项目不设置网络代理、proxy fallback
或代理凭据，也不强制直连；Chrome 按默认行为继承 macOS 系统网络/代理。没有 request
mocking、HTML dump 或证据抓取。退出时递归删除整个临时 profile，本机原 profile
保持不变。

## 列表页契约

- 从 page index `0` 开始，读取页面实时 mini-pager 总页数。
- 必须恰有一个 `.shop-search-result-view`，商品卡来自其 `a.contents`。
- pager 当前页必须等于请求页，总页数在遍历期间必须保持一致。
- 每个非末页必须有 30 张卡；末页必须有 1–30 张卡。
- 每个作用域内的 anchor 都必须成功解析。同页身份重复、标题缺失、价格缺失或不唯一、
  月销标签冲突都会使该页失败。
- 非末页必须有可用的 next link/button；末页必须没有 next link，且 next button 已禁用。
- 接受页面前必须获得稳定的卡片指纹；相邻两页指纹相同视为失败。
- 价格取自列表卡。月销只识别可见的 `N Sold/Month` 标签，支持逗号、`K`、`M` 和
  可选的 `+`。
- 页面不展示月销时，文字和数值留空，状态写 `not_displayed`，绝不推断为零；页面明确
  展示零时状态写 `displayed_zero`。

## PDP 契约

浏览器必须访问每个全局唯一商品 URL。请求 URL、最终 URL、可选 canonical URL、
可选 `og:url` 与页面嵌入数据都必须解析为预期 `(shop_id, item_id)`。

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

## 工作簿 schema

工作簿必须恰有四张来源表，且不含公式单元格：

1. `商品汇总`：每个唯一商品一行，含排名、来源列表页/页内位置、ID、标题、列表价、
   月销观察、SKU 数、主图、副图数和 PDP 链接。
2. `SKU明细`：每个 PDP model 一行，含商品身份、model ID、规格文字、SKU 图片和
   PDP 链接。
3. `图片明细`：每张主图或副图一行，保持商品顺序和图库顺序。
4. `抓取核验`：记录范围、列表/PDP 完整性、重复、月销、SKU/图片、URL 和最终审计；
   可发布的工作簿中 `最终状态` 必须为 `通过`。

Shop、item 和 model ID 均使用 Excel 文本格式。导出器先写临时 `.xlsx`，检查 ZIP 包，
重新打开并验证 sheet 名、表头、ID、链接、行数、公式和审计结果，然后原子替换固定
工作簿。替换前的任何失败都会保留旧工作簿；`result/` 不留下临时文件或伴随文件。

## 强制停止条件

- Shopee 验证/CAPTCHA、登录拦截、访问错误，或有界重试后仍有 HTTP 错误。
- 分页缺失、不连续、发生变化，卡片异常或相邻页重复。
- 任一 URL、canonical、OG、BFF 或店铺身份不匹配。
- 任一 PDP、SKU model 集合或商品图库缺失。
- PDP 失败数非零或商品数不一致。
- `result/` 出现未知文件、每日任务并发或工作簿/审计不通过。
