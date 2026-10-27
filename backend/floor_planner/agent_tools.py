"""Floor Planner tools registered on the shared Cozy Commons MCP server."""

from typing import Annotated

from fastapi import HTTPException
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AccessToken
from pydantic import Field
from starlette.concurrency import run_in_threadpool

from cc_mcp.server import ToolProvider
from .agent_operations import apply_operations, scene_schema
from .routes import document_access, get_document, list_document_rows, normalize_scene, public_plan, verified_email

READ_SCOPE = "floor-plans:read"
EDIT_SCOPE = "floor-plans:edit"


def register_tools(mcp, context):
    service_client = context.service_client
    need_scope = context.need_scope
    async def signed_in_user(access: AccessToken):
        user = await context.signed_in_user(access)
        email = verified_email(user)
        if not user or not email:
            raise ToolError("Use a verified Cozy Commons email address to access floor plans.")
        return user, email

    def readable_document(document_id: str, user):
        try:
            document = get_document(service_client, document_id)
        except HTTPException as error:
            raise ToolError("Plan not found or you do not have access.") from error
        access = document_access(service_client, document, user)
        if access is None:
            raise ToolError("Plan not found or you do not have access.")
        return document, access

    @mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False})
    async def list_floor_plans() -> dict:
        """List your plans and plans shared with your verified Cozy Commons account."""
        access = need_scope(READ_SCOPE)
        user, _email = await signed_in_user(access)
        grouped = await run_in_threadpool(list_document_rows, service_client, user)
        return {
            key: [public_plan(row, label) for row in grouped[key]]
            for key, label in (("mine", "owner"), ("shared", "editor"))
        }

    @mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False})
    async def get_floor_plan(plan_id: str) -> dict:
        """Read one plan you own, can edit, or can view publicly."""
        access = need_scope(READ_SCOPE)
        user, _email = await signed_in_user(access)
        document, permission = await run_in_threadpool(readable_document, plan_id, user)
        return {
            **public_plan(document, permission),
            "scene": document["scene"],
            "can_edit": permission in {"owner", "editor"},
        }

    @mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False})
    async def describe_floor_plan_schema() -> dict:
        """Describe scene version 2, inches, geometry fields, and atomic edit operations."""
        need_scope(READ_SCOPE)
        return scene_schema()

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False})
    async def edit_floor_plan(
        plan_id: str,
        expected_revision: Annotated[int, Field(strict=True, ge=1)],
        operations: list[dict],
    ) -> dict:
        """Atomically add, update, or delete up to 100 elements at the expected revision.

        Editing needs both floor-plans:read and floor-plans:edit. Plan visibility,
        invitations, ownership, and deletion remain controlled in the Cozy Commons UI.
        """
        access = need_scope(READ_SCOPE, EDIT_SCOPE)
        user, email = await signed_in_user(access)
        document, permission = await run_in_threadpool(readable_document, plan_id, user)
        if permission not in {"owner", "editor"}:
            raise ToolError("Public plans are read-only. Ask the owner to invite your verified account to edit.")
        if document["revision"] != expected_revision:
            raise ToolError(
                f"Revision conflict: this plan is now at revision {document['revision']}. Read it again before editing."
            )
        try:
            next_scene = apply_operations(document["scene"], operations)
        except HTTPException as error:
            raise ToolError(str(error.detail)) from error

        def save():
            return service_client.rpc(
                "floor_planner_update_document",
                {
                    "p_document_id": document["id"],
                    "p_actor_id": str(user.id),
                    "p_actor_email": email,
                    "p_expected_revision": expected_revision,
                    "p_changes": {"scene": normalize_scene(next_scene)},
                },
            ).execute().data

        try:
            result = await run_in_threadpool(save)
        except Exception as error:
            raise ToolError("Could not save the plan. Read it again and retry if the connection recovers.") from error
        if not isinstance(result, dict):
            raise ToolError("Could not save the plan.")
        if result.get("status") == "forbidden":
            raise ToolError("Your edit access changed. No plan changes were saved.")
        if result.get("status") == "missing":
            raise ToolError("Plan not found.")
        if result.get("status") == "conflict":
            raise ToolError(f"Revision conflict: the plan is now at revision {result.get('revision', 'newer')}. Read it again.")
        saved = result.get("document")
        if not isinstance(saved, dict):
            raise ToolError("Could not save the plan.")
        return {
            "id": saved["id"],
            "revision": saved["revision"],
            "applied_operations": len(operations),
            "scene": saved["scene"],
        }



provider = ToolProvider(name="floor-planner", scopes=(READ_SCOPE, EDIT_SCOPE), register=register_tools)
