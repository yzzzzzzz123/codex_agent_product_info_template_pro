# Jackery final-code adaptation

## Runtime strategy

- The extractor is live/API parseable. It derives the Shopify `products/<handle>.js` endpoint from `detail_url`, fetches current product/variant data, and parses the outer PDP for the checked variant and selected specification block.
- `curl_cffi.requests` with Chrome impersonation is the primary request path for this site. `common_request` remains the fallback. This is necessary because the checker's plain `requests` path returned HTTP 429 with `local_rate_limited`, while the browser-shaped request returned the real HTTP 200 product data.
- No captured JSON, sample URL branch, fixture, or local file is read by `final_code.py`.

## Contract adaptations

- The base URL projects top-level price, status, `Select Options`, and merchant `SKU` from checked/default variant `41349431033943`: origin `$5,699`, activity `$4,299`, status `1`.
- A valid `?variant=<id>` query has priority over the page default. An offline replay of final-code logic for `?variant=41389393444951` projected `$8,500 / $8,500`, `40-5050-USA112`, and status `1` while retaining all five SKUs.
- All five Shopify variants are emitted. Variant IDs are used only internally for selection and DOM mapping; output SKU objects have no standalone `sku_id`, `source_sku_id`, or `spu_id`. Merchant SKU is stored inside `sku_props`.
- Availability comes from `variants[].available`. Hidden generic `span.visually-hidden` text `Sold Out` is ignored because the radios are enabled and the visible CTA is `Add to cart`.
- Description headings and paragraphs remain six separate safe-text blocks, with a newline between each heading and paragraph.
- Basic task mode is enforced: `source_score` and `source_cmms` are both `None`.

## Validation

- Python compilation: passed for `extract_jackery_com.py` and `final_code.py`.
- Stage2 self-test core checks: passed with 0 errors and 0 warnings in the review-disabled compatibility case.
- The unmodified Stage2 self-test script does not read `self_test_config.json` and incorrectly rejects contract-correct null basic-mode review fields. The exact-delivery run is preserved as `self_test_result_contract_null_bug.json`; all non-review checks passed, and the only two errors were `source_score is not numeric: None` and `source_cmms is not an int: None`.
- Live checker attempt 1: failed because plain `requests` received transient HTTP 429 `local_rate_limited`; preserved in `final_code_check_live_attempt1.log`.
- Allowed single live-check retry: passed (`VALIDATION OK`) after adding the site-required `curl_cffi` request path; output is preserved in `final_code_check_live.log` and `script_res.json`.
- Final HTML rendering: passed and wrote `rendered_spu_skus_final.html`.
- Copied checker/renderer files remain byte-identical to the skill sources.

## Residual risk

- Prices and availability are promotional/live values and can change. The delivered code reads them at runtime instead of embedding captured values.
