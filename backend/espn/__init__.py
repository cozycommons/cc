"""Read-only ESPN Fantasy integration (multi-tenant).

Each friend onboards with their own ESPN cookies (espn_s2 + SWID) for a
single basketball league (one league per account). The cookies are
Fernet-encrypted at rest; every API call sends them as a Cookie header
against ESPN's unofficial read API. One personal bearer token ("cce_...")
per account.
"""
