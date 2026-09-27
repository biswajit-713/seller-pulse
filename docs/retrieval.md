# Retrieval: corpus coverage

Task 7's Definition of Done is "corpus covers all 6 sample queries in requirements.md." This
doc checks that claim against the six queries explicitly, rather than asserting it.

## Coverage by sample query

| # | Sample query | Covered by |
|---|---|---|
| 1 | "How did my sales perform last week?" | **Not corpus** — structured, Week 2 sales tool |
| 2 | "Why is my 'Boho Wall Hanging' listing underperforming?" | `SKU-1001` + `REV-501` (5★, "Beautiful and well made, arrived fast!") / `REV-504` (3★, "Cute but smaller than expected for the price.") |
| 3 | "Draft a reply to this 2-star review complaining about late delivery." | `REV-502` + `pol-5` (Communication with Buyers) + `pol-2a` (Review Guidelines) |
| 4 | "Which of my products are low on stock right now?" | **Not corpus** — structured, Week 2 inventory tool |
| 5 | "Notify me every Friday about my best-sellers running low." | **Not corpus** — memory, Week 2 |
| 6 | "Can you offer buyers a free gift for leaving a 5-star review?" | `pol-2a`, `pol-2b` (Review Guidelines — Enforcement Tiers) |

## Corpus counts

Taken from `rag/ingest.py`'s console output, not hand-written:

```
policy_kb      : 6 chunks (global, no tenant key)
seller_reviews : 111 chunks (seller_id=SELLER-001)
catalog        : 150 listings (structured, not embedded)
```

6 policy chunks · 111 reviews · 150 listings (not embedded)

## Corpus gaps worth knowing before querying it

- **65 of 150 SKUs have no reviews**, and the maximum on any SKU is 3. The "missing reviews"
  case from 6-pager Risk #6 is not rare — it is 43% of the catalogue.
- **111 reviews contain 24 unique comment strings.** This is why the listing title is joined
  into each review document (`rag/ingest.py`) — without it, near-duplicate comments across
  different SKUs would embed to the same vector.
- **"Boho Wall Hanging" matches three SKUs** — `SKU-1001`, `SKU-1011`, `SKU-1021` — and only
  `SKU-1001` has reviews. The ambiguous-product-name case from Risk #6 is live: a future
  resolver (Task 9) must return candidates rather than pick a winner.
