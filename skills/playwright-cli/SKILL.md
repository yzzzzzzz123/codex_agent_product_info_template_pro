---
name: playwright-cli
description: Automates browser interactions for web testing, form filling, screenshots, and data extraction. Use when the user needs to navigate websites, interact with web pages, fill forms, take screenshots, test web applications, or extract information from web pages. Start with normal `playwright-cli`; if access is blocked by risk control, geo/IP restriction, 403/429, or repeated navigation timeouts, fall back to the proxy-enabled Playwright flow documented in this skill.
---

# Browser Automation with playwright-cli

- Start with normal `playwright-cli` for interactive browsing, snapshots, DOM inspection, and page actions.
- For rendered HTML, screenshots, and snapshot evidence collection workflows, use [references/evidence-capture.md](references/evidence-capture.md).

## Operating policy

- If the normal flow hits "Just a moment...", "Please wait", "One more step", "security check", CAPTCHA, 403/429, geo/IP restriction, or repeated `goto` timeouts, switch to the proxy fallback in [references/proxy-fallback.md](references/proxy-fallback.md).
- In artifact collection workflows, use the proxy path only to recover rendered HTML, screenshots, and access evidence when the normal Playwright path cannot reach the real page.
- Do not leave `.playwright-cli/`, timestamped snapshots, console dumps, or page logs in the main repo root unless the user explicitly asked for those artifacts.
- If a workflow needs browser evidence, prefer running from the current site worktree so `.playwright-cli/` stays inside that worktree, or use explicit `--filename=...` paths for artifacts that must be kept.
- If the only evidence needed is only transient authoring comfort, prefer `--filename=...` outputs and clean up unnecessary `.playwright-cli/` leftovers before finishing the task.

## Quick start

```bash
# Open new browser
playwright-cli open https://example.com

# Navigate to a page
playwright-cli goto https://example.com/page

# Interact with the page using refs from the snapshot
playwright-cli click e15
playwright-cli type "search query"
playwright-cli press Enter

# Take a screenshot (rarely used, as snapshot is more common)
playwright-cli screenshot

# Close the browser
playwright-cli close
```

## Commands

### Core

```bash
playwright-cli open https://example.com
playwright-cli goto https://example.com/page
playwright-cli type "search query"
playwright-cli click e3
playwright-cli dblclick e7
playwright-cli fill e5 "user@example.com"
playwright-cli drag e2 e8
playwright-cli hover e4
playwright-cli select e9 "option-value"
playwright-cli upload ./document.pdf
playwright-cli check e12
playwright-cli uncheck e12
playwright-cli snapshot
playwright-cli snapshot --filename=after-click.yaml
playwright-cli eval "document.title"
playwright-cli eval "el => el.textContent" e5
playwright-cli dialog-accept
playwright-cli dialog-accept "confirmation text"
playwright-cli resize 1920 1080
playwright-cli close
```

### Navigation

```bash
playwright-cli go-back
playwright-cli go-forward
playwright-cli reload
```

### Keyboard

```bash
playwright-cli press Enter
playwright-cli press ArrowDown
playwright-cli keydown Shift
playwright-cli keys Shift
```

### Mouse

```bash
playwright-cli mousemove 150 300
playwright-cli mousedown
playwright-cli mousedown right
playwright-cli mouseup
playwright-cli mouseup right
playwright-cli mousewheel 0 100
```

### Save as

```bash
playwright-cli screenshot e5
playwright-cli screenshot --filename=page.png
playwright-cli pdf --filename=page.pdf
```

### Tabs

```bash
playwright-cli tab-list
playwright-cli tab-new
playwright-cli tab-new https://example.com
playwright-cli tab-select 0
playwright-cli tab-close
```

### Storage

```bash
playwright-cli state-save
playwright-cli state-save auth.json
playwright-cli state-load auth.json

# Cookies
playwright-cli cookie-list
playwright-cli cookie-list --domain=example.com
playwright-cli cookie-get session_id
playwright-cli cookie-set session_id abc123
playwright-cli cookie-set session_id abc123 --domain=example.com --httpOnly --secure
playwright-cli cookie-delete session_id
playwright-cli cookie-clear

# LocalStorage
playwright-cli localstorage-list
playwright-cli localstorage-get theme
playwright-cli localstorage-set theme dark
playwright-cli localstorage-delete theme

# SessionStorage
playwright-cli sessionstorage-list
playwright-cli sessionstorage-get step
playwright-cli sessionstorage-set step 3
playwright-cli sessionstorage-delete step
playwright-cli sessionstorage-clear

# Routing
playwright-cli route "**/*.jpg" --status=404
playwright-cli route "**/api/data" --body='{"mock": true}'
playwright-cli route-list
playwright-cli unroute "**/*.jpg"
playwright-cli unroute
```

### DevTools

```bash
playwright-cli console
playwright-cli console warnings
playwright-cli network
playwright-cli run-code "async page => await page.context().grantPermissions(['geolocation'])"
playwright-cli tracing-start
playwright-cli tracing-stop
playwright-cli video-start
playwright-cli video-stop video.webm
```

## Open parameters

```bash
# Use specific browser when creating session
playwright-cli open --browser=chrome
playwright-cli open --browser=chromium
playwright-cli open --browser=firefox
playwright-cli open --browser=msedge

# Connect to browser via extension
playwright-cli open --extension

# Use persistent profile (auto-generated location)
playwright-cli open --persistent

# Use persistent profile with custom directory
playwright-cli open --profile=/path/to/profile

# Start with config file
playwright-cli open --config=my-config.json
```

After each command, `playwright-cli` provides a snapshot of the current browser state.

```bash
playwright-cli goto https://example.com
playwright-cli snapshot
```

## Snapshots

```text
Page Title: Example Page
URL: https://example.com

### Snapshot
[snapshot]
```

You can also take a snapshot on demand using `playwright-cli snapshot`. The snapshot is saved to `.playwright-cli/snapshots/snapshot-{timestamp}.yaml`.

If `--filename` is not provided, a new snapshot file is created with a timestamp. Default to automatic file naming. Use `--filename=` when artifact is a part of the workflow result.

Low-visibility rule:

- Default to low-visibility execution when the current working directory is not the intended artifact directory
- Do not let default `.playwright-cli/` snapshots land in the main repo root during unrelated skill execution
- Use explicit `--filename=` paths for artifacts that must be kept, or run from inside a site worktree so `.playwright-cli/` stays inside that worktree

## Browser Sessions

```bash
# Create a new browser session named "my-session" with persistent profile
playwright-cli -s=my-session open https://example.com --persistent
playwright-cli -s=my-session snapshot

# List sessions
playwright-cli list

# Close all browsers
playwright-cli close-all

# Force kill all browser processes
playwright-cli kill-all
```

In some cases the user might want to install `playwright-cli` locally. If running globally available `playwright-cli` binary fails, use `npx playwright-cli` to run the commands. For example:

```bash
npx playwright-cli open https://example.com --persistent
```

## Example: Form submission

```bash
playwright-cli open https://example.com/login
playwright-cli snapshot

playwright-cli fill e1 "user@example.com"
playwright-cli fill e2 "password123"
playwright-cli click e3
playwright-cli snapshot
playwright-cli close
```

## Example: Multi-tab workflow

```bash
playwright-cli open https://example.com
playwright-cli tab-new https://example.com/page2
playwright-cli tab-list
playwright-cli tab-select 0
playwright-cli snapshot
playwright-cli close
```

## Example: Debugging with DevTools

```bash
playwright-cli open https://example.com
playwright-cli click e4
playwright-cli fill e7 "test"
playwright-cli tracing-stop
playwright-cli close
```

## Specific tasks

- **Proxy fallback for blocked or challenged pages**: [references/proxy-fallback.md](references/proxy-fallback.md)
- **Request mocking**: [references/request-mocking.md](references/request-mocking.md)
- **Running Playwright code**: [references/running-code.md](references/running-code.md)
- **Browser session management**: [references/session-management.md](references/session-management.md)
- **Storage state (cookies, localStorage)**: [references/storage-state.md](references/storage-state.md)
- **Test generation**: [references/test-generation.md](references/test-generation.md)
- **Tracing**: [references/tracing.md](references/tracing.md)
- **Video recordings**: [references/video-recording.md](references/video-recording.md)
- **Evidence capture for rendered HTML and snapshots**: [references/evidence-capture.md](references/evidence-capture.md)
