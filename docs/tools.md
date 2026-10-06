# Tools: the agent's contract

The written contract for the two Week 2 data tools, `get_sales_analytics` and
`check_inventory_status`. The domain code (`sales.py`, `inventory.py`), the LangChain wrappers
(`tools.py`), the MCP server and the system prompt all take their names, arguments and error
codes from here. If one of them disagrees with this doc, the doc is the spec.

Every example below was recomputed from `data/sales.csv` / `data/listings.csv`, and the sales
figures were cross-checked against SQ-01 and SQ-17 in `data/synthetic_queries/queries.jsonl`.

## 1. Seller binding

The domain functions take `seller_id`, matching `docs/tasks.md` #12's
`get_sales_analytics(seller_id, period)`:

```python
get_sales_analytics(seller_id: str, period: str) -> dict
check_inventory_status(seller_id: str, sku: str) -> dict
```

The **LLM-facing schema leaves `seller_id` out**. The tool layer fills it in from
`Settings.seller_id` (the `SELLER_ID` env var) before calling the domain function, so the model
only sees `period` / `sku`.

`SELLER_ID` has **no default**. If it's unset or blank, `load_settings()` raises at startup. A
fallback tenant would let a misconfigured process quietly serve one seller's data. Failing loudly
is the safer choice.

**`SELLER_ID` stands in for authentication, and only for this prototype.** In a real deployment
the tenant comes from who is logged in, not from process config. With an env var, one process
serves exactly one seller, and anyone who can reach it is treated as that seller. That's
acceptable here because the 6-pager scopes the build to a local, single-seller demo with no auth
requirement. It is not a production design.

What stays the same when real auth arrives is *where* the binding happens: the tool layer closes
over `seller_id`, and the LLM never sees or chooses it. Only the *source* changes:

```
now:     SELLER_ID env → Settings.seller_id → tools built once at startup
future:  login → session identity → seller_id → tools built per request
```

For Gradio that means `launch(auth=...)`, with `request.username` mapped to a `seller_id` inside
`chat.respond`. Over MCP, the stdio server already gets `SELLER_ID` per spawned subprocess. An
HTTP transport would read it from the auth token instead. Neither change touches the domain
functions or the tool schemas.

Why: this is tenant isolation, not a convenience. If `seller_id` were a tool argument, a prompt
injection hidden in a review, or just a confused model, could ask for another seller's data, and
nothing downstream could tell that request apart from a legitimate one. Keeping it out of the
schema means the model has no way to ask for another tenant's data.

The domain functions still check the tenant themselves. A `seller_id` with no rows gets
`NO_DATA_FOR_PERIOD` / `UNKNOWN_SKU`, never another seller's data and never a hint that the data
exists.

## 2. Result envelope

Every tool returns one of two shapes, and never raises for bad input:

```json
{"ok": true,  "data": { ... }}
{"ok": false, "error": {"code": "INVALID_PERIOD", "message": "..."}}
```

- `code` is a stable identifier from the table in §5. The prompt and the evals branch on it.
- `message` is written for the model to read, and the model sees it verbatim. It says what went
  wrong and, where it helps, what would work instead (the accepted period grammar, the last data
  date).
- An error is a normal result, not an exception. The agent loop passes it back to the model like
  any other tool output. Exceptions are kept for real bugs, such as a missing CSV.

## 3. `get_sales_analytics(period: str)`

Revenue, units and order lines for one inclusive date window, plus the prior equal-length window
for the trend.

### Period grammar

The input is normalised first: trimmed, lower-cased, and spaces/hyphens turned into underscores,
so `"last week"` and `"Last-Week"` both work. Dates are anchored on `prompts.TODAY`
(**2026-09-27, a Sunday**). The dataset is frozen, so the wall clock is never used. Weeks run
Mon–Sun.

| `period` | Window (with today = 2026-09-27) |
|---|---|
| `today` | 2026-09-27..2026-09-27 |
| `yesterday` | 2026-09-26..2026-09-26 |
| `this_week` | 2026-09-21..2026-09-27 (Monday → today) |
| `last_week` | 2026-09-14..2026-09-20 (previous Mon–Sun) |
| `last_7_days` | 2026-09-20..2026-09-26 (7 whole days ending yesterday) |
| `last_30_days` | 2026-08-28..2026-09-26 (30 whole days ending yesterday) |
| `this_month` | 2026-09-01..2026-09-27 (1st → today) |
| `last_month` | 2026-08-01..2026-08-31 |
| `YYYY-MM-DD` | that single day |
| `YYYY-MM-DD..YYYY-MM-DD` | inclusive range |

### Output `data`

| Field | Type | Meaning |
|---|---|---|
| `period` | str | The normalised period string as received |
| `start`, `end` | str (ISO date) | The resolved inclusive window |
| `revenue_usd` | float | Sum of `revenue_usd`, rounded to 2 dp once at the end (not per row) |
| `units_sold` | int | Sum of `units_sold` |
| `order_lines` | int | Number of `sales.csv` rows in the window. "Orders" in the requirements means order lines, the way SQ-01's expected answer counts them |
| `days_in_window` | int | Calendar days in the window (`end − start + 1`), so the model never has to count dates |
| `days_with_data` | int | Distinct dates in the window that have at least one row. Less than `days_in_window` means the window is only partly covered |
| `period_complete` | bool | `false` when `end` is on or after `data_end`, i.e. the window reaches the most recent recorded date and its totals may still grow (e.g. "September so far"). The prompt then calls it a partial period and never projects it. `previous` always ends before `start`, so it doesn't carry the field |
| `previous` | object \| null | `{start, end, revenue_usd, units_sold, order_lines, days_in_window, days_with_data}` for the window of the same length ending the day before `start`; `null` if that window has no rows |
| `data_start`, `data_end` | str (ISO date) | First and last dates this seller has any sales data |

`previous` is included because requirement #1 asks for "real figures … with a brief trend
summary; never estimates". A trend needs a baseline, and the no-estimation rule means that
baseline has to come from a tool, not from the model working out dates and calling again. The
prompt (w2-08) compares against `previous` only when it isn't null.

`days_in_window` and `days_with_data` appear on both windows because either one can be partly covered. The data
runs from 2026-08-03 to 2026-09-25, so a window that ends after `data_end` or starts before
`data_start` counts its missing days as zero. Two real examples:

| `period` | Current window | `previous` | Raw totals say | Per recorded day |
|---|---|---|---|---|
| `this_week` | $28,027.69 over **5 of 7** days | $41,904.71 over 7 of 7 | −33% | about −6% |
| `last_30_days` | $179,686.91 over 29 of 30 | $151,338.47 over **25 of 30** | +19% | about +2% |

This is the same rule as `NO_DATA_FOR_PERIOD`, applied to part of a window. When
`days_with_data < days_in_window` on either side, the prompt states the coverage ("5 of 7 days
recorded") or compares per-day averages instead of the raw totals. Both numbers come from the
tool, so the model compares two integers instead of doing date arithmetic, even for a custom
range like `2026-08-28..2026-09-26`.

### Errors

- `INVALID_PERIOD`: unknown keyword, malformed date, `start > end`, or `end` after today. The
  message lists the accepted grammar.
- `NO_DATA_FOR_PERIOD`: the resolved window has **zero rows** for this seller. The message names
  the seller's `last_data_date`. **No data is not the same as zero.** A window with no rows is
  never returned as `revenue_usd: 0`.

### Example: `last_week` (SQ-01)

```json
// get_sales_analytics(period="last_week")
{
  "ok": true,
  "data": {
    "period": "last_week",
    "start": "2026-09-14",
    "end": "2026-09-20",
    "revenue_usd": 41904.71,
    "units_sold": 904,
    "order_lines": 248,
    "days_in_window": 7,
    "days_with_data": 7,
    "previous": {
      "start": "2026-09-07",
      "end": "2026-09-13",
      "revenue_usd": 46283.07,
      "units_sold": 1000,
      "order_lines": 267,
      "days_in_window": 7,
      "days_with_data": 7
    },
    "data_start": "2026-08-03",
    "data_end": "2026-09-25"
  }
}
```

### Example: single day `2026-09-25` (SQ-17's fallback day)

```json
// get_sales_analytics(period="2026-09-25")
{
  "ok": true,
  "data": {
    "period": "2026-09-25",
    "start": "2026-09-25",
    "end": "2026-09-25",
    "revenue_usd": 6162.38,
    "units_sold": 142,
    "order_lines": 36,
    "days_in_window": 1,
    "days_with_data": 1,
    "previous": {
      "start": "2026-09-24",
      "end": "2026-09-24",
      "revenue_usd": 5565.09,
      "units_sold": 112,
      "order_lines": 31,
      "days_in_window": 1,
      "days_with_data": 1
    },
    "data_start": "2026-08-03",
    "data_end": "2026-09-25"
  }
}
```

### Example error: `yesterday` (SQ-17)

```json
// get_sales_analytics(period="yesterday")   → window 2026-09-26, no rows
{
  "ok": false,
  "error": {
    "code": "NO_DATA_FOR_PERIOD",
    "message": "No sales data for 2026-09-26..2026-09-26. The last date with sales data is 2026-09-25."
  }
}
```

### Example error: `fortnight`

```json
// get_sales_analytics(period="fortnight")
{
  "ok": false,
  "error": {
    "code": "INVALID_PERIOD",
    "message": "Unrecognised period 'fortnight'. Use one of: today, yesterday, this_week, last_week, last_7_days, last_30_days, this_month, last_month, YYYY-MM-DD, or YYYY-MM-DD..YYYY-MM-DD."
  }
}
```

## 4. `check_inventory_status(sku: str)`

Current stock and listing status for one SKU. Looking up a single SKU is the only operation this
week. There is no low-stock list (see `plan/w2-00-overview.md`, out of scope).

### Input

`sku` is trimmed and upper-cased, then has to match `^SKU-\d{4}$`. So `" sku-1001 "` is accepted.

### Output `data`

| Field | Type | Meaning |
|---|---|---|
| `sku` | str | Normalised SKU |
| `title` | str | Listing title |
| `stock_qty` | int | Units in stock, verbatim from `listings.csv` |
| `status` | str | Listing status, **verbatim** (`Active`, `Out of Stock`, …) |
| `price_usd` | float | Listing price |

`status` is never worked out from `stock_qty`. SKU-1013 and SKU-1020 return
`stock_qty: 0, status: "Active"`. The tool reports the
inconsistency as it is, so the agent can point it out instead of hiding it.

### Errors

- `INVALID_SKU`: after normalisation, the input doesn't match `SKU-\d{4}` (e.g.
  `"wall hanging"`). The message gives the expected format.
- `UNKNOWN_SKU`: the SKU is well-formed but isn't in this seller's catalog. A SKU that belongs
  to a different `seller_id` also gets `UNKNOWN_SKU`, so the error never reveals that another
  tenant has it.

Both are the "clear error for an unknown one" that `docs/tasks.md` #14's DoD asks for.

### Example: `SKU-1001`

```json
// check_inventory_status(sku="SKU-1001")
{
  "ok": true,
  "data": {
    "sku": "SKU-1001",
    "title": "Boho Wall Hanging - Macrame",
    "stock_qty": 6,
    "status": "Active",
    "price_usd": 34.99
  }
}
```

### Example: the fixture `SKU-1013`

```json
// check_inventory_status(sku="SKU-1013")
{
  "ok": true,
  "data": {
    "sku": "SKU-1013",
    "title": "Industrial Sconce Wall Sconce",
    "stock_qty": 0,
    "status": "Active",
    "price_usd": 75.6
  }
}
```

### Example errors

```json
// check_inventory_status(sku="SKU-9999")
{"ok": false, "error": {"code": "UNKNOWN_SKU", "message": "SKU-9999 is not in your catalog."}}

// check_inventory_status(sku="wall hanging")
{"ok": false, "error": {"code": "INVALID_SKU", "message": "'wall hanging' is not a SKU. Expected the form SKU-1234."}}
```

## 5. Error codes

| Code | Tool | Meaning | What the agent tells the seller |
|---|---|---|---|
| `INVALID_PERIOD` | `get_sales_analytics` | The period couldn't be parsed, the range is reversed, or it ends in the future | Say which time range it couldn't understand and suggest a supported one (e.g. "last week", or a date range). Don't guess a window. |
| `NO_DATA_FOR_PERIOD` | `get_sales_analytics` | The window has zero sales rows for this seller | Say plainly there's no sales data for that period and give the last date that has data. **Never report $0 or zero units.** Offer the last day/period that has data. |
| `INVALID_SKU` | `check_inventory_status` | The input isn't in `SKU-1234` form | Ask for the SKU code. If the seller gave a product name, say a lookup by name isn't supported yet. |
| `UNKNOWN_SKU` | `check_inventory_status` | The SKU is well-formed but not in the seller's catalog | Say that SKU isn't in their catalog and ask them to check the code. Don't invent stock figures. |

## 6. Memory tools

`save_preference` and its read-back counterpart are specced in `docs/memory.md` (w2-12), not here.
