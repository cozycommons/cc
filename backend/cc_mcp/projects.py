"""Per-user project enablement for the shared connector.

A stored row is the user's explicit choice. Without one, a project is enabled
when its cheap status callback reports `in_use` (the user already has trips,
plans or a linked account), so existing users keep their tools without a row.
Linked project accounts live in each project's own tables, never here.
"""
from datetime import datetime, timezone
import logging

from fastmcp.exceptions import ToolError

logger = logging.getLogger(__name__)

TABLE = "cc_mcp_project_settings"


def stored_choices(client, user_id, project_ids):
    try:
        rows = (client.table(TABLE).select("project_id,enabled").eq("user_id", str(user_id))
                .in_("project_id", list(project_ids)).execute().data) or []
    except Exception as error:
        logger.warning("Project settings unavailable")
        raise ToolError("Could not check your enabled projects. Retry in a moment.") from error
    return {row["project_id"]: bool(row["enabled"]) for row in rows}


def project_status(client, user, provider):
    if provider.status is None:
        return {"in_use": False}
    try:
        return dict(provider.status(client, user))
    except Exception:
        logger.warning("Project setup status unavailable: %s", provider.name)
        return {"in_use": False, "unavailable": True,
                "next_step": f"Status unavailable; open {provider.url} to check your setup."}


def linked_account(client, user, provider):
    if provider.link is None:
        return None
    try:
        return provider.link.linked(client, user)
    except Exception:
        logger.warning("Project account link unavailable: %s", provider.name)
        return None


def project_states(client, user, providers, with_status=True):
    """Return {project_id: {enabled, source, linked, account, status}}.

    Status callbacks run only when needed for a default or when requested.
    Failures leave a project disabled by default (fail closed) but never
    override the user's stored choice.
    """
    providers = list(providers)
    if not providers:
        return {}
    choices = stored_choices(client, user.id, [provider.name for provider in providers])
    states = {}
    for provider in providers:
        status = project_status(client, user, provider) if with_status or provider.name not in choices else None
        if provider.name in choices:
            enabled, source = choices[provider.name], "your choice"
        else:
            enabled = bool(status.get("in_use"))
            source = "default: you already use it" if enabled else "default: off until enabled"
        account = linked_account(client, user, provider) if provider.link and (enabled or with_status) else None
        states[provider.name] = {"enabled": enabled, "source": source,
                                 "linked": None if provider.link is None else account is not None,
                                 "account": account, "status": status}
    return states


def set_enabled(client, user_id, project_id, enabled):
    now = datetime.now(timezone.utc).isoformat()
    try:
        client.table(TABLE).upsert({"user_id": str(user_id), "project_id": project_id,
                                    "enabled": enabled, "updated_at": now},
                                   on_conflict="user_id,project_id").execute()
    except Exception as error:
        logger.warning("Project setting update failed: %s", project_id)
        raise ToolError("Could not save that change. Retry in a moment; nothing changed.") from error
