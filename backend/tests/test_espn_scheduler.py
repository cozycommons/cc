"""Unit tests for the ESPN server-side lineup scheduler (espn/scheduler.py).

Everything is mocked: the account list, the lineup runner, and the
run-log table. No live ESPN or Supabase calls. Covers the due-slot
math (incl. both DST transitions), the fan-out's isolation and
dedupe, and the container entry point's exit codes.

Reference day for the fan-out tests: Thu 2026-10-29, still on EDT
(UTC-4). The morning slot window is 09:00-12:00 ET = 13:00-16:00 UTC;
NOW inside it is 14:00 UTC (10:00 ET).
"""

from datetime import datetime, timezone

import pytest

from espn import scheduler
from espn.espn_client import EspnAuthError

NOW = datetime(2026, 10, 29, 14, 0, tzinfo=timezone.utc)  # 10:00 EDT


def _utc(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


def _due_names(now):
    return [slot.name for slot in scheduler.due_slots(now)]


# --- due-slot math -------------------------------------------------------------


def test_morning_slot_boundaries():
    assert _due_names(_utc(2026, 10, 29, 13, 0)) == ["morning"]  # 09:00 ET
    assert _due_names(_utc(2026, 10, 29, 12, 59)) == []  # 08:59 ET
    assert _due_names(_utc(2026, 10, 29, 15, 59)) == ["morning"]  # 11:59 ET
    assert _due_names(_utc(2026, 10, 29, 16, 0)) == []  # 12:00 ET: window over


def test_evening_slot_boundaries():
    assert _due_names(_utc(2026, 10, 29, 22, 29)) == []  # 18:29 ET
    assert _due_names(_utc(2026, 10, 29, 22, 30)) == ["evening"]  # 18:30 ET
    assert _due_names(_utc(2026, 10, 30, 1, 29)) == ["evening"]  # 21:29 ET
    assert _due_names(_utc(2026, 10, 30, 1, 30)) == []  # 21:30 ET: window over


def test_nothing_due_outside_windows():
    assert _due_names(_utc(2026, 10, 29, 7, 0)) == []  # 03:00 ET
    assert _due_names(_utc(2026, 10, 29, 19, 0)) == []  # 15:00 ET
    assert _due_names(_utc(2026, 10, 29, 4, 30)) == []  # 00:30 ET


def test_slot_window_shape():
    (slot,) = scheduler.due_slots(NOW)
    assert slot.name == "morning"
    assert slot.start.hour == 9 and slot.start.minute == 0
    assert slot.end.hour == 12
    assert slot.start.utcoffset().total_seconds() == -4 * 3600  # EDT


def test_dst_spring_forward_shifts_the_utc_start():
    # DST 2026 begins Sun Mar 8 (07:00 UTC). The ET 09:00 slot is due
    # at 14:00 UTC the day before (EST) and 13:00 UTC on the day (EDT).
    assert _due_names(_utc(2026, 3, 7, 13, 0)) == []  # 08:00 EST
    assert _due_names(_utc(2026, 3, 7, 14, 0)) == ["morning"]  # 09:00 EST
    assert _due_names(_utc(2026, 3, 8, 13, 0)) == ["morning"]  # 09:00 EDT
    assert _due_names(_utc(2026, 3, 8, 12, 0)) == []  # 08:00 EDT


def test_dst_fall_back_shifts_the_utc_start():
    # DST 2026 ends Sun Nov 1 (06:00 UTC). The ET 09:00 slot moves
    # from 13:00 UTC (EDT) to 14:00 UTC (EST).
    assert _due_names(_utc(2026, 10, 31, 13, 0)) == ["morning"]  # 09:00 EDT
    assert _due_names(_utc(2026, 11, 1, 13, 0)) == []  # 08:00 EST
    assert _due_names(_utc(2026, 11, 1, 14, 0)) == ["morning"]  # 09:00 EST


def test_due_slots_rejects_naive_now():
    with pytest.raises(ValueError):
        scheduler.due_slots(datetime(2026, 10, 29, 10, 0))


# --- fan-out fakes -------------------------------------------------------------


class FakeRunsTable:
    """In-memory espn_lineup_runs supporting the dedupe query chain."""

    def __init__(self, store):
        self._store = store
        self._rows = None

    def _base(self):
        return self._rows if self._rows is not None else list(self._store)

    def select(self, *a):
        self._rows = list(self._store)
        return self

    def eq(self, k, v):
        self._rows = [r for r in self._base() if r.get(k) == v]
        return self

    def in_(self, k, vals):
        self._rows = [r for r in self._base() if r.get(k) in vals]
        return self

    def gte(self, k, v):
        self._rows = [r for r in self._base() if (r.get(k) or "") >= v]
        return self

    def lt(self, k, v):
        self._rows = [r for r in self._base() if (r.get(k) or "") < v]
        return self

    def limit(self, n):
        self._rows = self._base()[:n]
        return self

    def execute(self):
        rows = self._rows

        class R:
            data = rows

        return R()


class FakeSupabase:
    def __init__(self, runs=()):
        self._runs = list(runs)

    def table(self, name):
        assert name == "espn_lineup_runs"
        return FakeRunsTable(self._runs)


def _account(aid, enabled=True):
    return {
        "id": aid,
        "label": aid,
        "league_id": 111,
        "season": 2027,
        "espn_s2": "s2",
        "swid": "{SWID}",
        "lineup_automation_enabled": enabled,
    }


def _run_row(account_id, status="ok", mode="live",
             created="2026-10-29T13:15:00+00:00"):
    # 13:15 UTC = 09:15 ET: inside the reference morning window.
    return {
        "account_id": account_id,
        "mode": mode,
        "status": status,
        "created_at": created,
    }


class RunnerStub:
    def __init__(self, behavior=None):
        self.calls = []
        self.behavior = behavior or {}

    def __call__(self, supabase, account, client, scoreboard=None):
        self.calls.append(
            {"account": account["id"], "client": client,
             "scoreboard": scoreboard}
        )
        action = self.behavior.get(
            account["id"],
            {"status": "ok", "scoring_period_id": 9, "conflicts": []},
        )
        if isinstance(action, Exception):
            raise action
        return action


def _tick(runs=(), accounts_list=(), runner=None, now=NOW):
    runner = runner or RunnerStub()
    summary = scheduler.run_tick(
        FakeSupabase(runs),
        now,
        accounts_loader=lambda supabase: list(accounts_list),
        runner=runner,
        client_factory=lambda account: f"client-{account['id']}",
        scoreboard_factory=lambda: "scoreboard",
    )
    return summary, runner


# --- fan-out -------------------------------------------------------------------


def test_nothing_due_never_loads_accounts():
    def exploding_loader(supabase):
        raise AssertionError("loader must not be called when nothing is due")

    summary = scheduler.run_tick(
        FakeSupabase(),
        _utc(2026, 10, 29, 19, 0),  # 15:00 ET
        accounts_loader=exploding_loader,
        runner=RunnerStub(),
    )
    assert summary == {
        "due_slots": [], "considered": 0, "ran": 0, "skipped": 0,
        "failed": 0,
    }


def test_tick_runs_every_enabled_account():
    summary, runner = _tick(
        accounts_list=[_account("acc-1"), _account("acc-2")],
    )
    assert summary["due_slots"] == ["morning"]
    assert summary["considered"] == 2
    assert summary["ran"] == 2
    assert summary["skipped"] == 0 and summary["failed"] == 0
    assert [c["account"] for c in runner.calls] == ["acc-1", "acc-2"]
    # the shared run path is built the way the run route builds it:
    # per-account client + a scoreboard
    assert runner.calls[0]["client"] == "client-acc-1"
    assert runner.calls[0]["scoreboard"] == "scoreboard"


def test_disabled_account_never_runs():
    summary, runner = _tick(
        accounts_list=[_account("acc-1"), _account("acc-2", enabled=False)],
    )
    assert [c["account"] for c in runner.calls] == ["acc-1"]
    assert summary["considered"] == 2
    assert summary["ran"] == 1 and summary["skipped"] == 1


def test_dedupe_skips_completed_run_in_window():
    summary, runner = _tick(
        runs=[_run_row("acc-1", status="ok")],
        accounts_list=[_account("acc-1")],
    )
    assert runner.calls == []
    assert summary["skipped"] == 1 and summary["ran"] == 0


def test_dedupe_counts_noop_and_conflict_as_completed():
    for status in ("noop", "conflict"):
        summary, runner = _tick(
            runs=[_run_row("acc-1", status=status)],
            accounts_list=[_account("acc-1")],
        )
        assert runner.calls == [], status
        assert summary["skipped"] == 1, status


def test_dedupe_ignores_failed_other_mode_and_other_account_rows():
    rows = [
        _run_row("acc-1", status="error"),  # failed pass: retry is due
        _run_row("acc-1", status="auth_error"),
        _run_row("acc-1", status="ok", mode="dry_run"),  # not a live pass
        _run_row("acc-2", status="ok"),  # someone else's run
        _run_row("acc-1", status="ok",
                 created="2026-10-29T12:00:00+00:00"),  # 08:00 ET: before
    ]
    summary, runner = _tick(runs=rows, accounts_list=[_account("acc-1")])
    assert [c["account"] for c in runner.calls] == ["acc-1"]
    assert summary["ran"] == 1 and summary["skipped"] == 0


def test_one_accounts_failure_does_not_stop_the_fanout():
    runner = RunnerStub(
        behavior={
            "acc-1": EspnAuthError("cookies expired"),  # escapes runner
            "acc-2": {"status": "auth_error", "scoring_period_id": None,
                      "conflicts": []},  # recorded failure status
            "acc-3": {"status": "ok", "scoring_period_id": 9,
                      "conflicts": []},
        }
    )
    summary, runner = _tick(
        accounts_list=[_account("acc-1"), _account("acc-2"),
                       _account("acc-3")],
        runner=runner,
    )
    assert [c["account"] for c in runner.calls] == ["acc-1", "acc-2",
                                                    "acc-3"]
    assert summary["considered"] == 3
    assert summary["ran"] == 1 and summary["failed"] == 2


# --- container entry point -----------------------------------------------------


def test_main_without_credentials_is_systemic_failure(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
    monkeypatch.setattr(scheduler, "load_dotenv", lambda **kw: None)
    assert scheduler.main() == 1


def test_main_successful_tick_exits_zero(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.invalid")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "service-key")
    monkeypatch.setattr(scheduler, "load_dotenv", lambda **kw: None)
    monkeypatch.setattr(scheduler, "create_client", lambda url, key: object())
    monkeypatch.setattr(
        scheduler, "run_tick",
        lambda supabase: {"due_slots": [], "considered": 0, "ran": 0,
                          "skipped": 0, "failed": 0},
    )
    assert scheduler.main() == 0


def test_main_systemic_tick_failure_exits_nonzero(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.invalid")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "service-key")
    monkeypatch.setattr(scheduler, "load_dotenv", lambda **kw: None)
    monkeypatch.setattr(scheduler, "create_client", lambda url, key: object())

    def boom(supabase):
        raise RuntimeError("supabase unreachable")

    monkeypatch.setattr(scheduler, "run_tick", boom)
    assert scheduler.main() == 1
