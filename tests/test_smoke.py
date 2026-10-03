from seller_pulse.inventory import catalog_size


def test_catalog_loads_all_listings():
    assert catalog_size() == 150
