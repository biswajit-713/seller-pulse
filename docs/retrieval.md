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
  resolver (not delivered by this thread — see the SQ-02 increment) must return candidates
  rather than pick a winner.

## Tier 1 scope: the five queries this app answers

`rag/retrieval.py` and `rag/stats.py` answer five of the sample-query set from scratch out of
`policy_kb` and `seller_reviews` alone — no sales or inventory data:

| Query | Path |
|---|---|
| SQ-06 — "Can you offer buyers a free gift for leaving a 5-star review?" | policy search |
| SQ-03 — "Draft a reply to this 2-star review complaining about late delivery." | policy + review search |
| SQ-18 — "...can I refund their shipping if they bump it to 4 stars?" | policy search |
| SQ-12 — "What are buyers complaining about most?" | `ReviewStats` (stats route) |
| SQ-13 — "Which product has my worst reviews?" | `ReviewStats` (stats route) |

Everything else in `queries.jsonl` is deliberately out of scope here. SQ-02 ("why is my Boho
Wall Hanging underperforming") needs sales/unit trend data; SQ-01, SQ-09, SQ-17, SQ-30, SQ-34,
SQ-35, SQ-37 and the rest of the sales/revenue questions need the sales tool; SQ-04, SQ-07,
SQ-21 through SQ-24, SQ-26, SQ-27 and SQ-36 need inventory data; SQ-05 and SQ-33 need memory.
This is the section that stops a reader from assuming the retrieval layer answers the full
26-query set — it answers five, by design, and the rest wait on Week 2's tools.

## Measured scores

From `uv run python -m seller_pulse.rag.evaluate`, 2026-10-01: **10/10 cases pass**, exit 0.

| Case | Query | Result |
|---|---|---|
| SR-01 (SQ-06) | free gift for a 5-star review | `pol-2a` 0.288, `pol-2b` 0.512 — both in top-3 |
| SR-02 (SQ-03) | draft a reply to a 2-star delivery complaint | `pol-2a` 0.620, `pol-5` 0.651; `REV-502` 0.356, `REV-508` 0.396 |
| SR-03 (SQ-18) | refund shipping if the rating goes up | `pol-2a` 0.544, `pol-2b` 0.601 — both in top-3 |
| SR-08 | discount code in exchange for a review (margin probe) | `pol-2b` 0.365 top-1; **margin 0.00877** (recorded 0.00800) |
| SR-09 (SQ-12) | what are buyers complaining about most | `low_rated_count` 17; distribution `{1:9, 2:8, 3:17, 4:31, 5:46}` — exact match |
| SR-10 (SQ-13) | worst-rated product | `SKU-1006`/`SKU-1088` tied at 2.0, `SKU-1075` at 2.5 — exact match |

The `pol-2b`/`pol-2a` margin (SR-08) is the most fragile number in this design — see `rag-02`'s
correction. The figure **0.002** recorded there and quoted in `rag-00` and `rag-11` is from the
reverted prototype and is stale; the live, current measurement is **0.008**, and the 2026-10-01
harness run above measured it at 0.00877 — drifting further from `warn_below: 0.004`, not
towards it, so the trend is healthy.

## The standing limit

Dense retrieval answers *"what does the data say about X"*. It cannot answer *"how many"* or
*"which is absent"*. Measured: top-k for "what are buyers complaining about most?" returns a
**5-star** review as its nearest hit, because a question *about* complaints is not textually
close to a complaint. SQ-12 and SQ-13 are answered by exact metadata scans and Python
aggregation, not by similarity — and SQ-19 ("which products have no reviews yet") cannot be
answered by retrieval at all, because the index contains only SKUs that *have* reviews.

The same gap shows up on single-item lookup, not just aggregates: SQ-18 ("the buyer who left me
a 1-star about shipping...") never surfaces `REV-586` in the top-6 review search — measured, it
ranks 12th at distance 0.835 against a top hit of 0.747. The question describes the review ("a
1-star about shipping") rather than echoing its words ("shipping delay again"), so similarity
search ranks it behind six unrelated reviews. See `docs/verification.md` for the measured ranks.

Write that down or somebody spends Week 3 tuning `k` to fix a counting problem.
