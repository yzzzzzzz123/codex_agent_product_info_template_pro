# Jackery v3 single-PDP run

- Site: `jackery.com`
- Worktree: `/Users/yuzhizheng/Desktop/codex/codex_agent_product_info_template_pro/worktrees/jackery.com`
- Product URL: `https://www.jackery.com/products/jackery-solar-generator-5000-plus`
- Task type: basic (`source_score = None`, `source_cmms = None`)
- Extra tasks: `[]` (no list discovery)

Execute `taojin_v3_crawl_skill` in v3 mode. Stage1 is owned by the parent execution unit. The downstream extract agent owns Stage2 browser rendering/parsing and Stage3 embedding/validation. Use the main project skills and references at `/Users/yuzhizheng/Desktop/codex/codex_agent_product_info_template_pro/skills/`.

Required deliverables are the standard Stage1-3 files under this worktree's `result/` directory. Follow the target schema and the stricter embedded Stage3 contract. Do not modify Goldrush source or checker logic. Use live validation when possible; use offline validation only after the required access escalation has been exhausted.
