# final_code.py change notes

## Scope

- Site: amazon.com
- PDP: https://www.amazon.com/Logitech-Wireless-Mouse-M185-Swift/dp/B004YAVF8I
- Task type: with_review_stats
- Stage3 output: result/script_gen/final_code.py

## Implementation

- Embedded a self-contained live HTML parser that only assumes `detail_url`, `rsp`, and `common_request`.
- Extracts title, Amazon media URLs, feature bullets, product tables/detail bullets, selected ASIN/color/style SKU props, price, currency, availability, and review score/count from the PDP HTML.
- Keeps one page-evidenced SKU for the selected Amazon variant. The SKU uses ASIN plus selected properties instead of standalone `sku_id` fields.
- Descriptions are emitted as safe text blocks, preserving the visible bullet/list structure without raw HTML.

## Validation

- Live checker passed:
  - Command: `python result/script_gen/final_code_check.py --final-code result/script_gen/final_code.py --detail-url https://www.amazon.com/Logitech-Wireless-Mouse-M185-Swift/dp/B004YAVF8I --output result/script_gen/script_res_live.json`
  - Result: `VALIDATION OK`
- Final spot-check HTML generated:
  - `result/script_gen/rendered_spu_skus_final.html`

## Notes

- The extractor remains live-parseable for the checked PDP and does not return fixture JSON.
- The worktree path bug was fixed at the orchestrator/tooling layer: default worktrees now live under project-root `worktrees/`, not the legacy output-based worktree folder.
