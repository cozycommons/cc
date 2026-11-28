"""Arcade state on a server volume, scoped by Commons account and game session."""
import hashlib
import json
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

DEFAULTS = {"das_ms": 200, "arr_ms": 35, "keys": {"left": "KeyJ", "right": "KeyL", "soft": "KeyK"},
            "sound": True, "opponent_level": 0, "frame_rate": 60}
DEFAULT_XML = "<UserSettings><CurDas>9001</CurDas><CurArr>9007</CurArr></UserSettings>"

class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS profiles (
                  user_id TEXT PRIMARY KEY, settings TEXT NOT NULL, legacy_settings TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions (
                  id TEXT PRIMARY KEY, user_id TEXT NOT NULL, token_hash TEXT UNIQUE NOT NULL,
                  expires_at INTEGER NOT NULL, current_run TEXT);
                CREATE TABLE IF NOT EXISTS runs (
                  id TEXT PRIMARY KEY, user_id TEXT NOT NULL, session_id TEXT NOT NULL,
                  started_at INTEGER NOT NULL, metrics TEXT NOT NULL DEFAULT '{}', record TEXT);
                CREATE INDEX IF NOT EXISTS runs_owner ON runs(user_id, started_at DESC);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def profile(self, user_id: str) -> dict:
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO profiles VALUES (?, ?, ?)",
                       (user_id, json.dumps(DEFAULTS), DEFAULT_XML))
            row = db.execute("SELECT * FROM profiles WHERE user_id=?", (user_id,)).fetchone()
        return {"settings": {**DEFAULTS, **json.loads(row["settings"])}, "legacy_settings": row["legacy_settings"]}

    def save_profile(self, user_id: str, settings: dict, legacy_settings: str | None = None):
        previous = self.profile(user_id)
        with self.connect() as db:
            db.execute("UPDATE profiles SET settings=?, legacy_settings=? WHERE user_id=?",
                       (json.dumps(settings), legacy_settings or previous["legacy_settings"], user_id))

    def launch(self, user_id: str) -> dict:
        self.profile(user_id)
        token = secrets.token_urlsafe(32)
        session_id = str(uuid4())
        with self.connect() as db:
            db.execute("INSERT INTO sessions VALUES (?, ?, ?, ?, NULL)",
                       (session_id, user_id, hashlib.sha256(token.encode()).hexdigest(), int(time.time()) + 6 * 3600))
        return {"id": session_id, "token": token}

    def session(self, token: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM sessions WHERE token_hash=? AND expires_at>?",
                             (hashlib.sha256(token.encode()).hexdigest(), int(time.time()))).fetchone()
        return dict(row) if row else None

    def start_run(self, session: dict) -> str:
        run_id = str(uuid4())
        with self.connect() as db:
            db.execute("INSERT INTO runs(id,user_id,session_id,started_at) VALUES(?,?,?,?)",
                       (run_id, session["user_id"], session["id"], int(time.time())))
            db.execute("UPDATE sessions SET current_run=? WHERE id=?", (run_id, session["id"]))
        return run_id

    def save_run(self, session: dict, metrics: dict, record: str | None = None):
        with self.connect() as db:
            row = db.execute("SELECT current_run FROM sessions WHERE id=?", (session["id"],)).fetchone()
            if not row or not row["current_run"]:
                raise ValueError("Start a game before saving a result")
            run_id = row["current_run"]
            old = db.execute("SELECT metrics FROM runs WHERE id=? AND user_id=?",
                             (run_id, session["user_id"])).fetchone()
            merged = {**json.loads(old["metrics"]), **metrics}
            db.execute("UPDATE runs SET metrics=?, record=coalesce(?, record) WHERE id=? AND user_id=?",
                       (json.dumps(merged), record, run_id, session["user_id"]))

    def runs(self, user_id: str) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT id,started_at,metrics,record IS NOT NULL AS complete FROM runs "
                              "WHERE user_id=? ORDER BY started_at DESC, rowid DESC LIMIT 30", (user_id,)).fetchall()
        return [{**dict(row), "metrics": json.loads(row["metrics"])} for row in rows]
