"""Unit tests for Maple EXP run normalization, identity and rates."""

import pytest

from maple import logic
from tests.maple_fakes import FakeSupabase

ENTRY = {
    "date": "2026-11-24",
    "map": "Cave of Evil Eye III",
    "map_read": "The Cave of Evil Eye III",
    "level": 37,
    "party": 2,
    "class": "Assassin",
    "exp": 109994,
    "seconds": 3600.0,
    "mesos": 78650,
    "mesos_seconds": 3600.0,
    "potion_cost": 12000,
    "potion_seconds": 3600.0,
    "install": "0aa101ab55d142a8",
    "updated": 1792821863.86,
}


def test_normalize_overlay_entry():
    run = logic.normalize_run(dict(ENTRY))
    assert run["log_date"] == "2026-11-24"
    assert run["map"] == "Cave of Evil Eye III"
    assert run["level"] == 37 and run["party"] == 2
    assert run["exp"] == 109994 and run["seconds"] == 3600.0
    assert run["potion_cost"] == 12000
    assert run["source_install"] == "0aa101ab55d142a8"
    assert run["run_id"] == logic.compute_run_id(
        {
            "install": "0aa101ab55d142a8",
            "date": "2026-11-24",
            "map": "Cave of Evil Eye III",
            "level": 37,
            "party": 2,
            "class": "Assassin",
        }
    )


def test_run_id_ignores_totals_so_entries_upsert():
    """A log line's totals grow while the player stays on the map; its id
    must not, or every re-post would duplicate the line."""
    grown = dict(ENTRY, exp=220000, seconds=7200.0, updated=1792825463.0)
    assert logic.normalize_run(grown)["run_id"] == logic.normalize_run(dict(ENTRY))["run_id"]


def test_run_id_changes_with_key_fields():
    base = logic.normalize_run(dict(ENTRY))["run_id"]
    assert logic.normalize_run(dict(ENTRY, map="Line 2 <Area 1>"))["run_id"] != base
    assert logic.normalize_run(dict(ENTRY, party=1))["run_id"] != base
    assert logic.normalize_run(dict(ENTRY, install="otherinstall"))["run_id"] != base


@pytest.mark.parametrize(
    "bad",
    [
        {},
        {"date": "24/11/2026", "map": "X", "exp": 1, "seconds": 1},
        {"date": "2026-11-24", "map": "", "exp": 1, "seconds": 1},
        {"date": "2026-11-24", "map": "X", "exp": "lots", "seconds": 1},
        {"date": "2026-11-24", "map": "X", "exp": 1, "seconds": -5},
        {"date": "2026-11-24", "map": "X", "exp": 1, "seconds": 1, "level": 0},
        {"date": "2026-11-24", "map": "X", "exp": 1, "seconds": 1, "party": 7},
        {"date": "2026-11-24", "map": "X", "exp": 1, "seconds": 1, "estimated": "yes"},
        "not-a-dict",
    ],
)
def test_normalize_rejects_malformed(bad):
    with pytest.raises(logic.RunError):
        logic.normalize_run(bad)


def test_rates_mirror_the_overlay():
    view = logic.run_view(logic.normalize_run(dict(ENTRY)))
    assert view["exp_per_hour"] == 109994.0
    assert view["mesos_per_hour"] == 78650.0
    # net = mesos/hr - potion_cost/hr, the overlay's net_text arithmetic
    assert view["net_per_hour"] == 78650.0 - 12000.0


def test_rates_handle_missing_mesos_and_potions():
    entry = dict(ENTRY)
    del entry["potion_cost"], entry["potion_seconds"]
    view = logic.run_view(logic.normalize_run(entry))
    assert view["net_per_hour"] is None
    entry = dict(ENTRY, mesos=0, mesos_seconds=0)
    view = logic.run_view(logic.normalize_run(entry))
    assert view["mesos_per_hour"] is None and view["net_per_hour"] is None


def test_ingest_accepts_valid_and_reports_invalid():
    db = FakeSupabase()
    result = logic.ingest_runs(db, "user-1", [dict(ENTRY), {"date": "nope"}, dict(ENTRY, map="Other Map")])
    assert len(result["accepted"]) == 2
    assert result["rejected"] == [{"index": 1, "error": "date must be an ISO date (YYYY-MM-DD)"}]
    assert len(db.stores["maple_exp_runs"]) == 2


def test_ingest_repost_replaces_totals():
    db = FakeSupabase()
    logic.ingest_runs(db, "user-1", [dict(ENTRY)])
    grown = dict(ENTRY, exp=220000, seconds=7200.0)
    result = logic.ingest_runs(db, "user-1", [grown])
    assert result["accepted"] == [logic.normalize_run(dict(ENTRY))["run_id"]]
    rows = db.stores["maple_exp_runs"]
    assert len(rows) == 1 and rows[0]["exp"] == 220000


def test_ingest_batch_limit():
    with pytest.raises(logic.RunError):
        logic.ingest_runs(FakeSupabase(), "user-1", [dict(ENTRY)] * (logic.MAX_BATCH + 1))
    with pytest.raises(logic.RunError):
        logic.ingest_runs(FakeSupabase(), "user-1", {"runs": []})


def test_list_runs_and_map_stats_are_per_user():
    db = FakeSupabase()
    logic.ingest_runs(db, "user-1", [dict(ENTRY), dict(ENTRY, map="Line 2 <Area 1>", exp=66000, seconds=1800.0)])
    logic.ingest_runs(db, "user-2", [dict(ENTRY, map="Someone Elses Map")])
    runs = logic.list_runs(db, "user-1")
    assert {r["map"] for r in runs} == {"Cave of Evil Eye III", "Line 2 <Area 1>"}
    assert logic.list_runs(db, "user-1", map_name="Line 2 <Area 1>")[0]["exp"] == 66000
    assert logic.list_runs(db, "user-1", level=99) == []
    stats = logic.map_stats(db, "user-1")
    assert [s["map"] for s in stats] == ["Line 2 <Area 1>", "Cave of Evil Eye III"]  # best first
    line2 = stats[0]
    assert line2["best_exp_per_hour"] == 132000.0
    assert line2["avg_exp_per_hour"] == 132000.0
    assert line2["runs"] == 1 and line2["last_date"] == "2026-11-24"
