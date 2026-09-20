# Human Operation Flow (taojin v3)

## 1. 概述

本文档定义了人工审核和返工（rework）的操作流程、数据结构和输出规范。

参考图片：IMG_5340

---

## 2. 人工审核流程

### 2.1 审核对象

人工审核的主要对象：
- Stage4 HTML 报告中的每个站点
- `final_code.py` 的质量
- 提取结果的准确性
- 列表发现的覆盖率

### 2.2 审核入口

通过 Stage4 HTML 报告进行人工审核：
- 打开 `output/stage4_report.html`
- 浏览各站点的覆盖状态
- 查看样本 PDP 链接
- 检查 `final_code.py` 和 `list_custom_code`
- 进行人工标记

### 2.3 人工标记状态

每个站点可以标记为以下状态：

| 状态 | 说明 |
|------|------|
| `待处理` | 未审核的初始状态 |
| `通过` | 审核通过，结果符合要求 |
| `拒绝` | 审核不通过，需要返工 |
| `重置` | 清除标记，恢复初始状态 |

**存储位置：**
- localStorage key: `lastSkuManualMarks:v2`
- 数据结构：`{site_key: {status, updated_at}}`

### 2.4 审核工具

HTML 报告提供以下工具：
- `导出 marks`：导出人工标记数据
- `导入 marks`：导入人工标记数据
- `复制 marks`：复制 localStorage JSON 到剪贴板
- `清空 marks`：清除所有人工标记

---

## 3. agent_rework_report.json 结构

### 3.1 结构定义

```json
{
  "report_version": "1.0",
  "generated_at": "2024-01-01T00:00:00Z",
  "total_sites": 100,
  "passed_count": 80,
  "rejected_count": 15,
  "pending_count": 5,
  "rework_items": [
    {
      "site_domain": "example.com",
      "input_site": "example.com",
      "coverage": "partial",
      "manual_mark": "rejected",
      "rejection_reason": "price extraction failed",
      "rejection_category": "price",
      "stage1_raw_gt_path": "output/per_site/example.com/raw_html/stage1_raw_gt.json",
      "stage2_script_res_path": "output/per_site/example.com/stage2_script_res.json",
      "final_code_path": "output/per_site/example.com/final_code.py",
      "stage4_result_path": "output/per_site/example.com.json",
      "rework_priority": "high",
      "lessons_learned": [
        "short text describing what was learned"
      ],
      "residual_risks": [
        "short text describing remaining risks"
      ]
    }
  ],
  "lessons_learned": [
    "全局经验总结 1",
    "全局经验总结 2"
  ],
  "residual_risks": [
    "全局残留风险 1",
    "全局残留风险 2"
  ]
}
```

### 3.2 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `report_version` | string | 报告版本号 |
| `generated_at` | string | 生成时间（ISO 8601） |
| `total_sites` | number | 总站点数 |
| `passed_count` | number | 通过数量 |
| `rejected_count` | number | 拒绝数量 |
| `pending_count` | number | 待处理数量 |
| `rework_items` | array | 需要返工的条目列表 |
| `lessons_learned` | array | 全局经验总结（short text 列表） |
| `residual_risks` | array | 全局残留风险（short text 列表） |

### 3.3 rework_item 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `site_domain` | string | 站点域名 |
| `input_site` | string | 输入站点 |
| `coverage` | string | 覆盖状态 |
| `manual_mark` | string | 人工标记 |
| `rejection_reason` | string | 拒绝原因 |
| `rejection_category` | string | 拒绝分类 |
| `rework_priority` | string | 返工优先级（high/medium/low） |
| `lessons_learned` | array | 该站点的经验总结（short text 列表） |
| `residual_risks` | array | 该站点的残留风险（short text 列表） |

---

## 4. lessons_learned 字段

### 4.1 用途

`lessons_learned` 用于记录从审核和返工过程中获得的经验和知识，用于：
- 指导后续类似问题的预防
- 改进自动化规则的优化方向
- 团队知识的积累和传承

### 4.2 格式要求

- 每条为 short text（简短文本）
- 具体、可操作
- 描述问题原因和解决方案
- 可以是全局的或针对特定站点的

### 4.3 示例

```json
"lessons_learned": [
  "Shopify 站点价格提取优先使用 /products/{handle}.js 的 price / compare_at_price",
  "Bazaarvoice review product id 优先从 data-bv-product-id 获取",
  "WooCommerce 变体使用 form.variations_form 的 data-product_variations"
]
```

---

## 5. residual_risks 字段

### 5.1 用途

`residual_risks` 用于记录审核后仍然存在的风险和不确定性：
- 无法完全验证的部分
- 已知的局限性
- 需要后续关注的问题

### 5.2 格式要求

- 每条为 short text（简短文本）
- 明确描述风险内容
- 说明影响范围
- 可以是全局的或针对特定站点的

### 5.3 示例

```json
"residual_risks": [
  "部分站点反爬机制可能变化，需要定期验证",
  "review stats 依赖第三方 widget 无法确认是否为 product-only 数据",
  "价格字段在促销期间可能变化频繁"
]
```

---

## 6. 返工流程

### 6.1 返工触发

当站点被标记为 `拒绝` 时，触发返工流程：
1. 生成 `agent_rework_report.json`
2. 按优先级排序返工条目
3. 分配给相应的 agent 进行返工

### 6.2 返工类型

| 类型 | 负责 agent | 说明 |
|------|-----------|------|
| 价格提取错误 | extract_agent | 重新提取价格字段 |
| SKU 提取错误 | extract_agent | 重新提取 SKU 变体 |
| 图片提取错误 | extract_agent | 重新提取图片 |
| 列表发现不足 | list_agent | 重新发现列表 |
| 站点被阻挡 | orchestrator_agent | 切换代理/重试策略 |

### 6.3 返工输出

返工完成后更新：
- `final_code.py`（如需要）
- `script_res.json`（如需要）
- `site_delivery_summary.md`（如需要）
- 更新 HTML 报告
- 更新 `lessons_learned` 和 `residual_risks`

---

## 7. 审核检查清单

### 7.1 Stage3 / final_code.py 检查

- [ ] `final_code.py` 可编译通过 `compile(...)`
- [ ] `script_res` 包含所有必需字段
- [ ] 缺失字段为 `None`，不省略
- [ ] 价格为数字类型
- [ ] 货币为 3 位大写代码
- [ ] `props` 和 `sku_props` 为 dict
- [ ] `source_pics` 为绝对 URL 列表
- [ ] `status` 为整数（0 或 1）
- [ ] 单 SKU 折叠规则正确
- [ ] 多 SKU `skus[]` 完整

### 7.2 Stage4 列表发现检查

- [ ] `sitemap` 非空
- [ ] 恰好一个主 companion 字段
- [ ] `Detail_url_pattern` 或 `list_custom_code` 有效
- [ ] `list_custom_code` 可编译通过
- [ ] `sample_detail_uris` 有 3-5 个样本
- [ ] `coverage` 标签正确
- [ ] `process_notes` 完整
- [ ] `observed_count` 合理

### 7.3 Review Stats 检查（如启用）

- [ ] `source_score` 和 `source_cmms` 来自同一 provider
- [ ] product-only stats 优先于 widget aggregate
- [ ] 零评论处理正确
- [ ] 证据文件齐全

---

## 8. 输出文件

人工审核和返工的输出包括：

```
output/
├── stage4_report.html          # 带人工标记的 HTML 报告
├── agent_rework_report.json    # 返工报告
└── per_site/
    ├── <site>.json             # 更新后的站点结果
    └── <site>/
        ├── final_code.py       # 更新后的 final_code
        ├── script_res.json     # 更新后的提取结果
        └── rework_notes.md     # 返工记录（如有）
```
