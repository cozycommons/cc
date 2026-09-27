"""Unit tests for the Beli app's pure logic (no network, no database)."""

import re

from beli import logic
from beli.beli_client import is_phone_identifier, login_body, results_of


def test_norm():
    assert logic.norm("Table Mercato") == "tablemercato"
    assert logic.norm("Lucali BK & Sons") == "lucalibkandsons"
    assert logic.norm(None) == ""


def test_confident_match_exact():
    businesses = [{"name": "Table Mercato"}, {"name": "Lucali"}]
    hit = logic.confident_match("table mercato", businesses)
    assert hit and hit[0]["name"] == "Table Mercato" and hit[1] == 1.0


def test_confident_match_near_exact():
    businesses = [{"name": "Lucali Bk"}]
    hit = logic.confident_match("Lucali", businesses)
    assert hit and hit[1] == 0.7


def test_confident_match_rejects_fuzzy():
    businesses = [{"name": "Big Apple"}, {"name": "Lucali"}]
    assert logic.confident_match("bigapple appetite", businesses) is None
    assert logic.confident_match("pizza", businesses) is None


def test_confident_match_empty():
    assert logic.confident_match("", [{"name": "X"}]) is None
    assert logic.confident_match("x", []) is None


def test_is_phone_identifier():
    assert is_phone_identifier("+19178872335")
    assert is_phone_identifier("9178872335")
    assert not is_phone_identifier("warner@example.com")
    assert not is_phone_identifier("not a phone")


def test_login_body_phone_vs_email():
    assert login_body("+19178872335", "pw") == {"phone_no": "+19178872335", "password": "pw"}
    assert login_body("a@b.com", "pw") == {"email": "a@b.com", "password": "pw"}


def test_results_of_envelopes():
    assert results_of([1, 2]) == [1, 2]
    assert results_of({"results": [1]}) == [1]
    assert results_of({"Restaurants": [{"id": 5}]}) == [{"id": 5}]
    assert results_of(None) == []
    assert results_of({"predictions": []}) == []


def test_resolve_day_passthrough():
    assert logic.resolve_day("2026-09-27") == "2026-09-27"
    assert logic.resolve_day(None) == logic.et_now().strftime("%Y-%m-%d")
    try:
        logic.resolve_day("funday")
        assert False, "should raise"
    except ValueError:
        pass


def test_parse_time_to_mins():
    assert logic.parse_time_to_mins("7pm") == 19 * 60
    assert logic.parse_time_to_mins("19:00") == 19 * 60
    assert logic.parse_time_to_mins("7:30 PM") == 19 * 60 + 30
    assert logic.parse_time_to_mins("12am") == 0
    assert logic.parse_time_to_mins("12pm") == 12 * 60
    assert logic.parse_time_to_mins("bogus") is None
    assert logic.parse_time_to_mins(None) is None


def test_hours_summary_open_closed():
    sets = [{"open_day": 6, "close_day": 6, "open_time": "17:00", "close_time": "23:00"}]
    assert logic.hours_summary(sets, 6, 19 * 60)["open"] is True
    assert logic.hours_summary(sets, 6, 12 * 60)["open"] is False
    assert logic.hours_summary(sets, 6, 19 * 60)["label"] == "5:00 PM – 11:00 PM"
    assert logic.hours_summary([], 6, None) == {"label": None, "open": None}


def test_hours_summary_overnight():
    sets = [{"open_day": 5, "close_day": 6, "open_time": "18:00", "close_time": "02:00"}]
    assert logic.hours_summary(sets, 5, 23 * 60)["open"] is True
    assert logic.hours_summary(sets, 6, 1 * 60)["open"] is True
    assert logic.hours_summary(sets, 6, 12 * 60)["open"] is False


def test_slots_for_business():
    payload = {
        "availability": [
            {"business": 123, "slots": ["7:00 PM", "7:30 PM"]},
            {"business": 456, "slots": ["8:00 PM"]},
        ]
    }
    slots = logic.slots_for_business(payload, 123)
    assert "7:00 PM" in slots and "8:00 PM" not in slots


def test_guess_city():
    assert logic.guess_city("best pizza in brooklyn 🍕") == "New York, NY"
    assert logic.guess_city("silver lake taco spot") == "Los Angeles, CA"
    assert logic.guess_city("some random caption") is None


def test_candidates_from_caption_pin():
    cands = logic.candidates_from_caption("📍 Table Mercato (East Village, Manhattan) is great")
    assert "Table Mercato" in cands


def test_candidates_from_caption_numbered_list():
    cands = logic.candidates_from_caption("our top 3:\n1. Lucali @lucali_bk\n2. Ceres @ceresnyc")
    assert "Lucali" in cands and "Ceres" in cands


def test_candidates_from_caption_mentions():
    cands = logic.candidates_from_caption("loved @lucali_bk last night")
    assert "Lucali Bk" in cands and "Lucali" in cands
    assert not any("beli_eats" in c.lower() for c in cands)


def test_candidates_from_caption_filters_junk():
    cands = logic.candidates_from_caption("the BEST nyc foodie guide part 3 @beli_eats")
    assert cands == []
