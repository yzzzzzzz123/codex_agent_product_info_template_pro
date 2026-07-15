"""Render final SPU/SKU data as a self-contained HTML report.

Reads a script_res JSON file and renders a single-file HTML for spot-check.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


def _escape(text: Any) -> str:
    if text is None:
        return ""
    return html.escape(str(text), quote=True)


def _format_price(value: Any, currency: Optional[str] = None) -> str:
    if value is None:
        return "-"
    try:
        num = float(value)
    except Exception:
        return str(value)
    prefix = ""
    if currency:
        mapping = {"USD": "$", "EUR": "€", "GBP": "£", "CNY": "¥"}
        prefix = mapping.get(currency.upper(), "")
    return "%s%.2f" % (prefix, num)


def _render_pics(pics: Optional[List[str]]) -> str:
    if not pics:
        return "<div class=\"muted\">无图片</div>"
    items = []
    for url in pics:
        items.append(
            "<div class=\"pic\"><img src=\"%s\" alt=\"\" loading=\"lazy\"></div>"
            % _escape(url)
        )
    return "".join(items)


def _render_props(props: Optional[Dict[str, Any]]) -> str:
    if not props:
        return "<div class=\"muted\">无属性</div>"
    rows = []
    for k, v in props.items():
        rows.append(
            "<div class=\"prop-row\"><span class=\"prop-key\">%s</span><span class=\"prop-val\">%s</span></div>"
            % (_escape(k), _escape(v))
        )
    return "".join(rows)


def _render_descriptions(descriptions: Optional[List[str]]) -> str:
    if not descriptions:
        return "<div class=\"muted\">无描述</div>"
    items = []
    for desc in descriptions:
        items.append("<div class=\"desc\">%s</div>" % _escape(desc))
    return "".join(items)


def _render_skus(skus: Optional[List[Dict[str, Any]]]) -> str:
    if not skus:
        return "<div class=\"muted\">无 SKU</div>"
    rows = []
    for idx, sku in enumerate(skus):
        sku_props = sku.get("sku_props") or {}
        props_html = "; ".join("%s=%s" % (k, v) for k, v in sku_props.items())
        rows.append(
            "<tr>"
            "<td>%d</td>"
            "<td>%s</td>"
            "<td>%s</td>"
            "<td>%s</td>"
            "<td>%d</td>"
            "<td>%d</td>"
            "</tr>" % (
                idx + 1,
                _escape(props_html),
                _format_price(sku.get("source_origin_price")),
                _format_price(sku.get("source_activity_price")),
                len(sku.get("source_pics") or []),
                int(sku.get("status") or 0),
            )
        )
    return (
        "<table class=\"sku-table\">"
        "<thead><tr><th>#</th><th>SKU Props</th><th>原价</th><th>活动价</th><th>图片数</th><th>状态</th></tr></thead>"
        "<tbody>" + "".join(rows) + "</tbody>"
        "</table>"
    )


def render_html(script_res: Dict[str, Any]) -> str:
    source_url = script_res.get("source_url", "")
    source_item_name = script_res.get("source_item_name", "")
    source_pics = script_res.get("source_pics") or []
    descriptions = script_res.get("descriptions") or []
    source_origin_price = script_res.get("source_origin_price")
    source_activity_price = script_res.get("source_activity_price")
    source_price_currency = script_res.get("source_price_currency")
    props = script_res.get("props") or {}
    skus = script_res.get("skus") or []
    status = script_res.get("status")
    source_score = script_res.get("source_score")
    source_cmms = script_res.get("source_cmms")
    not_detail = script_res.get("not_detail")

    status_text = "上架" if status == 1 else ("下架" if status == 0 else str(status))
    not_detail_badge = "<span class=\"badge warn\">%s</span>" % _escape(not_detail) if not_detail else ""

    return """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SPU Spot-check - {name}</title>
<style>
:root {{
  --border: #d7dde8;
  --text: #1f2937;
  --muted: #6b7280;
  --bg: #f5f7fa;
  --panel: #ffffff;
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  font-family: Arial, Helvetica, sans-serif;
  color: var(--text);
  background: var(--bg);
}}
header {{
  padding: 22px 28px 14px;
  background: #ffffff;
  border-bottom: 1px solid var(--border);
}}
h1 {{ margin: 0 0 8px; font-size: 22px; }}
.subtitle {{ color: var(--muted); font-size: 13px; line-height: 1.5; word-break: break-all; }}
.wrap {{ max-width: 1186px; margin: 0 auto; padding: 18px 22px 60px; }}
.panel {{
  margin-top: 16px;
  padding: 22px 26px;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 8px;
}}
.grid {{
  display: grid;
  grid-template-columns: 160px minmax(0, 1fr);
  gap: 12px 14px;
  align-items: start;
}}
.label {{ color: var(--muted); font-size: 13px; }}
.value {{ overflow-wrap: anywhere; line-height: 1.45; }}
.muted {{ color: var(--muted); font-size: 13px; }}
.pics {{ display: flex; flex-wrap: wrap; gap: 8px; }}
.pic {{ width: 120px; height: 120px; border: 1px solid var(--border); border-radius: 6px; overflow: hidden; }}
.pic img {{ width: 100%; height: 100%; object-fit: cover; }}
.prop-row {{ display: flex; gap: 8px; padding: 4px 0; border-bottom: 1px dashed var(--border); }}
.prop-key {{ color: var(--muted); min-width: 120px; }}
.desc {{ padding: 6px 0; border-bottom: 1px dashed var(--border); word-break: break-word; }}
.sku-table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
.sku-table th, .sku-table td {{ border: 1px solid var(--border); padding: 6px 8px; text-align: left; }}
.sku-table th {{ background: #f4f6fa; }}
.badge {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; }}
.badge.warn {{ background: #fff4e5; color: #b26b00; }}
</style>
</head>
<body>
<header>
  <h1>SPU Spot-check</h1>
  <div class="subtitle">{source_url}</div>
</header>
<div class="wrap">
  <div class="panel">
    <div class="grid">
      <div class="label">商品名称</div><div class="value">{name} {not_detail_badge}</div>
      <div class="label">原价</div><div class="value">{origin_price}</div>
      <div class="label">活动价</div><div class="value">{activity_price}</div>
      <div class="label">币种</div><div class="value">{currency}</div>
      <div class="label">状态</div><div class="value">{status}</div>
      <div class="label">评分</div><div class="value">{score}</div>
      <div class="label">评论数</div><div class="value">{cmms}</div>
      <div class="label">主图</div><div class="value pics">{pics}</div>
      <div class="label">属性</div><div class="value">{props}</div>
      <div class="label">描述</div><div class="value">{descriptions}</div>
      <div class="label">SKU 列表</div><div class="value">{skus}</div>
    </div>
  </div>
</div>
</body>
</html>""".format(
        source_url=_escape(source_url),
        name=_escape(source_item_name),
        not_detail_badge=not_detail_badge,
        origin_price=_format_price(source_origin_price, source_price_currency),
        activity_price=_format_price(source_activity_price, source_price_currency),
        currency=_escape(source_price_currency or "-"),
        status=_escape(status_text),
        score=_escape(source_score if source_score is not None else "-"),
        cmms=_escape(source_cmms if source_cmms is not None else "-"),
        pics=_render_pics(source_pics),
        props=_render_props(props),
        descriptions=_render_descriptions(descriptions),
        skus=_render_skus(skus),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Render SPU/SKU HTML report")
    parser.add_argument("--input", required=True, help="Path to script_res JSON")
    parser.add_argument("--output", required=True, help="Path to write HTML")
    args = parser.parse_args()

    input_path = Path(args.input).resolve()
    if not input_path.exists():
        print("input not found: %s" % input_path, file=sys.stderr)
        return 2

    try:
        script_res = json.loads(input_path.read_text(encoding="utf-8"))
    except Exception as e:
        print("failed to parse JSON: %s" % e, file=sys.stderr)
        return 1

    html_content = render_html(script_res)
    Path(args.output).write_text(html_content, encoding="utf-8")
    print("HTML written to %s" % args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
