import pytest

from seller_pulse.inventory import check_inventory_status

SELLER = "SELLER-001"


@pytest.mark.parametrize("sku", ["SKU-1001", " sku-1001 "])
def test_known_sku(sku):
    assert check_inventory_status(SELLER, sku) == {
        "ok": True,
        "data": {
            "sku": "SKU-1001",
            "title": "Boho Wall Hanging - Macrame",
            "stock_qty": 6,
            "status": "Active",
            "price_usd": 34.99,
        },
    }


@pytest.mark.parametrize("sku", ["SKU-1013", "SKU-1020"])
def test_zero_stock_active_fixture_reported_verbatim(sku):
    data = check_inventory_status(SELLER, sku)["data"]
    assert (data["stock_qty"], data["status"]) == (0, "Active")


def test_unknown_sku():
    result = check_inventory_status(SELLER, "SKU-9999")
    assert result["ok"] is False
    assert result["error"]["code"] == "UNKNOWN_SKU"
    assert "SKU-9999" in result["error"]["message"]


@pytest.mark.parametrize("sku", ["wall hanging", "SKU-10011", "1001", ""])
def test_invalid_sku(sku):
    result = check_inventory_status(SELLER, sku)
    assert result["error"]["code"] == "INVALID_SKU"
    assert "SKU-1234" in result["error"]["message"]


def test_other_tenant_gets_unknown_sku():
    result = check_inventory_status("SELLER-999", "SKU-1001")
    assert result["error"]["code"] == "UNKNOWN_SKU"
    assert "data" not in result
