---
name: "sitemap-list-discovery"
description: "Internal Stage4 single-site List-discovery engine for taojin_v3_crawl_skill."
---

# Sitemap List Discovery

## Purpose

This skill is the sitemap-first List-side strategy skill used only inside `taojin_v3_crawl_skill` Stage4.
Its job is to help the current Stage4 agent:

- discover the official sitemap family for the current site
- or Goldrush-compatible `list_custom_code`
- optionally surface `sample_detail_uris` / `process_notes` / `coverage` when the parent task needs them

Primary output is a single-site List-side only:

- `sitemap` + `Detail_url_pattern(pattern/regex/xpath/raw_st)` when the chosen sitemap source already exposes or can cleanly isolate PDP URLs
- otherwise `sitemap` + `list_custom_code`
- `scope_reason` explaining why the final delivery scope stays on the chosen origin

If the parent task also needs `detail_custom_code`, finish List discovery first, then hand off detail extraction to the more general List/detail workflow. This skill is not a full detail extraction engine.

Only output the code or concise result the parent Stage4 flow asked for. Do not generate unrelated helper files, scripts, docs, or project changes.

## Invocation Boundary

Within this project, use this skill only when all conditions are true:

- the current work is already inside `taojin_v3_crawl_skill` Stage4
- the parent handler explicitly asks for List-side discovery output
- the target is a single site (multi-site batch is owned by the parent orchestrator)

## References

Read these core references as needed:

- `references/discovery_playbook.md`
- `references/detail_url_pattern_rules.md`
- `references/runtime_compatibility.md`
- `references/output_templates.md`

Read these only when the parent Stage4 summary/report integration needs them:

- `references/html_report_contract.md`
- `references/html_report_template.html`

Read this specialized reference only when the site shows SFCC / Mobify PWA signals:

- `references/sfcc_mobify_playbook.md`

## Navigation

Default references:

- discovery workflow and coverage decisions: `references/discovery_playbook.md`
- `Detail_url_pattern` semantics and edge cases: `references/detail_url_pattern_rules.md`
- Goldrush runtime constraints: `references/runtime_compatibility.md`
- final answer shapes and code templates: `references/output_templates.md`
- site/batch report compatibility: `references/html_report_contract.md`
- report shell fragment reference: `references/html_report_template.html`
- SFCC / Mobify PWA playbook: `references/sfcc_mobify_playbook.md`

## Output Contract

Default user-facing output must be UI-ready and keep field names stable.

Default mode:

- the primary answer must contain `input_site`, `sitemap`, and exactly one companion field:
  - `Detail_url_pattern`
  - or `list_custom_code`
- only after re-checking the best route may the answer also include one lower-priority `extra`
- do not wrap the default answer in JSON unless explicitly requested
- do not omit `sitemap` in normal mode unless the parent task explicitly asks for code only

## Hard Rules

1. Never modify Goldrush source code unless the user explicitly asks for source edits.
2. Generated `list_custom_code` must follow the real Goldrush runtime behavior: Goldrush executes the code and only reads `script_res["detail_uris"]`.
3. Primary goal is to maximize discovery of real product detail page URLs for the given site. Prefer official discovery sources first, but keep expanding through other real list/category sources when they add more PDP coverage.
4. Prefer compatibility over cleverness. Keep generated code minimal and robust.
5. Always assume the user wants code that can be pasted directly into Goldrush UI fields.
6. Do not rely on extra local files or external workspace helpers.
7. Do not fabricate product URLs when the site is blocked or the discovery source is inconclusive.
8. Do not put browser-only logic inside final Goldrush embedded code. Browser fallback is for authoring-time discovery only.
9. When the official sitemap family is identifiable, output the recommended `sitemap` value unless the user explicitly asks for code-only output.
10. If the downstream UI requires a non-empty `sitemap`, do not return an empty one. When no real sitemap endpoint is usable, fall back to a stable, directly accessible discovery entry such as the homepage or a proven category/list landing and make that fallback explicit.
11. Prefer a working, reproducible, non-empty discovery path over a more official but broken one.
12. For single-site requests, default output mode is direct chat and UI-field-ready: return a plain `sitemap` value plus the simplest valid companion field. If the chosen source already allows clean PDP isolation through `Detail_url_pattern`, prefer that over `list_custom_code`; otherwise return plain Python `list_custom_code`.
13. Do not get locked into one discovery route just because it was the first plausible path. If the final rule still feels uncertain, explicitly rethink the site from another viable route before answering.
14. Before deciding the `sitemap` value, URL filters, or target domain, normalize the effective content site.
15. When no useful sitemap family exists, prefer embedded page state (`__NEXT_DATA__`, `__INITIAL_DATA__`, `window.__SSR_DATA__`, hydration JSON, JSON-LD) before falling back to noisy full-link extraction.
16. Do not switch final delivery to a different storefront host, iframe host, or lookalike external shop just because it appears easier or structurally similar. The user-given site is the delivery boundary unless the site itself directly redirects there.
17. Treat maintenance pages, fake sitemaps, and placeholder pages as first-class failure modes.
18. Category pages, list pages, shop pages, brand landing pages, and search result pages are valid discovery sources whenever they yield additional real PDP URLs.
19. Do not stop at the first workable source if other reachable sources are likely to add meaningful new PDP coverage.
20. When reporting the result, explicitly frame the base coverage as one of: `ok`, `partial`, `none`, `blocked`, `dead`, or `amb`. Do not use the old generic `FAIL` label.
21. `dead` as base coverage is allowed only when the full discovery workflow cannot recover any usable product data: `observed_count = 0` and there are no real PDP URLs. If anti-bot exists but URLs were found through sitemap, proxy, `curl_cffi`, read-only bypass, or another reproducible path, do not set `coverage = dead`; set base `coverage` to `ok`, `partial`, or `none` according to actual coverage, and add `coverage_note: "antibot"`.
22. When `coverage_note: "antibot"` exists, display coverage as `ok (antibot)`, `partial (antibot)`, or `none (antibot)`, but colors, filters, counts, retry logic, and statistics must still use the base `coverage`.
23. Validation must fail if any site has `coverage = dead` and `observed_count > 0`.
24. For Salesforce Commerce Cloud / Mobify PWA sites, do not stop at `productSearchResult.hits` embedded in the first page when `total > len(hits)`.
25. If the site has either a direct product sitemap or a mixed sitemap with a stable PDP path rule, and the downstream UI supports `Detail_url_pattern`, it is valid to skip `list_custom_code` entirely.
26. If `robots.txt` or the official sitemap index leads to child sitemap files that already expose real PDP URLs, prefer the best child sitemap directly and return the simplest valid `Detail_url_pattern`. Do not keep defaulting to homepage, HTML sitemap, category recursion, or `list_custom_code` unless those heavier paths are still required for material incremental coverage or the child sitemap is not actually usable.
27. When a plain string pattern already isolates the PDP family cleanly, prefer it over `regex` or `xpath`. `Detail_url_pattern(pattern/regex/xpath/raw_st)` are all valid; final delivery uses plain strings such as `https://example.com/products/*` whenever possible.
28. Do not describe proxy usage inside `playwright-cli` loosely. Follow the actual `playwright-cli` skill policy: start with normal browser access, switch to its proxy fallback only after challenge pages, 403/429, geo/IP restriction, or repeated navigation failures.
29. Do not stop early after the first three anti-bot steps fail. The last-resort third-party read-only bypass must still be attempted when it is the remaining path to verify site structure, PDP URL rules, or coverage signals.
30. Keep bypass observation and final delivery separate. A bypass may be required to understand the site, but that does not automatically make the bypass surface the correct final `sample_list_url` or runtime fetch surface.
31. Cross-subdomain commerce is a first-class discovery scenario. If the user-given site directly redirects to `shop.`, `store.`, `checkout.`, or another storefront host, or clearly links its commerce surface there, you must explicitly decide whether that storefront is the true `commerce_origin` before finalizing the result.
32. If the user provides a sample product URL, treat it as an anchor. Resolve its canonical URL first, then fail validation unless the final `sitemap` plus `Detail_url_pattern` or `list_custom_code` can recover that canonical or an equivalent normalized PDP URL.
33. URL quantity alone is not enough. For every site, sample at least 3 to 5 candidate URLs and verify product signals such as `og:type=product`, JSON-LD `Product`, visible price, SKU, availability, Shopify product handle, or clear `Add to cart` / `Buy now` signals before calling the corpus product coverage.
34. `/players/`, `/blogs/`, `/news/`, `/pages/`, `/stores/`, `/locations/`, `/articles/`, and other non-commerce detail families must not be counted as successful product coverage unless product signals prove they are real PDPs.
35. Validation must compare the sample URL type, host, canonical target, and final result corpus. A site cannot be marked `ok` or `partial` when the discovered URLs are mostly non-product detail pages or live on the wrong host.
36. For `list_custom_code`, compile success alone is insufficient. Authoring-time validation must also cover success path, `common_request(...)` exception, child-sitemap partial failure, HTML challenge response, and empty response handling before the code is considered ready.
37. For Shopify-style commerce subdomains such as `shop.example.com`, if the real storefront sitemap family exposes query-bearing child product shards like `sitemap_products_1.xml?from=...&to=...`, prefer that direct child product sitemap as the final `sitemap`. Do not stop on the marketing host, and do not guess child shard names when the root sitemap already exposes the real child URLs.
38. If the parent Stage4 flow later renders a site summary or batch report, preserve the same list-skill field contract inside each site panel: one primary `input_site`, one primary `sitemap`, and one primary companion field (`Detail_url_pattern` or `list_custom_code`), plus concise evidence notes.
39. Never emit both `Detail_url_pattern` and `list_custom_code` as equal-weight primary outputs for the same site.
40. If a parent-owned report copies `list_custom_code`, the copied code must be plain Python and must pass `compile(code, "<site>", "exec")`.
41. Avoid bytes literals such as `b"\x1F\x8b"` in generated code because they are fragile in HTML/copy pipelines; use `bytes([31, 139])` or equivalent instead.
42. Final `list_custom_code` must end with exactly one runtime contract output shape:
    - `script_res = {"detail_uris": detail_uris}`
43. If the chosen root sitemap is only a sitemap index, do not claim that `Detail_url_pattern` on the root sitemap will recurse into child sitemaps. Either choose a real child sitemap plus `Detail_url_pattern`, or keep root/index recursion inside `list_custom_code`.
44. Do not default to long sequential fetch chains across dozens of list pages. Prefer the highest-coverage entry first, then add a second source/page only when it materially improves coverage.
45. Even when a cross-origin storefront iframe exists, do not recommend that external storefront host, its sitemap, or its API as the final `sitemap` or delivery surface unless the user explicitly asked for that external host or the original site directly redirects there.
46. Generated `list_custom_code` must not assume ad hoc runtime variable names such as `sample_list_url`. Resolve the active list URL through runtime-safe probes such as `rsp.url`, `list_url`, or `url`, and fail explicitly if no usable source exists.
47. Whenever the final delivery uses `list_custom_code`, the copied value must be real runnable Python source, not a pseudo button payload. Do not include Markdown fences, leading field labels like `list_custom_code:`, bullets, JSON wrappers, surrounding quotes, explanatory prose, or placeholder text in the copied body. The report copy button is expected to place that exact plain Python body on the clipboard.
48. `list_custom_code` must be clipboard-safe in HTML/file preview mode. Avoid code shapes that are commonly damaged by HTML embedding or copy/paste, and ensure the copied body can still pass `compile(code, "<site>", "exec")` after being copied from the report.
49. Parent-level scheduling, polling cadence, retry waves, artifact paths, and batch HTML behavior are owned by `taojin_v3_crawl_skill`, not by this internal skill.

## Runtime Model

Goldrush executes `list_custom_code` with `exec(...)` and reads only:

```python
script_res["detail_uris"]
```

Implications:

- `detail_uris` must be a list
- relative URLs are acceptable, but absolute URLs are preferred
- final output should generally be list-side code only
- do not assume the runtime always injects a `sample_list_url` variable
- if the code needs the current list URL, probe the runtime carefully instead of hardcoding one symbol name
- do not switch final delivery to an external storefront host just because the shell page embeds it

## Core Decision Tree

When invoked for a target site, follow this order:

1. Normalize the effective site while keeping the user-given site as the delivery boundary unless a direct redirect proves otherwise.
2. Fetch `robots.txt` and collect declared sitemap entries.
3. If no sitemap entries are usable, probe common sitemap locations: `/sitemap.xml`, `/sitemap_index.xml`, `/sitemap-index.xml`, `/xml/sitemap.xml`.
4. Classify each sitemap: sitemap index, urlset sitemap, challenge/anti-bot page, fake sitemap/placeholder, unrelated HTML.
5. Rank child sitemaps: product sitemap, category sitemap, brand sitemap, landing/content sitemap, image/institutional/auxiliary sitemap.
6. If a clean child product sitemap exists:
   - choose that child sitemap as the user-facing `sitemap`
   - prefer the simplest valid plain string `Detail_url_pattern(pattern/regex/xpath/raw_st)`
   - stop unless broader coverage still requires a heavier source
7. Otherwise, fall back to embedded page state, structured JSON endpoints, static HTML list/category pages, or HTML full-link extraction with strict filtering.
8. Choose the simplest companion output:
   - `Detail_url_pattern(pattern/regex/xpath/raw_st)` when the chosen source already exposes or can cleanly isolate real PDP URLs
   - otherwise `list_custom_code`
9. Validate runtime compatibility and coverage honesty before answering.
10. If the parent flow is handling a multi-site batch, run this same single-site workflow per site and let the parent `orchestrator_agent` / `site_agent` decide polling, retries, and final assembly.

For anti-bot sites, standard authoring-time escalation is:

1. direct server-side fetch
2. normal `playwright-cli` skill
3. `playwright-cli` proxy fallback
4. third-party read-only bypass such as `r.jina.ai` only as last resort

Do not interpret step 4 as optional once steps 1-3 fail. It is still required for last-resort verification; just keep its evidence separate from the final delivery decision.

## Choosing Output Shape

Prefer `Detail_url_pattern` when:

- official child sitemap files already provide a clean PDP family, even if the root sitemap or homepage was noisy or challenge-prone
- category/list/shop/search expansion materially improves coverage
- the site is anti-bot protected and the final list-side path must be reconstructed

Do not:

- treat a regex hit on raw HTML as proof that `Detail_url_pattern` is valid if the apparent URLs exist only inside embedded JSON / `<script>` state or JS/API templates
- overcomplicate the answer once an official child sitemap already gives a clean PDP surface; prefer the minimal UI-ready output first

For the real semantics and edge cases of `pattern` / `regex` / `xpath` / `raw_st`, read:

- `references/detail_url_pattern_rules.md`

## Output Discipline

Default output mode:

- plain `Detail_url_pattern(pattern/regex/xpath/raw_st)` or plain Python under `list_custom_code`

Do not:

- wrap output in JSON unless the user explicitly asks for a config block
- prepend long theory unless requested
- create temp files or extra artifacts

For canonical code shapes and compact answer formats, read:

- `references/output_templates.md`

## Runtime Compatibility

Final Goldrush code should:

- prefer `common_request(...)` over raw `requests.get(...)` / `requests.post(...)`
- prefer byte-based XML/HTML parsing
- avoid browser-only logic
- avoid known failure patterns

## Discovery Strategy Details

If the site shows SFCC / Mobify PWA signals, additionally read:

- `references/sfcc_mobify_playbook.md`

## When To Use

Use this skill when the user says things like:

- "discover list URLs for example.com"
- "find the sitemap for shop.example.com"
- "give me `list_custom_code` for example.com"
- "what is the `Detail_url_pattern` for example.com"

Even when the user does not explicitly mention sitemap discovery, this skill should still maximize real PDP URL discovery through sitemaps, category/list pages, search pages, embedded state, and reproducible HTML discovery, as long as the parent Stage4 flow is running.

This skill is a single-execution kernel. It does not own a standalone delivery shell.
