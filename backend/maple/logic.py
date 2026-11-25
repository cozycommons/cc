"""Maple EXP telemetry: run normalization, identity, rates and storage.

A "run" is one line of the EXP overlay's log (exp_log.json `entries`): the
totals for one day, map, level, class and party size. Entries keep growing
while the player stays on the map, so a run's identity is its key —
(producer, source install, date, map, level, party, class) — never its
totals. The run_id is a sha256 over that key; re-posting an entry upserts
the same row with the newer totals, which is what makes ingest idempotent
for a shipper that checkpoints only on confirmed receipt.

Rates mirror the overlay's own arithmetic (maple_exp.py `log_row` /
`net_text`): EXP/hr = exp / seconds, mesos/hr = mesos / mesos_seconds,
net/hr = mesos/hr - potion_cost / potion_seconds (potion_seconds defaults
to seconds). Totals are stored raw; rates are computed on read.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime, timezone

PRODUCER_EXP = "exp"
MAX_BATCH = 500
MAX_ROWS_PER_USER_READ = 5000


class RunError(ValueError):
    pass


def compute_run_id(identity: dict) -> str:
    """Stable id for one log line's key. The shipper computes the same id
    from the same fields, so client and server agree without a round trip."""
    canonical = {
        "producer": PRODUCER_EXP,
        "install": identity.get("install") or "",
        "date": identity.get("date"),
        "map": identity.get("map"),
        "level": identity.get("level"),
        "party": identity.get("party"),
        "class": identity.get("class") or "",
    }
    blob = json.dumps(canonical, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _number(value, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RunError(f"{field} must be a number")
    value = float(value)
    if not math.isfinite(value) or abs(value) > 1e15:
        raise RunError(f"{field} is out of range")
    return value


def _optional_number(raw: dict, field: str):
    value = raw.get(field)
    if value is None:
        return None
    return _number(value, field)


def _optional_int(raw: dict, field: str, lo: int, hi: int):
    value = raw.get(field)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise RunError(f"{field} must be an integer")
    if not lo <= value <= hi:
        raise RunError(f"{field} must be between {lo} and {hi}")
    return value


def _optional_text(raw: dict, field: str, max_len: int = 200):
    value = raw.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise RunError(f"{field} must be a string")
    return value[:max_len]


def normalize_run(raw) -> dict:
    """Validate one overlay log entry and shape it for storage.

    Accepts the entry exactly as the overlay writes it in exp_log.json.
    Raises RunError with a caller-safe message on anything malformed.
    """
    if not isinstance(raw, dict):
        raise RunError("run must be an object")
    day = raw.get("date")
    if not isinstance(day, str):
        raise RunError("date is required")
    try:
        date.fromisoformat(day)
    except ValueError:
        raise RunError("date must be an ISO date (YYYY-MM-DD)")
    map_name = raw.get("map")
    if not isinstance(map_name, str) or not map_name.strip() or len(map_name) > 200:
        raise RunError("map must be a non-empty string")
    exp = _number(raw.get("exp"), "exp")
    seconds = _number(raw.get("seconds"), "seconds")
    if seconds < 0:
        raise RunError("seconds must be >= 0")
    mesos = _optional_number(raw, "mesos") or 0.0
    mesos_seconds = _optional_number(raw, "mesos_seconds") or 0.0
    if mesos_seconds < 0:
        raise RunError("mesos_seconds must be >= 0")
    potion_cost = _optional_number(raw, "potion_cost")
    if potion_cost is not None and potion_cost < 0:
        raise RunError("potion_cost must be >= 0")
    potion_seconds = _optional_number(raw, "potion_seconds")
    if potion_seconds is not None and potion_seconds < 0:
        raise RunError("potion_seconds must be >= 0")
    estimated = raw.get("estimated")
    if estimated is not None and not isinstance(estimated, bool):
        raise RunError("estimated must be a boolean")
    run = {
        "log_date": day,
        "map": map_name,
        "map_read": _optional_text(raw, "map_read"),
        "level": _optional_int(raw, "level", 1, 300),
        "class": _optional_text(raw, "class", 80),
        "party": _optional_int(raw, "party", 1, 6),
        "exp": int(round(exp)),
        "seconds": seconds,
        "mesos": int(round(mesos)),
        "mesos_seconds": mesos_seconds,
        "potion_cost": int(round(potion_cost)) if potion_cost is not None else None,
        "potion_seconds": potion_seconds,
        "estimated": bool(estimated),
        "source_install": _optional_text(raw, "install", 64),
        "source_updated": _optional_number(raw, "updated"),
    }
    run["run_id"] = compute_run_id(
        {
            "install": run["source_install"],
            "date": run["log_date"],
            "map": run["map"],
            "level": run["level"],
            "party": run["party"],
            "class": run["class"],
        }
    )
    return run


def run_view(row: dict) -> dict:
    """A stored row plus the overlay's own rates, as the API returns it."""
    seconds = row.get("seconds") or 0
    mesos_seconds = row.get("mesos_seconds") or 0
    exp_per_hour = row["exp"] / seconds * 3600 if seconds else None
    mesos_per_hour = row["mesos"] / mesos_seconds * 3600 if mesos_seconds else None
    net_per_hour = None
    if row.get("potion_cost") is not None and mesos_per_hour is not None:
        potion_seconds = row.get("potion_seconds")
        if potion_seconds is None:
            potion_seconds = seconds
        if potion_seconds:
            net_per_hour = mesos_per_hour - row["potion_cost"] / potion_seconds * 3600
    return {
        "run_id": row.get("run_id"),
        "date": row.get("log_date"),
        "map": row.get("map"),
        "map_read": row.get("map_read"),
        "level": row.get("level"),
        "class": row.get("class"),
        "party": row.get("party"),
        "exp": row.get("exp"),
        "seconds": row.get("seconds"),
        "mesos": row.get("mesos"),
        "mesos_seconds": row.get("mesos_seconds"),
        "potion_cost": row.get("potion_cost"),
        "potion_seconds": row.get("potion_seconds"),
        "estimated": bool(row.get("estimated")),
        "exp_per_hour": round(exp_per_hour, 1) if exp_per_hour is not None else None,
        "mesos_per_hour": (
            round(mesos_per_hour, 1) if mesos_per_hour is not None else None
        ),
        "net_per_hour": round(net_per_hour, 1) if net_per_hour is not None else None,
        "received_at": row.get("received_at"),
    }


def ingest_runs(supabase, user_id, raw_runs) -> dict:
    """Upsert a batch of overlay log entries for one account.

    Each entry is validated independently: valid rows are upserted on
    (user_id, run_id) so a re-post replaces the totals of the same log
    line instead of duplicating it; invalid rows are reported by index
    and store nothing.
    """
    if not isinstance(raw_runs, list):
        raise RunError("runs must be a list")
    if len(raw_runs) > MAX_BATCH:
        raise RunError(f"runs is limited to {MAX_BATCH} per request")
    accepted, rejected = [], []
    now = datetime.now(timezone.utc).isoformat()
    for index, raw in enumerate(raw_runs):
        try:
            run = normalize_run(raw)
        except RunError as e:
            rejected.append({"index": index, "error": str(e)})
            continue
        row = {"user_id": user_id, "producer": PRODUCER_EXP, "received_at": now, **run}
        supabase.table("maple_exp_runs").upsert(
            row, on_conflict="user_id,run_id"
        ).execute()
        accepted.append(run["run_id"])
    return {"accepted": accepted, "rejected": rejected}


def list_runs(supabase, user_id, limit: int = 25, map_name=None, level=None) -> list:
    limit = max(1, min(int(limit), 200))
    query = (
        supabase.table("maple_exp_runs")
        .select("*")
        .eq("user_id", user_id)
        .order("log_date", desc=True)
        .order("received_at", desc=True)
        .limit(limit)
    )
    if map_name:
        query = query.eq("map", map_name)
    if level is not None:
        query = query.eq("level", level)
    rows = query.execute().data or []
    return [run_view(r) for r in rows]


def map_stats(supabase, user_id, level=None) -> list:
    """Per-map aggregates over the account's stored runs, best rate first.

    best_exp_per_hour is the best single log line; avg_exp_per_hour is
    time-weighted (total EXP / total seconds), the number that survives
    short lucky stretches.
    """
    query = (
        supabase.table("maple_exp_runs")
        .select("*")
        .eq("user_id", user_id)
        .order("log_date", desc=True)
        .limit(MAX_ROWS_PER_USER_READ)
    )
    if level is not None:
        query = query.eq("level", level)
    rows = query.execute().data or []
    by_map: dict[str, dict] = {}
    for row in rows:
        agg = by_map.setdefault(
            row["map"],
            {
                "map": row["map"],
                "runs": 0,
                "total_seconds": 0.0,
                "total_exp": 0,
                "total_mesos": 0,
                "best_exp_per_hour": None,
                "last_date": None,
            },
        )
        agg["runs"] += 1
        agg["total_seconds"] += row.get("seconds") or 0
        agg["total_exp"] += row.get("exp") or 0
        agg["total_mesos"] += row.get("mesos") or 0
        view = run_view(row)
        if view["exp_per_hour"] is not None and (
            agg["best_exp_per_hour"] is None
            or view["exp_per_hour"] > agg["best_exp_per_hour"]
        ):
            agg["best_exp_per_hour"] = view["exp_per_hour"]
        if agg["last_date"] is None or str(row.get("log_date")) > agg["last_date"]:
            agg["last_date"] = row.get("log_date")
    result = []
    for agg in by_map.values():
        total_seconds = agg["total_seconds"]
        agg["avg_exp_per_hour"] = (
            round(agg["total_exp"] / total_seconds * 3600, 1) if total_seconds else None
        )
        agg["total_seconds"] = round(total_seconds, 1)
        result.append(agg)
    result.sort(key=lambda a: a["best_exp_per_hour"] or 0, reverse=True)
    return result
