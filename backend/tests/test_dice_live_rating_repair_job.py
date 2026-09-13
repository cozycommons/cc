from jobs import dice_live_rating_repairs as job
import pytest


def test_repair_job_processes_every_pending_match(monkeypatch):
    monkeypatch.setattr(job, "list_pending_live_rating_repairs", lambda _client, _limit: ["m1", "m2"])
    repaired = []
    monkeypatch.setattr(
        job,
        "sync_live_result_rating",
        lambda _client, match_id, **kwargs: repaired.append((match_id, kwargs)),
    )

    assert job.repair_pending_live_ratings(object()) == 2
    assert repaired == [
        ("m1", {"bounded": True}),
        ("m2", {"bounded": True}),
    ]


def test_repair_job_records_failure_and_continues(monkeypatch):
    monkeypatch.setattr(job, "list_pending_live_rating_repairs", lambda _client, _limit: ["bad", "good"])

    def repair(_client, match_id, **_kwargs):
        if match_id == "bad":
            raise RuntimeError("offline")

    failures = []
    monkeypatch.setattr(job, "sync_live_result_rating", repair)
    monkeypatch.setattr(
        job,
        "record_live_rating_repair_failure",
        lambda _client, match_id, error: failures.append((match_id, str(error))),
    )

    assert job.repair_pending_live_ratings(object()) == 1
    assert failures == [("bad", "offline")]


def test_scheduled_repair_reports_failure_after_processing_the_batch(monkeypatch):
    monkeypatch.setattr(job, "list_pending_live_rating_repairs", lambda _client, _limit: ["bad", "good"])
    processed = []
    failures = []

    def repair(_client, match_id, **_kwargs):
        processed.append(match_id)
        if match_id == "bad":
            raise RuntimeError("offline")

    monkeypatch.setattr(job, "sync_live_result_rating", repair)
    monkeypatch.setattr(job, "record_live_rating_repair_failure", lambda _client, match_id, error: failures.append(match_id))
    with pytest.raises(RuntimeError, match="1 match.*1 repaired"):
        job.repair_pending_live_ratings(object(), raise_on_error=True)
    assert processed == ["bad", "good"]
    assert failures == ["bad"]
