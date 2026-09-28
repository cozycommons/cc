"""Read-only Partiful integration (multi-tenant).

Each friend onboards with their own Partiful phone number (Firebase SMS OTP).
The Firebase refresh token is encrypted at rest; every API call mints a fresh
short-lived JWT from it. One personal bearer token ("ccp_...") per account.
"""
