#!/usr/bin/env python3
"""Evaluate the versioned pregame baseline from read-only Supabase rows."""

from __future__ import annotations

import json
import os
import hashlib

from supabase import create_client

from dice.prediction_dataset import build_prediction_dataset, ranked_matches_from_rows
from dice.prediction_model import evaluate_prediction_baselines, fit_prediction_model
from dice.rating_consistency import validate_canonical_rating_snapshot


def promotion_status(total_games: int, split_reports: dict[str, dict]) -> str:
    enough_data = total_games >= 40 and all(
        report["split"]["test_games"] >= 10 for report in split_reports.values()
    )
    beats_neutral = all(
        report["metrics"]["independent_model"]["brier"]
        < report["metrics"]["neutral_50"]["brier"]
        for report in split_reports.values()
    )
    return "accepted" if enough_data and beats_neutral else ("rejected" if enough_data else "insufficient_data")


def main() -> None:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_ANON_KEY")
    if not url or not key:
        raise SystemExit("SUPABASE_URL and SUPABASE_SERVICE_KEY or SUPABASE_ANON_KEY are required")
    client = create_client(url, key)
    snapshot = client.rpc("dice_rating_analytics_snapshot").execute().data or {}
    if snapshot.get("snapshot_version") != "dice-rating-analytics/v1":
        raise SystemExit("unsupported or unavailable rating analytics snapshot")
    try:
        validate_canonical_rating_snapshot(
            snapshot["profiles"], snapshot["games"], snapshot["players"]
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise SystemExit(f"rating analytics snapshot is incomplete: {exc}") from exc
    rows = build_prediction_dataset(ranked_matches_from_rows(snapshot["games"], snapshot["players"]))
    report = evaluate_prediction_baselines(rows)
    robustness_reports = {
        str(fraction): evaluate_prediction_baselines(rows, train_fraction=fraction)
        for fraction in (0.5, 0.6, 0.7, 0.8)
    }
    report["robustness_splits"] = {
        fraction: split_report["metrics"] for fraction, split_report in robustness_reports.items()
    }
    encoded_rows = json.dumps([row.as_dict() for row in rows], sort_keys=True, separators=(",", ":"))
    report["evaluation_version"] = "dice-prediction-evaluation/v1"
    report["dataset_digest"] = hashlib.sha256(encoded_rows.encode()).hexdigest()
    report["chronology"] = {
        "first_game_id": rows[0].game_id, "last_game_id": rows[-1].game_id,
        "train_end_game_id": rows[report["split"]["train_games"] - 1].game_id,
        "test_start_game_id": rows[report["split"]["train_games"]].game_id,
    }
    report["full_fit"] = fit_prediction_model(rows).as_dict()
    report["promotion"] = {
        "minimum_games": 40,
        "minimum_held_out_games": 10,
        "requires_brier_better_than_neutral_on_all_time_splits": [0.5, 0.6, 0.7, 0.8],
        "status": promotion_status(len(rows), robustness_reports),
    }
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
