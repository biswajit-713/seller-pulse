"""Week 4 edge cases (w4-10): the deterministic halves of the no-match fallbacks."""

from seller_pulse.guardrails import find_ungrounded
from seller_pulse.rag.context import render_context
from seller_pulse.rag.retrieval import RetrievalMode, RetrievalResult


def test_empty_retrieval_renders_explicit_no_records_line():
    block = render_context(RetrievalResult(mode=RetrievalMode.GENERAL, question="Any review about zebras?"))
    assert "No records in the seller's data matched this question." in block
    assert "REV-" not in block


def test_review_id_not_in_context_is_flagged_as_ungrounded():
    block = render_context(RetrievalResult(mode=RetrievalMode.GENERAL, question="zebras"))
    ids, _figures = find_ungrounded("One buyer complained in [REV-777].", [block])
    assert ids == ["REV-777"]
