"""Server-owned Arcade state in the Commons database, created by release migrations."""
import hashlib
import secrets
import time
from uuid import uuid4

from postgrest.exceptions import APIError
from supabase import Client

DEFAULTS = {"das_ms": 200, "arr_ms": 35, "keys": {"left": "KeyJ", "right": "KeyL", "soft": "KeyK"},
            "sound": True, "opponent_level": 0, "frame_rate": 60}
DEFAULT_XML = "<UserSettings><CurDas>9001</CurDas><CurArr>9007</CurArr></UserSettings>"

class Store:
    def __init__(self, client: Client):
        self.client = client

    def profile(self, user_id: str) -> dict:
        def read():
            return (self.client.table("arcade_profiles").select("settings,legacy_settings")
                    .eq("user_id", user_id).limit(1).execute().data)
        rows = read()
        if not rows:
            try:
                self.client.table("arcade_profiles").insert({"user_id": user_id}).execute()
            except APIError as error:
                if error.code != "23505":
                    raise
            rows = read()
        row = rows[0]
        return {"settings": {**DEFAULTS, **row["settings"]}, "legacy_settings": row["legacy_settings"]}

    def save_profile(self, user_id: str, settings: dict, legacy_settings: str | None = None):
        self.profile(user_id)
        changes = {"settings": settings}
        if legacy_settings is not None:
            changes["legacy_settings"] = legacy_settings
        self.client.table("arcade_profiles").update(changes).eq("user_id", user_id).execute()

    def launch(self, user_id: str) -> dict:
        self.profile(user_id)
        token = secrets.token_urlsafe(32)
        session_id = str(uuid4())
        self.client.table("arcade_sessions").insert({
            "id": session_id, "user_id": user_id, "token_hash": hashlib.sha256(token.encode()).hexdigest(),
            "expires_at": int(time.time()) + 6 * 3600,
        }).execute()
        return {"id": session_id, "token": token}

    def session(self, token: str) -> dict | None:
        rows = (self.client.table("arcade_sessions").select("id,user_id,current_run")
                .eq("token_hash", hashlib.sha256(token.encode()).hexdigest())
                .gt("expires_at", int(time.time())).limit(1).execute().data)
        return rows[0] if rows else None

    def start_run(self, session: dict) -> str:
        try:
            return self.client.rpc("arcade_start_run", {
                "p_session_id": session["id"], "p_user_id": session["user_id"],
            }).execute().data
        except APIError as error:
            if error.code == "P0001":
                raise ValueError("Game session unavailable") from None
            raise

    def save_run(self, session: dict, metrics: dict, record: str | None = None):
        try:
            self.client.rpc("arcade_save_run", {
                "p_session_id": session["id"], "p_user_id": session["user_id"],
                "p_metrics": metrics, "p_record": record,
            }).execute()
        except APIError as error:
            if error.code == "P0001":
                raise ValueError("Game run unavailable") from None
            raise

    def runs(self, user_id: str) -> list[dict]:
        rows = (self.client.table("arcade_runs").select("id,started_at,metrics,record")
                .eq("user_id", user_id).order("started_at", desc=True).order("id", desc=True)
                .limit(30).execute().data)
        # Replay XML stays on the server; history only needs whether a record exists.
        return [{"id": row["id"], "started_at": row["started_at"], "metrics": row["metrics"],
                 "complete": row["record"] is not None} for row in rows]
