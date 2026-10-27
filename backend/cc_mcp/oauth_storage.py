"""Async key-value adapter for OAuthProxy's server-only Supabase state."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any, SupportsFloat

from starlette.concurrency import run_in_threadpool

TABLE = "cc_mcp_oauth_state"
DEFAULT_COLLECTION = "default"


class SupabaseOAuthStore:
    """Store FastMCP proxy state through the service-only PostgREST table."""

    def __init__(self, service_client):
        self._client = service_client

    @staticmethod
    def _collection(collection: str | None) -> str:
        return collection or DEFAULT_COLLECTION

    @staticmethod
    def _expiry(ttl: SupportsFloat | None) -> str | None:
        if ttl is None:
            return None
        seconds = max(0.0, float(ttl))
        return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()

    @staticmethod
    def _remaining(expires_at: str | None) -> float | None:
        if expires_at is None:
            return None
        expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        return max(0.0, (expiry - datetime.now(timezone.utc)).total_seconds())

    @staticmethod
    def _data(response):
        return response.data if response else None

    def _read_one(self, collection: str, key: str) -> dict[str, Any] | None:
        response = (
            self._client.table(TABLE)
            .select("value,expires_at")
            .eq("collection", collection)
            .eq("key", key)
            .maybe_single()
            .execute()
        )
        row = self._data(response)
        if not row:
            return None
        if self._remaining(row.get("expires_at")) == 0:
            return None
        value = row.get("value")
        if not isinstance(value, dict):
            raise RuntimeError("Stored OAuth state is not a JSON object.")
        return {"value": value, "expires_at": row.get("expires_at")}

    def _read_many(self, collection: str, keys: Sequence[str]) -> dict[str, dict[str, Any]]:
        if not keys:
            return {}
        response = (
            self._client.table(TABLE)
            .select("key,value,expires_at")
            .eq("collection", collection)
            .in_("key", list(keys))
            .execute()
        )
        found = {}
        for row in self._data(response) or []:
            if self._remaining(row.get("expires_at")) == 0:
                continue
            elif isinstance(row.get("value"), dict):
                found[row["key"]] = row
            else:
                raise RuntimeError("Stored OAuth state is not a JSON object.")
        return found

    def _upsert_many(
        self,
        collection: str,
        keys: Sequence[str],
        values: Sequence[Mapping[str, Any]],
        ttl: SupportsFloat | None,
    ) -> None:
        if len(keys) != len(values):
            raise ValueError("OAuth storage keys and values must have matching lengths.")
        if not keys:
            return
        expiry = self._expiry(ttl)
        rows = [
            {
                "collection": collection,
                "key": key,
                "value": dict(value),
                "expires_at": expiry,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            for key, value in zip(keys, values)
        ]
        self._client.table(TABLE).upsert(rows, on_conflict="collection,key").execute()

    def _delete_many(self, collection: str, keys: Sequence[str]) -> int:
        if not keys:
            return 0
        response = (
            self._client.table(TABLE)
            .delete()
            .eq("collection", collection)
            .in_("key", list(keys))
            .execute()
        )
        return len(self._data(response) or [])

    async def get(self, key: str, *, collection: str | None = None) -> dict[str, Any] | None:
        row = await run_in_threadpool(self._read_one, self._collection(collection), key)
        return row["value"] if row else None

    async def ttl(self, key: str, *, collection: str | None = None) -> tuple[dict[str, Any] | None, float | None]:
        row = await run_in_threadpool(self._read_one, self._collection(collection), key)
        if not row:
            return None, None
        return row["value"], self._remaining(row["expires_at"])

    async def put(
        self,
        key: str,
        value: Mapping[str, Any],
        *,
        collection: str | None = None,
        ttl: SupportsFloat | None = None,
    ) -> None:
        await run_in_threadpool(self._upsert_many, self._collection(collection), [key], [value], ttl)

    async def delete(self, key: str, *, collection: str | None = None) -> bool:
        count = await run_in_threadpool(self._delete_many, self._collection(collection), [key])
        return count > 0

    async def get_many(self, keys: Sequence[str], *, collection: str | None = None) -> list[dict[str, Any] | None]:
        found = await run_in_threadpool(self._read_many, self._collection(collection), list(keys))
        return [found[key]["value"] if key in found else None for key in keys]

    async def ttl_many(
        self, keys: Sequence[str], *, collection: str | None = None
    ) -> list[tuple[dict[str, Any] | None, float | None]]:
        found = await run_in_threadpool(self._read_many, self._collection(collection), list(keys))
        return [
            (found[key]["value"], self._remaining(found[key].get("expires_at")))
            if key in found
            else (None, None)
            for key in keys
        ]

    async def put_many(
        self,
        keys: Sequence[str],
        values: Sequence[Mapping[str, Any]],
        *,
        collection: str | None = None,
        ttl: SupportsFloat | None = None,
    ) -> None:
        await run_in_threadpool(
            self._upsert_many, self._collection(collection), list(keys), list(values), ttl
        )

    async def delete_many(self, keys: Sequence[str], *, collection: str | None = None) -> int:
        return await run_in_threadpool(self._delete_many, self._collection(collection), list(keys))

    async def keys(self, collection: str | None = None, *, limit: int | None = None) -> list[str]:
        query = self._client.table(TABLE).select("key,expires_at").eq("collection", self._collection(collection))
        if limit is not None:
            query = query.limit(limit)
        response = await run_in_threadpool(query.execute)
        return [row["key"] for row in self._data(response) or [] if self._remaining(row.get("expires_at")) != 0]

    async def collections(self, *, limit: int | None = None) -> list[str]:
        query = self._client.table(TABLE).select("collection")
        if limit is not None:
            query = query.limit(limit)
        response = await run_in_threadpool(query.execute)
        values = sorted({row["collection"] for row in self._data(response) or []})
        return values[:limit] if limit is not None else values

    async def cull(self) -> None:
        now = datetime.now(timezone.utc).isoformat()
        query = self._client.table(TABLE).delete().lt("expires_at", now)
        await run_in_threadpool(query.execute)

    async def destroy_collection(self, collection: str) -> bool:
        query = self._client.table(TABLE).delete().eq("collection", collection)
        response = await run_in_threadpool(query.execute)
        return bool(self._data(response))

    async def destroy(self) -> bool:
        query = self._client.table(TABLE).delete().not_.is_("key", "null")
        response = await run_in_threadpool(query.execute)
        return bool(self._data(response))
