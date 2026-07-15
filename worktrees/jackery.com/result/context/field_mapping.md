# Field mapping

| Output field | Primary source | Fallback / validation |
|---|---|---|
| `source_url` | runtime `detail_url` | canonical URL |
| `source_item_name` | Shopify product JSON `title` | PDP `h1`; ProductGroup `name` |
| `source_pics` | product JSON `images[]` | ProductGroup `image[]` |
| `descriptions` | product JSON `description` blocks | ProductGroup `description` |
| `source_origin_price` | selected variant `compare_at_price / 100` | selected offer strikethrough price; activity price if compare-at is null |
| `source_activity_price` | selected variant `price / 100` | selected ProductGroup offer price; visible buybox |
| `source_price_currency` | Shopify shop/product page state | ProductGroup `priceCurrency`; US market lock |
| `props.Brand` | product JSON `vendor` | ProductGroup `brand.name` |
| `props.Product ID` | product JSON `id` | ProductGroup `productGroupID` |
| projected variant props | selected variant and option name | checked radio plus hidden product variant ID |
| base specifications | selected visible `.pdp-specs-v5-specs-variant .specs-item` | static DOM text |
| `status` | selected variant `available` | checked option disabled/sold-out state |
| `skus[]` | product JSON `variants[]` | `script#selected-variant`; ProductGroup `hasVariant[]` |
| SKU image | `variant.featured_image.src` | gallery media `variant_ids` mapping |
| review fields | `None` (basic mode) | page review data intentionally ignored |

The page is a multi-SKU PDP. Variant IDs and merchant SKUs are evidence fields, not standalone Stage3 SKU keys; the embedded contract stores the merchant SKU inside `sku_props`.
