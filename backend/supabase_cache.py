import hashlib
import json
from threading import Lock
from typing import Any

from cachetools import TTLCache

READ_METHODS = {"select"}
MUTATION_METHODS = {"insert", "update", "upsert", "delete"}


def _normalize_for_cache(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k): _normalize_for_cache(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple)):
        return [_normalize_for_cache(v) for v in value]
    if isinstance(value, set):
        return sorted(_normalize_for_cache(v) for v in value)
    return repr(value)


def _build_operation(method: str, args: tuple, kwargs: dict) -> dict[str, Any]:
    return {
        "method": method,
        "args": _normalize_for_cache(args),
        "kwargs": _normalize_for_cache(kwargs),
    }


class SupabaseTTLCacheStore:
    def __init__(self, ttl_seconds: int = 120, max_entries: int = 2048):
        self.cache = TTLCache(maxsize=max_entries, ttl=ttl_seconds)
        self.lock = Lock()
        self.epoch = 0


class CachedTableQuery:
    def __init__(
        self,
        query: Any,
        table_name: str,
        cache_store: SupabaseTTLCacheStore,
        operations: list[dict[str, Any]] | None = None,
        is_read_query: bool = False,
        is_mutation_query: bool = False,
    ):
        self._query = query
        self._table_name = table_name
        self._cache_store = cache_store
        self._operations = operations or []
        self._is_read_query = is_read_query
        self._is_mutation_query = is_mutation_query

    def __getattr__(self, name: str):
        attribute = getattr(self._query, name)
        if not callable(attribute):
            return attribute

        def _wrapped(*args, **kwargs):
            if name == "execute":
                return self._execute()

            result = attribute(*args, **kwargs)
            next_operations = [*self._operations, _build_operation(name, args, kwargs)]
            next_is_read_query = self._is_read_query or name in READ_METHODS
            next_is_mutation_query = self._is_mutation_query or name in MUTATION_METHODS

            if callable(getattr(result, "execute", None)):
                return CachedTableQuery(
                    query=result,
                    table_name=self._table_name,
                    cache_store=self._cache_store,
                    operations=next_operations,
                    is_read_query=next_is_read_query,
                    is_mutation_query=next_is_mutation_query,
                )

            return result

        return _wrapped

    def _cache_key(self) -> str:
        key_payload = {
            "table": self._table_name,
            "operations": self._operations,
        }
        raw = json.dumps(key_payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _execute(self):
        if self._is_read_query and not self._is_mutation_query:
            cache_key = self._cache_key()
            with self._cache_store.lock:
                cached_response = self._cache_store.cache.get(cache_key)
                read_epoch = self._cache_store.epoch
            if cached_response is not None:
                return cached_response

            response = self._query.execute()
            with self._cache_store.lock:
                if self._cache_store.epoch == read_epoch:
                    self._cache_store.cache[cache_key] = response
            return response

        response = self._query.execute()
        if self._is_mutation_query:
            with self._cache_store.lock:
                self._cache_store.cache.clear()
                self._cache_store.epoch += 1
        return response


class CachedSupabaseClient:
    def __init__(self, client: Any, cache_store: SupabaseTTLCacheStore):
        self._client = client
        self._cache_store = cache_store

    def table(self, table_name: str) -> CachedTableQuery:
        return CachedTableQuery(
            query=self._client.table(table_name),
            table_name=table_name,
            cache_store=self._cache_store,
        )

    def clear_cache(self) -> None:
        with self._cache_store.lock:
            self._cache_store.cache.clear()
            self._cache_store.epoch += 1

    def __getattr__(self, name: str):
        return getattr(self._client, name)
