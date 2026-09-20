# Browser Session Management

Run multiple isolated browser sessions, persistent profiles, and concurrent browser automation.

## Named Browser Sessions

Use `-s` flag to isolate browser contexts:

```bash
# Browser 1: Authentication flow
playwright-cli -s=auth open https://example.com/login

# Browser 2: Public browsing (no shared cookies, storage)
playwright-cli -s=public open https://example.com

# Commands are isolated by browser session
playwright-cli -s=auth fill e1 "user@example.com"
playwright-cli -s=public snapshot
```

## Browser Session Isolation Properties

Each browser session has independent:
- Cookies
- LocalStorage / sessionStorage
- IndexedDB
- Permissions
- Browser instance

## Browser Session Commands

```bash
# List all browser sessions
playwright-cli list

# Stop a browser session (close the browser)
playwright-cli close              # stop the default browser
playwright-cli -s=mysession close # stop a named browser

# Stop all browser sessions
playwright-cli close-all

# Delete browser session user data (profile directory)
playwright-cli delete-data              # delete default browser data
playwright-cli -s=mysession delete-data # delete named browser data
```

## Environment Variable

Set a default browser session name via environment variable:

```bash
export PLAYWRIGHT_CLI_SESSION="mysession"
playwright-cli open example.com  # Uses "mysession" automatically
```

## Common Patterns

### Concurrent Scraping

```bash
#!/bin/bash
# Scrape multiple sites concurrently
playwright-cli -s=site1 open https://site1.com &
playwright-cli -s=site2 open https://site2.com &
playwright-cli -s=site3 open https://site3.com &
wait

# Snapshot from each
playwright-cli -s=site1 snapshot
playwright-cli -s=site2 snapshot
playwright-cli -s=site3 snapshot

# Cleanup
playwright-cli close-all
```

### A/B Testing Sessions

```bash
# Test different user experiences
playwright-cli -s=variant-a open "https://example.com?variant=a"
playwright-cli -s=variant-b open "https://example.com?variant=b"

# Compare
playwright-cli -s=variant-a screenshot
playwright-cli -s=variant-b screenshot
```

### Persistent Profile

By default, browser profile is kept in memory only. Use `--persistent` flag on `open` to persist the browser profile to disk:

```bash
# Use persistent profile (auto-generated location)
playwright-cli open https://example.com --persistent

# Use persistent profile with custom directory
playwright-cli open https://example.com --profile=/path/to/profile
```

## Default Browser Session

```bash
# These use the same default browser session
playwright-cli open https://example.com
playwright-cli snapshot
playwright-cli close  # stops default browser
```

## Browser Session Configuration

Configure a browser session with specific settings when opening:

```bash
# Open with config file
playwright-cli open https://example.com --config=.playwright/my-cli.json

# Open with specific browser
playwright-cli open https://example.com --browser=firefox

# Open with persistent profile
playwright-cli open https://example.com --persistent
```

## Best Practices

### 1. Name Browser Sessions Semantically

```bash
# GOOD: Clear purpose
playwright-cli -s=github-auth open https://github.com
playwright-cli -s=product-scraper open https://example.com/product

# BAD: Generic names
playwright-cli -s=browser1 open https://github.com
```

### 2. Clean Up After Use

```bash
# Stop browsers when done
playwright-cli -s=auth close
playwright-cli -s=scraper close

# Or stop all at once
playwright-cli close-all
```

### 3. Handle Zombie Processes

If browsers become unresponsive or zombie processes remain:

```bash
# Force kill all browser processes
playwright-cli kill-all

# Delete data for stuck sessions
playwright-cli -s=oldsession delete-data
```
