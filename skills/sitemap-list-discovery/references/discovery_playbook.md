# Discovery Playbook

## Site Normalization

Before any fetch:

1. Strip trailing slash from the user-given site.
2. Lowercase the host.
3. If the user gave a full URL, extract the host only for the `input_site` field.
4. Keep the original user input as the delivery boundary unless a direct redirect proves otherwise.

## Sitemap Prioritization

When the site has multiple sitemap sources, rank them:

1. `robots.txt` declared sitemaps (highest priority)
2. `/sitemap.xml`
3. `/sitemap_index.xml`
4. `/sitemap-index.xml`
5. `/xml/sitemap.xml`
6. homepage-discovered sitemap links
7. category-page-discovered sitemap links

## Sitemap Classification

Each sitemap response must be classified as one of:

- **sitemap index**: contains `<sitemapindex>` and child `<sitemap>` entries
- **urlset sitemap**: contains `<urlset>` and child `<url>` entries with `<loc>`
- **challenge / anti-bot page**: HTML response with "Verifying your browser", "Please wait", Cloudflare challenge, DataDome 403, or similar
- **fake sitemap / placeholder**: returns 200 OK but body is `ERROR`, `Invalid parameter`, or other non-XML text
- **unrelated HTML**: response is HTML but not a sitemap

## Child Sitemap Ranking

When the root sitemap is an index, rank child sitemaps:

1. **product sitemap**: child sitemap whose URLs match product patterns like `/products/`, `/product/`, `/p/`, `/item/`, `/pd/`
2. **category sitemap**: child sitemap whose URLs match category patterns like `/category/`, `/categories/`, `/c/`
3. **brand sitemap**: child sitemap whose URLs match brand patterns like `/brand/`, `/brands/`, `/b/`
4. **landing / content sitemap**: child sitemap whose URLs match content patterns like `/page/`, `/pages/`, `/blog/`
5. **image / institutional / auxiliary sitemap**: everything else

Prefer the highest-ranked child sitemap that yields real PDP URLs.

## Product Authenticity Checks

Before calling a URL a PDP, verify at least one of:

- `og:type=product` meta tag
- JSON-LD `Product` schema
- visible price text
- SKU or product ID in the page
- availability signal
- Shopify product handle pattern
- clear `Add to cart` / `Buy now` button

Sample at least 3 to 5 candidate URLs per site.

## Narrowing and Filtering Rules

When the user provides a narrowed target phrase:

1. Tokenize the phrase conservatively.
   - Example: `"growth supplements"` -> `["growth", "supplements"]`
   - Example: `"polo wear"` -> `["polo", "wear"]`
2. Use conservative path matching:
   ```python
   def path_matches(url, target_words):
       path = (urllib.parse.urlsplit(url).path or "").lower()
       return all(tok in path for tok in target_words)
   ```
3. If the narrowed phrase can mean both a category and a product line:
   - first inspect product URL patterns
   - if product slugs already carry the phrase reliably, filter on product sitemap
   - if not, inspect brand sitemap
   - only use category sitemap as the final source when it is the only reproducible path

## Product URL Heuristics

Valid PDP URL patterns include:

- `/products/...`
- `/product/...`
- `/pd/...`
- `/p/...`
- paths ending with `/p`
- slugs containing a stable hash marker
- `/products/{slug}`
- `/product/{slug}`
- `/products/{id}/{slug}`

Exclude:

- category pages
- brand landing pages
- search pages
- institutional pages
- account / cart / checkout / quick view
- image sitemap URLs
- collection URLs unless the site architecture proves collections are the final PDP list source
- homepage promo URLs that only open category modules

## Challenge / Verification Handling

If official sitemap endpoints return:

- challenge HTML
- "Verifying your browser"
- "Please wait"
- empty or malformed XML due to anti-bot

Then:

1. Confirm whether the same endpoint works in a real browser.
2. Inspect with normal `skills/playwright-cli` first.
3. If the normal browser flow still hits challenge/interstitial pages, 403/429, geo/IP restriction, switch to the proxy fallback documented in `skills/playwright-cli/references/proxy-fallback.md`.
4. Record the true sitemap path and the real URL patterns.
5. Still generate final Goldrush code using server-side primitives only, if feasible.

Standard authoring-time escalation path:

1. direct server-side fetch
2. normal `playwright-cli` skill
3. `playwright-cli` proxy fallback
4. third-party read-only bypass such as `r.jina.ai` only as last resort

Important:

- Do not jump straight from direct fetch failure to `r.jina.ai`.
- Do not describe the `playwright-cli` proxy path as the default browser mode; the `playwright-cli` skill explicitly starts with the normal browser flow and treats proxy as fallback only.
- If a third-party bypass is used at all, treat it as an inspection/recovery aid unless the actual runtime explicitly accepts that same surface for first delivery.
- Do not skip the final bypass step just because you do not want to over-trust it for delivery; last-resort bypass evidence is still required when steps 1-3 fail and structure verification is otherwise impossible.
- After a bypass-assisted recovery, keep one formal final answer:
  - use `process_notes` and `risks` to explain which step recovered the structure
  - if that recovered structure yields a stable and reusable PDP discovery rule, deliver it directly as the formal List-skill result
  - do not invent a separate "observation-only" result layer in the final output

## Bypass and Runtime Alignment

If server-side Goldrush requests cannot reach real sitemap content at all:

- fall back to another discovery source only if it is real and reproducible
- otherwise say the sitemap path is blocked for server-side execution
- if the downstream system rejects empty `site_map_urls`, choose a non-empty fallback `sitemap` value that is actually reachable, such as the homepage, and let `list_custom_code` perform the real discovery from there

If discovery depends on a bypass surface such as proxy content, `r.jina.ai`, or browser-recovered text, do not stop at "the site structure is now understandable". Before finalizing any bypass-based answer, verify:

1. the delivered `sample_list_url` is non-empty in the intended runtime path
2. the recursive fetch path matches the surface that actually worked during discovery
3. canonical output URLs are separated from the fetch surface when needed

Hard rules:

- Do not assume the original site URL is a valid `sample_list_url` just because the site was understood through a bypass surface.
- If the original URL is blocked or returns empty content in the target runtime, do not still ship it as `sample_list_url`.
- `sample_list_url` itself must be able to return non-empty content in the intended runtime path.
- If category/list recursion also depends on the same bypass surface, keep that same fetch surface inside `list_custom_code`.
- It is valid for:
  - `sample_list_url` to use a bypass surface
  - recursive list fetching to keep using that same bypass surface
  - final `detail_uris` to still emit canonical product URLs on the original commerce host
- If the site structure is successfully recovered through the standard discovery chain and produces a stable PDP rule, that result is still a formal deliverable for List-skill; do not create an extra "observation-only" output layer in the final answer.

Common failure mode to avoid:

- authoring-time discovery succeeds through a bypass surface
- final answer switches `sample_list_url` back to the original blocked URL
- downstream runtime then returns "empty file" or `sample_list_url_res.total: 0`

## Cross-Origin Storefront Iframe Pattern

Some commerce sites render only a shell page on the main origin and mount the real product list inside a cross-origin iframe.

Typical signals:

- the main document has little or no product DOM even after JS hydration
- iframe `src` points to a storefront host such as `wix.ecwid.com`
- network calls from that iframe hit a structured storefront API
- the API response already contains final PDP fields such as `directPageUrl`

Required behavior:

1. Do not keep insisting on `Detail_url_pattern(xpath)` against the shell page.
2. You may inspect the iframe source only as an authoring-time clue about site structure.
3. Do not recommend the iframe host, its sitemap, or its API as the final user-facing `sitemap`.
4. Do not switch delivery to another external shop just because the shell resembles a standard storefront template.
5. If the user-given host itself does not expose a reproducible same-site discovery path, report that limitation honestly instead of substituting the external storefront host.
6. Use the shell/category URL only as the discovery entry when the final answer still stays on the user-given host.
7. Record in `process_notes`:
   - shell host
   - iframe host
   - storefront/API host if inspected during authoring
   - `store_id`
   - category/list identifier such as `category_id`
   - whether the external storefront was only diagnostic evidence or part of a same-site reproducible rule

This is not a license to use the external storefront as the final answer. The final delivery surface must remain on the user-given site unless that site directly redirects to a different verified commerce host.

## Non-Sitemap Fallback

If there is no useful sitemap family, fallback order is:

1. embedded page state:
   - `window.__SSR_DATA__`
   - hydration payloads
   - JSON-LD meta tags that contain real product URLs
2. structured JSON endpoint
3. static HTML list/category page
4. HTML full-link extraction with strict filtering

Do not jump to step 4 if a clean sitemap path exists.

Even when a sitemap family does exist, category sources remain valid secondary discovery sources if they materially increase PDP coverage.

If the downstream checker rejects empty `site_map_urls`, pick a non-empty fallback `sitemap` that is both reachable and productive:

- a proven category/list page, if homepage-only discovery is too weak
- avoid fake sitemap endpoints that return `200 OK` but contain no usable URLs

When using a category/list page as fallback `sitemap`, the final code should usually:

- start from `list_url`
- optionally also inspect homepage for more category seeds
- extract category/list URLs first
- then extract PDP URLs from those category/list pages

When coverage matters, also consider this expansion order:

1. homepage product modules
2. shop / collection / listing landings
3. category and subcategory pages
4. brand landings
5. search result pages that clearly enumerate products
6. embedded state or structured endpoints discovered from those pages

The list-side mandate is simple:

- maximize unique real PDP URLs
- deduplicate aggressively
- stop only when extra sources yield diminishing returns or fall below a coverage threshold

Long-chain fetch caveats:

- first try the highest-coverage entry:
  - best product child sitemap
  - strongest mixed sitemap
  - then category recursion
  - then homepage + embedded state
- only add a second source when the first source's coverage is below the minimum coverage threshold
- if a high-page-count listing family exists, write the decision in `process_notes`

## Recent Proven Fallback Patterns

- `vyclothingstore.com`:
  - `wp-sitemap.xml` can stall or fail
  - homepage and `/shop/` are the practical source
- `cortho.com`:
  - official browse/sitemap pages can be maintenance placeholders
  - homepage + category recursion is the productive fallback
- `tacheusa.com`:
  - main commerce page is a Wix shell and the product browser lives in a `wix.ecwid.com` iframe
  - the iframe/storefront path may explain the page structure, but it must not be delivered as another shop's sitemap or first host
  - category pages follow `/online-store/...-c<id>` and PDPs follow `/online-store/...-p<id>`
  - if same-site reproducible discovery is not available, report the limitation honestly rather than switching delivery to the external Ecwid storefront host
- `sivrock.com`:
  - no usable sitemap
  - homepage embeds PDP links and SSR state, but does not expose a full category tree
- `glee-ice.com`:
  - no usable sitemap XML; practical entry is `https://www.glee-ice.com/collections/all`
  - PDP URLs are not exposed as normal `href` links; they live inside inline JSON script data such as `data[].public.url` / `data[].path`
  - a raw regex can hit escaped strings like `\"products\/...\"` that does not make `Detail_url_pattern` reliable for the UI field
  - use `list_custom_code` to parse the embedded JSON and emit URLs
- `thriftbooks.com`:
  - `robots.txt` exposes the real sitemap family: `https://www.thriftbooks.com/static/sitemap/sitemap.xml`
  - direct homepage and `/sitemap/*` HTML category entry can be anti-bot or category-heavy, so do not stop there if the official static sitemap family is recoverable
  - once child sitemap URLs are available, prefer `w_sitemap_*.xml` over HTML category discovery because they already emit final PDP URLs
  - a concrete working example is `https://www.thriftbooks.com/static/sitemap/w_sitemap_1.xml` with plain string `Detail_url_pattern(pattern/regex/xpath/raw_st): /w/`
  - this is a reminder to prefer the official child product-like sitemap when it already exposes clean PDP surfaces, instead of overcomplicating with HTML sitemap recursion or `list_custom_code`
- `ubesgoo.com`:
  - the effective commerce host is `https://www.ubesgoo.com`, not the bare domain
  - the original site surface is Cloudflare-blocked for runtime fetching, while `r.jina.ai` provides readable category/list pages
  - `sitemap.xml` is not usable, but homepage and category pages expose stable category URLs like `*-c-<id>.html`, category pagination like `?page=<n>`, and PDP URLs like `*-p-<id>.html`
  - the first-pass mistake to avoid is understanding the site through the bypass surface but still delivering the blocked original homepage as `sample_list_url`
  - the correct pattern is:
    - use the bypass surface for `sample_list_url`
    - keep the same bypass surface for recursive list fetching
    - emit canonical product URLs on `https://www.ubesgoo.com/...-p<id>.html`
- `yankeecandle.com`:
  - direct sitemap/page requests can be Cloudflare-protected
  - SFCC / Mobify PWA exposes first-page `productSearchResult.hits` and a larger `total`
  - full category pagination requires SLAS guest PKCE auth and `mobify/caching/api/search/shopper-search/.../product-search`

## Process Notes Contract

For HTML-report mode, `process_notes` must be procedural. Do not reduce them to one-line conclusions.

Minimum content per site:

1. how the input domain or URL was normalized
2. whether redirects happened
3. how `effective_origin` was determined
4. whether `robots.txt` was reachable
5. whether `robots.txt` declared sitemap entries
6. whether the chosen root sitemap was `sitemapindex` or `urlset`
7. how child sitemap files were selected or rejected
8. how the PDP rule was confirmed
9. observed counts and shard counts when available
10. sample PDP URLs used for spot checks
11. a short Chinese reason for why each sample PDP was picked, such as "主类目命中: /shop 首页推荐", "canonical 命中: /products 主类目", "品牌命中: /brand 专区", or "分页命中: /collections 分页"
12. why `Detail_url_pattern` was enough, or why `list_custom_code` was required instead
13. if proxy-only recovery was used, the bypass surface and how it was kept separate from final delivery

`process_notes` must be concrete. Good notes explain the reasoning chain; bad notes only restate the final coverage label.
