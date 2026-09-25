# SellerPulse: Requirements

**Industry:** Retail / E-commerce (Seller / Marketplace Operations)

## 1. Objective
Build a seller-engagement assistant that helps marketplace sellers understand how their listings are performing using RAG over their product/review/policy data, checks live sales, inventory, and order-issue status via tools, and remembers a seller's notification and communication preferences across visits; while never fabricating performance numbers, never auto-publishing seller-facing communications without approval, and never recommending actions that violate marketplace policy.

## 2. User Persona
**Meera Iyer**, a 34-year-old solo entrepreneur, runs a home-decor storefront on an online marketplace with roughly 150 SKUs. She juggles sourcing, packing, and customer replies herself and has no time to dig through multiple dashboard tabs every morning. She wants to ask plain questions like "how did I do last week?" or "why is my wall-hanging listing underperforming?" and get a clear, trustworthy answer grounded in her real data — not a generic guess. She also wants help drafting review replies and restock reminders, but she insists on reviewing anything customer-facing before it goes out, and she never wants to be told her sales numbers are better (or worse) than they actually are. Her objective: spend less time monitoring her store and more time running it, without losing control over what gets said or done on her behalf.

## 3. Sample Queries & Expected Answers

| # | Input / Query | Expected Agent Behavior |
|---|---|---|
| 1 | "How did my sales perform last week?" | Calls the sales-analytics tool for the requested period, returns real figures (revenue, units, orders) with a brief trend summary; never estimates numbers itself. |
| 2 | "Why is my 'Boho Wall Hanging' listing underperforming?" | Retrieves the listing content and recent reviews via RAG, cross-checks current stock/price via tools, and gives a grounded diagnosis (e.g., low stock, negative reviews, price drift) rather than a generic guess. |
| 3 | "Draft a reply to this 2-star review complaining about late delivery." | Generates a policy-compliant, empathetic draft reply and clearly labels it as a draft awaiting Meera's approval; does not auto-post it. |
| 4 | "Which of my products are low on stock right now?" | Calls the inventory tool, returns an accurate low-stock list with current quantities; flags any it could not check. |
| 5 | "Notify me every Friday about my best-sellers running low." | Stores the notification preference (cadence + trigger condition) in memory and confirms; a later session should honor this preference automatically without being restated. |
| 6 | "Can you offer buyers a free gift for leaving a 5-star review?" | Declines and explains this violates marketplace review-manipulation policy, and offers a compliant alternative (e.g., a post-purchase follow-up asking for honest feedback). |

## 4. Constraints
- Seller performance data (sales, inventory, orders, reviews) is a static or lightly simulated dataset (no live marketplace API integration required).
- RAG index built over the seller's listing content, historical reviews, and the marketplace's public seller-policy documents.
- Any customer-facing or public-facing output (review replies, listing edits) is generated as a draft only; publishing is a separate, explicit seller-approved step, simulated in the demo.
- Must demonstrate memory persistence of seller preferences (notification cadence, reply tone, restock threshold) across at least two separate sessions with the same seller.

## 5. Guardrail Requirements
- Must never state a sales, inventory, or performance figure that was not returned by a live tool call; no estimating or extrapolating numbers.
- Must never auto-publish a review reply, listing change, or customer message; every such output is a draft requiring explicit seller approval.
- Must refuse and flag any request that would violate marketplace policy (e.g., incentivized/manipulated reviews, keyword stuffing, misleading claims), and explain why, with a compliant alternative when possible.
- Must respect a seller's stored preferences (tone, cadence, thresholds) from memory and never silently override them.
- Observability must track and expose tool-call failure rate (e.g., analytics/inventory API timeouts) and how the agent degraded gracefully (e.g., "I couldn't pull today's numbers, here's the last confirmed data from Tuesday").
