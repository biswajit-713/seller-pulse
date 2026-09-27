# SellerPulse: PR/FAQ

**Author:** Bharat Maripi
**Status:** DRAFT (Task 3). Complete draft, ready for review. To be committed to the repo in Task 4.
**Last updated:** 2026-09-25

*Setukart is a fictional marketplace invented for this project. SellerPulse is the seller assistant built on it.*

---

# Press Release

## Why did this listing stop selling? Now you can just ask.

**SellerPulse gives Setukart sellers the root cause behind a drop in sales, in plain language and grounded in their own shop data.**

BENGALURU, 27 September 2026 — Setukart today introduced SellerPulse, an assistant built into the Setukart Seller Hub. Sellers can ask, in their own words, why a listing is slipping and get the reason behind it, drawn from their own listings, reviews, sales and stock in one place. SellerPulse never states a figure that did not come from those records, and it sends nothing to a buyer without the seller's approval.

"My mornings used to go into monitoring," said Meera Iyer, who sells handmade home décor on Setukart. "Four tabs, one product at a time, and I still ended up guessing. Now I ask one question and have the reason in a couple of minutes, with the review it came from sitting right there. Last week that was a size complaint on my wall hanging, and I fixed the listing before breakfast. The rest of that morning went into a new piece instead of hunting."

SellerPulse works like a colleague who has already read everything. A seller asks a question the way she would say it out loud, and the assistant brings together the listing, its recent reviews, and its sales and stock. It answers with a reason rather than a chart, and it names the review or listing detail behind that reason, so the seller can check it in a click.

Anything a buyer would see stays in the seller's hands. When a seller asks for help replying to a difficult review, SellerPulse writes a draft, labels it as a draft, and waits. Nothing is posted until the seller approves it. The assistant also knows Setukart's seller policy, so it will not suggest a tactic that breaks the rules. Asked about offering a discount for five-star reviews, it declines, quotes the rule, and offers a compliant alternative instead. Over time it remembers how each seller prefers to work: their reply tone, their alert frequency, and the stock level at which they want a reminder.

"Setukart is a bridge between makers and the homes their work ends up in," said Rhea Nambiar, Head of Seller Experience at Setukart. "Our job is matchmaking: the right piece reaching the right buyer. A seller who understands why a listing is slipping fixes it faster, and a seller who knows the rules never learns them from a suspension notice. Better listings and fewer breaches mean better matches, which is what buyers come to us for."

SellerPulse is rolling out to home and lifestyle sellers in the Setukart Seller Hub. Sellers can open it from any listing page and ask their first question.

---

# Frequently Asked Questions

## External FAQs (for sellers)

**Where do I find SellerPulse, and does it cost anything?**
SellerPulse lives inside the Setukart Seller Hub, and you can open it from any listing page. It is part of your seller account, so there is no separate sign-up. For individual sellers it is free at launch, because it is part of how Setukart invests in the seller experience rather than a paid add-on.

**Where do the numbers come from, and can I trust them?**
Every figure comes from your own shop records: your listings, your reviews, and your sales and stock. SellerPulse never estimates a number, and if a figure is unavailable it tells you so instead of filling the gap. Each reason it gives names the review or listing detail it came from, so you can open the source and judge for yourself.

**Will it post replies to my buyers on its own?**
No. When you ask for help with a review reply, SellerPulse writes a draft and labels it as a draft. Publishing is a separate step that only you can take. We built it this way deliberately, because a message to a buyer carries your name, and you should be the one who decides what it says.

**Can it see my competitors' data, or can they see mine?**
No, in both directions. SellerPulse reads only your own shop's data, and no other seller's assistant can reach it. It does not hold market or competitor data at all, which is also why it will not tell you what another seller is charging.

**What happens if it gets something wrong?**
It can be wrong, which is why every answer points at the evidence behind it. If something looks off, open the review or listing it cited and check. You can report a bad answer from the chat, and those reports feed the test set we use to measure and improve accuracy.

## Internal FAQs (for Setukart)

**Who is the target customer?**
Solo sellers who run their shop alone, carry roughly 100 to 200 listings, and handle sourcing, packing and buyer messages themselves. Meera Iyer, our home-décor persona, is the reference case. This is one narrow segment on purpose: they have the least time and the least analytical support.

**What is the problem, and how big is it?**
When a listing slips, the reason is scattered across dashboards, review text and policy documents, and the seller has to assemble it alone. We estimate this costs a solo seller 30 to 45 minutes on a typical morning, and it often ends in a guess. That estimate is a hypothesis drawn from the persona and sample data. We have not yet interviewed sellers, and we have no marketplace-wide count of how many fit this profile. Two to three interviews are planned before the Week 2 milestone, and those, with public marketplace statistics, are how we would size it before investing further.

**What alternatives did we investigate, and why is this the best one?**
Sellers already have the seller dashboard, manual review reading, spreadsheet exports and paid analytics tools. Each shows one kind of data, and none connects numbers to the reasons sitting in review text. A general chatbot looks like a shortcut. It can misread numbers, does not know Setukart's policy, and forgets a seller's preferences, so it can put an account at risk. SellerPulse is the same convenience with the marketplace's own data, rules and approval step around it.

**Why not simply let sellers use ChatGPT with their exported data?**
Because the four failures above are exactly the ones that matter here. Numbers must come from records rather than from a model, policy advice must be grounded in the published rules, preferences must persist, and buyer-facing text must wait for approval. Those are product guarantees, not prompt instructions.

**What does success look like?**
For sellers: less time to a trustworthy answer, measured from an estimated 30 to 45 minutes today to under two minutes, and drafts accepted without edits. For the system: the right source retrieved for at least nine of ten test questions, and at least five of six sample queries passing the expected-answers table. For Setukart: faster seller response to listing problems, and over time better listings feeding into GMV, since a better match between piece and buyer is what the marketplace is for. Guardrail metrics stay at zero: no fabricated figures, nothing published without approval, and no policy-violating advice.

**How do we stop it recommending something against policy?**
The seller policy handbook is part of what the assistant reads, so a refusal quotes the rule it relies on rather than asserting one. A separate check in code, independent of the prompt, blocks buyer-facing text from being published and verifies that every figure came from a tool. We keep a list of indirectly worded attempts, test against it each week, and extend it whenever one succeeds. Every refusal and every block is logged, so we can see what is being asked and how often.

**What happens when the assistant is wrong and a seller acts on it?**
The worst realistic case is a wrong diagnosis leading to an unnecessary change, such as a price cut that was not needed. We reduce the chance by filtering retrieval to the listing in question and citing sources, and we limit the damage by never letting the assistant act on the seller's behalf. Reported errors go into the test set, and accuracy is measured rather than assumed.

**How is it phased?**
Four weekly milestones, each ending in a live demo: a grounded diagnosis first, then live figures and memory, then guardrails and caching, then observability, evals and demo readiness. The first milestone is deliberately the riskiest part of the idea. Section 8 of the 6-pager holds the detail.

**What are the spillover effects for Setukart?**
Three we expect. Buyer trust should improve, since better listing detail and faster replies reduce the mismatch complaints that drive returns. Support load should fall for questions sellers can now answer themselves, although it may rise briefly while sellers learn what the assistant can do. Policy enforcement should shift earlier, since sellers learn a rule when they ask rather than from a suspension notice. That is better for them and cheaper for trust and safety. We do not expect a negative GMV effect, and we would monitor return rate and suspension rate as guardrails.

**What is the current status?**
This is a four-week prototype built on a realistic synthetic dataset for one seller. Nothing described here runs on real seller data yet, and the launch framing above is written as the target experience.

---

# Feature prioritisation list

P1 is what the launch cannot happen without. P2 would be missing if left out, but would not stop the launch. P3 is built only if there is time. "Won't have" is stated so nobody assumes it is coming.

| ID | Feature | Priority | Milestone |
|---|---|---|---|
| F1 | Grounded diagnosis of a slipping listing, with the review or listing detail cited | P1 | Week 1 |
| F2 | Figures only from tools; missing data stated, never estimated | P1 | Week 2 |
| F3 | Buyer-facing output as a draft, with approval as a separate step | P1 | Week 3 |
| F4 | Policy refusal that quotes the rule and offers a compliant alternative | P1 | Weeks 1 and 3 |
| F5 | Chat interface in the Seller Hub (Gradio in the prototype) | P1 | Week 1 |
| F6 | Memory of reply tone, alert frequency and restock threshold | P2 | Week 2 |
| F7 | Agent-trace panel showing tool calls and recalled preferences | P2 | Week 2 |
| F8 | Caching for repeated questions | P2 | Week 3 |
| F9 | Proactive morning brief: overnight orders, low stock, new reviews | P3 | Stretch |
| F10 | Hybrid search: keyword plus meaning, for exact codes like SKU-1001 | P3 | Stretch |
| F11 | Cost versus quality comparison across models | P3 | Week 4 stretch |
| — | Competitor comparison | Won't have | — |
| — | Price recommendations | Won't have | — |
| — | Sales forecasting | Won't have | — |
| — | Push notifications | Won't have | — |
| — | Buyer-facing chat | Won't have | — |
| — | Production deployment and scale | Won't have | — |

Note on F6: memory sits in P2 rather than P1 because a seller still gets a trustworthy diagnosis without it. It is what makes the assistant feel like it knows her, which is why it is the first thing built after the P1 set.
