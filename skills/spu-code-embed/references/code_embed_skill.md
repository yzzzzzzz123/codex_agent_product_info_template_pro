# Code Embed Skill Reference

## Overview

This skill converts Stage2 extractor logic (`extract_{site_domain}.py`) into embedded runtime code (`final_code.py`) that can be executed by Goldrush.

## Purpose

Use this skill after Stage2 has produced a stable `extract_{site_domain}.py` and per-SPU evaluation results.

The skill performs these steps:

1. Read the embedding requirements from `final_code_change.md`
2. Generate `result/script_gen/final_code.py`
3. Keep only the required embedded output contract fields
4. Validate the result with `final_code_check.py`
5. Record the final adaptation notes for the site

## Required Inputs

- `extract_{site_domain}.py` - Stage2 extractor script
- Current batch `detail_url` list, typically `input/{site_domain}_uris.txt`
- `final_code_change.md` - Embedding requirements document

## Hard Rules

1. Never modify Goldrush source code unless the user explicitly asks for source edits.
2. Do not modify the checker logic during embedding.
3. `final_code.py` must be fully self-contained. Any required function, method, class, constant, configuration, or helper logic that would otherwise come from another file must be re-created explicitly within `final_code.py`.
4. If the site is live-parseable, validate with the live checker:
   ```bash
   python final_code_check.py \
     --detail_url_file input/{site_domain}_urls.txt \
     --clear_rendered_html \
     --continue_on_error
   ```
5. If the site is blocked but Stage1 evidence is sufficient, write an offline-capable `final_code.py` and validate with `final_code_check_offline.py`.
6. Validate the current batch of detail URLs before handoff.
7. If a transient network error happens during validation, retry once and record that in the change notes.
8. If Stage2 schema values need adaptation to satisfy the checker contract, keep that adaptation local to Stage3; do not rewrite Stage2 GT semantics.
9. Treat any of the following as an automatic failure that must be removed before handoff: "FIXTURES", branching on full sample URLs, returning embedded sample JSON blobs, or reading `stage1_gt.json` / `stage1_raw_gt.json` as the prediction source.
10. If the site exposes a visible selected variant, `final_code.py` top-level `props` / `source_origin_price` / `source_activity_price` / `status` must project from that selected combination; do not silently fall back to the lowest-price SKU.
11. Description extraction must preserve the visible block structure when the PDP has rich text, bullet lists, or tables; do not reduce the whole description area to a single flattened line.
12. Stage3 has an embedded delivery contract that is stricter than the Stage2 target schema. Do not carry over Stage2's single-empty-props SKU collapse into `final_code.py`.
13. `script_res["skus"][].sku_props` must be a dict. If a SKU has no meaningful attributes, use a stable page-evidenced business identifier as a fallback property.
14. `descriptions` should be safe text by default: preserve block structure, then strip HTML tags. Only keep raw HTML if explicitly required.

## Execution Checklist

1. Read `final_code_change.md`.
2. Inspect `extract_{site_domain}.py` and isolate the minimal download + parse logic.
3. Write `final_code.py` using the expected structure.
4. Copy the embedding rule file, both checkers, and `final_render_html.py` into `result/script_gen/`.
5. Validate the current batch once using live or offline checker.
6. During validation, inspect whether the top-level projection matches the current selected variant, whether `skus[]` covers the page-evidenced SKU units, and whether `descriptions` preserves visible structure.
7. Save any necessary explanation in `final_code_change.md`.

## Output Contract

Primary answer must contain `final_code.py` source.

`final_code.py` must end with exactly one runtime contract output shape:

```python
script_res = {
    "source_url": ...,
    "source_item_name": ...,
    "source_pics": [...],
    "descriptions": [...],
    "source_origin_price": ...,
    "source_activity_price": ...,
    "source_price_currency": ...,
    "props": {...},
    "status": ...,
    "skus": [
        {
            "sku_props": {...},
            "source_origin_price": ...,
            "source_activity_price": ...,
            "source_price_currency": ...,
            "source_pics": [...],
            "status": ...,
        },
        ...
    ],
    "source_score": None,
    "source_cmms": None,
}
```

Missing fields must be `None`, not absent.

## Runtime Model

Goldrush executes `final_code.py` with `exec(...)` and reads only `script_res`.

`final_code.py` may assume only these runtime symbols:

- `detail_url`: the PDP URL string
- `rsp`: the response object from `common_request(...)`
- `common_request`: the Goldrush request function

## Scripts

- `scripts/final_code_check.py`: Live checker that runs `final_code.py` against real URLs
- `scripts/final_code_check_offline.py`: Offline checker that runs `final_code.py` against Stage1 captured evidence
- `scripts/final_render_html.py`: Renders the final SPU/SKU HTML for spot-check

## References

- Main SKILL.md: `../SKILL.md`
- final_code Change Guide: `final_code_change.md`