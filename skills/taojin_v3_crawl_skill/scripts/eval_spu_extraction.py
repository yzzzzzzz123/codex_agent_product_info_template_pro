"""Evaluate SPU/SKU extraction quality against ground truth.

Computes precision, recall, and F1 scores across multiple dimensions:
sku_id, price, source_item_name, review, descriptions, spu_pics, sku_pics.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


DIM_WEIGHTS: Dict[str, float] = {
    "sku_id": 2.0,
    "price": 2.0,
    "source_item_name": 1.0,
    "review": 1.0,
    "descriptions": 1.0,
    "spu_pics": 1.0,
    "sku_pics": 2.0,
}

TOTAL_WEIGHT: float = sum(DIM_WEIGHTS.values())


def _norm_str(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip()


def _norm_list(v: Any) -> List[str]:
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    return [str(v).strip()] if str(v).strip() else []


def _norm_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        s = str(v).strip()
        if not s:
            return None
        s = s.replace(",", "").replace("$", "").replace("￥", "").replace("€", "").replace("£", "")
        s = s.strip()
        if not s:
            return None
        try:
            return float(s)
        except (TypeError, ValueError):
            return None


def _set_match(gt_list: List[str], pred_list: List[str]) -> Tuple[int, int, int]:
    gt_set = set(gt_list)
    pred_set = set(pred_list)
    tp = len(gt_set & pred_set)
    fp = len(pred_set - gt_set)
    fn = len(gt_set - pred_set)
    return tp, fp, fn


def _exact_match(gt: Any, pred: Any) -> Tuple[int, int, int]:
    gt_s = _norm_str(gt)
    pred_s = _norm_str(pred)
    has_gt = bool(gt_s)
    has_pred = bool(pred_s)
    if has_gt and has_pred:
        if gt_s == pred_s:
            return 1, 0, 0
        return 0, 1, 1
    if has_gt and not has_pred:
        return 0, 0, 1
    if not has_gt and has_pred:
        return 0, 1, 0
    return 0, 0, 0


def _price_match(gt: Any, pred: Any) -> Tuple[int, int, int]:
    gt_f = _norm_float(gt)
    pred_f = _norm_float(pred)
    has_gt = gt_f is not None
    has_pred = pred_f is not None
    if has_gt and has_pred:
        if abs(gt_f - pred_f) < 1e-6:
            return 1, 0, 0
        return 0, 1, 1
    if has_gt and not has_pred:
        return 0, 0, 1
    if not has_gt and has_pred:
        return 0, 1, 0
    return 0, 0, 0


def _list_dim_match(gt: Any, pred: Any) -> Tuple[int, int, int]:
    gt_list = _norm_list(gt)
    pred_list = _norm_list(pred)
    return _set_match(gt_list, pred_list)


def _sku_id_match(gt: Any, pred: Any) -> Tuple[int, int, int]:
    return _exact_match(gt, pred)


def _source_item_name_match(gt: Any, pred: Any) -> Tuple[int, int, int]:
    return _exact_match(gt, pred)


def _review_match(gt: Any, pred: Any) -> Tuple[int, int, int]:
    return _exact_match(gt, pred)


def _descriptions_match(gt: Any, pred: Any) -> Tuple[int, int, int]:
    return _list_dim_match(gt, pred)


def _spu_pics_match(gt: Any, pred: Any) -> Tuple[int, int, int]:
    return _list_dim_match(gt, pred)


def _sku_pics_match(gt: Any, pred: Any) -> Tuple[int, int, int]:
    return _list_dim_match(gt, pred)


DIM_MATCHERS = {
    "sku_id": _sku_id_match,
    "price": _price_match,
    "source_item_name": _source_item_name_match,
    "review": _review_match,
    "descriptions": _descriptions_match,
    "spu_pics": _spu_pics_match,
    "sku_pics": _sku_pics_match,
}


def _prf(tp: int, fp: int, fn: int) -> Tuple[float, float, float]:
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    return precision, recall, f1


def evaluate_sku(gt_sku: Dict[str, Any], pred_sku: Dict[str, Any]) -> Dict[str, Any]:
    dim_scores: Dict[str, Dict[str, float]] = {}
    total_weighted_tp = 0.0
    total_weighted_fp = 0.0
    total_weighted_fn = 0.0

    for dim, matcher in DIM_MATCHERS.items():
        gt_val = gt_sku.get(dim)
        pred_val = pred_sku.get(dim)
        tp, fp, fn = matcher(gt_val, pred_val)
        p, r, f = _prf(tp, fp, fn)
        w = DIM_WEIGHTS[dim]
        dim_scores[dim] = {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": p,
            "recall": r,
            "f1": f,
            "weight": w,
        }
        total_weighted_tp += tp * w
        total_weighted_fp += fp * w
        total_weighted_fn += fn * w

    overall_p, overall_r, overall_f = _prf(
        int(round(total_weighted_tp)),
        int(round(total_weighted_fp)),
        int(round(total_weighted_fn)),
    )

    return {
        "dimensions": dim_scores,
        "overall": {
            "precision": overall_p,
            "recall": overall_r,
            "f1": overall_f,
            "total_weight": TOTAL_WEIGHT,
            "weighted_tp": total_weighted_tp,
            "weighted_fp": total_weighted_fp,
            "weighted_fn": total_weighted_fn,
        },
    }


def evaluate_dataset(
    gt_list: List[Dict[str, Any]],
    pred_list: List[Dict[str, Any]],
    index: Optional[int] = None,
) -> Dict[str, Any]:
    if index is not None:
        if index < 0 or index >= len(gt_list) or index >= len(pred_list):
            raise IndexError(f"Index {index} out of range")
        gt_list = [gt_list[index]]
        pred_list = [pred_list[index]]

    per_sku: List[Dict[str, Any]] = []
    agg_dim: Dict[str, Dict[str, int]] = {
        d: {"tp": 0, "fp": 0, "fn": 0} for d in DIM_MATCHERS
    }

    n = min(len(gt_list), len(pred_list))
    for i in range(n):
        gt = gt_list[i] if i < len(gt_list) else {}
        pred = pred_list[i] if i < len(pred_list) else {}
        sku_result = evaluate_sku(gt, pred)
        per_sku.append({"index": i, **sku_result})
        for dim, scores in sku_result["dimensions"].items():
            agg_dim[dim]["tp"] += scores["tp"]
            agg_dim[dim]["fp"] += scores["fp"]
            agg_dim[dim]["fn"] += scores["fn"]

    dim_summary: Dict[str, Dict[str, float]] = {}
    total_weighted_tp = 0.0
    total_weighted_fp = 0.0
    total_weighted_fn = 0.0
    for dim, counts in agg_dim.items():
        p, r, f = _prf(counts["tp"], counts["fp"], counts["fn"])
        w = DIM_WEIGHTS[dim]
        dim_summary[dim] = {
            "precision": p,
            "recall": r,
            "f1": f,
            "weight": w,
            "tp": counts["tp"],
            "fp": counts["fp"],
            "fn": counts["fn"],
        }
        total_weighted_tp += counts["tp"] * w
        total_weighted_fp += counts["fp"] * w
        total_weighted_fn += counts["fn"] * w

    overall_p, overall_r, overall_f = _prf(
        int(round(total_weighted_tp)),
        int(round(total_weighted_fp)),
        int(round(total_weighted_fn)),
    )

    return {
        "n_samples": n,
        "overall": {
            "precision": overall_p,
            "recall": overall_r,
            "f1": overall_f,
            "total_weight": TOTAL_WEIGHT,
            "weighted_tp": total_weighted_tp,
            "weighted_fp": total_weighted_fp,
            "weighted_fn": total_weighted_fn,
        },
        "dimension_summary": dim_summary,
        "per_sku": per_sku,
    }


def _load_json(path: Path) -> List[Dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return [data]
    return data if isinstance(data, list) else []


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate SPU/SKU extraction")
    parser.add_argument("--gt", required=True, help="Ground truth JSON file")
    parser.add_argument("--pred", required=True, help="Prediction JSON file")
    parser.add_argument("--index", type=int, default=None, help="Evaluate only a specific index")
    args = parser.parse_args()

    gt_path = Path(args.gt).resolve()
    pred_path = Path(args.pred).resolve()

    if not gt_path.exists():
        print(f"GT file not found: {gt_path}", file=sys.stderr)
        return 2
    if not pred_path.exists():
        print(f"Pred file not found: {pred_path}", file=sys.stderr)
        return 2

    gt_list = _load_json(gt_path)
    pred_list = _load_json(pred_path)

    try:
        result = evaluate_dataset(gt_list, pred_list, index=args.index)
    except IndexError as e:
        print(str(e), file=sys.stderr)
        return 2

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
