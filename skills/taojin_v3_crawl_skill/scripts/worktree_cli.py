"""Worktree management CLI for taojin_v3_crawl_skill.

Provides utilities for seed discovery, worktree setup/cleanup/list,
prompt rendering, and Stage4 summary/report generation.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
REPO_ROOT = SKILL_ROOT.parents[1]
DEFAULT_WORKTREE_ROOT = REPO_ROOT / "worktrees"

DEFAULT_EFFECTIVE_PRICE_FIELDS = ["source_activity_price", "source_origin_price"]


def _safe_resolve(path_str: Optional[str]) -> Optional[Path]:
    if not path_str:
        return None
    return Path(path_str).expanduser().resolve()


def _ensure_git_repo(repo_root: Path) -> None:
    if not (repo_root / ".git").exists():
        raise ValueError(f"not a git repository: {repo_root}")


def _run_git_simple(repo_root: Path, args: List[str]) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _normalize_site_domain(site: str) -> str:
    s = (site or "").strip().lower()
    if "://" in s:
        s = urllib.parse.urlsplit(s).hostname or s
    return s.rstrip("/")


def _normalize_site_token(raw: str) -> str:
    token = _normalize_site_domain(raw)
    if not token:
        raise ValueError(f"invalid site token: {raw!r}")
    return token


def _generate_worktree_name(selection_name: Optional[str] = None) -> str:
    date_str = datetime.now().strftime("%Y%m%d")
    if selection_name:
        name = re.sub(r'[^\w\u4e00-\u9fff\-]+', '_', selection_name.strip())
        name = name.strip('_')
        if name:
            return f"{date_str}_{name}"
    return date_str


def _validate_site_domain(site_domain: str, idx: int) -> None:
    if not site_domain or "." not in site_domain:
        raise ValueError(f"item #{idx}: invalid site_domain: {site_domain!r}")


def _derive_site_domain_from_urls(urls: List[str], idx: int) -> str:
    hosts = set()
    for url in urls:
        try:
            parsed = urllib.parse.urlparse(url)
            if parsed.netloc:
                hosts.add(parsed.netloc.lower())
        except Exception:
            continue
    if not hosts:
        raise ValueError(f"item #{idx}: cannot derive site_domain from urls")
    primary = sorted(hosts, key=lambda h: (h.count("."), len(h)))[0]
    if primary.startswith("www."):
        primary = primary[4:]
    return primary


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def extract_links_from_html(html_text: str, base_url: str) -> List[str]:
    if not html_text:
        return []
    hrefs = re.findall(r'(?is)<a[^>]+href=["\']([^"\']+)["\']', html_text)
    result: List[str] = []
    seen = set()
    for href in hrefs:
        try:
            absolute = urllib.parse.urljoin(base_url, href)
        except Exception:
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        result.append(absolute)
    return result


def _detail_url_score(url: str) -> int:
    if not url:
        return -100
    parsed = urllib.parse.urlparse(url)
    path = parsed.path.lower()
    score = 0
    detail_tokens = [
        ("/product/", 5),
        ("/products/", 5),
        ("/p/", 3),
        ("/item/", 3),
        ("/detail/", 3),
        ("/goods/", 3),
        ("-p-", 2),
        ("/dp/", 4),
        ("/gp/", 3),
    ]
    for token, weight in detail_tokens:
        if token in path:
            score += weight
    if re.search(r"\d{4,}", path):
        score += 1
    if any(path.endswith(ext) for ext in (".html", ".htm", ".php", ".jsp")):
        score += 1
    if parsed.query:
        query = parsed.query.lower()
        if "id=" in query or "productid=" in query or "sku=" in query:
            score += 2
    return score


def _extract_robots_sitemap_urls(robots_text: str) -> List[str]:
    if not robots_text:
        return []
    urls: List[str] = []
    for line in robots_text.splitlines():
        line = line.strip()
        if line.lower().startswith("sitemap:"):
            url = line.split(":", 1)[1].strip()
            if url:
                urls.append(url)
    return urls


def _parse_sitemap_locs(xml_text: str) -> List[str]:
    if not xml_text:
        return []
    locs = re.findall(r'(?is)<loc>(.*?)</loc>', xml_text)
    return [loc.strip() for loc in locs if loc.strip()]


def _pick_seed_urls(urls: List[str], max_count: int, site_domain: str) -> List[str]:
    scored: List[Tuple[int, str]] = []
    seen = set()
    for url in urls:
        try:
            parsed = urllib.parse.urlparse(url)
        except Exception:
            continue
        host = (parsed.netloc or "").lower()
        allowed = {site_domain.lower()}
        if site_domain.startswith("www."):
            allowed.add(site_domain[4:].lower())
        else:
            allowed.add(f"www.{site_domain.lower()}")
        if host not in allowed:
            continue
        identity = _normalize_identity_url(url)
        if identity in seen:
            continue
        seen.add(identity)
        score = _detail_url_score(url)
        if score >= 3:
            scored.append((score, url))
    scored.sort(reverse=True)
    return [url for _, url in scored[:max_count]]


def _normalize_identity_url(url: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(url.strip())
    except Exception:
        return url
    scheme = parsed.scheme.lower() if parsed.scheme else "https"
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/")
    query_pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    filtered = [
        (k, v)
        for k, v in query_pairs
        if k.lower() not in {
            "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
            "gclid", "fbclid",
        }
    ]
    new_query = urllib.parse.urlencode(filtered)
    return urllib.parse.urlunsplit((scheme, netloc, path, new_query, ""))


def discover_seed_urls(
    site_domain: str,
    target_count: int,
    worktree_root: Optional[Path] = None,
    selection_name: Optional[str] = None,
) -> Dict[str, Any]:
    site = _normalize_site_token(site_domain)
    worktree_name = _generate_worktree_name(selection_name)
    worktree_base = worktree_root or DEFAULT_WORKTREE_ROOT
    worktree = worktree_base / worktree_name
    worktree.mkdir(parents=True, exist_ok=True)

    return {
        "site_domain": site,
        "target_count": target_count,
        "worktree_path": str(worktree),
        "spu_urls": [],
        "status": "placeholder",
        "note": "seed discover placeholder - delegates to site-seed-discovery skill",
    }


def worktree_setup(
    site: str,
    worktree_root: Optional[Path] = None,
    branch: Optional[str] = None,
    selection_name: Optional[str] = None,
) -> Dict[str, Any]:
    site_domain = _normalize_site_token(site)
    worktree_base = worktree_root or DEFAULT_WORKTREE_ROOT
    worktree_name = _generate_worktree_name(selection_name)
    worktree_path = worktree_base / worktree_name
    branch_name = branch or f"worktree/{worktree_name}"

    result: Dict[str, Any] = {
        "site_domain": site_domain,
        "worktree_path": str(worktree_path),
        "branch": branch_name,
    }

    try:
        _ensure_git_repo(REPO_ROOT)
        if worktree_path.exists():
            result["status"] = "exists"
            result["note"] = "worktree already exists"
            return result
        try:
            _run_git_simple(REPO_ROOT, ["rev-parse", "--verify", branch_name])
        except RuntimeError:
            _run_git_simple(REPO_ROOT, ["branch", branch_name])
        _run_git_simple(REPO_ROOT, ["worktree", "add", str(worktree_path), branch_name])
        result["status"] = "created"
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
    return result


def worktree_cleanup(
    site: str,
    worktree_root: Optional[Path] = None,
    remove_branch: bool = False,
) -> Dict[str, Any]:
    site_domain = _normalize_site_token(site)
    worktree_base = worktree_root or DEFAULT_WORKTREE_ROOT
    worktree_path = worktree_base / site_domain
    branch_name = f"worktree/{site_domain}"

    result: Dict[str, Any] = {
        "site_domain": site_domain,
        "worktree_path": str(worktree_path),
    }

    try:
        _ensure_git_repo(REPO_ROOT)
        if worktree_path.exists():
            _run_git_simple(REPO_ROOT, ["worktree", "remove", str(worktree_path), "--force"])
            result["worktree_removed"] = True
        if remove_branch:
            try:
                _run_git_simple(REPO_ROOT, ["branch", "-D", branch_name])
                result["branch_removed"] = True
            except RuntimeError:
                result["branch_removed"] = False
        result["status"] = "cleaned"
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
    return result


def worktree_list(worktree_root: Optional[Path] = None) -> List[Dict[str, Any]]:
    worktree_base = worktree_root or DEFAULT_WORKTREE_ROOT
    if not worktree_base.exists():
        return []
    result: List[Dict[str, Any]] = []
    for item in sorted(worktree_base.iterdir()):
        if item.is_dir():
            info: Dict[str, Any] = {
                "site_domain": item.name,
                "path": str(item),
            }
            try:
                git_dir = item / ".git"
                if git_dir.exists() or (item / ".git").is_file():
                    info["has_git"] = True
            except Exception:
                info["has_git"] = False
            result.append(info)
    return result


def render_run_prompt(
    site: str,
    worktree_root: Optional[Path] = None,
    template_path: Optional[Path] = None,
    selection_name: Optional[str] = None,
) -> str:
    site_domain = _normalize_site_token(site)
    template = template_path or (SKILL_ROOT / "references" / "run_prompt_template.md")
    template_text = ""
    if template.exists():
        template_text = template.read_text(encoding="utf-8")
    else:
        template_text = (
            "# Run Prompt: {site_domain}\n\n"
            "Site: {site_domain}\n"
            "Worktree: {{worktree_path}}\n\n"
            "## Task\n\n"
            "Process site {site_domain} through the crawl pipeline.\n\n"
            "## Steps\n\n"
            "1. Stage4: List discovery\n"
            "2. Stage3: SPU/SKU extraction\n"
            "3. Stage2: Self-test\n"
            "4. Stage1: Post-processing\n"
        )

    worktree_name = _generate_worktree_name(selection_name)
    worktree_path = (worktree_root or DEFAULT_WORKTREE_ROOT) / worktree_name
    rendered = template_text.replace("{site_domain}", site_domain)
    rendered = rendered.replace("{worktree_path}", str(worktree_path))
    return rendered


def render_stage4_site_summary(site_result: Dict[str, Any]) -> str:
    site = site_result.get("input_site") or site_result.get("site_domain") or "unknown"
    coverage = site_result.get("coverage", "unknown")
    observed = site_result.get("observed_count", 0)
    sitemap = site_result.get("sitemap", "")
    companion = site_result.get("companion") or {}
    companion_type = companion.get("type", "")
    companion_value = companion.get("value", "")
    process_notes = site_result.get("process_notes") or []
    sample_uris = site_result.get("sample_detail_uris") or []

    lines = [
        f"# Stage4 Summary: {site}",
        "",
        f"- **Coverage**: {coverage}",
        f"- **Observed count**: {observed}",
        f"- **Sitemap**: {sitemap}",
        f"- **Companion type**: {companion_type}",
        "",
        "## Companion value",
        "",
        f"```\n{companion_value}\n```",
        "",
        "## Process notes",
        "",
    ]
    for note in process_notes:
        lines.append(f"- {note}")
    lines.append("")
    lines.append("## Sample detail URIs")
    lines.append("")
    for uri in sample_uris[:10]:
        lines.append(f"- {uri}")
    if len(sample_uris) > 10:
        lines.append(f"- ... and {len(sample_uris) - 10} more")
    lines.append("")
    return "\n".join(lines)


def render_stage4_batch_report(results: List[Dict[str, Any]]) -> str:
    total = len(results)
    by_coverage: Dict[str, int] = {}
    for r in results:
        cov = r.get("coverage", "unknown")
        by_coverage[cov] = by_coverage.get(cov, 0) + 1

    lines = [
        "# Stage4 Batch Report",
        "",
        f"- **Total sites**: {total}",
        "",
        "## Coverage breakdown",
        "",
    ]
    for cov, count in sorted(by_coverage.items()):
        lines.append(f"- **{cov}**: {count}")
    lines.append("")
    lines.append("## Per-site summary")
    lines.append("")
    for r in results:
        site = r.get("input_site") or r.get("site_domain") or "unknown"
        cov = r.get("coverage", "unknown")
        observed = r.get("observed_count", 0)
        lines.append(f"- **{site}**: {cov} ({observed} observed)")
    lines.append("")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Worktree management CLI for taojin_v3_crawl_skill")
    subparsers = parser.add_subparsers(dest="command", required=True)

    seed_parser = subparsers.add_parser("seed", help="Seed discovery commands")
    seed_sub = seed_parser.add_subparsers(dest="seed_command", required=True)
    discover_parser = seed_sub.add_parser("discover", help="Discover seed URLs for a site")
    discover_parser.add_argument("--site-domain", required=True, help="Target site domain")
    discover_parser.add_argument("--count", type=int, default=5, help="Target seed count")
    discover_parser.add_argument("--worktree-root", help="Worktree root directory")
    discover_parser.add_argument("--selection-name", help="Selection name for worktree naming (format: date+selection)")

    wt_parser = subparsers.add_parser("worktree", help="Worktree commands")
    wt_sub = wt_parser.add_subparsers(dest="worktree_command", required=True)

    setup_parser = wt_sub.add_parser("setup", help="Create a worktree")
    setup_parser.add_argument("--site", required=True, help="Site domain")
    setup_parser.add_argument("--worktree-root", help="Worktree root directory")
    setup_parser.add_argument("--branch", help="Branch name")
    setup_parser.add_argument("--selection-name", help="Selection name for worktree naming (format: date+selection)")

    cleanup_parser = wt_sub.add_parser("cleanup", help="Clean up a worktree")
    cleanup_parser.add_argument("--site", required=True, help="Site domain")
    cleanup_parser.add_argument("--worktree-root", help="Worktree root directory")
    cleanup_parser.add_argument("--remove-branch", action="store_true", help="Also remove branch")

    list_parser = wt_sub.add_parser("list", help="List worktrees")
    list_parser.add_argument("--worktree-root", help="Worktree root directory")

    prompt_parser = subparsers.add_parser("prompt", help="Prompt commands")
    prompt_sub = prompt_parser.add_subparsers(dest="prompt_command", required=True)
    render_parser = prompt_sub.add_parser("render", help="Render run_prompt.md")
    render_parser.add_argument("--site", required=True, help="Site domain")
    render_parser.add_argument("--worktree-root", help="Worktree root directory")
    render_parser.add_argument("--template", help="Template path")
    render_parser.add_argument("--output", help="Output path")
    render_parser.add_argument("--selection-name", help="Selection name for worktree naming (format: date+selection)")

    s4_parser = subparsers.add_parser("stage4", help="Stage4 commands")
    s4_sub = s4_parser.add_subparsers(dest="stage4_command", required=True)

    site_summary_parser = s4_sub.add_parser("site-summary", help="Render single site Stage4 summary")
    site_summary_parser.add_argument("--site", required=True, help="Site domain")
    site_summary_parser.add_argument("--input", help="Input JSON path")
    site_summary_parser.add_argument("--output", help="Output path")

    batch_report_parser = s4_sub.add_parser("batch-report", help="Render batch Stage4 report")
    batch_report_parser.add_argument("--input-dir", help="Input directory with per-site JSON")
    batch_report_parser.add_argument("--output", help="Output path")

    return parser


def main(argv: Sequence[str] = ()) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "seed" and args.seed_command == "discover":
        result = discover_seed_urls(
            args.site_domain,
            args.count,
            _safe_resolve(args.worktree_root),
            args.selection_name,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    if args.command == "worktree":
        if args.worktree_command == "setup":
            result = worktree_setup(
                args.site,
                _safe_resolve(args.worktree_root),
                args.branch,
                args.selection_name,
            )
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0
        if args.worktree_command == "cleanup":
            result = worktree_cleanup(
                args.site,
                _safe_resolve(args.worktree_root),
                args.remove_branch,
            )
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0
        if args.worktree_command == "list":
            result = worktree_list(_safe_resolve(args.worktree_root))
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0

    if args.command == "prompt" and args.prompt_command == "render":
        content = render_run_prompt(
            args.site,
            _safe_resolve(args.worktree_root),
            _safe_resolve(args.template),
            args.selection_name,
        )
        if args.output:
            out_path = Path(args.output).resolve()
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(content, encoding="utf-8")
            print(f"Prompt written to {out_path}")
        else:
            print(content)
        return 0

    if args.command == "stage4":
        if args.stage4_command == "site-summary":
            input_path = _safe_resolve(args.input)
            if input_path and input_path.exists():
                site_result = _load_json(input_path)
            else:
                site_result = {"input_site": args.site, "coverage": "unknown"}
            content = render_stage4_site_summary(site_result)
            if args.output:
                out_path = Path(args.output).resolve()
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(content, encoding="utf-8")
                print(f"Summary written to {out_path}")
            else:
                print(content)
            return 0
        if args.stage4_command == "batch-report":
            input_dir = _safe_resolve(args.input_dir) or (REPO_ROOT / "output" / "per_site")
            results: List[Dict[str, Any]] = []
            if input_dir.exists():
                for json_path in sorted(input_dir.glob("*.json")):
                    try:
                        results.append(_load_json(json_path))
                    except Exception:
                        continue
            content = render_stage4_batch_report(results)
            if args.output:
                out_path = Path(args.output).resolve()
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(content, encoding="utf-8")
                print(f"Report written to {out_path}")
            else:
                print(content)
            return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
