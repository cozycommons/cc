"""Daily snapshots for the single-process local manager."""

import json
import logging
import math
import shutil
import time
import uuid

INTERVAL = 24 * 60 * 60
RETAIN = 3
RETRY = 5 * 60
log = logging.getLogger(__name__)


class Backups:
    def __init__(self, store, runtime, state, clock=time.time):
        self.store = store
        self.runtime = runtime
        self.root = state / "backups"
        self.clock = clock

    def list(self, name):
        result = []
        for manifest in self.root.glob("*/manifest.json"):
            try:
                data = json.loads(manifest.read_text())
                valid_id = len(manifest.parent.name) == 32 and all(c in "0123456789abcdef" for c in manifest.parent.name)
                if valid_id and data["id"] == manifest.parent.name and data["app"] == name:
                    if isinstance(data["created"], (int, float)) and math.isfinite(data["created"]):
                        data.setdefault("format", "legacy-database")
                        data.setdefault("kind", "manual")
                        result.append(data)
            except (OSError, ValueError, KeyError, TypeError):
                log.error("Invalid backup manifest in %s", manifest.parent.name)
        return sorted(result, key=lambda item: (item["created"], item["id"]), reverse=True)

    def prune(self, name):
        snapshots = [item for item in self.list(name) if item["format"] == "workspace-v1"]
        for item in snapshots[RETAIN:]:
            shutil.rmtree(self.root / item["id"])

    def recover(self, record):
        """Resume only interrupted backups, never a failed restore."""
        pending = record.get("backup_pending")
        if not pending:
            return
        folder = self.root / pending["id"]
        if not (folder / "manifest.json").exists():
            shutil.rmtree(folder, ignore_errors=True)
            record["next_backup_at"] = self.clock() + RETRY
            record["backup_error"] = "Backup interrupted; retry scheduled"
        else:
            manifest = json.loads((folder / "manifest.json").read_text())
            record["next_backup_at"] = manifest["created"] + INTERVAL
            record.pop("backup_error", None)
        if pending["was_running"]:
            if self.runtime.status(record["name"]) != "running":
                self.runtime.container(record["name"]).start()
            record["status"] = "running"
        else:
            record["status"] = "stopped"
        record.pop("backup_pending")
        self.store.put(record)
        self.prune(record["name"])

    def create(self, record, kind="manual"):
        # Caller holds store.lock, also used by lifecycle/restore/exec admission.
        name = record["name"]
        if "db_password" in record:
            raise ValueError("Export the legacy managed database into a new sandbox before backup")
        actual = self.runtime.status(name)
        if record["status"] not in {"running", "stopped"} or actual not in {"running", "stopped"}:
            raise ValueError("App is unavailable for backup")
        backup_id = uuid.uuid4().hex
        folder = self.root / backup_id
        was_running = actual == "running"
        record.update(status="maintenance", backup_pending={"id": backup_id, "was_running": was_running})
        self.store.put(record)
        try:
            folder.mkdir(parents=True)
            if was_running:
                self.runtime.container(name).stop(timeout=10)
            self.runtime.archive(name, backup_id)
            manifest = {"id": backup_id, "app": name, "created": self.clock(), "kind": kind, "format": "workspace-v1"}
            temporary = folder / "manifest.tmp"
            temporary.write_text(json.dumps(manifest))
            temporary.replace(folder / "manifest.json")
            record["next_backup_at"] = manifest["created"] + INTERVAL
            record.pop("backup_error", None)
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            record["backup_error"] = "Backup failed; previous snapshots retained"
            record["next_backup_at"] = self.clock() + RETRY
            raise
        finally:
            try:
                if was_running:
                    self.runtime.container(name).start()
                record["status"] = "running" if was_running else "stopped"
                record.pop("backup_pending", None)
            except Exception:
                # Keep the recovery marker so a manager restart can resume it.
                record["status"] = "error"
                record["backup_error"] = "App restart after backup failed"
                raise
            finally:
                self.store.put(record)
        self.prune(name)
        return manifest

    def tick(self, stop=None):
        for entry in self.store.all():
            if stop is not None and stop.is_set():
                break
            with self.store.lock:
                record = self.store.get(entry["name"])
                try:
                    if "db_password" in record:
                        record["backup_error"] = "Legacy managed database requires migration to sandbox storage; old backups retained"
                        self.store.put(record)
                        continue
                    self.recover(record)
                    self.prune(record["name"])
                    if "next_backup_at" not in record:
                        history = self.list(record["name"])
                        record["next_backup_at"] = (history[0]["created"] if history else self.clock()) + INTERVAL
                        self.store.put(record)
                    if record["status"] in {"running", "stopped"} and record["next_backup_at"] <= self.clock():
                        self.create(record, kind="automatic")
                except Exception:
                    # Never log database credentials or subprocess error output.
                    current = self.store.get(record["name"])
                    current.setdefault("backup_error", "Backup maintenance failed; inspect manager logs")
                    self.store.put(current)
                    log.error("Backup maintenance failed for app %s", record["name"])

    def run(self, stop):
        while not stop.is_set():
            try:
                self.tick(stop=stop)
            except Exception:
                # A temporary registry/storage failure must not kill scheduling.
                log.error("Backup scheduler unavailable; retrying")
            stop.wait(30)
