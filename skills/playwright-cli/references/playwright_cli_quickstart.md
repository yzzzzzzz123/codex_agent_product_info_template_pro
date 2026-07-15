# Playwright CLI Quickstart

## Overview

`playwright-cli` is a browser automation tool for web testing, form filling, screenshots, and data extraction.

## Quick Start

```bash
# Open new browser
playwright-cli open https://example.com

# Navigate to a page
playwright-cli goto https://example.com/page

# Interact with the page using refs from the snapshot
playwright-cli click e15
playwright-cli type "search query"
playwright-cli press Enter

# Take a screenshot
playwright-cli screenshot

# Close the browser
playwright-cli close
```

## Core Commands

```bash
playwright-cli open https://example.com
playwright-cli goto https://example.com/page
playwright-cli type "search query"
playwright-cli click e3
playwright-cli fill e5 "user@example.com"
playwright-cli snapshot
playwright-cli eval "document.title"
playwright-cli close
```

## Open Parameters

```bash
# Use specific browser
playwright-cli open --browser=chrome
playwright-cli open --browser=chromium

# Use persistent profile
playwright-cli open --persistent

# Start with config file
playwright-cli open --config=my-config.json
```

## Snapshots

After each command, `playwright-cli` provides a snapshot of the current browser state:

```bash
playwright-cli goto https://example.com
playwright-cli snapshot
```

Snapshots are saved to `.playwright-cli/snapshots/snapshot-{timestamp}.yaml`.

## Browser Sessions

```bash
# Create a named browser session
playwright-cli -s=my-session open https://example.com --persistent
playwright-cli -s=my-session snapshot

# List sessions
playwright-cli list

# Close all browsers
playwright-cli close-all
```

## Form Submission Example

```bash
playwright-cli open https://example.com/login
playwright-cli snapshot

playwright-cli fill e1 "user@example.com"
playwright-cli fill e2 "password123"
playwright-cli click e3
playwright-cli snapshot
playwright-cli close
```

## Error Handling

If normal flow hits "Just a moment...", "Please wait", "security check", CAPTCHA, 403/429, or repeated navigation timeouts, switch to the proxy fallback documented in `proxy-fallback.md`.

## References

- Main SKILL.md: `../SKILL.md`
- Proxy Fallback: `proxy-fallback.md`
- Evidence Capture: `evidence-capture.md`
- Request Mocking: `request-mocking.md`
- Running Code: `running-code.md`
- Session Management: `session-management.md`
- Storage State: `storage-state.md`
- Tracing: `tracing.md`