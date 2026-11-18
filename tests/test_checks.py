

def test_contains_folds_non_breaking_hyphens_and_narrow_spaces():
    from seller_pulse.evals.checks import _contains

    assert _contains("SKU‑1013 within 24 hours", set(), "SKU-1013")
    assert _contains("SKU‑1013 within 24 hours", set(), "24 hours")
