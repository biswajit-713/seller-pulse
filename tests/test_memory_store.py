import json

import pytest

from seller_pulse.memory import PreferenceStore

SELLER = "SELLER-001"


def test_missing_file_reads_empty(tmp_path):
    assert PreferenceStore(tmp_path, SELLER).get_all() == {}


def test_write_then_read_back_in_new_store(tmp_path):
    saved = PreferenceStore(tmp_path, SELLER).upsert("restock_threshold", "5")

    pref = PreferenceStore(tmp_path, SELLER).get_all()["restock_threshold"]
    assert pref == saved
    assert (pref.value, pref.previous_value) == ("5", None)


def test_update_keeps_previous_value(tmp_path):
    store = PreferenceStore(tmp_path, SELLER)
    store.upsert("restock_threshold", "5")

    assert store.upsert("restock_threshold", "3").previous_value == "5"
    assert store.get_all()["restock_threshold"].value == "3"


def test_keys_are_independent(tmp_path):
    store = PreferenceStore(tmp_path, SELLER)
    store.upsert("notification_cadence", "weekly, every Friday: best-sellers at or below threshold")
    store.upsert("reply_tone", "short and warm, no emojis")

    assert set(store.get_all()) == {"notification_cadence", "reply_tone"}
    assert store.get_all()["reply_tone"].previous_value is None


@pytest.mark.parametrize("value", ["few", "-1", "2.5", "", "³"])
def test_threshold_must_be_whole_number(tmp_path, value):
    store = PreferenceStore(tmp_path, SELLER)
    with pytest.raises(ValueError):
        store.upsert("restock_threshold", value)
    assert store.get_all() == {}


def test_threshold_normalised(tmp_path):
    assert PreferenceStore(tmp_path, SELLER).upsert("restock_threshold", " 05 ").value == "5"


def test_unknown_key_and_blank_value_rejected(tmp_path):
    store = PreferenceStore(tmp_path, SELLER)
    with pytest.raises(ValueError):
        store.upsert("favourite_colour", "blue")
    with pytest.raises(ValueError):
        store.upsert("reply_tone", "   ")


def test_sellers_are_isolated(tmp_path):
    PreferenceStore(tmp_path, SELLER).upsert("reply_tone", "formal")
    assert PreferenceStore(tmp_path, "SELLER-002").get_all() == {}


@pytest.mark.parametrize("seller_id", ["../evil", "a/b", "", "x.json"])
def test_unsafe_seller_id_rejected(tmp_path, seller_id):
    with pytest.raises(ValueError):
        PreferenceStore(tmp_path, seller_id)


def test_delete(tmp_path):
    store = PreferenceStore(tmp_path, SELLER)
    store.upsert("reply_tone", "formal")

    assert store.delete("reply_tone").value == "formal"
    assert store.delete("reply_tone") is None
    assert store.get_all() == {}


def test_file_layout_and_no_temp_leftovers(tmp_path):
    PreferenceStore(tmp_path, SELLER).upsert("restock_threshold", "5")

    assert [p.name for p in tmp_path.iterdir()] == [f"{SELLER}.json"]
    record = json.loads((tmp_path / f"{SELLER}.json").read_text())["restock_threshold"]
    assert set(record) == {"value", "updated_at", "previous_value"}


def test_corrupt_file_raises_rather_than_reading_empty(tmp_path):
    (tmp_path / f"{SELLER}.json").write_text("{not json")
    with pytest.raises(json.JSONDecodeError):
        PreferenceStore(tmp_path, SELLER).get_all()
