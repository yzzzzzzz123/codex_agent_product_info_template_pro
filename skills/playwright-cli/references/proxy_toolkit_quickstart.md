# Proxy Toolkit Quickstart

## Overview

Use the proxy toolkit when normal `playwright-cli` flow fails due to anti-bot measures, geo/IP restrictions, 403/429 errors, or repeated navigation timeouts.

## When to Use

- Challenge or interstitial pages: "Just a moment...", "Please wait", "One more step", "security check", CAPTCHA
- 403/429 status codes
- Geo/IP restrictions
- Repeated `goto` timeouts
- Rendered HTML is empty, extremely short, or missing expected product DOM

## Command

```bash
export OUTPUT_DIR="result/{source_spu_id}/raw_html"
node skills/playwright-cli/scripts/proxy-access.js "https://www.example.com" "$OUTPUT_DIR"
```

## Path Requirements

- `OUTPUT_DIR` must be explicitly passed
- Must point to a task-owned directory (preferably inside the site worktree)
- Do NOT omit `OUTPUT_DIR` and rely on the script's current working directory
- Do NOT write artifacts to global project directories like `log/`, `.playwright-cli/`, or other non-task folders

## Output Files

The proxy script writes these files to `OUTPUT_DIR`:

- `rendered_page.html` - Full rendered HTML
- `screenshot.png` - Full-page screenshot
- `meta.json` - Metadata including title, URL, user agent, locale, timezone

## Environment Loading

The script loads environment variables in this order:

1. Current shell environment
2. `.env` file (searched from current directory, script-local defaults, and parent directories)
3. `.bashrc` lines in `export KEY=VALUE` form
4. Built-in defaults for `GOLDRUSH_PROXY_SERVER`, `GOLDRUSH_PROXY_USERNAME`, `GOLDRUSH_PROXY_PASSWORD`, and `HEADLESS`

## Optional Configuration

```bash
export PLAYWRIGHT_PROXY_POST_LOAD_WAIT_MS=6000
export PLAYWRIGHT_PROXY_VIEWPORT=1366x768
export PLAYWRIGHT_PROXY_USER_AGENT="Mozilla/5.0 ..."
export PLAYWRIGHT_PROXY_LOCALE="en-US"
export PLAYWRIGHT_PROXY_TIMEZONE="America/New_York"
```

## Built-in Defaults

```bash
GOLDRUSH_PROXY_SERVER=http://goldrush-proxy.byteintl.net:1935
GOLDRUSH_PROXY_USERNAME=browserAmazon
HEADLESS=true
```

## Workflow

1. First try normal `playwright-cli` flow
2. If blocked, save snapshot, screenshot, and rendered HTML as evidence
3. Switch to proxy fallback using `proxy-access.js`
4. Record blocked evidence instead of pretending the product page was reached

## Notes

- The bundled script enables proxy, stealth hardening, stable UA/Locale/Timezone/Viewport defaults, and ignores HTTPS errors
- Keep proxy usage as a fallback path, not the default browser workflow
- If the saved title is still "Just a moment...", "Access Denied", or another challenge page, record blocked evidence
- This is the same proxy + stealth injection path used by Stage1 workflows

## References

- Main SKILL.md: `../SKILL.md`
- Playwright CLI Quickstart: `playwright_cli_quickstart.md`
- Proxy Fallback: `proxy-fallback.md`
- Evidence Capture: `evidence-capture.md`