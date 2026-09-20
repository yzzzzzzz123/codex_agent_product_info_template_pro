# AGENTS.md

## Project Purpose

`codex_agent_product_info_template_pro` is an end-to-end product crawl orchestrator project.

It drives:

- Stage4: List discovery (find PDP URLs for a site)
- Stage3: SPU/SKU extraction (extract product data from a PDP)
- Final HTML report assembly

The project is organized as a set of skills under `skills/`, each with a focused responsibility.

## Skill Inventory

| Skill | Purpose |
|-------|---------|
| `taojin_v3_crawl_skill` | Top-level orchestrator. Owns batch scheduling, retry waves, and final HTML report. v2-derived, end-to-end crawler workflow for extracting product information from a single e-commerce website. v3 keeps v2's Stage1/Stage2 data contract, lets the parent execution unit own Stage1, delegates Stage2-3 to a dedicated downstream agent, delegates browser fallback to `skills/playwright-cli`, and enters an optional Stage4 that directly calls `skills/sitemap-list-discovery` for single-site List discovery when the current task enables list discovery. |
| `sitemap-list-discovery` | Stage4 List discovery. Finds PDP URLs for a single site. |
| `spu-code-embed` | Stage3 SPU/SKU extraction. Generates and validates `final_code.py` for a single PDP. |
| `playwright-cli` | Browser-based authoring-time recovery. Used when direct server-side fetch fails. |
| `site-seed-discovery` | Seed URL discovery for initial dataset population. |

## Agent Architecture

### Agents

- `orchestrator_agent`: batch scheduling, retry waves, worktree management, final HTML ownership. Priority `5.5xhigh`.
- `seed_agent`: seed URL discovery. Reports to `orchestrator_agent`. Priority `xhigh`.
- `site_agent`: single-site crawl coordination (Stage4 + Stage3). Reports to `orchestrator_agent`. Priority `xhigh`. One worktree per site.
- `extract_agent`: Stage2-3 SPU/SKU extraction. Runs inside a site worktree.
- `list_agent`: Stage4 List discovery. Runs inside a site worktree when `extra_tasks` includes `list_discovery`.

### Worktree Model

Each site gets its own worktree under `worktrees/`. The worktree contains:

- `input/`: input dataset and URL files
- `result/prompt/run_prompt.md`: rendered prompt for the site agent
- `result/script_gen/`: Stage3 output (final_code.py, checkers, rendered HTML)
- `log/`: agent logs and phase markers
- `raw_html/`: captured HTML evidence
- `context/`: analysis context (field mappings, evidence logs, etc.)

Worktree operations are managed by `skills/taojin_v3_crawl_skill/scripts/worktree_cli.py`.

For details, see `skills/taojin_v3_crawl_skill/references/worktree_operations.md`.

## Invocation Boundary

- Use `taojin_v3_crawl_skill` for multi-site batch crawl and final HTML report.
- Use `sitemap-list-discovery` directly for single-site List discovery.
- Use `spu-code-embed` directly for single-PDP SPU/SKU extraction.
- Use `playwright-cli` for browser-based recovery during authoring.
- Use `site-seed-discovery` for seed URL discovery.

Do not reimplement sub-skill logic in the parent skill or vice versa.

## Task Types

- `type = "with_review_stats"`: enables review stats extraction (`source_score`, `source_cmms`)
- `extra_tasks = ["list_discovery"]`: enables Stage4 list discovery, outputs `site_delivery_summary.md`

Combinations:

- Basic mode: default (no review stats, no list discovery)
- Review only: `type: "with_review_stats"`
- List discovery only: `extra_tasks: ["list_discovery"]`
- Full mode: `type: "with_review_stats"` + `extra_tasks: ["list_discovery"]`

## Hard Rules

1. Never modify Goldrush source code unless the user explicitly asks for source edits.
2. `final_code.py` must be fully self-contained. No external file dependencies.
3. `final_code.py` must use only standard library plus `requests`, `curl_cffi.requests`, `lxml`, `json`, `re`, `urllib.parse`, `html`, `from lxml.html import fromstring`, `fromstring`, `etree`.
4. `final_code.py` must not import `Path`, `os`, or any other module that touches the filesystem.
5. `final_code.py` must not reference `random_va()`, `gen_headers()`, `static_simple_curl_cffi_req()`, `save_rendered_spu_html()`, or any other helper from the checker globals.
6. `final_code.py` must not read or write files such as `raw_html/static_page.html`, `rendered_page.html`, `*_request.json`, `*_response.json`, `stage1_gt.json`, or `stage1_raw_gt.json`.
7. Generated `list_custom_code` must follow the real Goldrush runtime behavior: Goldrush executes the code and only reads `script_res["detail_uris"]`.
8. Final `list_custom_code` must end with exactly one runtime contract output shape: `script_res = {"detail_uris": detail_uris}`.
9. Final `final_code.py` must end with exactly one runtime contract output shape: `script_res = {...}` with all required SPU/SKU fields.
10. Missing fields in `script_res` must be `None`, not absent.
11. `source_origin_price` and `source_activity_price` must be numeric. If the site shows `Free`, `$0`, or similar, normalize to `0`.
12. `source_price_currency` must be a 3-character upper-case string such as `USD` / `CNY` / `EUR`.
13. `props` must be a dict. If the site has no SPU-level props, emit `{}`.
14. `skus[].sku_props` must be a dict. If the site has no SKU-level props, emit `{"SKU": "<sku_id>"}` or similar.
15. `descriptions` must be a list of strings or HTML strings.
16. `source_pics` must be a list of strings. Each string must be an absolute URL.
17. `skus[].source_pics` must be a list of strings. Each string must be an absolute URL.
18. `status` must be an integer. `1` means on-shelf, `0` means off-shelf.
19. Batch scheduling, polling cadence, retry waves, and final HTML ownership belong to `taojin_v3_crawl_skill`, not to the internal sub-skills.
20. Final HTML report must be self-contained: all data, CSS, and JS embedded in one file.
21. Coverage labels must follow the contract: `ok`, `partial`, `none`, `blocked`, `dead`, `amb`.
22. Anti-bot condition is surfaced through `coverage_note: "antibot"`, while colors, filters, and statistics still use base `coverage`.
23. Validation must fail if any site has `coverage = dead` and `observed_count > 0`.
24. Do not emit both `Detail_url_pattern` and `list_custom_code` as equal-weight primary outputs for the same site.
25. `list_custom_code` must be clipboard-safe in HTML/file preview mode. Avoid code shapes that are commonly damaged by HTML embedding or copy/paste.
26. Avoid bytes literals such as `b"\x1F\x8b"` in generated code; use `bytes([31, 139])` or equivalent instead.

## Runtime Model

Goldrush executes `final_code.py` and `list_custom_code` with `exec(...)`.

For `list_custom_code`, Goldrush reads only:

```python
script_res["detail_uris"]
```

For `final_code.py`, Goldrush reads only:

```python
script_res
```

`final_code.py` may assume only these runtime symbols:

- `detail_url`: the PDP URL string
- `rsp`: the response object from `common_request(...)`
- `common_request`: the Goldrush request function

Do not assume any other runtime variable names.

## Stage Flow

### Stage4: List Discovery

For each site:

1. Normalize the site.
2. Delegate to `sitemap-list-discovery` for List discovery.
3. Collect: `sitemap`, `Detail_url_pattern` or `list_custom_code`, `sample_detail_uris`, `process_notes`, `coverage`, `coverage_note`, `observed_count`.
4. Write per-site `site_delivery_summary.md`.

### Stage3: SPU/SKU Extraction

For each PDP URL from Stage4 (or seed):

1. Delegate to `spu-code-embed` for SPU/SKU extraction.
2. Collect: `final_code.py`, `script_res`, `rendered_spu_skus_final.html`.
3. Validate with `final_code_check.py` (live) or `final_code_check_offline.py` (offline).

### Final HTML Report

1. Read all per-site results.
2. Assemble final HTML report using `skills/taojin_v3_crawl_skill/scripts/assemble_html_report.py` or `render_stage4_batch_report.py`.
3. Write to output directory.

## Retry Waves

`taojin_v3_crawl_skill` owns retry waves for the batch:

1. **First pass**: run all sites once.
2. **Second pass**: re-run sites that were `blocked`, `dead`, `amb`, or `none` after the first pass.
3. **Third pass**: re-run sites that were still `blocked`, `dead`, `amb`, or `none` after the second pass.
4. Final HTML report is assembled only after the third pass.

Each site's `process_notes` must record whether a second pass and third pass ran.

## Coverage Labels

Base `coverage` must be one of:

- `ok`: site has real PDP URLs and they were successfully discovered
- `partial`: site has some real PDP URLs but coverage is incomplete
- `none`: site is reachable but no real PDP URLs were found
- `blocked`: site is blocked by anti-bot and no bypass worked
- `dead`: site is parked, expired, or permanently unreachable
- `amb`: site is reachable but the effective commerce surface is ambiguous

`coverage_note` is optional. The only currently defined value is:

- `antibot`: site has anti-bot symptoms but real PDP URLs were discovered

## Anti-Bot Escalation

Standard authoring-time escalation path:

1. direct server-side fetch
2. normal `playwright-cli` skill
3. `playwright-cli` proxy fallback
4. third-party read-only bypass such as `r.jina.ai` only as last resort

Do not skip the final bypass step just because you do not want to over-trust it for delivery; last-resort bypass evidence is still required when steps 1-3 fail and structure verification is otherwise impossible.

## References

- Agent responsibilities: `skills/taojin_v3_crawl_skill/references/agent_responsibilities.md`
- Worktree operations: `skills/taojin_v3_crawl_skill/references/worktree_operations.md`
- Web analysis playbook: `skills/taojin_v3_crawl_skill/references/web_analysis_playbook.md`
- Human operation flow: `skills/taojin_v3_crawl_skill/references/human_operation_flow.md`
