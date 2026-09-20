"""Render per-site Stage4 delivery summary as Markdown.

Reads the sitemap-list-discovery result JSON for a single site and
produces a site_delivery_summary.md with validated fields.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse


REQUIRED_FIELDS: List[str] = [
    "input_site",
    "effective_origin",
    "sitemap",
    "companion",
    "sample_detail_uris",
    "sample_detail_reasons",
    "process_notes",
    "coverage",
]

VALID_COVERAGE: List[str] = ["ok", "partial", "none", "blocked", "dead", "amb"]

CHINESE_PATTERN = re.compile(r"[\u4e00-\u9fff]")


def _project_root(start: Optional[Path] = None) -> Path:
    here = (start or Path(__file__).resolve()).parent
    for candidate in [here, *here.parents]:
        if (candidate / "skills" / "taojin_v3_crawl_skill").is_dir():
            return candidate
    return here.parents[2] if len(here.parents) >= 3 else here


def _is_valid_url(s: str) -> bool:
    if not s:
        return False
    try:
        parsed = urlparse(s)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except Exception:
        return False


def _has_chinese(s: str) -> bool:
    if not s:
        return False
    return bool(CHINESE_PATTERN.search(s))


def validate_sitemap(result: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    sitemap = result.get("sitemap")
    if not sitemap:
        errors.append("sitemap 字段为空")
    elif not _is_valid_url(str(sitemap)):
        errors.append(f"sitemap 不是有效的 URL: {sitemap}")
    return errors


def validate_companion(result: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    companion = result.get("companion")
    if not companion or not isinstance(companion, dict):
        errors.append("companion 字段缺失或不是对象")
        return errors

    ctype = companion.get("type")
    cvalue = companion.get("value")

    valid_types = {"Detail_url_pattern", "list_custom_code", "sitemap"}
    if ctype not in valid_types:
        errors.append(f"companion.type 无效: {ctype}")

    if not cvalue:
        errors.append("companion.value 为空")
    elif ctype == "list_custom_code":
        try:
            compile(str(cvalue), "list_custom_code", "exec")
        except SyntaxError as e:
            errors.append(f"list_custom_code 编译失败: {e}")
    elif ctype == "Detail_url_pattern":
        if "*" not in str(cvalue) and not _is_valid_url(str(cvalue)):
            errors.append(f"Detail_url_pattern 格式可疑: {cvalue}")

    return errors


def validate_sample_urls(result: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    uris = result.get("sample_detail_uris") or []
    reasons = result.get("sample_detail_reasons") or []

    if not isinstance(uris, list):
        errors.append("sample_detail_uris 不是列表")
        return errors
    if not isinstance(reasons, list):
        errors.append("sample_detail_reasons 不是列表")
        return errors

    if len(uris) != len(reasons):
        errors.append(
            f"sample_detail_uris ({len(uris)}) 与 sample_detail_reasons ({len(reasons)}) 长度不一致"
        )

    for i, u in enumerate(uris):
        if u and not _is_valid_url(str(u)):
            errors.append(f"sample_detail_uris[{i}] 不是有效 URL: {u}")

    for i, r in enumerate(reasons):
        if r and not _has_chinese(str(r)):
            errors.append(f"sample_detail_reasons[{i}] 缺少中文说明: {r}")

    return errors


def validate_risk_and_process(result: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    notes = result.get("process_notes") or []
    if not isinstance(notes, list) or not notes:
        errors.append("process_notes 为空或不是列表")
        return errors

    all_text = " ".join(str(n) for n in notes)
    if not _has_chinese(all_text):
        errors.append("process_notes 中没有中文内容")

    coverage = result.get("coverage", "")
    if coverage not in VALID_COVERAGE:
        errors.append(f"coverage 值无效: {coverage}")

    observed = result.get("observed_count")
    if coverage == "dead" and isinstance(observed, (int, float)) and observed > 0:
        errors.append(f"coverage=dead 但 observed_count={observed} > 0")

    return errors


def validate_runtime_evidence(result: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    notes = result.get("process_notes") or []
    notes_str = " ".join(str(n) for n in notes)

    evidence_keywords = ["sitemap", "列表页", "详情页", "验证", "抓取", "爬取", "测试", "样本"]
    found = any(kw in notes_str.lower() for kw in evidence_keywords)
    if not found:
        errors.append("process_notes 中缺少运行时证据关键词")

    return errors


def validate_artifact_sync(result: Dict[str, Any], artifact_dir: Optional[Path] = None) -> List[str]:
    errors: List[str] = []
    if artifact_dir is None:
        return errors
    if not artifact_dir.exists():
        errors.append(f"artifact 目录不存在: {artifact_dir}")
        return errors

    site = result.get("input_site") or ""
    if not site:
        errors.append("input_site 为空，无法验证 artifact 同步")
        return errors

    expected_files = [
        artifact_dir / f"{site}.json",
        artifact_dir / site / "raw_html",
    ]
    for f in expected_files:
        if not f.exists():
            errors.append(f"artifact 缺失: {f}")

    return errors


def validate_site_result(
    result: Dict[str, Any],
    artifact_dir: Optional[Path] = None,
) -> Dict[str, List[str]]:
    return {
        "sitemap": validate_sitemap(result),
        "companion": validate_companion(result),
        "sample_urls": validate_sample_urls(result),
        "risk_process": validate_risk_and_process(result),
        "runtime_evidence": validate_runtime_evidence(result),
        "artifact_sync": validate_artifact_sync(result, artifact_dir),
    }


def _fmt_list(items: List[str], prefix: str = "- ") -> str:
    if not items:
        return ""
    return "\n".join(f"{prefix}{x}" for x in items)


def render_markdown(
    result: Dict[str, Any],
    validation: Dict[str, List[str]],
    *,
    patch_label: Optional[str] = None,
) -> str:
    site = result.get("input_site", "(unknown)")
    coverage = result.get("coverage", "")
    coverage_note = result.get("coverage_note") or ""
    observed = result.get("observed_count", "")

    companion = result.get("companion") or {}
    ctype = companion.get("type", "")
    cvalue = companion.get("value", "")

    sample_uris = result.get("sample_detail_uris") or []
    sample_reasons = result.get("sample_detail_reasons") or []

    process_notes = result.get("process_notes") or []

    total_errors = sum(len(v) for v in validation.values())

    lines: List[str] = []
    lines.append(f"# Stage4 站点交付摘要: {site}")
    lines.append("")
    if patch_label:
        lines.append(f"> patch-label: {patch_label}")
        lines.append("")

    lines.append("## 基本信息")
    lines.append("")
    lines.append(f"- **input_site**: {site}")
    lines.append(f"- **effective_origin**: {result.get('effective_origin', '')}")
    lines.append(f"- **commerce_origin**: {result.get('commerce_origin', '')}")
    lines.append(f"- **scope_reason**: {result.get('scope_reason', '')}")
    lines.append(f"- **coverage**: {coverage}{(' (' + coverage_note + ')') if coverage_note else ''}")
    lines.append(f"- **observed_count**: {observed}")
    lines.append("")

    lines.append("## Sitemap")
    lines.append("")
    lines.append(f"{result.get('sitemap', '')}")
    lines.append("")

    lines.append(f"## Companion: {ctype}")
    lines.append("")
    if ctype == "list_custom_code":
        lines.append("```python")
        lines.append(str(cvalue))
        lines.append("```")
    else:
        lines.append(str(cvalue))
    lines.append("")

    lines.append("## 样本详情页")
    lines.append("")
    if sample_uris:
        for i, u in enumerate(sample_uris):
            reason = sample_reasons[i] if i < len(sample_reasons) else ""
            lines.append(f"{i + 1}. [{u}]({u})")
            if reason:
                lines.append(f"   - 原因: {reason}")
    else:
        lines.append("_无样本_")
    lines.append("")

    lines.append("## 流程说明")
    lines.append("")
    if process_notes:
        for n in process_notes:
            lines.append(f"- {n}")
    else:
        lines.append("_无_")
    lines.append("")

    lines.append("## 验证结果")
    lines.append("")
    if total_errors == 0:
        lines.append("✅ **全部验证通过**")
    else:
        lines.append(f"⚠️  **发现 {total_errors} 个问题**")
    lines.append("")

    for section, errs in validation.items():
        lines.append(f"### {section}")
        lines.append("")
        if errs:
            for e in errs:
                lines.append(f"- ❌ {e}")
        else:
            lines.append("- ✅ 通过")
        lines.append("")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Render per-site Stage4 summary markdown")
    parser.add_argument("--input", required=True, help="Path to site result JSON")
    parser.add_argument("--output", help="Path to write site_delivery_summary.md")
    parser.add_argument("--artifact-dir", help="Artifact directory for sync validation")
    parser.add_argument("--patch-label", help="Optional patch label to include")
    parser.add_argument("--strict", action="store_true", help="Fail on validation errors")
    args = parser.parse_args()

    input_path = Path(args.input).resolve()
    if not input_path.exists():
        print(f"Input file not found: {input_path}", file=sys.stderr)
        return 2

    result = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(result, dict):
        print("Input JSON is not an object", file=sys.stderr)
        return 2

    artifact_dir = Path(args.artifact_dir).resolve() if args.artifact_dir else None
    validation = validate_site_result(result, artifact_dir)
    total_errors = sum(len(v) for v in validation.values())

    md_content = render_markdown(result, validation, patch_label=args.patch_label)

    if args.output:
        output_path = Path(args.output).resolve()
    else:
        output_path = input_path.parent / "site_delivery_summary.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(md_content, encoding="utf-8")
    print(f"Summary written to {output_path}")

    if total_errors > 0:
        print(f"Validation errors: {total_errors}", file=sys.stderr)
        if args.strict:
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
