"""Index of agent connections beside the encrypted OAuth store (cc_mcp 0003).

A connection is one approval and its refresh family, keyed by FastMCP's
`upstream_token_id`. The encrypted store stays the authority: deleting a
connection's upstream token set is what disconnects it, and this index only
lets the account page find a user's connections without decrypting every token.

Client names are self-reported at dynamic registration. They are display text
next to the redirect host, never proof of which agent is connected.
"""
from datetime import datetime, timezone
from urllib.parse import urlsplit

TABLE = "cc_mcp_connections"
LISTED = "id,client_name,redirect_host,scopes,approved_at,last_used_at,expires_at"
NAME_LIMIT = 80
HOST_LIMIT = 255


def timestamp(epoch: float | None) -> str | None:
    return None if epoch is None else datetime.fromtimestamp(epoch, timezone.utc).isoformat()


def client_label(name) -> str | None:
    text = " ".join(str(name or "").split())[:NAME_LIMIT]
    return text or None


def redirect_host(*uris) -> str | None:
    """The redirect host(s) a client can send codes to, e.g. `claude.ai`."""
    hosts = sorted({host for uri in uris if (host := urlsplit(str(uri)).hostname)})
    joined = ", ".join(hosts)
    return joined[:HOST_LIMIT] or None


def touch(client, *, upstream_token_id, user_id, client_id, client_name, redirect_host,
          scopes, approved_at, expires_at, last_used_at):
    client.rpc("cc_mcp_touch_connection", {
        "p_upstream_token_id": upstream_token_id, "p_user_id": str(user_id),
        "p_client_id": client_id, "p_client_name": client_name, "p_redirect_host": redirect_host,
        "p_scopes": list(scopes), "p_approved_at": approved_at, "p_expires_at": expires_at,
        "p_last_used_at": last_used_at,
    }).execute()


def mark_revoked(client, upstream_token_id):
    (client.table(TABLE).update({"revoked_at": datetime.now(timezone.utc).isoformat()})
     .eq("upstream_token_id", upstream_token_id).is_("revoked_at", "null").execute())


def active_connections(client, user_id) -> list[dict]:
    """The user's connections that are neither revoked nor past their refresh family."""
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return (client.table(TABLE).select(LISTED).eq("user_id", str(user_id)).is_("revoked_at", "null")
            .or_(f"expires_at.is.null,expires_at.gt.{now}").order("approved_at", desc=True)
            .execute().data) or []


def own_connection(client, user_id, connection_id) -> dict | None:
    rows = (client.table(TABLE).select("id,upstream_token_id,revoked_at")
            .eq("id", str(connection_id)).eq("user_id", str(user_id)).limit(1).execute().data)
    return rows[0] if rows else None
