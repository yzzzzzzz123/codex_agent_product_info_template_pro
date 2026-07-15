# Evidence log

- 2026-07-15: direct web open reached the real PDP.
- 2026-07-15: `curl_cffi` static fetch returned HTTP 200, 2,602,392 bytes; saved as `raw_html/static_page.html` with request/response metadata.
- 2026-07-15: Shopify product endpoint returned HTTP 200, 17,496 bytes; saved as `raw_html/product_js_response.json` with request metadata.
- Stage1 confirms one product, twelve gallery images, five variants, USD pricing, and a selected default variant of `41349431033943`.
- Review extraction is disabled by task type; review fields remain `None`.
- 2026-07-15: repo-local Playwright library capture reached the real PDP at HTTP 200 and wrote `raw_html/rendered_page.html`, `raw_html/jackery_5000_plus_snapshot.json`, and `raw_html/jackery_5000_plus_screenshot.png`.
- Rendered evidence confirms five enabled option radios, checked/default variant `41349431033943`, visible `$4,299.00 / $5,699.00`, and an enabled `Add to cart` CTA. Hidden per-option `span.visually-hidden` text `Sold Out` is template/accessibility text and is not treated as stock evidence.
- Stage2 live extraction produced five SKUs and projected the base URL from variant `41349431033943`; a query projection check for variant `41389393444951` produced `$8,500 / $8,500`, SKU `40-5050-USA112`, and status `1`.
