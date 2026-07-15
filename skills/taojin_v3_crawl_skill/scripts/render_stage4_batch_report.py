"""Render batch Stage4 report from multiple site_delivery_summary.md files.

Collects per-site summaries from a worktree and produces a single
HTML batch report with overview statistics and per-site details.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


REQUIRED_SITE_FIELDS: List[str] = [
    "input_site",
    "effective_origin",
    "sitemap",
    "companion",
    "coverage",
]

VALID_COVERAGE: List[str] = ["ok", "partial", "none", "blocked", "dead", "amb"]

COVERAGE_COLORS: Dict[str, str] = {
    "ok": "#0ba63e",
    "partial": "#008af7",
    "none": "#ff8a00",
    "blocked": "#6b7280",
    "dead": "#e60023",
    "amb": "#7c3aed",
}


def _project_root(start: Optional[Path] = None) -> Path:
    here = (start or Path(__file__).resolve()).parent
    for candidate in [here, *here.parents]:
        if (candidate / "skills" / "taojin_v3_crawl_skill").is_dir():
            return candidate
    return here.parents[2] if len(here.parents) >= 3 else here


def find_site_summaries(worktree_root: Path) -> List[Path]:
    """Find all site_delivery_summary.md files under the worktree."""
    results: List[Path] = []
    if not worktree_root.exists():
        return results
    for md_path in sorted(worktree_root.rglob("site_delivery_summary.md")):
        results.append(md_path)
    return results


def find_site_json_files(worktree_root: Path) -> List[Path]:
    """Find per-site JSON result files."""
    results: List[Path] = []
    if not worktree_root.exists():
        return results
    per_site_dir = worktree_root / "output" / "per_site"
    if per_site_dir.exists():
        for jp in sorted(per_site_dir.glob("*.json")):
            if jp.is_file():
                results.append(jp)
    return results


def parse_site_summary_md(md_path: Path) -> Dict[str, Any]:
    """Parse a site_delivery_summary.md into a structured dict."""
    text = md_path.read_text(encoding="utf-8")
    data: Dict[str, Any] = {"source_md": str(md_path)}

    title_match = re.search(r"^# Stage4 站点交付摘要:\s*(.+)$", text, re.MULTILINE)
    if title_match:
        data["input_site"] = title_match.group(1).strip()

    field_patterns = {
        "effective_origin": r"-\s*\*\*effective_origin\*\*:\s*(.+)",
        "commerce_origin": r"-\s*\*\*commerce_origin\*\*:\s*(.+)",
        "scope_reason": r"-\s*\*\*scope_reason\*\*:\s*(.+)",
        "coverage": r"-\s*\*\*coverage\*\*:\s*([^\(]+?)(?:\s*\(|$)",
        "observed_count": r"-\s*\*\*observed_count\*\*:\s*(.+)",
    }
    for key, pat in field_patterns.items():
        m = re.search(pat, text, re.MULTILINE)
        if m:
            val = m.group(1).strip()
            if key == "observed_count":
                try:
                    data[key] = int(val) if val else None
                except ValueError:
                    data[key] = val
            else:
                data[key] = val

    sitemap_match = re.search(r"## Sitemap\s*\n\s*\n(.+?)\s*\n", text)
    if sitemap_match:
        data["sitemap"] = sitemap_match.group(1).strip()

    companion_type_match = re.search(r"## Companion:\s*(.+?)\s*\n", text)
    if companion_type_match:
        ctype = companion_type_match.group(1).strip()
        data.setdefault("companion", {})["type"] = ctype
        if ctype == "list_custom_code":
            code_match = re.search(r"```python\s*\n(.*?)```", text, re.DOTALL)
            if code_match:
                data["companion"]["value"] = code_match.group(1).strip()
        else:
            next_section = re.search(
                r"## Companion:.*?\s*\n\s*\n(.*?)\s*\n\s*## ",
                text,
                re.DOTALL,
            )
            if next_section:
                data["companion"]["value"] = next_section.group(1).strip()

    sample_section = re.search(
        r"## 样本详情页\s*\n\s*\n(.*?)\s*\n\s*## ",
        text,
        re.DOTALL,
    )
    if sample_section:
        sample_text = sample_section.group(1)
        uris: List[str] = []
        reasons: List[str] = []
        for m in re.finditer(r"\d+\.\s*\[(.+?)\]\(.+?\)", sample_text):
            uris.append(m.group(1).strip())
        for m in re.finditer(r"- 原因:\s*(.+)", sample_text):
            reasons.append(m.group(1).strip())
        data["sample_detail_uris"] = uris
        data["sample_detail_reasons"] = reasons

    process_section = re.search(
        r"## 流程说明\s*\n\s*\n(.*?)\s*\n\s*## ",
        text,
        re.DOTALL,
    )
    if process_section:
        proc_text = process_section.group(1)
        notes = [
            m.group(1).strip()
            for m in re.finditer(r"^-\s*(.+)$", proc_text, re.MULTILINE)
        ]
        data["process_notes"] = notes

    patch_match = re.search(r"> patch-label:\s*(.+?)\s*\n", text)
    if patch_match:
        data["patch_label"] = patch_match.group(1).strip()

    return data


def load_site_json(json_path: Path) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return None


def collect_sites(worktree_root: Path) -> List[Dict[str, Any]]:
    """Collect site data from both JSON files and markdown summaries."""
    json_files = find_site_json_files(worktree_root)
    md_files = find_site_summaries(worktree_root)

    site_map: Dict[str, Dict[str, Any]] = {}

    for jp in json_files:
        d = load_site_json(jp)
        if not d:
            continue
        site = d.get("input_site") or jp.stem
        if site in site_map:
            site_map[site].update(d)
        else:
            site_map[site] = dict(d)
        site_map[site]["_json_path"] = str(jp)

    for mp in md_files:
        d = parse_site_summary_md(mp)
        site = d.get("input_site") or mp.parent.name
        if site in site_map:
            site_map[site].update(d)
        else:
            site_map[site] = d
        site_map[site]["_md_path"] = str(mp)

    return sorted(site_map.values(), key=lambda x: x.get("input_site", ""))


def validate_sites(sites: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    """Validate per-site required fields and consistency."""
    errors_by_site: Dict[str, List[str]] = {}

    for site_data in sites:
        site = site_data.get("input_site") or "(unknown)"
        errs: List[str] = []

        for field in REQUIRED_SITE_FIELDS:
            val = site_data.get(field)
            if val is None or val == "" or (isinstance(val, list) and not val):
                if field != "companion":
                    errs.append(f"缺少必填字段: {field}")
            if field == "companion" and isinstance(val, dict):
                if not val.get("type") or not val.get("value"):
                    errs.append("companion 缺少 type 或 value")

        coverage = site_data.get("coverage", "")
        if coverage and coverage not in VALID_COVERAGE:
            errs.append(f"coverage 值无效: {coverage}")

        observed = site_data.get("observed_count")
        if coverage == "dead" and isinstance(observed, (int, float)) and observed > 0:
            errs.append(f"coverage=dead 但 observed_count={observed} > 0")

        if errs:
            errors_by_site[site] = errs

    return errors_by_site


def build_overview(sites: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build overview statistics."""
    total = len(sites)
    by_coverage: Dict[str, int] = {c: 0 for c in VALID_COVERAGE}
    total_observed = 0

    for s in sites:
        cov = s.get("coverage", "")
        if cov in by_coverage:
            by_coverage[cov] += 1
        else:
            by_coverage.setdefault("unknown", 0)
            by_coverage["unknown"] += 1
        obs = s.get("observed_count")
        if isinstance(obs, (int, float)):
            total_observed += int(obs)

    return {
        "total_sites": total,
        "by_coverage": by_coverage,
        "total_observed_count": total_observed,
    }


def render_html(sites: List[Dict[str, Any]], overview: Dict[str, Any], patch_label: Optional[str] = None) -> str:
    """Render the batch HTML report."""
    payload = {
        "sites": sites,
        "overview": overview,
        "patch_label": patch_label or "",
    }
    encoded = base64.b64encode(
        json.dumps(payload, ensure_ascii=False).encode("utf-8")
    ).decode("ascii")

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Stage4 Batch Report</title>
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
h1 {{ margin: 0 0 8px; font-size: 24px; }}
.subtitle {{ color: var(--muted); font-size: 13px; line-height: 1.5; }}
.wrap {{ max-width: 1186px; margin: 0 auto; padding: 18px 22px 60px; }}
.legend, .tools, .switcher, .site-head, .mark-inline {{
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}}
.legend {{ margin-bottom: 24px; }}
.legend span {{
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--muted);
}}
.dot {{
  width: 20px;
  height: 20px;
  border-radius: 50%;
  display: inline-block;
}}
.tools {{ margin: 14px 0; }}
button {{
  border: 1px solid var(--border);
  background: #ffffff;
  color: #202938;
  border-radius: 6px;
  padding: 6px 12px;
  cursor: pointer;
  font-size: 13px;
}}
button:hover {{ background: #f275f9; }}
.site-btn {{
  border-color: transparent;
  color: #ffffff;
  opacity: 0.88;
}}
.site-btn.active {{
  filter: brightness(1.08) saturate(1.05);
  font-weight: 700;
}}
.panel {{
  margin-top: 16px;
  padding: 22px 26px;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 8px;
}}
.grid {{
  display: grid;
  grid-template-columns: 180px minmax(0, 1fr);
  gap: 12px 14px;
  align-items: start;
}}
.label {{ color: var(--muted); font-size: 13px; }}
.value {{ overflow-wrap: anywhere; line-height: 1.45; }}
pre {{
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: #f4f6fa;
  overflow: auto;
  white-space: pre-wrap;
  font-size: 12px;
}}
.code-box {{
  border: 1px solid var(--border);
  border-radius: 8px;
  background: #f4f6fa;
  padding: 12px;
}}
.code-tools {{
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 8px;
}}
.collapsed pre {{ max-height: 120px; overflow: auto; }}
.sample-links {{ list-style: none; padding: 0; margin: 0; }}
.sample-links li {{ margin-bottom: 6px; }}
.sample-links a {{ color: #1f6feb; text-decoration: none; }}
.sample-links a:hover {{ text-decoration: underline; }}
.sample-note {{ color: var(--muted); font-size: 12px; margin-top: 2px; }}
.overview-cards {{
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 12px;
  margin-bottom: 20px;
}}
.overview-card {{
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 14px 16px;
  text-align: center;
}}
.overview-card .num {{
  font-size: 28px;
  font-weight: 700;
  margin-bottom: 4px;
}}
.overview-card .lbl {{
  font-size: 12px;
  color: var(--muted);
}}
.table {{
  width: 100%;
  border-collapse: collapse;
  margin-top: 12px;
  font-size: 13px;
}}
.table th, .table td {{
  border-bottom: 1px solid var(--border);
  padding: 8px 10px;
  text-align: left;
}}
.table th {{
  background: #f4f6fa;
  font-weight: 600;
  color: var(--muted);
}}
.badge {{
  display: inline-block;
  padding: 2px 8px;
  border-radius: 10px;
  color: #fff;
  font-size: 12px;
  font-weight: 600;
}}
</style>
</head>
<body>
<header>
  <h1>Stage4 Batch Report</h1>
  <div class="subtitle">批量站点 Stage4 交付汇总报告。{"patch-label: " + patch_label if patch_label else ""}</div>
</header>
<div class="wrap">
  <div class="overview-cards" id="overviewCards"></div>
  <div class="legend">
    <span><i class="dot" style="background:#0ba63e"></i>ok</span>
    <span><i class="dot" style="background:#008af7"></i>partial</span>
    <span><i class="dot" style="background:#ff8a00"></i>none</span>
    <span><i class="dot" style="background:#6b7280"></i>blocked</span>
    <span><i class="dot" style="background:#e60023"></i>dead</span>
    <span><i class="dot" style="background:#7c3aed"></i>amb</span>
  </div>
  <div class="tools">
    <button id="showAll">显示全部</button>
    <button id="failOnly">仅失败</button>
    <button id="tableView">表格视图</button>
    <button id="detailView">详情视图</button>
  </div>
  <div id="tableViewPanel" class="panel" style="display:none;">
    <table class="table" id="siteTable">
      <thead>
        <tr>
          <th>站点</th>
          <th>coverage</th>
          <th>observed_count</th>
          <th>sitemap</th>
          <th>companion 类型</th>
        </tr>
      </thead>
      <tbody></tbody>
    </table>
  </div>
  <div id="detailViewPanel">
    <div id="switcher" class="switcher"></div>
    <div id="panel" class="panel"></div>
  </div>
</div>
<script id="report-data-b64" type="text/plain">{encoded}</script>
<script>
const PAYLOAD = JSON.parse(new TextDecoder().decode(Uint8Array.from(atob(document.getElementById('report-data-b64').textContent.trim()), c => c.charCodeAt(0))));
const DATA = PAYLOAD.sites || [];
const OVERVIEW = PAYLOAD.overview || {{}};
const COLORS = {{ "ok":"#0ba63e", "partial":"#008af7", "none":"#ff8a00", "blocked":"#6b7280", "dead":"#e60023", "amb":"#7c3aed", "unknown":"#9ca3af" }};
let active = 0;
let failOnly = false;
let viewMode = "detail";

function esc(s) {{
  return String(s == null ? "" : s).replace(/[&<>"']/g, m => ({{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}}[m]));
}}
function coverageBadge(cov) {{
  const color = COLORS[cov] || "#9ca3af";
  return '<span class="badge" style="background:' + color + '">' + esc(cov || "unknown") + '</span>';
}}
function renderOverview() {{
  const cards = document.getElementById("overviewCards");
  const ov = OVERVIEW;
  const items = [
    {{ num: ov.total_sites || 0, lbl: "站点总数" }},
    {{ num: (ov.by_coverage && ov.by_coverage.ok) || 0, lbl: "ok", color: COLORS.ok }},
    {{ num: (ov.by_coverage && ov.by_coverage.partial) || 0, lbl: "partial", color: COLORS.partial }},
    {{ num: (ov.by_coverage && ov.by_coverage.none) || 0, lbl: "none", color: COLORS.none }},
    {{ num: (ov.by_coverage && ov.by_coverage.blocked) || 0, lbl: "blocked", color: COLORS.blocked }},
    {{ num: (ov.by_coverage && ov.by_coverage.dead) || 0, lbl: "dead", color: COLORS.dead }},
    {{ num: (ov.by_coverage && ov.by_coverage.amb) || 0, lbl: "amb", color: COLORS.amb }},
    {{ num: ov.total_observed_count || 0, lbl: "总 observed_count" }},
  ];
  cards.innerHTML = items.map(it =>
    '<div class="overview-card">' +
    '<div class="num"' + (it.color ? ' style="color:' + it.color + '"' : '') + '>' + it.num + '</div>' +
    '<div class="lbl">' + esc(it.lbl) + '</div>' +
    '</div>'
  ).join("");
}}
function renderTable() {{
  const tbody = document.querySelector("#siteTable tbody");
  tbody.innerHTML = "";
  DATA.forEach((d) => {{
    if (failOnly && !["blocked","dead","amb","none"].includes(d.coverage)) return;
    const comp = d.companion || {{}};
    const tr = document.createElement("tr");
    tr.innerHTML =
      "<td>" + esc(d.input_site || "") + "</td>" +
      "<td>" + coverageBadge(d.coverage) + "</td>" +
      "<td>" + esc(d.observed_count == null ? "" : d.observed_count) + "</td>" +
      "<td>" + esc(d.sitemap || "") + "</td>" +
      "<td>" + esc(comp.type || "") + "</td>";
    tbody.appendChild(tr);
  }});
}}
function renderSwitcher() {{
  const wrap = document.getElementById("switcher"); wrap.innerHTML = "";
  DATA.forEach((d, i) => {{
    if (failOnly && !["blocked","dead","amb","none"].includes(d.coverage)) return;
    const b = document.createElement("button");
    b.className = "site-btn" + (i === active ? " active" : "");
    b.style.background = COLORS[d.coverage] || "#6b7280";
    b.textContent = d.input_site || d.effective_origin || ("site-" + (i + 1));
    b.onclick = () => {{ active = i; renderPanel(); }};
    wrap.appendChild(b);
  }});
}}
function sampleLinks(items, reasons) {{
  return '<ul class="sample-links">' + (items || []).map((u, i) => {{
    const url = String(u == null ? "" : u);
    const reason = String((reasons || [])[i] || "");
    const note = reason ? '<div class="sample-note">' + esc(reason) + '</div>' : "";
    return '<li><a href="' + esc(url) + '" target="_blank" rel="noopener noreferrer">' + esc(url) + '</a>' + note + '</li>';
  }}).join("") + "</ul>";
}}
function listItems(items) {{
  return "<ul>" + (items || []).map(x => "<li>" + esc(x) + "</li>").join("") + "</ul>";
}}
function renderPanel() {{
  const d = DATA[active];
  if (!d) return;
  const comp = d.companion || {{}};
  const asCode = comp.type === "list_custom_code";
  const companionHtml = asCode
    ? '<div class="code-box collapsed" id="codeBox"><div class="code-tools"><button class="code-toggle" id="toggleCode">展开 list_custom_code</button><button id="copyCode">复制 list_custom_code</button></div><pre>' + esc(comp.value || "") + "</pre></div>"
    : '<div class="value">' + esc(comp.value || "") + "</div>";
  document.getElementById("panel").innerHTML =
    '<div class="site-head"><h2>' + esc(d.input_site || "") + '</h2>' + coverageBadge(d.coverage) + '</div>' +
    '<div class="grid">' +
    '<div class="label">effective_origin</div><div class="value">' + esc(d.effective_origin || "") + '</div>' +
    '<div class="label">commerce_origin</div><div class="value">' + esc(d.commerce_origin || "") + '</div>' +
    '<div class="label">scope_reason</div><div class="value">' + esc(d.scope_reason || "") + '</div>' +
    '<div class="label">sitemap</div><div class="value">' + esc(d.sitemap || "") + '</div>' +
    '<div class="label">' + esc(comp.type || "companion") + '</div>' + companionHtml +
    '<div class="label">sample_detail_uris</div><div class="value">' + sampleLinks(d.sample_detail_uris, d.sample_detail_reasons) + '</div>' +
    '<div class="label">process_notes</div><div class="value">' + listItems(d.process_notes) + '</div>' +
    '<div class="label">coverage</div><div class="value">' + coverageBadge(d.coverage) + (d.coverage_note ? " (" + esc(d.coverage_note) + ")" : "") + '</div>' +
    '<div class="label">observed_count</div><div class="value">' + esc(d.observed_count == null ? "" : d.observed_count) + '</div>' +
    "</div>";
  const toggle = document.getElementById("toggleCode");
  if (toggle) {{
    toggle.onclick = () => {{
      const box = document.getElementById("codeBox");
      const collapsed = box.classList.toggle("collapsed");
      toggle.textContent = collapsed ? "展开 list_custom_code" : "收起 list_custom_code";
    }};
  }}
  const copy = document.getElementById("copyCode");
  if (copy) {{
    copy.onclick = async () => {{
      try {{
        const ta = document.createElement("textarea");
        ta.value = comp.value || "";
        ta.style.position = "fixed";
        ta.style.opacity = "0";
        document.body.appendChild(ta);
        ta.focus();
        ta.select();
        ta.setSelectionRange(0, ta.value.length);
        document.execCommand("copy");
        document.body.removeChild(ta);
      }} catch (e) {{}}
    }};
  }}
}}
function renderAll() {{
  renderOverview();
  renderTable();
  if (viewMode === "detail") {{
    document.getElementById("tableViewPanel").style.display = "none";
    document.getElementById("detailViewPanel").style.display = "";
    renderSwitcher();
    renderPanel();
  }} else {{
    document.getElementById("tableViewPanel").style.display = "";
    document.getElementById("detailViewPanel").style.display = "none";
  }}
}}
document.getElementById("showAll").onclick = () => {{ failOnly = false; renderAll(); }};
document.getElementById("failOnly").onclick = () => {{ failOnly = true; renderAll(); }};
document.getElementById("tableView").onclick = () => {{ viewMode = "table"; renderAll(); }};
document.getElementById("detailView").onclick = () => {{ viewMode = "detail"; renderAll(); }};
renderAll();
</script>
</body>
</html>"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Render batch Stage4 HTML report")
    parser.add_argument("--worktree-root", help="Worktree root directory")
    parser.add_argument("--output-dir", help="Output directory (default: output)")
    parser.add_argument("--output", help="Output HTML file path")
    parser.add_argument("--patch-label", help="Patch label to include in report")
    parser.add_argument("--strict", action="store_true", help="Fail on validation errors")
    args = parser.parse_args()

    if args.worktree_root:
        worktree_root = Path(args.worktree_root).resolve()
    else:
        worktree_root = _project_root() / "worktrees"

    sites = collect_sites(worktree_root)
    if not sites:
        print("No site results found.", file=sys.stderr)
        return 2

    validation_errors = validate_sites(sites)
    total_error_count = sum(len(v) for v in validation_errors.values())

    overview = build_overview(sites)

    html_content = render_html(sites, overview, patch_label=args.patch_label)

    if args.output:
        output_path = Path(args.output).resolve()
    else:
        out_dir = Path(args.output_dir).resolve() if args.output_dir else (worktree_root / "output")
        output_path = out_dir / "stage4_batch_report.html"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_content, encoding="utf-8")
    print(f"Batch report written to {output_path}")
    print(f"  Sites: {len(sites)}")
    print(f"  Validation errors: {total_error_count}")

    if validation_errors:
        for site, errs in validation_errors.items():
            print(f"  {site}:", file=sys.stderr)
            for e in errs:
                print(f"    - {e}", file=sys.stderr)
        if args.strict:
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
