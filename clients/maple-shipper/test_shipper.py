"""Stdlib-only tests for shipper.py. Run: python3 -m unittest test_shipper -v

Covers the two behaviors the backend contract depends on: the run_id
computation (must match backend/maple/logic.py) and first-run backfill
(an empty checkpoint makes every existing log line pending).
"""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import shipper

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
}


def write_log(folder: Path, entries, install="0aa101ab55d142a8"):
    path = folder / "exp_log.json"
    path.write_text(
        json.dumps({"version": 4, "install": install, "entries": entries, "aliases": {}, "runs": []}),
        encoding="utf-8",
    )
    return path


class ShipperTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        self.log_path = write_log(self.folder, [dict(ENTRY), dict(ENTRY, map="Line 2 <Area 1>")])
        self.config = {
            "api_base": "https://api.cozycommons.dev",
            "token": "ccm_test",
            "log_path": str(self.log_path),
            "checkpoint_path": str(self.folder / "checkpoint.json"),
            "poll_seconds": 20,
        }

    def tearDown(self):
        self.tmp.cleanup()

    def test_run_id_matches_backend_formula(self):
        canonical = {
            "producer": "exp",
            "install": "0aa101ab55d142a8",
            "date": "2026-11-24",
            "map": "Cave of Evil Eye III",
            "level": 37,
            "party": 2,
            "class": "Assassin",
        }
        expected = hashlib.sha256(
            json.dumps(canonical, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).hexdigest()
        self.assertEqual(shipper.run_id_for(ENTRY, "0aa101ab55d142a8"), expected)

    def test_first_run_backfills_entire_history(self):
        checkpoint = {"shipped": {}}
        pending = shipper.pending_entries(self.config, checkpoint)
        self.assertEqual(len(pending), 2)  # both existing lines, not zero
        self.assertTrue(all(p["install"] == "0aa101ab55d142a8" for _, _, p in pending))

    def test_confirmed_lines_are_not_resent_until_totals_change(self):
        checkpoint = {"shipped": {}}
        pending = shipper.pending_entries(self.config, checkpoint)
        for rid, fp, _ in pending:
            checkpoint["shipped"][rid] = fp
        self.assertEqual(shipper.pending_entries(self.config, checkpoint), [])
        # The line grows during the day: exactly that line becomes pending.
        entries = [dict(ENTRY, exp=220000, seconds=7200.0), dict(ENTRY, map="Line 2 <Area 1>")]
        write_log(self.folder, entries)
        pending = shipper.pending_entries(self.config, checkpoint)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0][2]["exp"], 220000)

    def test_unreadable_log_is_none_not_crash(self):
        self.config["log_path"] = str(self.folder / "missing.json")
        self.assertIsNone(shipper.pending_entries(self.config, {"shipped": {}}))


if __name__ == "__main__":
    unittest.main()
