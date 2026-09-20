#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASET_JSON = REPO_ROOT / "input" / "dataset_url_template.json"


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _validate_site_domain(site_domain: str, idx: int) -> None:
    if not site_domain:
        raise ValueError(f"item #{idx}: missing site_domain")
    if site_domain in {".", ".."} or "/" in site_domain or any(ch.isspace() for ch in site_domain):
        raise ValueError(f"item #{idx}: invalid site_domain '{site_domain}'")


def _normalize_site_domain(site_domain: str) -> str:
    return site_domain.strip().lower().rstrip(".")


def _derive_site_domain_from_urls(spu_uris: Sequence[str], idx: int) -> str:
    derived_domains: List[str] = []
    for url_idx, url in enumerate(spu_uris, start=1):
        hostname = urllib.parse.urlparse(url).hostname
        if not hostname:
            raise ValueError(f"item #{idx} url #{url_idx}: unable to derive site_domain")
        domains.append(_normalize_site_domain(hostname))
    site_domain = derived_domains[0]
    mismatched = sorted({domain for domain in derived_domains if domain != site_domain})
    if mismatched:
        raise ValueError(
            f"item #{idx}: spu_urls span multiple domains: expected {site_domain}, got {', '.join(mismatched)}"
        )
    _validate_site_domain(site_domain, idx)
    return site_domain


def _normalize_entries(raw: Any, allow_shortfall: bool) -> List[Dict[str, Any]]:
    if not isinstance(raw, list):
        raise ValueError("entries file must be a JSON array")
    seen_sites = set()
    normalized: List[Dict[str, Any]] = []
    for idx, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"item #{idx} is not an object")
        site_domain_raw = str(item.get("site_domain", "")).strip()
        site_domain = _normalize_site_domain(site_domain_raw) if site_domain_raw else ""
        if site_domain in seen_sites:
            raise ValueError(f"duplicate site_domain found: {site_domain}")
        seen_sites.add(site_domain)

        spu_uris = item.get("spu_urls")
        if not isinstance(spu_uris, list) or not spu_uris:
            raise ValueError(f"item #{idx}: spu_urls must be a non-empty array")

        deduped_uris: List[str] = []
        seen_urls = set()
        for url_idx, value in enumerate(spu_uris, start=1):
            url = str(value).strip()
            if not url:
                raise ValueError(f"item #{idx} url #{url_idx}: empty url")
            if not (url.startswith("http://") or url.startswith("https://")):
                raise ValueError(f"item #{idx} url #{url_idx}: not an absolute http(s) url: {url}")
            if url in seen_urls:
                continue
            seen_urls.add(url)
            deduped_uris.append(url)

        if not site_domain:
            site_domain = _derive_site_domain_from_urls(deduped_uris, idx)

        normalized_item: Dict[str, Any] = {"site_domain": site_domain, "spu_urls": deduped_uris}
        task_type = str(item.get("type", "")).strip()
        if task_type:
            normalized_item["type"] = task_type
        normalized.append(normalized_item)

    if not normalized:
        raise ValueError("entries file has no valid items")
    return normalized


def _merge_entries(existing: List[Dict[str, Any]], incoming: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized_existing = _normalize_entries(existing, allow_shortfall=True)
    site_map = {str(item["site_domain"]).strip(): item for item in normalized_existing}
    ordered_sites: List[str] = []
    for item in normalized_existing:
        ordered_sites.append(str(item["site_domain"]).strip())
    for item in incoming:
        site = item["site_domain"]
        site_map[site] = item
        if site not in ordered_sites:
            ordered_sites.append(site)
    return [site_map[site] for site in ordered_sites]


def _write_dataset(path: Path, entries: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serializable_entries: List[Dict[str, Any]] = []
    for entry in entries:
        item: Dict[str, Any] = {"spu_urls": list(entry.get("spu_urls") or [])}
        task_type = entry.get("type")
        if task_type:
            item["type"] = task_type
        serializable_entries.append(item)
    text = json.dumps(serializable_entries, ensure_ascii=False, indent=2) + "\n"
    path.write_text(text, encoding="utf-8")


def _run_git(repo_root: Path, args: List[str]) -> None:
    subprocess.run(["git", "-C", str(repo_root), *args], check=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Update input/dataset_url_template.json from discovered site seed urls"
    )
    parser.add_argument(
        "--dataset-json",
        default=str(DEFAULT_DATASET_JSON),
        help="Target dataset json path (default: input/dataset_url_template.json)",
    )
    parser.add_argument(
        "--entries-file",
        required=True,
        help="JSON array file with [{'spu_urls': [...]}] or legacy [{'site_domain': ..., 'spu_urls': [...]}]",
    )
    parser.add_argument(
        "--replace-all",
        action="store_true",
        help="Replace the whole dataset with discovered entries (recommended for current batch input)",
    )
    parser.add_argument(
        "--allow-shortfall",
        action="store_true",
        help="Allow fewer than 5 urls for a site only after confirming the site truly has fewer valid SPU urls",
    )
    parser.add_argument(
        "--git-commit",
        action="store_true",
        help="Run git add + git commit for the dataset file after writing (optional; disabled by default)",
    )
    parser.add_argument(
        "--commit-message",
        default="Update dataset_url_template.json from site seed discovery",
        help="Commit message used with --git-commit",
    )
    parser.add_argument(
        "--repo-root",
        default=str(REPO_ROOT),
        help="Git repo root used when --git-commit is enabled",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    dataset_json = Path(args.dataset_json).expanduser().resolve()
    entries_file = Path(args.entries_file).expanduser().resolve()
    repo_root = Path(args.repo_root).expanduser().resolve()

    incoming = _normalize_entries(_load_json(entries_file), args.allow_shortfall)

    if args.replace_all or not dataset_json.exists():
        final_entries = incoming
    else:
        existing = _load_json(dataset_json)
        if not isinstance(existing, list):
            raise ValueError(f"existing dataset file is not a JSON array: {dataset_json}")
        final_entries = _merge_entries(existing, incoming)

    _write_dataset(dataset_json, final_entries)
    print(f"[written] {dataset_json}")
    print(json.dumps(final_entries, ensure_ascii=False, indent=2))

    if args.git_commit:
        _run_git(repo_root, ["add", str(dataset_json)])
        _run_git(repo_root, ["commit", "-m", args.commit_message])
        print(f"[committed] {args.commit_message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
