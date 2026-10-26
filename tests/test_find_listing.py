import pytest

from seller_pulse.inventory import find_listing

SELLER = "SELLER-001"


def _skus(result: dict) -> list[str]:
    return [m["sku"] for m in result["data"]["matches"]]


@pytest.mark.parametrize(
    "name",
    ["Boho Wall Hanging", "BohoWall Hanging", "boho-wall hanging", "BOHO WALL HANGING - MACRAME", "Boho Wal Hanging"],
)
def test_resolves_name_variants_to_sku_1001(name):
    result = find_listing(SELLER, name)
    assert result["ok"] and _skus(result)[0] == "SKU-1001"


def test_ambiguous_name_returns_candidates_capped():
    result = find_listing(SELLER, "vase")
    assert result["ok"] and 1 < len(result["data"]["matches"]) <= 3
    assert result["data"]["truncated"] is True or len(result["data"]["matches"]) < 3


def test_no_match_is_unknown_listing():
    assert find_listing(SELLER, "Quantum Flux Capacitor")["error"]["code"] == "UNKNOWN_LISTING"


@pytest.mark.parametrize("name", ["", "  ", "a", "--", "vs"])
def test_too_short_is_invalid_name(name):
    assert find_listing(SELLER, name)["error"]["code"] == "INVALID_NAME"


def test_other_tenant_sees_unknown_listing():
    assert find_listing("SELLER-999", "Boho Wall Hanging")["error"]["code"] == "UNKNOWN_LISTING"
