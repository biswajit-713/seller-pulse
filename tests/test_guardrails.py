import json

from seller_pulse.agent import ToolCallRecord
from seller_pulse.guardrails import annotate, check_output, find_ungrounded
from seller_pulse.memory import Preference
from seller_pulse.prompts import DRAFT_LABEL
from seller_pulse.router import Route

SOURCES = [json.dumps({"revenue": 4210.5, "previous_revenue": 3890})]


def test_derived_percent_is_sourced_forecast_is_not():
    answer = "Revenue $4,210.50, up 8.2% on $3,890.00. Expect $4,500 next week."
    assert find_ungrounded(answer, SOURCES) == ([], ["4,500"])


def test_underivable_percent_is_unsourced():
    assert find_ungrounded("Revenue $4,210.50, up 12%.", SOURCES) == ([], ["12"])


def test_derived_percent_needs_adjacent_sign():
    assert find_ungrounded("Up 8.2 points.", SOURCES) == ([], ["8.2"])


def test_negative_change_matches_absolute_value():
    assert find_ungrounded("Revenue down 7.6% to 3,890.", SOURCES) == ([], [])


def test_dates_are_not_percent_operands():
    assert find_ungrounded("Up 0.1%.", ["2026-09-27", "2026-09-28", "5"]) == ([], ["0.1"])


def test_ids_fabricated_and_unicode_hyphen():
    answer = "SKU‑1001 is fine; see REV-999 and REV-567, REV-999 again."
    assert find_ungrounded(answer, ["SKU-1001 REV-567"]) == (["REV-999"], [])


def test_unsourced_numbers_deduped_in_answer_order():
    assert find_ungrounded("1. 7 then 5 then 7.", ["nothing"]) == ([], ["7", "5"])


# --- check_output / annotate ---------------------------------------------------------------

SALES = ToolCallRecord(
    name="get_sales_analytics",
    args={"period": "last_week"},
    result={"ok": True, "data": {"revenue": 4210.5, "previous_revenue": 3890}},
)
POLICY_CONTEXT = "[pol-2a] Sellers must not offer incentives in exchange for reviews."
REFUSAL = (
    "I can't offer a free gift in exchange for a 5-star review — that breaks [pol-2a], "
    "and repeat violations can suspend the listing. Instead, send a neutral follow-up asking for honest feedback."
)


def check(answer, *, trace=(), context="", query="", preferences=(), routes=(Route.DATA,)):
    return check_output(
        answer,
        trace=list(trace),
        retrieved_context=context,
        query=query,
        preferences=list(preferences),
        routes=set(routes),
    )


def test_policy_refusal_flagged_and_text_unchanged():
    report = check(REFUSAL, context=POLICY_CONTEXT, query="Can I offer a free gift for a 5-star review?", routes={Route.POLICY})
    assert report.policy_refusal
    assert report.policy_clauses == ["pol-2a"]
    assert annotate(REFUSAL, report) == REFUSAL


def test_policy_refusal_needs_policy_route():
    report = check(REFUSAL, context=POLICY_CONTEXT, query="free gift for a 5-star review?", routes={Route.REVIEWS})
    assert not report.policy_refusal


def test_policy_refusal_needs_retrieved_clause_and_refusal_first():
    query = "free gift for a 5-star review?"
    not_retrieved = check(REFUSAL, context="[pol-9z] something else", query=query, routes={Route.POLICY})
    assert not not_retrieved.policy_refusal and not_retrieved.policy_clauses == []
    later = "Sure, here are some ideas. You can't offer a gift though [pol-2a]."
    assert not check(later, context=POLICY_CONTEXT, routes={Route.POLICY}).policy_refusal


def test_curly_apostrophe_refusal():
    answer = REFUSAL.replace("can't", "can’t")
    assert check(answer, context=POLICY_CONTEXT, query="5-star", routes={Route.POLICY}).policy_refusal


def test_draft_pending_and_text_unchanged():
    answer = f"{DRAFT_LABEL}\n\nHi Priya, thanks for letting us know the vase arrived chipped — we're sorry."
    report = check(answer, routes={Route.REVIEWS})
    assert report.draft_pending and not report.publish_claim
    assert annotate(answer, report) == answer


def test_publish_claim_gets_correction_line():
    answer = "I've posted the reply."
    report = check(answer)
    assert report.publish_claim
    assert annotate(answer, report) == (
        "I've posted the reply.\n\n⚠ Guardrail: nothing has been posted or sent — drafts wait for your approval."
    )


def test_publish_claim_variants():
    assert check("The message was sent to the buyer.").publish_claim
    assert check("I’ve published the listing change.").publish_claim
    assert not check(f"{DRAFT_LABEL} Review it before it's sent.").publish_claim


def test_fabricated_figure_and_id_annotated_derived_percent_not():
    answer = "Revenue $4,210.50, up 8.2% on $3,890.00. Expect $4,500 next week; see REV-999."
    report = check(answer, trace=[SALES])
    assert report.unverified_figures == ["4,500"]
    assert report.ungrounded_ids == ["REV-999"]
    assert annotate(answer, report) == (
        f"{answer}\n\n⚠ Guardrail: couldn't verify REV-999, 4,500 against this turn's tool results "
        "or retrieved data — treat as unverified."
    )


def test_saved_preference_is_a_source():
    pref = Preference(key="restock_threshold", value="5", updated_at="2026-09-20T00:00:00Z", previous_value=None)
    answer = "Your restock threshold is 5 units."
    assert check(answer).unverified_figures == ["5"]
    assert check(answer, preferences=[pref]).unverified_figures == []


def test_clean_grounded_answer_not_triggered():
    answer = "Revenue last week was $4,210.50, up 8.2% on $3,890.00."
    report = check(answer, trace=[SALES])
    assert not report.triggered
    assert annotate(answer, report) == answer
