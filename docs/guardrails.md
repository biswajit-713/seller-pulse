# Guardrails

The rules SellerPulse must never break, where each comes from, and which layer enforces it.
Requirement: `docs/requirements.md` §5 (Guardrail Requirements). Build plan:
`plan/week-3/gr-00-overview.md` (`docs/tasks.md` #19–#21).

Four layers enforce these rules, from strongest to weakest:

- **Structural**: the agent has no way to do the forbidden thing at all.
- **Prompt**: rules in the system prompt (`prompts.py`) that the model is told to follow.
- **Runtime check**: deterministic code that inspects the finished answer before the seller
  sees it.
- **Eval**: offline cases scored by deterministic checks and an LLM judge (`docs/evals.md`).

The runtime check is planned, not built yet. Rows marked *(gr-03/gr-04)* name functions that
those tasks add. Until then those rules rely on the prompt, structural and eval layers only.

## 1. Rules

| Rule | Requirement (§5) | Enforced by | Verified by |
|---|---|---|---|
| **G1 — No fabricated figures or ids.** Every sales, inventory or performance figure must come from a tool call made in this turn (or the review statistics in the retrieved context). Never estimate, extrapolate or invent a SKU, review or policy id. | b1: "Must never state a sales, inventory, or performance figure that was not returned by a live tool call; no estimating or extrapolating numbers." | **Prompt:** `CORE` "Grounding and citation" + "Data you don't have"; `_DATA` "Figures come from tools" (tool error codes → plain statement, never zero or an estimate). **Runtime** *(gr-03/gr-04)*: `guardrails.check_output` lists figures and ids that no source carries, and `guardrails.annotate` appends a caution line. | **Eval:** `evals/checks.py:check_groundedness` on every case (a fabricated id fails the case; an unsourced number goes to the judge); AE-06 (no forecast), AE-10 (no competitor data). |
| **G2 — No auto-publish.** A review reply, listing change or buyer message is always a draft that needs the seller's explicit approval. Never say or imply it was posted or sent. | b2: "Must never auto-publish a review reply, listing change, or customer message; every such output is a draft requiring explicit seller approval." | **Structural:** no publish, post or send tool exists. `router.ROUTE_TOOLS` binds only the two analytics tools and the two preference tools, so the agent cannot publish anything. **Prompt:** `CORE` "Drafts vs. internal notes": every customer-facing output opens with `prompts.DRAFT_LABEL` ("DRAFT — for your approval, not sent."). **Runtime** *(gr-03/gr-04)*: `draft_pending` is set when the label is present; a "posted/sent" claim gets a correction line. | **Eval:** AE-11 (SQ-03 review reply), AE-08 (buyer message in a refusal). **Live:** §5 below. |
| **G3 — Refuse policy-violating requests, explain why, offer an alternative.** Covers incentivised or manipulated reviews, keyword stuffing, misleading claims and price anchoring. | b3: "Must refuse and flag any request that would violate marketplace policy (e.g., incentivized/manipulated reviews, keyword stuffing, misleading claims), and explain why, with a compliant alternative when possible." | **Prompt:** `CORE` "Policy tripwire" (on every turn, so a routing miss still ends in a short refusal); `_POLICY` refusal procedure: refuse in the first sentence, cite the `pol-` clause, give the enforcement tier, offer a compliant alternative, and for a remedy tied to a review, draft the buyer message. **Runtime** *(gr-03/gr-04)*: `policy_refusal` is flagged when the `policy` route ran, the answer cites a `pol-` clause that was retrieved this turn, and the first sentence refuses. | **Eval:** AE-05 (SQ-06 free gift), AE-07 (SQ-14 keyword stuffing), AE-08 (SQ-18 refund for a rating), AE-09 (SQ-25 unsupported claims). **Live:** §5 below. |
| **G4 — Respect stored preferences.** Apply the saved tone, cadence and restock threshold without being asked. On a conflict, point it out and ask which to use; never silently override a preference. | b4: "Must respect a seller's stored preferences (tone, cadence, thresholds) from memory and never silently override them." | **Prompt:** `prompts.render_preferences` (saved preferences plus their rules, on every turn regardless of route); memory tool descriptions (`tools.py`) require confirming a change as old → new. | **Eval / live:** `docs/memory.md`, w2-15 two-session run. **Not runtime-checked:** whether a reply matches a tone can't be checked deterministically. |
| *Observability* | b5: tool-call failure rate and graceful degradation exposed. | Out of scope here: Week 4 (`docs/tasks.md` #26, #31). Degradation wording is already in `_DATA` (tool error codes). | AE-04 (no data for the period), AE-20 (fault injection: `today` times out). |

## 2. The runtime check *(gr-03/gr-04)*

`guardrails.check_output` runs in `chat.respond` on the model's final answer, after the
tool loop and before the answer is returned. It makes no model call and never regenerates the
answer.

- **Sources** a figure or id can come from:
  - this turn's tool calls (arguments and results)
  - the retrieved context block exactly as the model saw it
  - the seller's message
  - saved preference values (a `restock_threshold` may be stated)
  - the dates `TODAY`, `DATA_START` and `DATA_END`

  This is the same set `check_groundedness` uses in the eval, plus preferences. Earlier
  assistant turns and the system prompt's example wording are **not** sources.
- **Matching** uses one tokeniser shared with the eval (it moves from `evals/checks.py` into
  `guardrails.py`). It works on canonical numbers, so `$41,904.71`, `41904.71` and
  `41,904.71` match each other while `904` never matches inside `9045`. Ids are matched by
  form (`SKU-1234`, `REV-123`, `pol-2a`), and Unicode hyphens are converted to `-` first.
- **Derived percentages count as sourced.** A `%` value counts as sourced when it equals
  `round((a-b)/b*100, 1)` for two numbers in the sources, which is exactly the derivation
  `_DATA` allows. Example: tool revenue 4210.50 against a previous 3890.00. "Up 8.2%" passes;
  "about $4,500 next week" is flagged.
- **What changes the answer text** (`guardrails.annotate`):
  - Unverified figures or ids: the answer is kept and this line is appended:
    `⚠ Guardrail: couldn't verify <…> against this turn's tool results or retrieved data — treat as unverified.`
  - A claim that something was posted or sent: this line is appended:
    `⚠ Guardrail: nothing has been posted or sent — drafts wait for your approval.`
- **Status only, no text change:** `draft_pending` and `policy_refusal` (with the cited clause
  ids). They show up in the per-turn log line, the Agent trace panel and, later, the #25
  badges.

## 3. Decisions

- **Annotate, don't block.** A plain match against the sources can't tell a legitimately
  derived number from an invented one. Blocking would throw away correct answers, so the
  seller sees the answer plus a caution line.
- **The policy check looks only at the answer.** There is no input-side policy classifier: no
  router schema change and no extra model call. The `policy` route plus the prompt's refusal
  procedure produce the refusal, and the runtime layer recognises it and checks that the
  clause it cites was actually retrieved.
- **Tool results stay trusted structured data.** They are SKUs, integers and status values
  from the seller's own CSVs, so they reach the model without sanitising. This closes the
  "see task #20" note in `sanitize.py`. Retrieved documents and seller text are still
  sanitised (`sanitize.py`).

## 4. Known limits

- **A customer-facing draft that is missing its label isn't detected.** The runtime check
  only sees the label when it is there. Telling an unlabelled reply apart from an ordinary
  answer would need a classifier, so this relies on the prompt and AE-11.
- **The refusal markers are a heuristic.** `policy_refusal` needs one of: `can't`, `cannot`,
  `won't`, `will not`, `not allowed`, `isn't allowed`, `decline` in the first sentence. A
  refusal worded differently goes unflagged, but the answer itself is unchanged.
- **The publish-claim pattern is a heuristic.** It matches "I've / I have posted|published|sent"
  and "has / have been / was / were posted|published|sent". It must not fire on the draft
  label's own "not sent".
- **Figures inside a draft are checked too.** A delivery promise like "3–5 days" with no source
  gets flagged. That is intended: a draft must not promise what the data doesn't show.
- **Preferences (G4) are not runtime-checked**; see the table.

## 5. Test runs

*To be filled by `plan/week-3/gr-06-verification.md`: SQ-06 and SQ-03 transcripts (answer,
guardrail log line, trace panel text) and the AE-05 / AE-11 eval results.*
