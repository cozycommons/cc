# Durable GET gateway

`espn.read_gateway.ReadGateway` is a standalone stdlib primitive copied from
Courtside. It has no application imports and accepts only GET requests. Callers
supply a private storage directory, host buckets, budgets, credential scopes,
TTL, decoding and validation. Cache bodies, pacing, cooldowns, budgets and
invalidation epochs are shared through SQLite; file locks and Futures coalesce
fills across processes and threads. Compressed and expanded bodies are capped.
Fresh reads bypass caches and fill coalescing, and writes can invalidate a scope
before and after their existing one-attempt transport. Refresh reads (a user's
"refresh now") reread any expiring entry under the fill lock and store the result,
so later cached readers see it; permanent entries (ttl None) still hit, and a
refresh never spends the critical reserve.

This patch adds the primitive and offline tests only. It does not switch CC's
existing `ReadCache`, change deployment storage, choose traffic budgets, or wire
writes. Adoption requires a separate caller integration that selects durable
storage and per-account HMAC scopes, with a reviewed TTL and volume policy. Use
no raw credential as a scope. Keep storage outside the web root and backed by a
private local filesystem supporting SQLite and advisory locks (Linux/macOS).
Counters are internal operational data, never public response content.

Verification: from `backend`, `python -m pytest tests/test_espn_read_gateway.py`.
Tests use fake transports, clocks and temporary storage, including process sharing,
credential isolation, invalidation, fresh bypass, refresh rereads, limits and breakers.
