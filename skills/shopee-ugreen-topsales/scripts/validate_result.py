#!/usr/bin/env python3
"""校验 Skill 的固定工作簿，不生成任何伴随文件。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from excel import validate_excel


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    args = parser.parse_args()
    root = args.project_root.expanduser().resolve()
    target = root / "result/ugreen_topsales.xlsx"
    if not target.is_file():
        print(f"错误：找不到工作簿：{target}", file=sys.stderr)
        return 2
    entries = sorted(path.name for path in target.parent.iterdir())
    if entries != [target.name]:
        print(f"错误：result/ 只能包含 {target.name}；当前为 {entries}", file=sys.stderr)
        return 2
    try:
        stats = validate_excel(target)
    except (OSError, ValueError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    if stats.audit_status != "通过":
        print("错误：工作簿审计状态不是“通过”", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "path": str(target),
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
