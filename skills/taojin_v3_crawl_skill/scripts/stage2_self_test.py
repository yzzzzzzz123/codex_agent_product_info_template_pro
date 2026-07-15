"""Stage2 self-test tool.

Validates case directory required files, SPU/SKU field consistency,
review stats evidence, price/currency/SKU attributes, and single-empty-props
SKU collapse verification.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


REQUIRED_SPU_FIELDS = (
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

OPTIONAL_SPU_FIELDS = (
    "source_score",
    "source_cmms",
    "not_detail",
    "default_sku_index",
    "effective_price",
)

REQUIRED_SKU_FIELDS = (
    "sku_props",
    "source_origin_price",
    "source_activity_price",
    "source_pics",
    "status",
)

REQUIRED_CASE_FILES = (
    "final_code.py",
    "script_res.json",
)

OPTIONAL_CASE_FILES = (
    "raw_html/static_page.html",
    "fixtures",
)

ISO_CURRENCIES = {
    "USD", "EUR", "GBP", "CNY", "JPY", "AUD", "CAD", "CHF", "HKD", "SGD",
    "SEK", "NOK", "DKK", "INR", "KRW", "RUB", "BRL", "TRY", "MXN", "PLN",
    "ZAR", "THB", "MYR", "IDR", "PHP", "VND", "ILS", "ARS", "CLP", "COP",
    "PEN", "UAH", "KZT", "NGN", "GHS", "EGP", "KES", "TWD", "NZD",
}


def _is_numeric(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return True
    try:
        float(str(value).replace(",", "").strip())
        return True
    except Exception:
        return False


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        cleaned = str(value).replace(",", "").strip()
        return float(cleaned)
    except Exception:
        return None


class ValidationResult:
    def __init__(self) -> None:
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.info: List[str] = []

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)

    def add_info(self, msg: str) -> None:
        self.info.append(msg)

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "errors": self.errors,
            "warnings": self.warnings,
            "info": self.info,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "info_count": len(self.info),
        }


def validate_case_files(case_dir: Path) -> ValidationResult:
    result = ValidationResult()

    if not case_dir.exists():
        result.add_error(f"case directory does not exist: {case_dir}")
        return result

    if not case_dir.is_dir():
        result.add_error(f"case path is not a directory: {case_dir}")
        return result

    for filename in REQUIRED_CASE_FILES:
        file_path = case_dir / filename
        if not file_path.exists():
            result.add_error(f"missing required file: {filename}")

    for filename in OPTIONAL_CASE_FILES:
        file_path = case_dir / filename
        if not file_path.exists():
            result.add_info(f"optional file not present: {filename}")

    return result


def validate_spu_fields(script_res: Dict[str, Any], detail_url: str) -> ValidationResult:
    result = ValidationResult()

    if not isinstance(script_res, dict):
        result.add_error("script_res is not a dict")
        return result

    for field in REQUIRED_SPU_FIELDS:
        if field not in script_res:
            result.add_error(f"missing required SPU field: {field}")

    if script_res.get("source_url") != detail_url:
        result.add_warning(
            f"source_url mismatch: expected {detail_url}, got {script_res.get('source_url')}"
        )

    if not isinstance(script_res.get("source_item_name"), str) or not script_res.get("source_item_name"):
        result.add_error("source_item_name is not a non-empty string")

    if not isinstance(script_res.get("source_pics"), list):
        result.add_error("source_pics is not a list")
    elif len(script_res["source_pics"]) == 0:
        result.add_warning("source_pics is empty")

    if not isinstance(script_res.get("descriptions"), list):
        result.add_error("descriptions is not a list")

    if not isinstance(script_res.get("props"), dict):
        result.add_error("props is not a dict")

    if not isinstance(script_res.get("skus"), list):
        result.add_error("skus is not a list")
    elif len(script_res["skus"]) == 0:
        result.add_warning("skus is empty")

    status = script_res.get("status")
    if not isinstance(status, int):
        result.add_error("status is not an int")

    return result


def validate_price_and_currency(script_res: Dict[str, Any]) -> ValidationResult:
    result = ValidationResult()

    activity_price = script_res.get("source_activity_price")
    origin_price = script_res.get("source_origin_price")
    currency = script_res.get("source_price_currency")

    if not _is_numeric(activity_price):
        result.add_error(f"source_activity_price is not numeric: {activity_price!r}")
    else:
        activity_val = _to_float(activity_price)
        if activity_val is not None and activity_val < 0:
            result.add_error(f"source_activity_price is negative: {activity_val}")

    if not _is_numeric(origin_price):
        result.add_error(f"source_origin_price is not numeric: {origin_price!r}")
    else:
        origin_val = _to_float(origin_price)
        if origin_val is not None and origin_val < 0:
            result.add_error(f"source_origin_price is negative: {origin_val}")

    if _is_numeric(activity_price) and _is_numeric(origin_price):
        activity_val = _to_float(activity_price)
        origin_val = _to_float(origin_price)
        if activity_val is not None and origin_val is not None:
            if activity_val > origin_val:
                result.add_warning(
                    f"source_activity_price ({activity_val}) > source_origin_price ({origin_val})"
                )

    if not isinstance(currency, str):
        result.add_error(f"source_price_currency is not a string: {currency!r}")
    else:
        if len(currency) != 3:
            result.add_error(f"source_price_currency must be 3 characters: {currency!r}")
        if currency != currency.upper():
            result.add_error(f"source_price_currency must be uppercase: {currency!r}")
        if currency not in ISO_CURRENCIES:
            result.add_warning(f"source_price_currency not in known ISO list: {currency}")

    return result


def validate_sku_fields(script_res: Dict[str, Any]) -> ValidationResult:
    result = ValidationResult()

    skus = script_res.get("skus")
    if not isinstance(skus, list):
        return result

    sku_props_keys: List[set] = []

    for idx, sku in enumerate(skus):
        prefix = f"skus[{idx}]"

        if not isinstance(sku, dict):
            result.add_error(f"{prefix} is not a dict")
            continue

        for field in REQUIRED_SKU_FIELDS:
            if field not in sku:
                result.add_error(f"{prefix} missing required field: {field}")

        if not isinstance(sku.get("sku_props"), dict):
            result.add_error(f"{prefix}.sku_props is not a dict")
        else:
            sku_props_keys.append(set(sku["sku_props"].keys()))

        sku_activity = sku.get("source_activity_price")
        sku_origin = sku.get("source_origin_price")

        if not _is_numeric(sku_activity):
            result.add_error(f"{prefix}.source_activity_price is not numeric: {sku_activity!r}")
        else:
            val = _to_float(sku_activity)
            if val is not None and val < 0:
                result.add_error(f"{prefix}.source_activity_price is negative: {val}")

        if not _is_numeric(sku_origin):
            result.add_error(f"{prefix}.source_origin_price is not numeric: {sku_origin!r}")
        else:
            val = _to_float(sku_origin)
            if val is not None and val < 0:
                result.add_error(f"{prefix}.source_origin_price is negative: {val}")

        if _is_numeric(sku_activity) and _is_numeric(sku_origin):
            act_val = _to_float(sku_activity)
            orig_val = _to_float(sku_origin)
            if act_val is not None and orig_val is not None and act_val > orig_val:
                result.add_warning(
                    f"{prefix}: source_activity_price ({act_val}) > source_origin_price ({orig_val})"
                )

        if not isinstance(sku.get("source_pics"), list):
            result.add_error(f"{prefix}.source_pics is not a list")

        if not isinstance(sku.get("status"), int):
            result.add_error(f"{prefix}.status is not an int")

    if sku_props_keys:
        first_keys = sku_props_keys[0]
        for i, keys in enumerate(sku_props_keys[1:], start=1):
            if keys != first_keys:
                result.add_warning(
                    f"skus[{i}] sku_props keys differ from skus[0]: "
                    f"{sorted(keys)} vs {sorted(first_keys)}"
                )
                break

    return result


def validate_review_stats_evidence(script_res: Dict[str, Any]) -> ValidationResult:
    result = ValidationResult()

    has_score = "source_score" in script_res
    has_cmms = "source_cmms" in script_res

    if has_score:
        score = script_res["source_score"]
        if not isinstance(score, (int, float)):
            result.add_error(f"source_score is not numeric: {score!r}")
        else:
            if score < 0 or score > 5:
                result.add_warning(f"source_score out of typical 0-5 range: {score}")

    if has_cmms:
        cmms = script_res["source_cmms"]
        if not isinstance(cmms, int):
            result.add_error(f"source_cmms is not an int: {cmms!r}")
        elif cmms < 0:
            result.add_error(f"source_cmms is negative: {cmms}")

    if has_score and not has_cmms:
        result.add_info("source_score present but source_cmms missing")

    if has_cmms and not has_score:
        result.add_info("source_cmms present but source_score missing")

    return result


def validate_single_empty_props_sku_collapse(script_res: Dict[str, Any]) -> ValidationResult:
    result = ValidationResult()

    skus = script_res.get("skus")
    if not isinstance(skus, list) or len(skus) <= 1:
        return result

    empty_props_indices: List[int] = []
    for idx, sku in enumerate(skus):
        sku_props = sku.get("sku_props") or {}
        if not sku_props or all(v is None or v == "" for v in sku_props.values()):
            empty_props_indices.append(idx)

    if len(empty_props_indices) <= 1:
        return result

    prices: List[Optional[float]] = []
    for idx in empty_props_indices:
        sku = skus[idx]
        activity = sku.get("source_activity_price")
        origin = sku.get("source_origin_price")
        price = _to_float(activity) if _is_numeric(activity) else _to_float(origin)
        prices.append(price)

    unique_prices = {p for p in prices if p is not None}

    if len(unique_prices) <= 1:
        result.add_warning(
            f"found {len(empty_props_indices)} SKUs with empty sku_props and same price "
            f"(indices: {empty_props_indices}); consider collapsing into one SKU"
        )

    return result


def validate_spu_sku_consistency(script_res: Dict[str, Any]) -> ValidationResult:
    result = ValidationResult()

    skus = script_res.get("skus")
    if not isinstance(skus, list) or len(skus) == 0:
        return result

    spu_currency = script_res.get("source_price_currency")

    for idx, sku in enumerate(skus):
        sku_currency = sku.get("source_price_currency")
        if sku_currency and spu_currency and sku_currency != spu_currency:
            result.add_error(
                f"skus[{idx}].source_price_currency ({sku_currency}) "
                f"!= SPU source_price_currency ({spu_currency})"
            )

    default_idx = script_res.get("default_sku_index")
    if default_idx is not None:
        if not isinstance(default_idx, int):
            result.add_error("default_sku_index is not an int")
        elif default_idx < 0 or default_idx >= len(skus):
            result.add_error(
                f"default_sku_index ({default_idx}) out of range [0, {len(skus) - 1}]"
            )

    return result


def run_self_test(
    case_dir: Path,
    detail_url: Optional[str] = None,
) -> Dict[str, Any]:
    case_dir = case_dir.resolve()
    all_results: Dict[str, Any] = {
        "case_dir": str(case_dir),
        "checks": {},
    }

    file_result = validate_case_files(case_dir)
    all_results["checks"]["case_files"] = file_result.to_dict()

    script_res_path = case_dir / "script_res.json"
    script_res: Dict[str, Any] = {}
    if script_res_path.exists():
        try:
            script_res = json.loads(script_res_path.read_text(encoding="utf-8"))
        except Exception as e:
            all_results["script_res_parse_error"] = str(e)
            script_res = {}

    if not detail_url:
        detail_url = str(script_res.get("source_url", ""))

    if script_res:
        all_results["checks"]["spu_fields"] = validate_spu_fields(
            script_res, detail_url
        ).to_dict()

        all_results["checks"]["price_currency"] = validate_price_and_currency(
            script_res
        ).to_dict()

        all_results["checks"]["sku_fields"] = validate_sku_fields(
            script_res
        ).to_dict()

        all_results["checks"]["review_stats"] = validate_review_stats_evidence(
            script_res
        ).to_dict()

        all_results["checks"]["empty_sku_collapse"] = validate_single_empty_props_sku_collapse(
            script_res
        ).to_dict()

        all_results["checks"]["spu_sku_consistency"] = validate_spu_sku_consistency(
            script_res
        ).to_dict()

    total_errors = 0
    total_warnings = 0
    for check_name, check_result in all_results["checks"].items():
        if isinstance(check_result, dict):
            total_errors += check_result.get("error_count", 0)
            total_warnings += check_result.get("warning_count", 0)

    all_results["total_errors"] = total_errors
    all_results["total_warnings"] = total_warnings
    all_results["overall_ok"] = total_errors == 0

    return all_results


def format_result(result: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append(f"Case: {result.get('case_dir', 'unknown')}")
    lines.append(f"Overall: {'PASS' if result.get('overall_ok') else 'FAIL'}")
    lines.append(f"Total errors: {result.get('total_errors', 0)}")
    lines.append(f"Total warnings: {result.get('total_warnings', 0)}")
    lines.append("")

    checks = result.get("checks", {})
    for check_name, check_result in checks.items():
        if not isinstance(check_result, dict):
            continue
        status = "PASS" if check_result.get("ok") else "FAIL"
        lines.append(f"[{status}] {check_name}")
        for err in check_result.get("errors", []):
            lines.append(f"  ERROR: {err}")
        for warn in check_result.get("warnings", []):
            lines.append(f"  WARN:  {warn}")
        for info in check_result.get("info", []):
            lines.append(f"  INFO:  {info}")
        lines.append("")

    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stage2 self-test tool")
    parser.add_argument("--case-dir", required=True, help="Case directory path")
    parser.add_argument("--detail-url", help="Expected detail URL (default: read from script_res.json)")
    parser.add_argument("--output", help="Output JSON path for full results")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    parser.add_argument("--strict", action="store_true", help="Exit with error on warnings too")
    return parser


def main(argv: Sequence[str] = ()) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    case_dir = Path(args.case_dir).resolve()
    result = run_self_test(case_dir, args.detail_url)

    if args.output:
        out_path = Path(args.output).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(result, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(format_result(result))

    if not result.get("overall_ok"):
        return 1

    if args.strict and result.get("total_warnings", 0) > 0:
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
