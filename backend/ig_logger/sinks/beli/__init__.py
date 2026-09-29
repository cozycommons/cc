"""Beli app module: personal Beli restaurant recommendations + Want to Try bookmarks.

Multi-tenant: every request authenticates with the caller's own API token
(see accounts.py) and only ever touches that caller's Beli account.
"""
