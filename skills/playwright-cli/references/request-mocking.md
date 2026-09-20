# Request Mocking

Mock, intercept, and block network requests.

## Basic Mocking

```bash
# Mock a GET request with a JSON response
playwright-cli route "**/api/users" --status=200 --content-type=application/json --body='[{"id":1,"name":"Alice"}]'

# Mock with a file as the response body
playwright-cli route "**/api/data" --body-file=./mock-data.json

# Return a specific status code
playwright-cli route "**/api/missing" --status=404

# Block requests by URL pattern
playwright-cli route "**/*.jpg" --status=404
playwright-cli route "**/analytics.js" --aborted

# Remove headers from requests
playwright-cli route "**/*" --remove-headers=Authorization

# Remove a route (stop mocking)
playwright-cli unroute "**/*.jpg"

# Remove all routes
playwright-cli unroute
```

## URL Patterns

- `**/api/users` — Wildcard in path
- `**/*.jpg` — Match file extensions
- `https://example.com/api/*` — Exact path match

## Advanced Mocking with run-code

For request body inspection, response modification, or delays, use `run-code`:

### Response Based on Request

```bash
playwright-cli run-code "async page => {
  await page.route('**/api/login', route => {
    const body = route.request().postDataJSON();
    if (body.username === 'admin') {
      route.fulfill({ status: 200, body: JSON.stringify({ token: 'mock-token' }) });
    } else {
      route.fulfill({ status: 401, body: JSON.stringify({ error: 'Invalid' }) });
    }
  });
}"
```

### Modify Response

```bash
playwright-cli run-code "async page => {
  await page.route('**/api/user', async route => {
    const response = await route.fetch();
    const json = await response.json();
    json.isPremium = true;
    await route.fulfill({ response, json });
  });
}"
```

### Simulate Network Failures

```bash
playwright-cli run-code "async page => {
  await page.route('**/api/offline', route => route.abort('InternetDisconnected'));
}"
```

Options: `failed`, `timedout`, `connectionreset`, `internetdisconnected`

### Delay Responses

```bash
playwright-cli run-code "async page => {
  await page.route('**/api/slow', async route => {
    await new Promise(r => setTimeout(r, 3000));
    route.fulfill({ status: 200, body: JSON.stringify({ data: 'loaded' }) });
  });
}"
```
