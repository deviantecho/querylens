# Use your own shop data

QueryLens 0.4.0 accepts an orders spreadsheet and creates a temporary analytics
workspace. The sample shop stays available, and public browser sessions keep
their uploads separate. The feature is available in the
[live app](https://querylens-deviantecho.onrender.com) and local installation.

## Four steps

1. Open **Your shop data** and choose a UTF-8 CSV or Excel `.xlsx` file.
   Put column names in the first row and one whole order in each following row.
   For a workbook, choose the orders worksheet; sheets are not combined.
2. Review the suggested column matches. Select a shop name, currency, number
   format, and text date format. Map each distinct order status to **completed**
   or **cancelled**, and confirm the displayed assumptions.
3. Choose **Check my data**. Fix any reported rows in the original file and
   upload it again. A successful check shows revenue, completed orders, average
   order value, refund rate, and a few normalized records. Compare these totals
   with your export before proceeding.
4. Choose **Import and open my shop**. Dashboard totals, charts, business rules,
   and reviewed queries now use that sheet. A failed check never replaces the
   active shop. To replace it, upload another sheet; to remove it, use
   **Remove uploaded data and use sample shop**.

Start with [this small example CSV](querylens/static/orders-template.csv).
It has three orders and two customers. Expected net revenue is USD 80.00,
completed orders 2, AOV USD 40.00, and amount-based refund rate 52.94%.

## Required and optional columns

| Field | Requirement and meaning |
| --- | --- |
| Order date | Required; an Excel date, `YYYY-MM-DD`, or the explicitly selected `DD/MM/YYYY` or `MM/DD/YYYY` text format |
| Order amount before refunds | Required; non-negative amount with at most two decimal places, before subtracting the refund |
| Order ID | Optional; must be non-empty and unique when provided. Without it, internal IDs are generated and duplicate orders cannot be detected. |
| Refund amount | Optional; defaults to zero. Must be non-negative and no larger than that order's amount. |
| Order status | Optional; defaults to completed. Confirm how each status should be counted; do not silently treat pending/unpaid orders as sales. |
| Customer ID | Optional; stable IDs support repeat-customer grouping and rankings. Without IDs, customer rankings are unavailable. |
| Customer name | Optional; requires customer IDs. A name alone is not used as a unique identity. |
| Customer region | Optional; enables regional reports. A customer ID must have consistent region/name/segment details throughout the file. |
| Sales channel | Optional; accepts your channel labels and enables channel reports. |
| Customer segment | Optional; accepts your segment labels. |
| Currency code | Optional; when matched, every row must agree with the currency selected for the upload. |

Order and customer identifiers are translated to internal numeric IDs so they
fit the existing models. Original identifiers are not exposed as additional
query columns. If customer IDs are present without names, generated display
labels use those IDs. Missing dimensions are marked Unspecified; QueryLens
rejects planned queries that explicitly reference an absent channel, region,
segment, or unavailable customer-name field.

Columns are suggested by their names, not silently inferred from their values.
Always check the matches. Both comma-separated and semicolon/tab-separated CSV
exports are recognized. An extra product, shipping, or tax column is ignored
unless matched to a supported field; this is an orders importer, not arbitrary
spreadsheet analytics.

## Money and order rules

- Net revenue is gross amount minus refunds on completed orders. Cancelled
  orders contribute zero net revenue and do not enter completed-order AOV.
- Fully refunded completed orders still count as completed orders in AOV.
- Refund rate is completed-order refund amounts divided by completed-order
  gross amounts. It is not the percentage of orders that received a refund.
- Supported currencies are USD, INR, EUR, GBP, CAD, AUD, SGD, and AED. Choose one
  currency per file. No exchange-rate lookup or conversion is performed.
- Choose `1,234.56` or `1.234,56` for text amounts. Actual numeric Excel cells
  are read as numbers. The selected currency symbol/code can precede an amount.
- Values are checked using decimal arithmetic before import. The existing
  DuckDB models store amounts as DOUBLE; this remains an analytics application,
  not an accounting ledger or a multi-currency financial system.

Combine line items into one row per order first. Duplicate order IDs are
rejected instead of being silently summed or discarded. Conflicting details
for a customer ID also need correction. A file with only cancelled orders can
produce undefined AOV/refund-rate values; these display as unavailable.

## Limits and data handling

| Boundary | Behavior |
| --- | --- |
| File | CSV or `.xlsx`, at most 2 MiB; no legacy `.xls` or macro-enabled files |
| Sheet | First-row unique headers, at most 50 columns, 10,000 orders, 100,000 cells, and two million characters of cell text |
| Values | At most 500 characters per cell; amounts from 0 to 1,000,000,000 with at most two decimal places |
| Reporting range | At most 3,660 days per upload |
| Workbook parsing | Read-only streaming, bounded ZIP expansion (16 MiB / 256 entries), XML protections, no external links, and no formula/error cells |
| Preview | In-memory parsed rows and validated snapshot; expires after 15 minutes |
| Capacity | Eight upload workspaces per server process, including pending previews |
| Query bounds | Existing read-only SQL policy, execution interrupt, database budget, and 200-row result cap still apply |

Your browser sends the file to the QueryLens server. The original upload is
not saved as a publicly accessible asset. Parsed rows are held temporarily;
committing writes a separate DuckDB warehouse and history database under an
application-generated temporary directory. Imported data never enters the
classifier's training corpus or saved benchmark reports. Local model prompts
receive the uploaded dataset's business context and schema, not the raw orders.

On the public demo, an upload belongs to the anonymous session cookie. Another
tab sharing that cookie shares the workspace. A different browser session
continues to see its own shop or the sample. Sessions expire after one hour of
inactivity or capacity eviction; expired workspace files are removed when the
session manager next cleans up. Reset and normal server shutdown also remove
the temporary workspace. Restart/crash ends access; free hosting has ephemeral
storage. Keep your source export and do not treat this as durable cloud storage.

Local mode is one shared workspace for the running local server, including
other browsers pointed at it. Sample-shop history remains local; uploaded-shop
history is temporary. Uploading/replacing/removing a shop invalidates reviewed
API plans, so an earlier plan cannot accidentally execute on a different sheet.

The free public app remains an anonymous demonstration. It has no accounts,
durable storage, data backups, enterprise access controls, or scheduled shop
sync. Use a local installation when that better fits your data handling needs.

## Questions you can ask

The nine existing report types work against the uploaded orders when their
required fields exist. For example, total revenue needs the amount/date fields;
channel revenue also needs a mapped channel; customer rankings need customer IDs.
The classifier still covers the same nine unfiltered report types. Uploading a
file does not train it on new questions or make it support arbitrary filters.
Use the SQL editor for filters or optional local Qwen/Ollama generation.

Business-context text and the local Qwen prompt use the upload's actual period,
currency, and available fields instead of the sample shop's 2025/USD assumptions.
The sample-data benchmark scores are unchanged and are not a measurement of
correctness on a shop's uploaded data. Review query meaning and totals yourself.

Product rankings, profit, advertising effectiveness, and forecasts remain
unsupported because this import does not supply their necessary data/models.

## API flow

All POST routes retain the existing Host, Origin, session-token, request-budget,
and public operation-slot controls. Upload IDs and preview IDs are scoped to the
current workspace.

| Route | JSON body / result |
| --- | --- |
| `POST /api/import/inspect` | `filename`, base64 `content`, optional `sheet`; returns sheet names, headers, first five rows, column suggestions, and `upload_id` |
| `POST /api/import/statuses` | `upload_id`, `column`; returns up to 50 distinct status values and suggested completed/cancelled classifications |
| `POST /api/import/validate` | `upload_id`, `mapping`, `options`; returns up to 20 row errors or checked totals and a `preview_id` |
| `POST /api/import/commit` | `upload_id`, `preview_id`; imports the server-held checked snapshot and returns the updated bootstrap payload |
| `POST /api/import/cancel` | `{}`; discards the pending preview while keeping the active shop |
| `POST /api/import/reset` | `{}`; removes the uploaded shop and returns the sample-shop bootstrap payload |

Inspection permits a 2,800,000-byte JSON envelope for the encoded file.
Validation permits 64,000 bytes; other POST bodies remain capped at 24,000 bytes.
`options` includes `shop_name`, `currency`, `date_format` (`iso`, `dmy`, `mdy`),
`decimal_mark` (`.` or `,`), `status_map`, and the required boolean confirmations
`one_row_per_order` and `confirm_defaults`. Column mappings use exact header names.
