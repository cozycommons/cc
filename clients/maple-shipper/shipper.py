#!/usr/bin/env python3
"""Maple EXP shipper: overlay log -> Cozy Commons telemetry.

Watches the Maple Classic EXP Overlay's log file (exp_log.json) and POSTs
new or changed log lines to the Cozy Commons backend
(POST /telemetry/ingest/exp-runs), where Muse can read them back over
/telemetry and /telemetry/mcp.

Design:
- Stdlib only. No dependency on the overlay's code — the only contract is
  the exp_log.json file format (a data interface).
- Store-and-forward: a local checkpoint records the fingerprint of every
  line the server has confirmed. A line is (re)sent whenever its totals
  change, and the checkpoint advances only for run_ids the server
  accepted, so a crash, a closed laptop or a dead network loses nothing.
- Each line's run_id is a sha256 over its key (producer, install, date,
  map, level, party, class) — the same computation the backend performs —
  so re-posts upsert one row instead of duplicating it.

Usage:
  shipper.py [--config PATH] [--once] [--dry-run] [--interval SECONDS]

Modes:
  (default)   poll the log file forever (this is what launchd runs)
  --once      ship whatever is new right now, then exit
  --dry-run   print what would be sent; no network, no checkpoint writes
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_API_BASE = "https://api.cozycommons.dev"
DEFAULT_LOG_PATH = "~/Library/Application Support/MapleEXP/exp_log.json"
DEFAULT_CONFIG_PATH = "~/Library/Application Support/MapleShipper/config.json"
BATCH_LIMIT = 500  # the backend accepts at most 500 runs per request


def log(message: str) -> None:
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    print(f"[{stamp}] {message}", flush=True)


def run_id_for(entry: dict, install: str) -> str:
    """Must match backend/maple/logic.py compute_run_id exactly."""
    canonical = {
        "producer": "exp",
        "install": install or "",
        "date": entry.get("date"),
        "map": entry.get("map"),
        "level": entry.get("level"),
        "party": entry.get("party"),
        "class": entry.get("class") or "",
    }
    blob = json.dumps(canonical, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def fingerprint(entry: dict) -> str:
    """Hash of the mutable totals: a changed fingerprint means re-ship."""
    totals = {
        key: entry.get(key)
        for key in (
            "exp",
            "seconds",
            "mesos",
            "mesos_seconds",
            "potion_cost",
            "potion_seconds",
            "updated",
        )
    }
    blob = json.dumps(totals, separators=(",", ":"), sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def load_config(path: Path) -> dict:
    config = {
        "api_base": DEFAULT_API_BASE,
        "token": "",
        "log_path": DEFAULT_LOG_PATH,
        "checkpoint_path": "",
        "poll_seconds": 20,
    }
    if path.exists():
        with path.open(encoding="utf-8") as f:
            config.update(json.load(f))
    config["log_path"] = os.path.expanduser(str(config["log_path"]))
    if not config["checkpoint_path"]:
        config["checkpoint_path"] = str(path.parent / "checkpoint.json")
    else:
        config["checkpoint_path"] = os.path.expanduser(str(config["checkpoint_path"]))
    config["api_base"] = str(config["api_base"]).rstrip("/")
    return config


def load_checkpoint(path: Path) -> dict:
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("shipped"), dict):
            return data
    except (OSError, ValueError):
        pass
    return {"shipped": {}}


def save_checkpoint(path: Path, checkpoint: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(checkpoint, f, indent=1, sort_keys=True)
    os.replace(tmp, path)


def read_log_entries(log_path: Path):
    """(install_id, entries) from exp_log.json, or None if unreadable.

    The overlay rewrites the whole file on every change; a read can race
    a write, so a parse failure just means "try again next poll".
    """
    try:
        text = log_path.read_text(encoding="utf-8-sig")
        data = json.loads(text)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        return None
    install = data.get("install") if isinstance(data.get("install"), str) else ""
    return install, [e for e in data["entries"] if isinstance(e, dict)]


def pending_entries(config: dict, checkpoint: dict):
    """[(run_id, fingerprint, payload)] for lines new or changed since
    the checkpoint. The payload is the overlay entry plus its install id,
    exactly what the backend's ingest expects."""
    found = read_log_entries(Path(config["log_path"]))
    if found is None:
        return None
    install, entries = found
    shipped = checkpoint["shipped"]
    pending = []
    for entry in entries:
        rid = run_id_for(entry, install)
        fp = fingerprint(entry)
        if shipped.get(rid) != fp:
            payload = dict(entry)
            payload["install"] = install
            pending.append((rid, fp, payload))
    return pending


def post_batch(config: dict, payloads: list) -> dict:
    url = config["api_base"] + "/telemetry/ingest/exp-runs"
    body = json.dumps({"runs": payloads}).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    request.add_header("Authorization", f"Bearer {config['token']}")
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def ship_pending(config: dict, checkpoint: dict, checkpoint_path: Path) -> int:
    """One shipping pass. Returns how many lines were confirmed shipped."""
    pending = pending_entries(config, checkpoint)
    if pending is None:
        log(f"log file not readable yet: {config['log_path']}")
        return 0
    if not pending:
        return 0
    confirmed = 0
    for start in range(0, len(pending), BATCH_LIMIT):
        batch = pending[start : start + BATCH_LIMIT]
        try:
            result = post_batch(config, [p for _, _, p in batch])
        except (urllib.error.URLError, OSError, ValueError) as e:
            log(f"ingest failed ({e}); will retry next poll")
            break
        accepted = set(result.get("accepted") or [])
        for rid, fp, _ in batch:
            if rid in accepted:
                checkpoint["shipped"][rid] = fp
                confirmed += 1
        for rejected in result.get("rejected") or []:
            log(f"server rejected a run: {rejected}")
        save_checkpoint(checkpoint_path, checkpoint)
        if len(accepted) < len(batch):
            log("some runs were not accepted; the rest retry next poll")
            break
    if confirmed:
        log(f"shipped {confirmed} log line(s)")
    return confirmed


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Ship EXP overlay log lines to Cozy Commons.")
    parser.add_argument("--config", default=os.path.expanduser(DEFAULT_CONFIG_PATH))
    parser.add_argument("--once", action="store_true", help="ship new lines once, then exit")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print what would be sent; no network, no checkpoint writes",
    )
    parser.add_argument("--interval", type=int, default=None, help="poll seconds (overrides config)")
    args = parser.parse_args(argv)

    config_path = Path(args.config)
    config = load_config(config_path)
    checkpoint_path = Path(config["checkpoint_path"])
    checkpoint = load_checkpoint(checkpoint_path)

    if args.dry_run:
        pending = pending_entries(config, checkpoint)
        if pending is None:
            print(f"log file not readable: {config['log_path']}")
            return 1
        print(f"{len(pending)} line(s) would be sent to {config['api_base']}/telemetry/ingest/exp-runs")
        for rid, _, payload in pending:
            print(json.dumps({"run_id": rid, "run": payload}, indent=1, sort_keys=True))
        return 0

    if not config["token"]:
        print(
            f"no token configured: put your ccm_... token in {config_path} "
            "(see README.md, 'Get a token')",
            file=sys.stderr,
        )
        return 2

    interval = args.interval or int(config.get("poll_seconds") or 20)
    if args.once:
        ship_pending(config, checkpoint, checkpoint_path)
        return 0

    log(f"watching {config['log_path']} every {interval}s -> {config['api_base']}")
    last_mtime = None
    while True:
        try:
            mtime = Path(config["log_path"]).stat().st_mtime
        except OSError:
            mtime = None
        if mtime != last_mtime:
            last_mtime = mtime
            ship_pending(config, checkpoint, checkpoint_path)
        time.sleep(interval)


if __name__ == "__main__":
    sys.exit(main())
