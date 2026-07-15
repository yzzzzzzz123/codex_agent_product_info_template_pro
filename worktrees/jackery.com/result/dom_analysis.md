# Jackery Solar Generator 5000 Plus — DOM analysis

## Scope and access

- `input_site`: `jackery.com`
- `effective_origin`: `https://www.jackery.com`
- `commerce_origin`: `https://www.jackery.com`
- `source_from`: static HTML, browser-rendered HTML, and the live Shopify product endpoint
- Outer PDP returned HTTP 200 through `curl_cffi` with a Chrome impersonation and contains the complete buybox, variant controls, JSON-LD, and specifications.
- Inner endpoint: `https://www.jackery.com/products/jackery-solar-generator-5000-plus.js` returned HTTP 200 and exposes the authoritative product, image, option, variant, price, SKU, and availability data.
- Browser evidence: repo-local Playwright loaded the real PDP at HTTP 200; `raw_html/rendered_page.html`, `raw_html/jackery_5000_plus_snapshot.json`, and `raw_html/jackery_5000_plus_screenshot.png` preserve the rendered state.

## Core anchors

- Title: `//h1[normalize-space()]`, cross-checked with the Shopify product JSON `title` and ProductGroup JSON-LD `name`.
- Product ID: ProductGroup JSON-LD `productGroupID` and product JSON `id` (`7308401999959`).
- Main gallery: Shopify product JSON `images[]`; protocol-relative URLs are normalized to `https:`.
- Description: Shopify product JSON `description`; each heading and following paragraph is preserved as a separate structured text block.
- Brand: product JSON `vendor` and ProductGroup JSON-LD `brand.name`.
- Specifications: the non-hidden `div.pdp-specs-v5-specs-variant[variant_id] .specs-item`; four stable base-unit specs are retained at SPU level.
- Default selected variant: `input.product-variant-id[name="id"]@value`, cross-checked with `input[type="radio"][name="Select Options"][checked]@data-id`.
- Variant matrix: live product JSON `options[]` plus `variants[]`; static fallback is `script#selected-variant`.
- Variant image: `variants[].featured_image.src`, cross-checked against the main gallery image whose `variant_ids` contains the variant ID.
- Availability: `variants[].available`; `true -> status=1`, `false -> status=0`.

## Price semantics

- `visible_activity_price`: the checked `Select Options` radio label shows `$4,299.00`.
- `visible_origin_price`: the same checked option shows the struck/list price `$5,699.00`.
- `visible_price_mode`: list plus sale/current price.
- Payload fields: Shopify `variants[].price` and `variants[].compare_at_price`, both in cents.
- Chosen rule: exact selected-variant payload price is authoritative; divide cents by 100. If `compare_at_price` is missing, use the activity price as origin price for the no-discount SKU.
- Currency rule: Shopify shop JSON declares `USD`; ProductGroup offers use `priceCurrency=USD`; the visible buybox uses `$` on the US storefront.
- Discount sanity check: default variant `(5699 - 4299) / 5699 = 24.57%`, consistent with the page's approximately 24% promotion.
- Price priority: exact Shopify variant payload > ProductGroup JSON-LD offer > visible buybox DOM.
- Market lock: US storefront, country `US`, currency `USD`.

## Variant handling

- `sku_topology`: `variant_sku`.
- Option name source: `product.options[0].name` (`Select Options`).
- Option value source: `variants[].option1` / `variants[].title`.
- SKU map source: Shopify product endpoint `variants[]`, with five page-evidenced variants.
- SKU ID source: `variants[].id`; merchant code source: `variants[].sku`.
- `sku_props`: `Select Options -> variant.option1` and `SKU -> variant.sku`.
- Current dimension evidence: checked radio and hidden `input[name="id"]` both identify variant `41349431033943`.
- Visible selector coverage: five option values in product JSON and five variants in `script#selected-variant` / ProductGroup JSON-LD.
- Stock rule: `available=false` or a genuinely visible disabled/sold-out option maps to `status=0`; all five captured variants are currently available. Each option contains a CSS-hidden `span.visually-hidden` with the generic text `Sold Out`, but the radios are enabled, Shopify reports `available=true`, and the visible CTA says `Add to cart`, so that hidden accessibility/template text is not an out-of-stock signal.
- Variant images: one authoritative featured image per SKU from `featured_image.src`; SPU gallery retains all twelve product images.

## Top-level projection

For a URL without `?variant=`, the page selects variant `41349431033943` (`Explorer 5000 Plus + SolarSaga 500 X x 2`). Top-level price, status, `Select Options`, and `SKU` therefore project from that variant. For a URL with `?variant=<id>`, Stage3 must project from the matching variant; it must not choose the minimum- or maximum-price SKU.

## Description handling

The product description consists of six visible heading/paragraph pairs. Delivery uses safe plain text with a newline between each heading and paragraph. The trailing self-referential “Learn more” link is omitted.

## Review stats

Basic mode is active. Although the page exposes Judge.me aggregate data, `source_score` and `source_cmms` are deliberately `None` under the task contract.

## Reconciliation checks

1. Default variant: visible buybox `$4,299.00 / $5,699.00` = `script#selected-variant` `429900 / 569900` cents = ProductGroup offer `4299 / 5699` USD.
2. Variant count and identity: five checked-option candidates in page data = five Shopify endpoint variants = five ProductGroup `hasVariant` entries.
3. Availability: page options are enabled and the endpoint reports all five `available=true`; top-level and SKU statuses are `1`.
4. Browser state: the rendered snapshot records checked radio `41349431033943`, hidden product-form variant `41349431033943`, five enabled option radios, and an enabled `Add to cart` button.

## Risks

- Promotions are time-sensitive; Stage3 reads live variant values rather than embedding the captured prices.
- The standalone product telemetry advertises the minimum variant price (`$2,879`) in some marketing scripts, so it must not override the checked buybox variant (`$4,299`).
- Shopify's product endpoint is preferred for per-SKU images because the static `script#selected-variant` payload omits `featured_image` in this capture.
