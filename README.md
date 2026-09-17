# shopees_ugreen_topsales_scraper

这是一个由 Codex Skill 驱动的专用项目，只处理 Shopee Philippines 的 UGREEN
官方店铺 Top Sales：遍历全部列表页、逐个进入全部商品详情页，并把商品链接、价格、
月销、SKU、主图和副图发布为唯一一份 Excel。

固定输出：

```text
result/ugreen_topsales.xlsx
```

## 使用方式

在 Codex 中调用：

```text
使用 $shopee-ugreen-topsales 执行今天的完整抓取
```

也可以只分析已有结果：

```text
使用 $shopee-ugreen-topsales 分析现有 Excel 的价格和月销分布，不重新抓取
```

Skill 会先区分“只抓取 / 只分析 / 抓取后分析”。AI 负责选择模式、创建或复用当天
Git worktree、运行与监控、校验结果以及后续表格分析；分页、PDP 身份校验、SKU/图片
解析和 Excel 原子发布由 Skill 内的确定性脚本完成。所有面向用户的提示、进度与分析
默认使用中文。

完整工作流与停止条件见
[`skills/shopee-ugreen-topsales/SKILL.md`](skills/shopee-ugreen-topsales/SKILL.md)。

## 环境

- Python 3.10+
- macOS Google Chrome
- 可正常访问 Shopee Philippines 的本机网络

初始化一次：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

不需要安装 Playwright 自带 Chromium：运行时固定使用本机 Google Chrome。每次运行都
创建独立临时 profile，只复制最近使用的本机 profile 中必要会话状态，绝不直接启动或
修改原 profile，结束后删除临时副本。UA、语言、时区、屏幕等环境指纹全部由 Skill 内
的 JavaScript 初始化注入，不通过项目代理或 Playwright context 伪装。Chrome 不配置
自定义代理或代理凭据，按默认行为使用 macOS 系统代理。

## 每日 worktree

每天按上海时区使用：

```text
worktrees/YYYYMMDD_ugreen_topsales
```

当天路径会安全复用，不会创建随机后缀。主工作树和当天 worktree 必须干净并处于同一
已提交 `HEAD`；项目不会自动 commit、stash、reset、clean 或删除 worktree。因此，
代码改写完成后应先由用户审阅并提交，再启动第一次每日任务。

抓取始终从当天 worktree 的脚本启动，但最终结果原子发布回主项目的固定 `result/`
路径。失败不会覆盖上一份有效工作簿。

## 输出约束

工作簿固定包含 `商品汇总`、`SKU明细`、`图片明细`、`抓取核验` 四张表。ID 以文本
写入；页面未展示月销时留空并标记为未知，绝不按 `0` 推断。

`result/` 只允许存在 `ugreen_topsales.xlsx`。项目不生成 HTML、JSON、截图、页面
快照、证据包或其他中间文件，也不包含或配置任何网络代理。
