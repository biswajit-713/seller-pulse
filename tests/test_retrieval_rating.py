import pytest

from seller_pulse.rag.retrieval import mentioned_rating


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("The buyer who left me a 1-star about shipping - can I refund their shipping if they bump it to 4 stars?", 1),
        ("Draft a reply to this 2-star review complaining about late delivery.", 2),
        ("Can you offer buyers a free gift for leaving a 5-star review?", 5),
        ("Reply to the 3 star review on the rug", 3),
        ("Reply to the one-star review on the mirror", 1),
        ("Who left a 1★ on the vase?", 1),
        ("Can I ask them to change it into a 5 star?", None),
        ("Help me reply to 2-star reviews about delivery", 2),
        ("The 1-star buyer - can I get them to raise it up to 5 stars?", 1),
        ("Should I ask the 1-star buyer to update their review to a 4-star?", 1),
        ("Compare my 1-star and 2-star reviews", None),
        ("What are buyers complaining about most?", None),
        ("Do I have 10 stars anywhere?", None),
    ],
)
def test_mentioned_rating(question: str, expected: int | None) -> None:
    assert mentioned_rating(question) == expected
