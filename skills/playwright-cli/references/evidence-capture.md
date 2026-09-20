# Evidence Capture

Use normal `playwright-cli` when Stage1 needs rendered HTML, screenshots, or page-state evidence after direct HTML is not enough.

## Artifact discipline

- default to low-visibility execution
- do not leave `.playwright-cli/` snapshots, console logs, or page logs in the main repo root
- if you are inside a site worktree, keep browser side artifacts inside that worktree
- if you are not inside a site worktree, save only explicit named artifacts into a temporary or task-owned directory instead of relying on default timestamped outputs

## Common commands

```bash
playwright-cli open https://example.com
playwright-cli snapshot --filename=tmp/page_snapshot.yaml
playwright-cli click e3
playwright-cli fill e5 "text"
playwright-cli eval "document.title"
playwright-cli screenshot --filename=tmp/page.png
playwright-cli close
```

## Rendered HTML workflow

```bash
playwright-cli open https://example.com/product/1
playwright-cli snapshot --filename=raw_html/page_snapshot.yaml
playwright-cli screenshot --filename=raw_html/page_screenshot.png
playwright-cli eval "document.documentElement.outerHTML" > raw_html/rendered_page.html
playwright-cli eval "document.title"
playwright-cli eval "Array.from(document.querySelectorAll('h1')).map(x => x.textContent.trim()).filter(Boolean)"
```

## Blocked pages

- If the page keeps showing "Please wait", "Just a moment", "captcha", or "security check", do not pretend the real page loaded.
- Save snapshot, screenshot, and rendered HTML first.
- Only after the normal flow is confirmed blocked should you switch to [proxy-fallback.md](proxy-fallback.md).

## Cleanup expectation

- keep only the files that are part of the intended evidence set
- if normal `playwright-cli` generated incidental `.playwright-cli/` artifacts in the wrong place, clean them up before finishing the task
