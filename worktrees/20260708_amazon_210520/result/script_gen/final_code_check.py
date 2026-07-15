"""Live checker for final_code.py.

Runs final_code.py against a real URL and validates script_res.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, Optional

REQUIRED_FIELDS = (
    "source_url",
    "source_item_name",
    "source_pics",
    "descriptions",
    "source_origin_price",
    "source_activity_price",
    "source_price_currency",
    "props",
    "skus",
    "status",
)

OPTIONAL_FIELDS = (
    "source_score",
    "source_cmms",
    "not_detail",
)


def basic_runtime_namespace() -> Dict[str, Any]:
    """Return the base namespace that final_code.py runs against."""
    try:
        import requests as _requests  # noqa: F401
    except Exception:
        _requests = None
    try:
        from curl_cffi import requests as _curl_requests  # noqa: F401
    except Exception:
        _curl_requests = None

    def common_request(method, url, **kwargs):
        method = (method or "get").lower()
        timeout = kwargs.pop("timeout", 40)
        if method == "get":
            return _requests.get(url, timeout=timeout, **kwargs)
        if method == "post":
            return _requests.post(url, timeout=timeout, **kwargs)
        raise ValueError("unsupported method: %s" % method)

    return {
        "__name__": "__main__",
        "requests": _requests,
        "common_request": common_request,
    }


def _is_numeric(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return True
    try:
        float(value)
        return True
    except Exception:
        return False


def validate_script_res(script_res: Dict[str, Any], detail_url: str) -> Optional[str]:
    if not isinstance(script_res, dict):
        return "script_res is not a dict"

    for field in REQUIRED_FIELDS:
        if field not in script_res:
            return "missing required field: %s" % field

    if script_res.get("source_url") != detail_url:
        return "source_url mismatch: expected %s, got %s" % (
            detail_url,
            script_res.get("source_url"),
        )

    if not isinstance(script_res.get("source_pics"), list):
        return "source_pics is not a list"

    if not isinstance(script_res.get("descriptions"), list):
        return "descriptions is not a list"

    if not _is_numeric(script_res.get("source_origin_price")):
        return "source_origin_price is not numeric: %r" % script_res.get("source_origin_price")

    if not _is_numeric(script_res.get("source_activity_price")):
        return "source_activity_price is not numeric: %r" % script_res.get("source_activity_price")

    currency = script_res.get("source_price_currency")
    if not isinstance(currency, str) or len(currency) != 3 or currency != currency.upper():
        return "source_price_currency must be a 3-char upper-case string: %r" % currency

    if not isinstance(script_res.get("props"), dict):
        return "props is not a dict"

    skus = script_res.get("skus")
    if not isinstance(skus, list):
        return "skus is not a list"

    for idx, sku in enumerate(skus):
        if not isinstance(sku, dict):
            return "skus[%d] is not a dict" % idx
        if not isinstance(sku.get("sku_props"), dict):
            return "skus[%d].sku_props is not a dict" % idx
        if not _is_numeric(sku.get("source_origin_price")):
            return "skus[%d].source_origin_price is not numeric" % idx
        if not _is_numeric(sku.get("source_activity_price")):
            return "skus[%d].source_activity_price is not numeric" % idx
        if not isinstance(sku.get("source_pics"), list):
            return "skus[%d].source_pics is not a list" % idx
        if not isinstance(sku.get("status"), int):
            return "skus[%d].status is not an int" % idx

    if not isinstance(script_res.get("status"), int):
        return "status is not an int"

    score = script_res.get("source_score")
    if score is not None and not isinstance(score, (int, float)):
        return "source_score must be a float"

    cmms = script_res.get("source_cmms")
    if cmms is not None and not isinstance(cmms, int):
        return "source_cmms must be an int"

    not_detail = script_res.get("not_detail")
    if not_detail is not None and not isinstance(not_detail, str):
        return "not_detail must be a string"

    return None


def run_final_code(final_code_path: Path, detail_url: str) -> Dict[str, Any]:
    namespace = basic_runtime_namespace()
    namespace["detail_url"] = detail_url

    code = final_code_path.read_text(encoding="utf-8")
    compile(code, str(final_code_path), "exec")

    exec(compile(code, str(final_code_path), "exec"), namespace)

    script_res = namespace.get("script_res")
    if script_res is None:
        raise ValueError("final_code.py did not set script_res")

    return script_res


def main() -> int:
    parser = argparse.ArgumentParser(description="Live checker for final_code.py")
    parser.add_argument("--final-code", required=True, help="Path to final_code.py")
    parser.add_argument("--detail-url", required=True, help="PDP URL to check against")
    parser.add_argument("--output", help="Optional path to write script_res JSON")
    args = parser.parse_args()

    final_code_path = Path(args.final_code).resolve()
    if not final_code_path.exists():
        print("final_code.py not found: %s" % final_code_path, file=sys.stderr)
        return 2

    try:
        script_res = run_final_code(final_code_path, args.detail_url)
    except Exception:
        traceback.print_exc()
        return 1

    error = validate_script_res(script_res, args.detail_url)
    if error:
        print("VALIDATION FAILED: %s" % error, file=sys.stderr)
        print(json.dumps(script_res, indent=2, ensure_ascii=False))
        return 1

    print("VALIDATION OK")
    print(json.dumps(script_res, indent=2, ensure_ascii=False))

    if args.output:
        Path(args.output).write_text(
            json.dumps(script_res, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
