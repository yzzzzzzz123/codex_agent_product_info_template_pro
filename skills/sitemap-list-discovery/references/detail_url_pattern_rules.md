# Detail URL Pattern Rules

## Pattern Types

`Detail_url_pattern` accepts four pattern kinds:

- `pattern`: plain string with optional `*` wildcard, such as `https://example.com/products/*`
- `regex`: Python regex, such as `regex /products/[^/]+/?$`
- `xpath`: XPath expression against the sitemap XML body, such as `xpath .//*[local-name()="url"]/*[local-name()="loc"][contains(text(), "/products/")]/text()`
- `raw_st`: raw substring match, such as `raw_st /products/`

## When To Use Each

- `pattern`: when the PDP family follows a clean prefix + slug shape and a wildcard is enough
- `regex`: when the PDP family requires a more precise path match
- `xpath`: when the sitemap XML body must be filtered structurally (for example, only `<loc>` entries whose text contains `/products/`)
- `raw_st`: when a simple substring match is enough and the sitemap corpus is already clean

## Hard Rules

- final delivery must be a real plain string, not a pseudo-template
- do not use `/products/*` or `/products/{slug}` as final `Detail_url_pattern`; final delivery must be a real plain string such as `https://example.com/products/*`
- do not treat a regex hit on raw HTML as proof that `Detail_url_pattern` is valid if the apparent URLs exist only inside embedded JSON / `<script>` state or JS/API templates
- when a plain string pattern already isolates the PDP family cleanly, prefer it over `regex` or `xpath`
- if the chosen root sitemap is only a sitemap index, do not claim that `Detail_url_pattern` on the root sitemap will recurse into child sitemaps; either choose a real child sitemap plus `Detail_url_pattern`, or keep root/index recursion inside `list_custom_code`

## Examples

### pattern

```
https://thriftbooks.com/static/sitemap/w/*
```

### regex

```
regex /products/[a-z0-9\-]+/?$
```

### xpath

```
xpath .//*[local-name()="url"]/*[local-name()="loc"][contains(text(), "/products/")]/text()
```

### raw_st

```
raw_st /products/
```

## Validation

Before finalizing `Detail_url_pattern`:

1. confirm the chosen sitemap source actually contains URLs matching the pattern
2. sample 3 to 5 matches and verify they are real PDPs (product signals)
3. ensure the pattern does not over-match non-PDP URLs
4. ensure the pattern does not under-match the real PDP family
