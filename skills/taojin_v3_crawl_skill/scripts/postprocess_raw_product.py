"""Stage1 raw product post-processing.

Converts raw product data to target format, with price normalization,
SKU projection, and default SKU selection.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


DEFAULT_EFFECTIVE_PRICE_FIELDS = ["source_activity_price", "source_origin_price"]

CURRENCY_SYMBOLS: Dict[str, str] = {
    "$": "USD",
    "€": "EUR",
    "£": "GBP",
    "¥": "CNY",
    "₹": "INR",
    "₩": "KRW",
    "₽": "RUB",
    "R$": "BRL",
    "₺": "TRY",
    "₱": "PHP",
    "₫": "VND",
    "฿": "THB",
    "₴": "UAH",
    "₦": "NGN",
    "₪": "ILS",
    "₵": "GHS",
    "₸": "KZT",
}

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


def _extract_price_and_currency(
    raw_value: Any,
    default_currency: Optional[str] = None,
) -> Tuple[Optional[float], Optional[str]]:
    if raw_value is None:
        return None, None

    if isinstance(raw_value, (int, float)):
        return float(raw_value), default_currency

    text = str(raw_value).strip()
    if not text:
        return None, None

    currency: Optional[str] = default_currency

    for symbol, iso in CURRENCY_SYMBOLS.items():
        if symbol in text:
            currency = iso
            text = text.replace(symbol, "").strip()
            break

    iso_match = re.search(r'\b([A-Z]{3})\b', text)
    if iso_match and iso_match.group(1) in ISO_CURRENCIES:
        currency = iso_match.group(1)
        text = text.replace(iso_match.group(1), "").strip()

    text = text.replace(",", "").strip()

    price_match = re.search(r'(\d+(?:\.\d+)?)', text)
    if price_match:
        try:
            price = float(price_match.group(1))
            return price, currency
        except Exception:
            pass

    return None, currency


def normalize_price(
    raw_activity_price: Any,
    raw_origin_price: Any,
    raw_currency: Any,
) -> Dict[str, Any]:
    activity_price, activity_currency = _extract_price_and_currency(
        raw_activity_price, raw_currency
    )
    origin_price, origin_currency = _extract_price_and_currency(
        raw_origin_price, raw_currency
    )

    currency = activity_currency or origin_currency or raw_currency
    if isinstance(currency, str):
        currency = currency.strip().upper()
        if len(currency) == 3 and currency in ISO_CURRENCIES:
            pass
        else:
            for symbol, iso in CURRENCY_SYMBOLS.items():
                if currency == symbol:
                    currency = iso
                    break

    if origin_price is None and activity_price is not None:
        origin_price = activity_price

    if activity_price is None and origin_price is not None:
        activity_price = origin_price

    return {
        "source_activity_price": activity_price,
        "source_origin_price": origin_price,
        "source_price_currency": currency if isinstance(currency, str) and len(currency) == 3 else None,
    }


def get_effective_price(
    product: Dict[str, Any],
    price_fields: Optional[List[str]] = None,
) -> Optional[float]:
    fields = price_fields or DEFAULT_EFFECTIVE_PRICE_FIELDS
    for field in fields:
        value = product.get(field)
        if _is_numeric(value):
            return _to_float(value)
    return None


def project_sku_props(
    sku: Dict[str, Any],
    projection_mode: str = "all",
    projection_props: Optional[List[str]] = None,
) -> Dict[str, Any]:
    sku_props = dict(sku.get("sku_props") or {})

    if projection_mode == "all":
        return sku_props

    if projection_mode == "none":
        return {}

    if projection_mode == "include" and projection_props:
        return {k: v for k, v in sku_props.items() if k in projection_props}

    if projection_mode == "exclude" and projection_props:
        return {k: v for k, v in sku_props.items() if k not in projection_props}

    return sku_props


def select_default_sku(
    skus: List[Dict[str, Any]],
    price_fields: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    if not skus:
        return None

    active_skus = [sku for sku in skus if sku.get("status", 1) == 1]
    candidates = active_skus or skus

    if not candidates:
        return None

    def sort_key(sku: Dict[str, Any]) -> Tuple[int, float]:
        status = 1 if sku.get("status", 1) == 1 else 0
        price = get_effective_price(sku, price_fields) or float("inf")
        return (status, price)

    sorted_skus = sorted(candidates, key=sort_key, reverse=True)
    return sorted_skus[0]


def collapse_single_empty_props_skus(
    skus: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    if len(skus) <= 1:
        return skus

    empty_props_skus: List[Dict[str, Any]] = []
    other_skus: List[Dict[str, Any]] = []

    for sku in skus:
        sku_props = sku.get("sku_props") or {}
        if not sku_props or all(v is None or v == "" for v in sku_props.values()):
            empty_props_skus.append(sku)
        else:
            other_skus.append(sku)

    if len(empty_props_skus) <= 1:
        return skus

    base = dict(empty_props_skus[0])
    prices_seen = set()
    for sku in empty_props_skus:
        price = get_effective_price(sku)
        if price is not None:
            prices_seen.add(price)

    if len(prices_seen) <= 1:
        return [base, *other_skus]

    return skus


def postprocess_raw_product(
    raw_product: Dict[str, Any],
    *,
    projection_mode: str = "all",
    projection_props: Optional[List[str]] = None,
    price_fields: Optional[List[str]] = None,
    collapse_empty_skus: bool = True,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {}

    direct_fields = [
        "source_url",
        "source_item_name",
        "source_pics",
        "descriptions",
        "props",
        "source_score",
        "source_cmms",
        "not_detail",
        "status",
    ]
    for field in direct_fields:
        if field in raw_product:
            result[field] = raw_product[field]

    raw_activity = raw_product.get("source_activity_price")
    raw_origin = raw_product.get("source_origin_price")
    raw_currency = raw_product.get("source_price_currency")
    normalized = normalize_price(raw_activity, raw_origin, raw_currency)
    result.update(normalized)

    raw_skus = raw_product.get("skus") or []
    processed_skus: List[Dict[str, Any]] = []
    for raw_sku in raw_skus:
        sku: Dict[str, Any] = {}
        sku_direct = [
            "source_pics",
            "status",
            "sku_id",
        ]
        for field in sku_direct:
            if field in raw_sku:
                sku[field] = raw_sku[field]

        sku_raw_activity = raw_sku.get("source_activity_price")
        sku_raw_origin = raw_sku.get("source_origin_price")
        sku_raw_currency = raw_sku.get("source_price_currency") or result.get("source_price_currency")
        sku_normalized = normalize_price(sku_raw_activity, sku_raw_origin, sku_raw_currency)
        sku.update(sku_normalized)

        sku["sku_props"] = project_sku_props(
            raw_sku,
            projection_mode=projection_mode,
            projection_props=projection_props,
        )
        processed_skus.append(sku)

    if collapse_empty_skus:
        processed_skus = collapse_single_empty_props_skus(processed_skus)

    result["skus"] = processed_skus

    default_sku = select_default_sku(processed_skus, price_fields)
    if default_sku:
        result["default_sku_index"] = processed_skus.index(default_sku)
        effective_price = get_effective_price(default_sku, price_fields)
        if effective_price is not None:
            result["effective_price"] = effective_price

    result["_projection_mode"] = projection_mode
    result["_projection_props"] = projection_props or []

    return result


def postprocess_file(
    input_path: Path,
    output_path: Optional[Path] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    raw = json.loads(input_path.read_text(encoding="utf-8"))
    processed = postprocess_raw_product(raw, **kwargs)
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(processed, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    return processed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stage1 raw product post-processing")
    parser.add_argument("--input", required=True, help="Input raw product JSON file")
    parser.add_argument("--output", help="Output processed product JSON file")
    parser.add_argument(
        "--projection-mode",
        default="all",
        choices=["all", "none", "include", "exclude"],
        help="SKU props projection mode (default: all)",
    )
    parser.add_argument(
        "--projection-prop",
        action="append",
        dest="projection_props",
        help="SKU prop to include/exclude (repeatable)",
    )
    parser.add_argument(
        "--price-field",
        action="append",
        dest="price_fields",
        help="Price field for effective price (repeatable, priority order)",
    )
    parser.add_argument(
        "--no-collapse-empty-skus",
        action="store_true",
        help="Disable collapsing of empty-props SKUs",
    )
    return parser


def main(argv: Sequence[str] = ()) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    input_path = Path(args.input).resolve()
    if not input_path.exists():
        print(f"Input file not found: {input_path}", file=sys.stderr)
        return 2

    output_path = Path(args.output).resolve() if args.output else None

    try:
        result = postprocess_file(
            input_path,
            output_path,
            projection_mode=args.projection_mode,
            projection_props=args.projection_props,
            price_fields=args.price_fields,
            collapse_empty_skus=not args.no_collapse_empty_skus,
        )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if not output_path:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"Processed product written to {output_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
