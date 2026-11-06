"""Shared authenticated local client for CLI and MCP."""

import os
import urllib.parse

import httpx


def call(method, path, data=None):
    token = os.environ.get("COMMONS_TOKEN")
    if not token:
        raise ValueError("Set COMMONS_TOKEN to a local user's token")
    base = os.environ.get("COMMONS_URL", "http://127.0.0.1:8091")
    parsed = urllib.parse.urlparse(base)
    if parsed.scheme != "http" or parsed.hostname not in {
        "127.0.0.1",
        "localhost",
        "::1",
    }:
        raise ValueError("This prototype client only connects to loopback HTTP")
    with httpx.Client(timeout=180, trust_env=False) as client:
        result = client.request(
            method, base + path, json=data, headers={"Authorization": "Bearer " + token}
        )
        result.raise_for_status()
        return result.json()


def segment(value):
    return urllib.parse.quote(value, safe="")
