"""Unit tests for the bookmark service: dedup, ranked-guard, duplicate-record
guard, confidence gate. BeliClient is faked — no network."""

from ig_logger.sinks.beli.logic import bookmark_name


class FakeClient:
    def __init__(self, bookmarked=(), ranked=(), predictions=(), business_detail=None):
        self.bookmarked = bookmarked
        self.ranked = ranked
        self.predictions = predictions
        self.business_detail = business_detail or {}
        self.writes = []

    def api_with_reauth(self, path, method="GET", body=None):
        if path.startswith("/api/user/logged-in/"):
            return {"uuid": "u1"}
        if path.startswith("/api/get-bookmark/"):
            return {"Restaurants": [{"business": {"id": i}} for i in self.bookmarked]}
        if path.startswith("/api/get-ranking/"):
            return {"results": [{"business": {"id": i}} for i in self.ranked]}
        if path.startswith("/api/search-app/"):
            return {"predictions": self.predictions}
        if path.startswith("/api/business/?id="):
            bid = int(path.split("id=")[1])
            d = self.business_detail.get(bid, {"id": bid, "name": "Resolved", "neighborhood": "X"})
            return [d]
        if path.startswith("/api/business/?place_id="):
            return [{"business": {"id": 777, "name": "Created Biz", "neighborhood": "Y"}}]
        if path.startswith("/api/add-bookmark/"):
            assert method == "POST"
            self.writes.append(body)
            return None
        raise AssertionError(f"unexpected path {path}")


def _pred(name, business=None, place_id=None, secondary="Somewhere"):
    return {
        "place_id": place_id,
        "business": business,
        "structured_formatting": {"main_text": name, "secondary_text": secondary},
    }


def test_already_bookmarked_no_write():
    c = FakeClient(bookmarked=(111,), predictions=[_pred("Table Mercato", business=111)])
    out = bookmark_name(c, "Table Mercato")
    assert out["status"] == "already_bookmarked"
    assert c.writes == []


def test_already_ranked_no_write():
    c = FakeClient(ranked=(222,), predictions=[_pred("Ceres", business=222)])
    out = bookmark_name(c, "Ceres")
    assert out["status"] == "already_ranked"
    assert c.writes == []


def test_duplicate_record_guard_reports_ranked():
    # Beli holds two records for one restaurant; the top hit is the unranked
    # duplicate, the second is the ranked one the user already rated.
    c = FakeClient(
        ranked=(1358080,),
        predictions=[
            _pred("Chrissy's Pizza", business=518218),
            _pred("Chrissy's Pizza", business=1358080),
        ],
    )
    out = bookmark_name(c, "Chrissy's Pizza")
    assert out["status"] == "already_ranked"
    assert out["business"]["id"] == 1358080
    assert c.writes == []


def test_ambiguous_writes_nothing():
    c = FakeClient(predictions=[_pred("Big Apple"), _pred("Lucali")])
    out = bookmark_name(c, "Bigapple Appetite")
    assert out["status"] == "ambiguous"
    assert len(out["candidates"]) == 2
    assert c.writes == []


def test_no_results():
    c = FakeClient(predictions=[])
    assert bookmark_name(c, "No Such Place")["status"] == "no_results"


def test_dry_run_would_bookmark():
    c = FakeClient(predictions=[_pred("Parla", business=744569)])
    out = bookmark_name(c, "Parla", dry_run=True)
    assert out["status"] == "would_bookmark"
    assert out["business"]["id"] == 744569
    assert c.writes == []


def test_live_write_via_place_id_get_or_create():
    c = FakeClient(predictions=[_pred("New Spot", place_id="ChIJ123")])
    out = bookmark_name(c, "New Spot")
    assert out["status"] == "bookmarked"
    assert out["business"]["id"] == 777
    assert c.writes == [{"user_id": "u1", "business_id": 777}]


def test_live_write_direct_business_id():
    c = FakeClient(predictions=[_pred("Parla", business=744569)])
    out = bookmark_name(c, "Parla")
    assert out["status"] == "bookmarked"
    assert c.writes == [{"user_id": "u1", "business_id": 744569}]


def test_ranking_failure_does_not_block_bookmark():
    class Flaky(FakeClient):
        def api_with_reauth(self, path, method="GET", body=None):
            if path.startswith("/api/get-ranking/"):
                raise RuntimeError("ranking down")
            return super().api_with_reauth(path, method, body)

    c = Flaky(predictions=[_pred("Parla", business=744569)])
    out = bookmark_name(c, "Parla")
    assert out["status"] == "bookmarked"
    assert len(c.writes) == 1
