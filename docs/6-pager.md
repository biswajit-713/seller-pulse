# SellerPulse: 6-Pager

**Author:** Bharat Maripi
**Status:** Complete draft (Task 2), ready for review. To be committed to the repo in Task 4.
**Last updated:** 2026-09-21

---

## 1. Introduction

This memo proposes SellerPulse, a seller-engagement assistant for solo marketplace sellers. It addresses one problem: when a listing starts slipping, the reason is scattered across dashboards, review text and policy documents, and the seller has to piece it together alone. We propose an assistant that answers that question in plain language, grounded in the seller's own data. It never states a number a tool did not return, and it publishes nothing without her approval. The memo sets out the customer and the problem, the alternatives available today, and the proposed experience. It then covers goals and non-goals, success metrics, the main risks, and a four-week plan. We are asking readers to agree that this is a problem worth solving, and that the first milestone is the right place to start.

## 2. The customer and the problem

Meera Iyer runs a home-décor store of about 150 products on an online marketplace, and does the sourcing, packing and customer replies herself. When a listing starts slipping, the question she needs answered is not *whether* sales fell but *why*, and the answer is scattered. Sales figures live in one dashboard, stock levels in another, and the reasons live in review text that no dashboard reads. Take her Boho Wall Hanging. In the first half of September its sales slid from three units to two to one. Over the same weeks, its reviews moved from a five-star "beautiful and well made" to a three-star "smaller than expected for the price." The dashboard shows the decline, but connecting it to that review is left to Meera, product by product. So is ruling out stock or pricing as the cause. We estimate this costs a solo seller 30–45 minutes on a typical morning, and it often ends in a guess. A wrong guess is expensive: she might cut the price and give away margin, when the real fix is stating the size clearly in the listing. This problem statement is a hypothesis based on the persona and sample data. We will test it, including the time estimate, with two to three real sellers before the Week 2 demo.

## 3. What Meera does today, and why it isn't enough

Today, when a listing slips, Meera starts with the seller dashboard. It tells her that sales fell and by how much, but not why. To find the reason, she opens the product's reviews and reads them one by one, then checks stock and price on separate pages. She can export everything to a spreadsheet, but that only rearranges the numbers. The reasons still sit in review text she has to read herself. Paid analytics tools add richer charts and search-ranking data, but they are also built around numbers, and they cost a monthly fee. The gap is the same in every case: each tool shows one kind of data, and none connects them into a reason she can act on.

A general chatbot looks like a shortcut, but it fails where it matters most to her. It can misread or invent numbers when she pastes in her data. It does not know the marketplace's seller policy, so it may suggest a tactic like a discount code for a five-star review. Under the policy, that is a moderate violation with a seven-day listing suspension. It also forgets her preferences between sessions, and hands her replies that are easy to post without checking. What has changed is cost and speed. A model can now read a product's reviews and link them to its numbers in seconds, for well under a cent per question. What Meera needs is one place that connects her numbers, her reviews and the marketplace's rules, and that she can trust without double-checking.

## 4. Proposed solution

With SellerPulse, Meera asks her question the way she would ask a colleague, by typing it into a chat window. For example: "Why is my Boho Wall Hanging slipping?" SellerPulse replies that its sales fell from three units to one across the first half of September. It points to the likely reason: a recent three-star review saying the item is smaller than expected for the price. It confirms that stock is not the cause, since six units are available. It then suggests a fix: state the dimensions clearly in the listing, as the marketplace's listing standards already require. Instead of spending her morning hunting for the problem, Meera starts it knowing what to fix.

Meera can trust the answer because of how SellerPulse is built. Every number comes from her own sales and stock records, never from an estimate. If a figure is missing, it says so instead of guessing. Every reason points to the review or listing it came from, so she can check it herself. If she asks for something the marketplace forbids, such as a discount code for five-star reviews, SellerPulse declines. It quotes the policy line that forbids it, explains the risk, and offers an allowed alternative, like asking buyers for honest feedback. When it writes a reply to a buyer, it labels it as a draft, and nothing is posted until she approves it. It also remembers how she likes to work: her reply tone, how often she wants alerts, and the stock level that should trigger a restock reminder.

None of this is magic. SellerPulse draws on four sources only: her listings, her reviews, her sales and stock records, and the marketplace's seller policy handbook. For this build, those sources are a realistic synthetic dataset for a store of about 150 products. The first version is a working prototype Meera can chat with, built over four weeks and gaining one capability each week.

## 5. Goals and non-goals

This build has one primary goal: when a listing slips, Meera gets a diagnosis she can act on, grounded in her own data. Three promises make that diagnosis trustworthy, and each is a goal in its own right. Every number comes from her records rather than an estimate. Every reason names the review or listing it came from. Nothing buyer-facing is published without her approval. By the end of Week 4, SellerPulse should handle all six sample queries in the requirements, with the listing diagnosis and the policy refusal as the two that matter most. The build goal is a working local demo, backed by an eval score that is recorded in Week 4 and improves after error analysis.

Several things are deliberately out of scope. SellerPulse will not connect to a live marketplace, since the requirements call for a static, lightly simulated dataset. It will not compare Meera's listings with competitors, because it has no competitor data and any comparison would be a guess. It will not recommend specific prices, for the same reason. It will not forecast future sales; it explains what happened rather than predicting what comes next. It will not post anything on Meera's behalf, and that is a design decision rather than a temporary limit. The prototype will not send push notifications, so a preference like "tell me every Friday" is stored and applied the next time she opens it. It will not talk to buyers directly, because it is a tool for the seller. Finally, it will not be deployed to production or built for scale, since the deliverable is a local demo. Data is still keyed by seller, so support for more sellers stays possible later.

*Note for Section 8 (phasing): stock and sales confirmation inside an answer arrives with tools in Week 2; the Week 1 demo diagnoses from listings and reviews only.*

## 6. Success metrics

SellerPulse succeeds if Meera gets a diagnosis she can act on, quickly and without checking it twice. Today that work takes her an estimated 30 to 45 minutes across several tabs. Trust is hard to measure directly, so we use observable proxies: a draft reply approved without edits, and an answer acted on without reopening the dashboard. The three groups below separate the outcome for Meera, the system quality that produces it, and the limits that must never be crossed while chasing either. All figures are measured in testing against synthetic data, not with real sellers, so they indicate promise rather than proof.

| Metric | Type | Baseline | Target | Measured by |
|---|---|---|---|---|
| Time to a diagnosis Meera can act on | Output | 30–45 min | Under 2 min | Timed rehearsal (Task 33) |
| Draft replies approved without edits | Output (trust proxy) | — | 4 of 5 | Test sessions |
| Answers acted on without reopening the dashboard | Output (trust proxy) | — | Majority in testing | Test sessions |
| Right chunk in the top 3 results | Input | — | ≥ 9 of 10 test questions | Retrieval log (Task 9) |
| Sample queries passing the expected-answers table | Input | Recorded in Week 4 | ≥ 5 of 6 after error analysis | Eval harness (Tasks 27–30) |
| Answer latency | Input | — | Median under 3 seconds | Request traces (Task 26) |
| Cost per question | Input | — | Under $0.01 | Request traces |
| Fabricated figures | Guardrail | — | 0: no number appears unless a tool returned it | Eval + guardrail log |
| Buyer-facing content published without approval | Guardrail | — | 0 | Guardrail log |
| Policy violations recommended | Guardrail | — | 0, tested with the gift-for-review request and three rewordings | Eval (Task 21) |
| Tool failures handled with an honest fallback | Guardrail | — | 100% of simulated failures | Dashboard (Task 31) |

Tool failures are the one guardrail that is not held at zero, because failures will happen. What must hold is that every failure produces an honest fallback rather than a guess.

## 7. Risks and mitigations

Seven risks stand out. Each one has a mitigation we are actually building, not an intention to be careful. The fifth is the largest, because it questions the memo itself rather than the system.

| # | Risk | What it looks like | Mitigation | Where it lives |
|---|---|---|---|---|
| 1 | Wrong diagnosis | Retrieval returns another product's reviews; the answer sounds confident but is wrong | Every retrieval is filtered by SKU; every answer cites the review it used; top-three accuracy measured on ten test questions before the demo | Tasks 7–9 |
| 2 | Fabricated figure | The agent states a sales or stock number no tool returned | No number reaches Meera unless a tool returned it; a guardrail compares every figure against tool output; missing data is stated, never estimated | Tasks 13–14, 20 |
| 3 | Indirect policy violation | "How can I thank buyers who leave five stars?" slips past the check | The policy handbook is in the corpus, so refusals quote the rule; a list of reworded attempts is tested in Week 3 and extended whenever one succeeds | Tasks 19–21, red-team stretch goal |
| 4 | A draft treated as final | Meera posts a generated reply unchanged | Every buyer-facing output is labelled a draft; approval is a separate step in the interface; nothing publishes without it | Tasks 20, 25 |
| 5 | **The problem itself is wrong** | Meera is a persona; no seller has been interviewed | Two to three seller interviews of about twenty minutes before the Week 2 session; their questions become a list of twenty to thirty; the problem statement and the 30–45 minute estimate are corrected if they differ | Task 6 and the eval set |
| 6 | Synthetic data too clean | The demo works, but reality would not | Awkward cases are seeded on purpose: missing reviews, ambiguous product names, and a listing still active after stock ran out. Sellers validate the questions, not their own data, which stays with them | Task 6 |
| 7 | Tool or API failure during the demo | A live call times out mid-answer | Fall back to the last confirmed data with an honest message; failure rate visible on the dashboard; a recorded backup demo exists | Tasks 26, 31–32, 34 |

## 8. Phasing

SellerPulse is built in four weekly milestones, each ending in a live demo. Every week adds one capability and keeps everything built before it. Because there is no session on the weekend of 10–11 October, the four milestones spread across five calendar weeks.

| Week | Demo goal | What Meera can do by the end | Not yet true |
|---|---|---|---|
| 1 | Gradio chat with a RAG-grounded diagnosis | Ask why a listing is slipping and get a reason drawn from her listings and reviews | No live numbers, so no stock or sales confirmation; no memory; guardrails not enforced in code |
| 2 | Tools, MCP and memory | Get exact sales and stock figures, and have her preferences remembered between visits | Guardrails still rely on the prompt; no caching |
| 3 | Guardrails and caching | See policy refusals with the rule quoted, drafts labelled for approval, and faster repeat answers | Quality is not yet measured; no observability |
| 4 | Observability, evals and demo readiness | The same experience, now traced, scored against the expected answers, and rehearsed | Not deployed; still one seller and synthetic data |

The first milestone is deliberately the riskiest part of the idea: can the agent give a grounded reason rather than a generic guess? Everything after it adds accuracy, safety and proof.

