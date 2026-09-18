#!/usr/bin/env python3
"""只读校验指定每日 worktree 的工作簿，不回退到主项目历史结果。"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

from excel import validate_excel
from prepare_daily_worktree import WorktreeError, _git, _project_root


def _target_workbook(project_root: Path, worktree: Path) -> Path:
    """绑定本仓库注册的日期 worktree；允许历史日期和跨午夜校验。"""

    for label, value in (("主项目", project_root), ("worktree", worktree)):
        if ".." in value.parts:
            raise ValueError(f"{label}路径不能包含 ..：{value}")
        if value.expanduser().is_symlink():
            raise ValueError(f"{label}路径不能是符号链接：{value}")

    root = project_root.expanduser().resolve()
    if not root.is_dir() or _project_root(root) != root:
        raise ValueError(f"--project-root 必须指向主项目 Git 根目录：{root}")

    worktree_root = root / "worktrees"
    if worktree_root.is_symlink():
        raise ValueError(f"worktrees 目录不能是符号链接：{worktree_root}")

    daily = worktree.expanduser().resolve()
    if daily.parent != worktree_root:
        raise ValueError(f"--worktree 必须位于主项目的 worktrees/ 下：{daily}")
    match = re.fullmatch(r"([0-9]{8})_ugreen_topsales", daily.name)
    if match is None:
        raise ValueError("--worktree 目录名必须为 YYYYMMDD_ugreen_topsales")
    compact_date = match.group(1)
    try:
        date(int(compact_date[:4]), int(compact_date[4:6]), int(compact_date[6:8]))
    except ValueError as exc:
        raise ValueError(f"worktree 目录日期无效：{compact_date}") from exc
    if not daily.is_dir():
        raise ValueError(f"找不到指定每日 worktree：{daily}")

    if _project_root(daily) != root:
        raise ValueError(f"指定 worktree 不属于主项目 Git 仓库：{daily}")
    top = Path(_git(daily, "rev-parse", "--show-toplevel").stdout.strip()).resolve()
    if top != daily:
        raise ValueError(f"指定目录不是独立的 Git worktree 根目录：{daily}")
    registrations = _git(root, "worktree", "list", "--porcelain", "-z").stdout
    registered_paths = {
        Path(field.removeprefix("worktree ")).resolve()
        for field in registrations.split("\0")
        if field.startswith("worktree ")
    }
    if daily not in registered_paths:
        raise ValueError(f"指定 worktree 未在主项目 Git 仓库注册：{daily}")

    target = daily / "result/ugreen_topsales.xlsx"
    if target.parent.is_symlink() or target.is_symlink():
        raise ValueError(f"结果目录和工作簿不能是符号链接：{target}")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--worktree", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        target = _target_workbook(args.project_root, args.worktree)
        if not target.is_file():
            raise ValueError(f"找不到指定 worktree 的工作簿（不会读取主项目历史结果）：{target}")
        entries = sorted(path.name for path in target.parent.iterdir())
        if entries != [target.name]:
            raise ValueError(f"result/ 只能包含 {target.name}；当前为 {entries}")
        stats = validate_excel(target)
    except (OSError, ValueError, WorktreeError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    if stats.audit_status != "通过":
        print("错误：工作簿审计状态不是“通过”", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "path": str(target),
                "collection_mode": stats.collection_mode,
                "product_count": stats.product_count,
                "sku_count": stats.sku_count,
                "main_image_count": stats.main_image_count,
                "secondary_image_count": stats.secondary_image_count,
                "audit_status": stats.audit_status,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
