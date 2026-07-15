# Proxy Fallback

Use this path only after the normal `playwright-cli` flow fails to reach the real page.

## When to switch

- challenge or interstitial pages such as "Just a moment...", "Please wait", "One more step", "security check", or CAPTCHA
- 403/429, geo/IP restriction, or repeated timeouts
- rendered HTML is empty / extremely short / missing the expected product DOM after normal Playwright access

## Command

```bash
export OUTPUT_DIR="result/{source_spu_id}/raw_html"
node skills/playwright-cli/scripts/proxy-access.js "https://www.example.com" "$OUTPUT_DIR"
```

Path requirements:

- `OUTPUT_DIR` 必须显式传入，且必须指向当前任务的自有目录（优先站点 worktree 内目录）。
- 不允许省略 `OUTPUT_DIR` 后由脚本 shell 的 `cwd` 作为默认输出目录。
- 不允许将代码产出写到全局项目目录 `log/`、`.playwright-cli/` 或其他非当前任务文件夹。
- 若脚本不在站点 worktree 内，又无法给出明确的输出路径，则不得执行该命令。

The bundled script writes:

- `rendered_page.html`
- `screenshot.png`
- `meta.json`

## Environment loading

- Read current shell env first.
- If needed, auto-load `.env`.
- If still missing, fall back to `.bashrc` lines in `export KEY=VALUE` form.
- Candidate files are searched from the current directory, the script-local defaults, and parent directories of `OUTPUT_DIR`.
- If no values are found, the script falls back to built-in defaults for `GOLDRUSH_PROXY_SERVER`, `GOLDRUSH_PROXY_USERNAME`, `GOLDRUSH_PROXY_PASSWORD`, and `HEADLESS`.

Optional knobs:

```bash
export PLAYWRIGHT_PROXY_POST_LOAD_WAIT_MS=6000
export PLAYWRIGHT_PROXY_VIEWPORT=1366x768
export PLAYWRIGHT_PROXY_USER_AGENT="Mozilla/5.0 ..."
export PLAYWRIGHT_PROXY_LOCALE="en-US"
export PLAYWRIGHT_PROXY_TIMEZONE="America/New_York"
```

## Notes

- The bundled script enables proxy, stealth hardening, stable UA/Locale/Timezone/Viewport defaults, and ignores HTTPS errors.
- Keep proxy usage as a fallback path, not the default browser workflow.
- If the saved title is still "Just a moment...", "Access Denied", or another challenge page, record blocked evidence instead of pretending the product page was reached.
- This is the same proxy + stealth injection path that Stage1 workflows use when normal Playwright evidence capture is blocked.
