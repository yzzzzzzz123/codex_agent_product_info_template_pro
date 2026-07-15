# HTML Report Contract

## Purpose

This file is not a standalone multi-site report contract for `sitemap-list-discovery`.

Inside `codex_agent_product_info_template_pro`, batch scheduling, polling cadence, retry waves, output directories, and final HTML ownership belong to the parent `taojin_v3_crawl_skill`.

Keep this file only as a field-level compatibility note when the parent Stage4 flow needs to embed List-discovery results into a site summary or parent-owned batch report.

## Ownership Boundary

- this internal skill does not own standalone multi-site reports
- this internal skill does not define its own polling cadence
- this internal skill does not define a separate `worktrees/list/*` artifact workflow
- parent `taojin_v3_crawl_skill` decides where and how Stage4 results are rendered

## Stage4 Field Contract

When the parent flow renders a site summary, it must own or preserve these list-side fields:

- `input_site`
- `effective_origin`
- `commerce_origin`
- `scope_reason`
- `sitemap`
- exactly one primary companion field:
  - `Detail_url_pattern`
  - or `list_custom_code`
- optional `extra` field for lower-priority secondary answers
- `sample_detail_uris`
- `process_notes`
- `coverage`
- `coverage_note` (optional)
- `observed_count`

Hard rules:

- one site panel must have exactly one primary companion field
- do not show both `Detail_url_pattern` and `list_custom_code` as equal-weight primary outputs for the same site
- `extra` must clearly separate from the primary answer and stay visually secondary
- `extra` content must still align with the same site and same origin

## HTML Requirements

- all data embedded in the HTML itself
- all CSS embedded in the HTML itself
- all JS embedded in the HTML itself
- no external asset dependency
- no external CSS / JS references

Opening the one file in a browser should be enough.

The page must contain:

- header
- coverage legend
- top site switch buttons
- one active site detail panel
- top-detail manual mark controls
- process notes
- copy buttons for code fields

Use the same color mapping for the top site buttons and the legend.

## Coverage Display Contract

Base `coverage` must be one of:

- `ok`
- `partial`
- `none`
- `blocked`
- `dead`
- `amb`

`coverage_note` is optional. The only currently defined value is:

- `antibot`

Use `coverage = dead` only when:

- the domain is parked, expired, dead, permanently unreachable, maintenance-only with no live commerce surface, or has no product discovery surface after all required checks
- after the full discovery workflow and required escalation path, anti-bot or access protection still prevents all usable product discovery, `observed_count = 0`, and no real PDP URL was found
- the site is reachable but the effective commerce surface, product URL pattern, sitemap meaning, or reproducible discovery path remains ambiguous after the required checks

Anti-bot nuance:

- if the site has anti-bot symptoms but real PDP URLs were discovered through sitemap, proxy, `curl_cffi`, head-only bypass, or another reproducible path, do not set `coverage = dead`
- instead, label base `coverage` as `ok`, `partial`, or `none` according to actual discovered URL coverage
- add `coverage_note: "antibot"` to record the anti-bot condition
- display it as `ok (antibot)`, `partial (antibot)`, or `none (antibot)`
- colors, filters, statistics, retry selection, and coverage grouping must use the base `coverage`, not `coverage_note`
- validation must fail if `coverage = dead` and `observed_count > 0`

Colors:

- `ok`: `#0ba63e`
- `partial`: `#008af7`
- `none`: `#ff8a00`
- `blocked`: `#6b7280`
- `dead`: `#e60023`
- `amb`: `#7c3aed`

If `coverage_note` is present, colors still follow base `coverage`, not `coverage_note`.

## Selected-state CSS Rules

- do not add black outlines
- do not add red outlines
- do not add dashed outlines
- selected state may only use mild brightness / saturation change

## Manual Marking Contract

Each active site detail panel must show these manual mark controls in the top detail area, in the position previously used by previous / next navigation:

- `待处理`
- `通过`
- `拒绝`
- `重置`

Do not include:

- `<select>`
- `<textarea>`

All manual marks must be stored in localStorage under:

- `lastSkuManualMarks:v2`

Top-level manual mark utilities must:

- `导出 marks`
- `导入 marks`
- `复制 marks`
- `清空 marks`

`复制 marks` should copy the localStorage JSON payload to the clipboard.

Manual-mark UI constraints:

- do not use black background
- do not use green background
- do not use red background
- do not use bold text or underline

If the site has a manual mark, append plain text:

- `(待处理)`
- `(通过)`
- `(拒绝)`

Do not render those status labels as green/black badges. Keep them as normal text.

## Copy Button Contract

After click, show a short success hint:

- `已复制`

The copied content must be:

- plain Python source for `list_custom_code`
- plain string for `Detail_url_pattern`

## List_custom_code Display Contract

Default collapsed state:

- show only a small preview
- recommended `max-height: 120px`
- preview should be read-only or focus-disabled

Expansion must not break the one-site panel layout.

`Detail_url_pattern` does not need folding; should display normally.

## Data Model

The HTML may embed its data as a JS constant, or as an inline rendered data block.

Minimum per-site data model:

- `input_site`
- `effective_origin`
- `commerce_origin`
- `scope_reason`
- `sitemap`
- `companion`:
  - `type`: `Detail_url_pattern` or `list_custom_code`
  - `value`: the code or pattern string
- `sample_detail_uris`
- `sample_detail_reasons` (optional but strongly recommended)
- `process_notes`
- `coverage`
- `coverage_note`
- `observed_count`

HTML shell may add view-only fields such as:

- `site_name`
- `manual_mark`
- `index`

But the required contract above must still be present.

`sample_detail_reasons` is optional but strongly recommended for HTML-report mode. When present:

- it should align by index with `sample_detail_uris`
- each reason must be written in Chinese by default, because the final report label is `抽样详情理由`
- each reason should concisely answer both questions: (i) PDP 命中了什么路径/类目/品牌，(ii) 为什么这条 URL 具有代表性
- preferred format is `命中: ...; 代表: ...`. Such as:
  - `命中: Snowboards / Men's; 代表: 主力类目，价格区间典型，颜色/尺码齐全`
  - `命中: Jackets / Men's; 代表: 季节性主推 PDP，覆盖多 SKU 与活动价`

## Process Notes Contract

`process_notes` must be procedural and reflect the actual discovery path.

Minimum content:

- how the input domain or URL was normalized
- whether redirects happened
- how `effective_origin` was determined
- whether `robots.txt` was reachable
- whether `robots.txt` declared sitemap entries
- whether the chosen root sitemap was `sitemapindex` or `urlset`
- how child sitemap files were selected or rejected
- how the PDP rule was confirmed
- observed counts and shard counts when available
- sample PDP URLs used for spot checks
- a short Chinese reason for why each sample PDP was picked
- why `Detail_url_pattern` was enough, or why `list_custom_code` was required instead
- if proxy-only recovery was used, the bypass surface and how it was kept separate from final delivery
- for sites that were still `blocked`, `dead`, `amb`, or `none` after the first pass, whether the required second full list-discovery pass ran after all first-pass sites completed
- for sites that were still `blocked`, `dead`, `amb`, or `none` after the second pass, whether the required third full list-discovery pass ran before final output
- for repeated low-substance sites, which coverage limitation, blocking, ambiguity, or absence of discovery evidence persisted

## Evidence Notes

`evidence_notes` should stay concise and decision-oriented.

Good notes explain:

- why the chosen sitemap or fallback source is the best runtime surface
- why the coverage label is honest
- why `coverage_note: "antibot"` was used when anti-bot existed but URLs were still discovered
- why a heavier source was or was not needed
- why a sample PDP was or was not included

When sample PDP notes are added, they should stay short and selection-oriented rather than repeating the full evidence chain.

Common evidence tags:

- `Cloudflare challenge`
- `DataDome 403`
- `empty file`
- `common_request empty response on sitemap`
- `sitemap works in authoring but blocked at runtime`
- `detail sitemap 403 while category/list fallback still works`
- `curl_cffi fallback used`
- `input_site differs from effective_origin`

## List_custom_code Quality Contract

1. run `compile(code, "<site>", "exec")`
2. ensure the copied code is plain Python
3. ensure the copy button copies only the raw `list_custom_code` body; never include Markdown fences, field labels, JSON wrappers, surrounding quotes, or explanatory text in the clipboard payload

## Coverage Rules

Do not use the old generic `FAIL` label in new reports. Pick one of `blocked`, `dead`, or `amb` instead.

## Validation Checklist

Before finalizing the HTML:

1. site count is correct
2. each site has a non-empty `sitemap`
3. each site has exactly one primary companion field
4. each `list_custom_code` passes `compile(...)`
5. HTML is self-contained
6. no external CSS / JS is referenced
7. each site has `process_notes`
8. `textarea` is not present
9. `<select>` and `<input>` are not present
10. manual mark controls include `待处理 / 通过 / 拒绝 / 重置` in the top detail area
11. `list_custom_code` defaults to a short collapsed preview, recommended `max-height: 120px`
12. expanded `list_custom_code` container is a rounded panel, recommended `border-radius: 8px`
13. every site that was `blocked`, `dead`, `amb`, or `none` after the first pass has an explicit second-pass note
14. every site that was still `blocked`, `dead`, `amb`, or `none` after the second pass has an explicit third-pass note, and final HTML was assembled only after that third full pass
15. anti-bot condition is surfaced through `coverage_note`, while colors, filters, and statistics still use base `coverage`
