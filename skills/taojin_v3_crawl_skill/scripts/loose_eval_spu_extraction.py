"""Loose evaluation of SPU/SKU extraction against ground truth.

Uses relaxed matching rules compared to eval_spu_extraction:
- Price: within 5% tolerance
- source_item_name: substring match after normalization
- descriptions: partial overlap counts as partial match
- spu_pics / sku_pics: path-level match (ignore query params and domain)
- review: number-only comparison
- sku_id: still exact match
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse


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

PRICE_TOLERANCE_RATIO: float = 0.05


def _norm_str(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip().lower()


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
        s = re.sub(r"[^\d.\-]", "", s)
        if not s:
            return None
        try:
            return float(s)
        except (TypeError, ValueError):
            return None


def _url_path_only(url: str) -> str:
    if not url:
        return ""
    if "://" not in url:
        return url.strip().lower()
    try:
        parsed = urlparse(url)
        return (parsed.path or "").strip().lower()
    except Exception:
        return url.strip().lower()


def _norm_pic_list(v: Any) -> List[str]:
    items = _norm_list(v)
    return [_url_path_only(x) for x in items if x]


def _norm_text(s: str) -> str:
    s = s.lower()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[^\w\s\u4e00-\u9fff]", "", s)
    return s.strip()


def _token_set(s: str) -> set:
    if not s:
        return set()
    normalized = _norm_text(s)
    tokens = re.split(r"[\s,;，；、]+", normalized)
    return {t for t in tokens if t}


def _price_loose_match(gt: Any, pred: Any) -> Tuple[int, int, int]:
    gt_f = _norm_float(gt)
    pred_f = _norm_float(pred)
    has_gt = gt_f is not None
    has_pred = pred_f is not None
    if has_gt and has_pred:
        if gt_f == 0 and pred_f == 0:
            return 1, 0, 0
        base = max(abs(gt_f), abs(pred_f))
        if base == 0:
            return 1, 0, 0
        diff = abs(gt_f - pred_f)
        if diff / base <= PRICE_TOLERANCE_RATIO:
            return 1, 0, 0
        return 0, 1, 1
    if has_gt and not has_pred:
        return 0, 0, 1
    if not has_gt and has_pred:
        return 0, 1, 0
    return 0, 0, 0


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


def _item_name_loose_match(gt: Any, pred: Any) -> Tuple[int, int, int]:
    gt_s = _norm_str(gt)
    pred_s = _norm_str(pred)
    has_gt = bool(gt_s)
    has_pred = bool(pred_s)
    if has_gt and has_pred:
        gt_norm = _norm_text(gt_s)
        pred_norm = _norm_text(pred_s)
        if not gt_norm or not pred_norm:
            return 0, 1, 1
        if gt_norm == pred_norm:
            return 1, 0, 0
        if gt_norm in pred_norm or pred_norm in gt_norm:
            return 1, 0, 0
        gt_tokens = _token_set(gt_s)
        pred_tokens = _token_set(pred_s)
        if not gt_tokens or not pred_tokens:
            return 0, 1, 1
        overlap = len(gt_tokens & pred_tokens)
        gt_ratio = overlap / len(gt_tokens)
        pred_ratio = overlap / len(pred_tokens)
        if gt_ratio >= 0.6 and pred_ratio >= 0.6:
            return 1, 0, 0
        return 0, 1, 1
    if has_gt and not has_pred:
        return 0, 0, 1
    if not has_gt and has_pred:
        return 0, 1, 0
    return 0, 0, 0


def _review_loose_match(gt: Any, pred: Any) -> Tuple[int, int, int]:
    gt_num = _norm_float(gt)
    pred_num = _norm_float(pred)
    has_gt = gt_num is not None
    has_pred = pred_num is not None
    if has_gt and has_pred:
        if gt_num == pred_num:
            return 1, 0, 0
        base = max(abs(gt_num), abs(pred_num))
        if base == 0:
            return 1, 0, 0
        diff = abs(gt_num - pred_num)
        if diff / base <= 0.1:
            return 1, 0, 0
        return 0, 1, 1
    if has_gt and not has_pred:
        return 0, 0, 1
    if not has_gt and has_pred:
        return 0, 1, 0
    return 0, 0, 0


def _list_loose_match(gt_list: List[str], pred_list: List[str]) -> Tuple[int, int, int]:
    if not gt_list and not pred_list:
        return 0, 0, 0
    gt_norm = [_norm_text(x) for x in gt_list if _norm_text(x)]
    pred_norm = [_norm_text(x) for x in pred_list if _norm_text(x)]
    if not gt_norm and not pred_norm:
        return 0, 0, 0
    matched_pred = set()
    matched_gt = set()
    for i, g in enumerate(gt_norm):
        for j, p in enumerate(pred_norm):
            if j in matched_pred:
                continue
            if g == p:
                matched_gt.add(i)
                matched_pred.add(j)
                break
    for i, g in enumerate(gt_norm):
        if i in matched_gt:
            continue
        for j, p in enumerate(pred_norm):
            if j in matched_pred:
                continue
            if g in p or p in g:
                matched_gt.add(i)
                matched_pred.add(j)
                break
    tp = len(matched_gt)
    fp = len(pred_norm) - len(matched_pred)
    fn = len(gt_norm) - len(matched_gt)
    return tp, fp, fn


def _descriptions_loose_match(gt: Any, pred: Any) -> Tuple[int, int, int]:
    gt_list = _norm_list(gt)
    pred_list = _norm_list(pred)
    return _list_loose_match(gt_list, pred_list)


def _pics_loose_match(gt: Any, pred: Any) -> Tuple[int, int, int]:
    gt_list = _norm_pic_list(gt)
    pred_list = _norm_pic_list(pred)
    if not gt_list and not pred_list:
        return 0, 0, 0
    matched_pred = set()
    matched_gt = set()
    for i, g in enumerate(gt_list):
        for j, p in enumerate(pred_list):
            if j in matched_pred:
                continue
            if g == p:
                matched_gt.add(i)
                matched_pred.add(j)
                break
    for i, g in enumerate(gt_list):
        if i in matched_gt:
            continue
        for j, p in enumerate(pred_list):
            if j in matched_pred:
                continue
            g_base = Path(g).name
            p_base = Path(p).name
            if g_base and p_base and g_base == p_base:
                matched_gt.add(i)
                matched_pred.add(j)
                break
    tp = len(matched_gt)
    fp = len(pred_list) - len(matched_pred)
    fn = len(gt_list) - len(matched_gt)
    return tp, fp, fn


def _spu_pics_loose_match(gt: Any, pred: Any) -> Tuple[int, int, int]:
    return _pics_loose_match(gt, pred)


def _sku_pics_loose_match(gt: Any, pred: Any) -> Tuple[int, int, int]:
    return _pics_loose_match(gt, pred)


def _sku_id_loose_match(gt: Any, pred: Any) -> Tuple[int, int, int]:
    return _exact_match(gt, pred)


DIM_MATCHERS = {
    "sku_id": _sku_id_loose_match,
    "price": _price_loose_match,
    "source_item_name": _item_name_loose_match,
    "review": _review_loose_match,
    "descriptions": _descriptions_loose_match,
    "spu_pics": _spu_pics_loose_match,
    "sku_pics": _sku_pics_loose_match,
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
    parser = argparse.ArgumentParser(description="Loose evaluation of SPU/SKU extraction")
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
