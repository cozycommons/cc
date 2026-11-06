import json
import threading

import pytest

from app_runtime.backups import Backups, INTERVAL, RETRY
from app_runtime.core import Store


class Runtime:
    def __init__(self, state):
        self.state = state
        self.states = {"trip": "running", "other": "stopped"}
        self.stops = []
        self.starts = []
        self.fail = None
        self.current = None

    def status(self, name):
        return self.states[name]

    def container(self, name):
        self.current = name
        return self

    def stop(self, timeout):
        self.stops.append(self.current)
        self.states[self.current] = "stopped"

    def start(self):
        if self.fail == "start":
            raise RuntimeError("synthetic restart failure")
        self.starts.append(self.current)
        self.states[self.current] = "running"

    def archive(self, name, backup_id):
        (self.state / "backups" / backup_id / "workspace.tgz").write_bytes(b"synthetic")
        if self.fail == "archive":
            raise RuntimeError("synthetic archive failure")


@pytest.fixture
def setup(tmp_path):
    clock = [1000000.0]
    store = Store(tmp_path / "registry.sqlite3")
    runtime = Runtime(tmp_path)
    for name, status in runtime.states.items():
        store.put({"name": name, "status": status, "next_backup_at": clock[0] + INTERVAL})
    return Backups(store, runtime, tmp_path, clock=lambda: clock[0]), clock


def test_daily_schedule_survives_restart_and_skips_missed_intervals(setup):
    backups, clock = setup
    backups.tick()
    assert backups.list("trip") == []
    clock[0] += INTERVAL
    backups.tick()
    assert len(backups.list("trip")) == 1
    assert backups.runtime.states == {"trip": "running", "other": "stopped"}
    assert backups.runtime.starts == ["trip"]
    # A fresh scheduler uses persisted timestamps, not process uptime.
    restarted = Backups(backups.store, backups.runtime, backups.root.parent, lambda: clock[0])
    restarted.tick()
    assert len(backups.list("trip")) == 1
    clock[0] += 4 * INTERVAL
    restarted.tick()
    assert len(backups.list("trip")) == 2
    assert backups.store.get("trip")["next_backup_at"] == clock[0] + INTERVAL


def test_retention_is_per_app_and_includes_manual_backups(setup):
    backups, clock = setup
    ids = []
    for _ in range(5):
        clock[0] += INTERVAL
        backups.tick()
        ids.append(backups.list("trip")[0]["id"])
    assert [b["id"] for b in backups.list("trip")] == ids[-3:][::-1]
    assert len(backups.list("other")) == 3
    assert not (backups.root / ids[0]).exists()
    clock[0] += 1
    with backups.store.app_lock("trip"):
        manual = backups.create(backups.store.get("trip"))
    assert len(backups.list("trip")) == 3
    assert backups.list("trip")[0] == manual
    assert manual["kind"] == "manual"
    assert len(backups.list("other")) == 3


def test_failure_keeps_good_backups_removes_partial_and_retries(setup):
    backups, clock = setup
    for _ in range(3):
        clock[0] += INTERVAL
        backups.tick()
    previous = backups.list("trip")
    backups.runtime.fail = "archive"
    clock[0] += INTERVAL
    backups.tick()
    assert backups.list("trip") == previous
    assert len(list(backups.root.iterdir())) == 6
    record = backups.store.get("trip")
    assert record["status"] == "running"
    assert record["next_backup_at"] == clock[0] + RETRY
    assert "backup_pending" not in record
    backups.runtime.fail = None
    clock[0] += RETRY
    backups.tick()
    assert backups.list("trip") != previous
    assert len(backups.list("trip")) == 3
    assert "backup_error" not in backups.store.get("trip")


@pytest.mark.parametrize("complete", [False, True])
def test_recovers_interrupted_backup_but_never_failed_restore(setup, complete):
    backups, clock = setup
    backup_id = "a" * 32
    folder = backups.root / backup_id
    folder.mkdir(parents=True)
    if complete:
        (folder / "manifest.json").write_text(json.dumps({"app": "trip", "id": backup_id, "created": clock[0], "format": "workspace-v1"}))
    record = backups.store.get("trip")
    record.update(status="maintenance", backup_pending={"id": backup_id, "was_running": True})
    backups.store.put(record)
    backups.runtime.states["trip"] = "stopped"
    failed_restore = backups.store.get("other")
    failed_restore["status"] = "error"
    backups.store.put(failed_restore)
    backups.tick()
    assert backups.runtime.states["trip"] == "running"
    assert backups.store.get("trip")["status"] == "running"
    assert "backup_pending" not in backups.store.get("trip")
    assert folder.exists() == complete
    assert backups.store.get("other")["status"] == "error"
    assert backups.runtime.states["other"] == "stopped"


def test_restart_failure_recovers_without_duplicate_snapshot(setup):
    backups, clock = setup
    backups.runtime.fail = "start"
    clock[0] += INTERVAL
    backups.tick()
    assert len(backups.list("trip")) == 1
    assert backups.store.get("trip")["status"] == "error"
    backups.runtime.fail = None
    backups.tick()
    assert backups.store.get("trip")["status"] == "running"
    assert len(backups.list("trip")) == 1


def test_legacy_app_first_backup_due_in_one_day_and_loop_stops(setup):
    backups, clock = setup
    record = backups.store.get("trip")
    record.pop("next_backup_at")
    backups.store.put(record)
    backups.tick()
    assert backups.store.get("trip")["next_backup_at"] == clock[0] + INTERVAL
    stop = threading.Event()
    backups.tick = lambda **kwargs: stop.set()
    backups.run(stop)
    assert stop.is_set()


def test_scheduler_survives_temporary_registry_failure(setup):
    backups, _ = setup
    stop = threading.Event()
    stop.wait = lambda seconds: None
    attempts = []

    def tick(**kwargs):
        attempts.append(True)
        if len(attempts) == 1:
            raise OSError("synthetic storage failure")
        stop.set()

    backups.tick = tick
    backups.run(stop)
    assert len(attempts) == 2


def test_legacy_managed_database_and_backups_require_migration(setup):
    backups, clock = setup
    record = backups.store.get("trip")
    record["db_password"] = "legacy-test-only"
    backups.store.put(record)
    for n in range(4):
        folder = backups.root / f"{n:032x}"
        folder.mkdir(parents=True)
        (folder / "manifest.json").write_text(json.dumps({"id": folder.name, "app": "trip", "created": clock[0]}))
    clock[0] += INTERVAL
    backups.tick()
    assert len(backups.list("trip")) == 4
    assert "migration" in backups.store.get("trip")["backup_error"]
    assert "trip" not in backups.runtime.stops
    with pytest.raises(ValueError, match="legacy managed database"):
        backups.create(record)
