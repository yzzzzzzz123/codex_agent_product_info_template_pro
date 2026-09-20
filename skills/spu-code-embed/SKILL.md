---
name: "spu-code-embed"
description: "Stage3 SPU/SKU extraction skill used inside taojin_v3_crawl_skill. Converts extract_{site}.py into final embedded code and validates it with final_code_check.py."
---

# SPU Code Embed

## Purpose

Use this skill after Stage2 has produced a stable `extract_{site_domain}.py` and per-SPU evaluation results.

This skill is the final delivery step that converts the Stage2 extractor into embedded runtime code:

1. read the embedding requirements from `final_code_change.md`
2. generate `result/script_gen/final_code.py`
3. keep only the required embedded output contract fields
4. validate the result with `final_code_check.py`
5. record the final adaptation notes for the site

Invoke after Stage2 is complete and the extractor logic is stable.

Invoke when the task requires `final_code.py`, `final_code_check.py`, or "code embedding".

## Required inputs

- `extract_{site_domain}.py`
- the current batch `detail_url` list, typically `input/{site_domain}_uris.txt`
- `final_code_change.md`

## Hard Rules

1. Never modify Goldrush source code unless the user explicitly asks for source edits.
2. Do not modify the checker logic during embedding.
3. `final_code.py` must be fully self-contained. Direct or indirect dependency on any other local file is not allowed. Any required function, method, class, constant, configuration, or helper logic that would otherwise come from another file must be re-created explicitly within `final_code.py`. Access through `import`, path-based lookup, dynamic module loading, file reads, or any other external-file mechanism is strictly forbidden.
4. If the site is live-parseable, validate `final_code.py` with the live checker:
   ```
   python final_code_check.py \
     --detail_url_file input/{site_domain}_urls.txt \
     --clear_rendered_html \
     --continue_on_error
   ```
5. If the site is blocked but Stage1 evidence is sufficient, write an offline-capable `final_code.py` that parses Stage1 evidence through real logic and validate it with `final_code_check_offline.py`. The offline path is a fallback layered on top of the normal live path; only stop and report blocked when neither live access nor sufficient Stage1 evidence exists.
6. Validate the current batch of detail URLs before handoff. When the site is live-parseable, run `python final_code_check.py --detail_url_file input/{site_domain}_urls.txt --clear_rendered_html --continue_on_error` once. If the site is blocked but Stage1 evidence is sufficient, run `python final_code_check_offline.py --detail_url_file input/{site_domain}_urls.txt --clear_rendered_html --continue_on_error` once instead.
7. If a transient network error happens during validation, retry once and record that in the change notes.
8. If Stage2 schema values need adaptation to satisfy the checker contract, keep that adaptation local to Stage3; do not rewrite Stage2 GT semantics.
9. Treat any of the following as an automatic failure that must be removed before handoff: "FIXTURES", branching on full sample URLs, returning embedded sample JSON blobs, or reading `stage1_gt.json` / `stage1_raw_gt.json` as the prediction source.
10. If the site exposes a visible selected variant, `final_code.py` top-level `props` / `source_origin_price` / `source_activity_price` / `status` must project from that selected combination; do not silently fall back to the lowest-price SKU.
11. Description extraction in `final_code.py` must preserve the visible block structure when the PDP has rich text, bullet lists, or tables; do not reduce the whole description area to a single flattened line unless the page itself only exposes a single plain-text node.
12. Stage3 has an embedded delivery contract that is stricter than the Stage2 target schema. Do not carry over Stage2's single-empty-props SKU collapse into `final_code.py`: if live/offline evidence exposes SKU units such as `childSkus`, `skuList`, `variants`, or `offers`, output them under `script_res["skus"]`.
13. `script_res["skus"][].sku_props` must be a dict. If a SKU has no meaningful attributes, use a stable page-evidenced business identifier as a fallback property, such as `{"SKU": sku_id}` or a site-local label like `{"Código SKU": sku_id}`. Do not add standalone `sku_id`, `source_sku_id`, or `spu_id` fields.
14. `descriptions` should be safe text by default: preserve block structure by converting rich-text blocks, `<br>`, lists, and table rows into newlines or bullets, then strip HTML tags. Only keep raw HTML if the task explicitly requires rich text and the downstream renderer supports a safe tag whitelist.

## Execution checklist

1. Read `final_code_change.md`.
2. Inspect `extract_{site_domain}.py` and isolate the minimal download + parse logic.
3. Write `final_code.py` using the sample structure expected by `final_code_check.py` / `final_code_check_offline.py`, but ensure the data still comes from live parsing or from Stage1 raw evidence parsing rather than precomputed fixtures.
4. Copy the current embedding rule file, both checkers, and `final_render_html.py` into `result/script_gen/` if they are not already there.
5. Validate the current batch once: use the live checker with `--detail_url_file ... --clear_rendered_html --continue_on_error` when the site is accessible, or the offline checker with the same batch flags when Stage1 evidence is sufficient for blocked sites.
6. During validation, explicitly inspect whether the top-level projection matches the current selected variant, whether `skus[]` covers the page-evidenced SKU units, and whether `descriptions` preserves visible structure without leaking unsafe raw HTML tags.
7. Save any necessary explanation in `final_code_change.md`, including whether the site was live-parseable, API-parseable, or validated via offline evidence.

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

Do not assume any other runtime variable names.

## Scripts

- `scripts/final_code_check.py`: live checker that runs `final_code.py` against a real URL
- `scripts/final_code_check_offline.py`: offline checker that runs `final_code.py` against Stage1 captured evidence
- `scripts/final_render_html.py`: renders the final SPU/SKU HTML for spot-check

## References

- `references/final_code_change.md`

## When To Use

Use this skill when the user says things like:

- "generate final_code.py for https://example.com/products/..."
- "extract SPU/SKU for this PDP"
- "validate final_code.py against Stage1 evidence"
- "embed the extractor into final_code.py"

This skill is a single-execution kernel. It does not own a standalone delivery shell.
