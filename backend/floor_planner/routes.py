"""Floor plan documents with verified-email invitations and owner-controlled sharing."""
import json
import math
import re
from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from gotrue.errors import AuthApiError
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

router = APIRouter(tags=["Floor Planner"])
bearer = HTTPBearer(auto_error=False)
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
EMAIL = re.compile(r"^[^\s@]+@[^\s@.]+(?:\.[^\s@.]+)+$")
MAX_SCENE_BYTES = 2 * 1024 * 1024
SCENE_VERSION = 2


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreatePlan(Input):
    title: Name = "Untitled plan"
    template: Literal["blank", "apartment"]
    scene: dict


class UpdatePlan(Input):
    expected_revision: Annotated[int, Field(strict=True, ge=1)]
    title: Name | None = None
    visibility: Literal["private", "public"] | None = None
    scene: dict | None = None

    @field_validator("title")
    @classmethod
    def nonblank_title(cls, value):
        if value is not None and not value.strip():
            raise ValueError("Plan title cannot be blank")
        return value

    @model_validator(mode="before")
    @classmethod
    def reject_explicit_null(cls, values):
        if isinstance(values, dict):
            for key in ("title", "visibility", "scene"):
                if key in values and values[key] is None:
                    raise ValueError(f"{key} cannot be null")
        return values


class AddInvitation(Input):
    email: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=254)]

    @field_validator("email")
    @classmethod
    def valid_email(cls, value):
        normalized = value.lower()
        if not EMAIL.fullmatch(normalized):
            raise ValueError("Enter a valid email address")
        return normalized


def database(request: Request):
    return request.app.state.floor_planner_supabase


def verified_email(user) -> str | None:
    value = getattr(user, "email", None)
    confirmed = getattr(user, "email_confirmed_at", None)
    return value.lower() if value and confirmed else None


def current_user(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    if not credentials:
        return None
    try:
        user = database(request).auth.get_user(credentials.credentials).user
    except AuthApiError:
        raise HTTPException(401, "Your session expired. Please sign in again.")
    if not user:
        raise HTTPException(401, "Sign in to use Floor Planner.")
    return user


def require_verified(user):
    if user is None:
        raise HTTPException(401, "Sign in with the invited email address to continue.")
    if not verified_email(user):
        raise HTTPException(403, "Verify your email address before creating or editing plans.")
    return user


def rows(query):
    result = query.execute()
    return result.data if result and result.data else []


def one(query):
    result = query.maybe_single().execute()
    return result.data if result else None


def normalize_scene(scene: dict) -> dict:
    if not isinstance(scene, dict) or scene.get("version") != SCENE_VERSION or scene.get("units") != "inches":
        raise HTTPException(422, "This floor plan uses an unsupported scene format.")
    elements = scene.get("elements")
    if not isinstance(elements, list) or len(elements) > 10000:
        raise HTTPException(422, "A floor plan must contain a valid list of drawing elements.")
    allowed = {"wall", "opening", "furniture", "rectangle", "ellipse", "line", "freehand"}
    numeric = {
        "wall": ("x", "y", "length", "thickness", "rotation"),
        "opening": ("x", "y", "width", "thickness", "rotation"),
        "furniture": ("x", "y", "width", "height", "rotation"),
        "rectangle": ("x", "y", "width", "height", "rotation"),
        "ellipse": ("x", "y", "width", "height", "rotation"),
        "line": ("x1", "y1", "x2", "y2"),
    }
    element_ids = set()
    for item in elements:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"].strip() or item.get("type") not in allowed:
            raise HTTPException(422, "Every drawing element needs a string ID and supported type.")
        if item["id"] in element_ids:
            raise HTTPException(422, "Drawing element IDs must be unique within a plan.")
        element_ids.add(item["id"])
        if any(key in item and not isinstance(item[key], str) for key in ("label", "kind", "furnitureType")):
            raise HTTPException(422, "Drawing labels and types must be strings.")
        if item["type"] == "freehand":
            points = item.get("points")
            if not isinstance(points, list) or len(points) < 1 or len(points) > 10000:
                raise HTTPException(422, "Freehand elements need a valid list of points.")
            values = [coordinate for point in points if isinstance(point, dict) for coordinate in (point.get("x"), point.get("y"))]
            if len(values) != len(points) * 2 or any(not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or abs(value) > 1_000_000 for value in values):
                raise HTTPException(422, "Freehand points must contain finite coordinates.")
        else:
            for key in numeric[item["type"]]:
                value = item.get(key)
                if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or abs(value) > 1_000_000:
                    raise HTTPException(422, f"Drawing element field {key} must be a finite number.")
            size_fields = {"wall": ("length", "thickness"), "opening": ("width", "thickness"),
                           "furniture": ("width", "height"), "rectangle": ("width", "height"),
                           "ellipse": ("width", "height")}.get(item["type"], ())
            if any(item[key] <= 0 for key in size_fields):
                raise HTTPException(422, "Drawing dimensions must be greater than zero.")
    viewport = scene.get("viewport")
    if viewport is not None and (not isinstance(viewport, dict) or any(not isinstance(viewport.get(key), (int, float)) or isinstance(viewport.get(key), bool) or not math.isfinite(viewport[key]) for key in ("x", "y", "zoom")) or viewport["zoom"] <= 0):
        raise HTTPException(422, "Viewport must contain finite x, y, and positive zoom values.")
    try:
        if len(json.dumps(scene, separators=(",", ":"), allow_nan=False).encode("utf-8")) > MAX_SCENE_BYTES:
            raise HTTPException(413, "This floor plan is too large to save.")
    except (TypeError, ValueError):
        raise HTTPException(422, "This floor plan contains unsupported data.")
    return scene


def claim_email_invitations(client, user, document_id: str | None = None):
    email = verified_email(user)
    if not email:
        return
    query = (client.table("floor_plan_invitations").select("id")
             .eq("email", email).is_("accepted_user_id", "null").is_("revoked_at", "null"))
    if document_id:
        query = query.eq("document_id", document_id)
    pending = rows(query)
    for invitation in pending:
        (client.table("floor_plan_invitations").update({"accepted_user_id": str(user.id)})
         .eq("id", invitation["id"]).is_("accepted_user_id", "null").is_("revoked_at", "null").execute())


def list_document_rows(client, user):
    public = rows(client.table("floor_plan_documents")
                  .select("id,title,visibility,template_key,revision,updated_at")
                  .eq("visibility", "public").order("updated_at", desc=True))
    if not user or not verified_email(user):
        return {"mine": [], "shared": [], "public": public}

    claim_email_invitations(client, user)
    owned = rows(client.table("floor_plan_documents")
                 .select("id,title,visibility,template_key,revision,updated_at")
                 .eq("owner_id", str(user.id)).order("updated_at", desc=True))
    shared_ids = {
        row["document_id"]
        for row in rows(client.table("floor_plan_invitations").select("document_id")
                        .eq("accepted_user_id", str(user.id)).is_("revoked_at", "null"))
    }
    owned_ids = {row["id"] for row in owned}
    shared_ids -= owned_ids
    shared = []
    for document_id in shared_ids:
        document = one(client.table("floor_plan_documents")
                       .select("id,title,visibility,template_key,revision,updated_at")
                       .eq("id", document_id))
        if document:
            shared.append(document)
    shared.sort(key=lambda row: row.get("updated_at", ""), reverse=True)
    return {"mine": owned, "shared": shared, "public": public}


def get_document(client, document_id: str):
    try:
        parsed = str(UUID(document_id))
    except (ValueError, TypeError):
        raise HTTPException(404, "Floor plan not found.")
    document = one(client.table("floor_plan_documents").select("*").eq("id", parsed))
    if not document:
        raise HTTPException(404, "Floor plan not found.")
    return document


def document_access(client, document, user):
    if user and verified_email(user):
        if str(document["owner_id"]) == str(user.id):
            return "owner"
        claim_email_invitations(client, user, document["id"])
        invitation = one(client.table("floor_plan_invitations").select("id").limit(1)
                         .eq("document_id", document["id"]).eq("accepted_user_id", str(user.id))
                         .is_("revoked_at", "null"))
        if not invitation:
            invitation = one(client.table("floor_plan_invitations").select("id").limit(1)
                             .eq("document_id", document["id"]).eq("email", verified_email(user))
                             .is_("revoked_at", "null"))
        if invitation:
            return "editor"
    return "public" if document["visibility"] == "public" else None


def public_plan(document, access):
    return {
        "id": document["id"], "title": document["title"], "visibility": document["visibility"],
        "template": document["template_key"], "revision": document["revision"],
        "updated_at": document["updated_at"], "access": access,
    }


@router.get("/plans")
def list_plans(request: Request, user=Depends(current_user)):
    client = database(request)
    grouped = list_document_rows(client, user)
    owned_ids = {row["id"] for row in grouped["mine"]}
    shared_ids = {row["id"] for row in grouped["shared"]}
    public_rows = [(row, "owner" if row["id"] in owned_ids else "editor" if row["id"] in shared_ids else "public")
                   for row in grouped["public"]]
    return {key: [public_plan(document, access) for document, access in documents]
            for key, documents in (("mine", ((row, "owner") for row in grouped["mine"])),
                                   ("shared", ((row, "editor") for row in grouped["shared"])),
                                   ("public", public_rows)) }


@router.post("/plans", status_code=201)
def create_plan(payload: CreatePlan, request: Request, user=Depends(current_user)):
    user = require_verified(user)
    scene = normalize_scene(payload.scene)
    client = database(request)
    document_id = str(uuid4())
    rows(client.table("floor_plan_documents").insert({
        "id": document_id, "owner_id": str(user.id), "title": payload.title.strip(), "visibility": "private",
        "template_key": payload.template, "scene": scene,
        "viewport": scene.get("viewport") or {}, "revision": 1,
    }))
    created = one(client.table("floor_plan_documents").select("*").eq("id", document_id))
    if not created:
        raise HTTPException(500, "Could not create this floor plan.")
    return {**public_plan(created, "owner"), "scene": created["scene"], "viewport": created["viewport"], "can_edit": True, "is_owner": True}


@router.get("/plans/{document_id}")
def read_plan(document_id: str, request: Request, user=Depends(current_user)):
    client = database(request)
    document = get_document(client, document_id)
    access = document_access(client, document, user)
    if access is None:
        raise HTTPException(404, "Floor plan not found or you do not have access.")
    is_owner = access == "owner"
    can_edit = access in {"owner", "editor"}
    return {
        **public_plan(document, access), "scene": document["scene"], "viewport": document["viewport"],
        "can_edit": can_edit, "is_owner": is_owner,
    }


@router.patch("/plans/{document_id}")
def update_plan(document_id: str, payload: UpdatePlan, request: Request, user=Depends(current_user)):
    user = require_verified(user)
    client = database(request)
    document = get_document(client, document_id)
    access = document_access(client, document, user)
    if access not in {"owner", "editor"}:
        raise HTTPException(404, "Floor plan not found or you do not have edit access.")
    fields = payload.model_fields_set - {"expected_revision"}
    if not fields:
        raise HTTPException(422, "Add a plan change to save.")
    if access != "owner" and fields & {"title", "visibility"}:
        raise HTTPException(403, "Only the plan owner can change its title or visibility.")
    changes = {}
    if "title" in fields:
        changes["title"] = payload.title.strip()
    if "visibility" in fields:
        changes["visibility"] = payload.visibility
    if "scene" in fields:
        changes["scene"] = normalize_scene(payload.scene)
        changes["viewport"] = payload.scene.get("viewport") or {}
    result = client.rpc("floor_planner_update_document", {
        "p_document_id": document["id"], "p_actor_id": str(user.id),
        "p_actor_email": verified_email(user), "p_expected_revision": payload.expected_revision,
        "p_changes": changes,
    }).execute().data
    if not isinstance(result, dict):
        raise HTTPException(500, "Could not save this floor plan.")
    if result.get("status") == "forbidden":
        raise HTTPException(403, "Your edit access changed. Your local draft is still available.")
    if result.get("status") == "missing":
        raise HTTPException(404, "Floor plan not found.")
    if result.get("status") == "conflict":
        raise HTTPException(409, "This plan changed elsewhere. Your local draft is still available.")
    saved = result.get("document")
    if not isinstance(saved, dict):
        raise HTTPException(500, "Could not save this floor plan.")
    return {**public_plan(saved, access), "scene": saved["scene"], "viewport": saved["viewport"], "can_edit": True, "is_owner": access == "owner"}


@router.delete("/plans/{document_id}", status_code=204)
def delete_plan(document_id: str, request: Request, user=Depends(current_user)):
    user = require_verified(user)
    client = database(request)
    document = get_document(client, document_id)
    if str(document["owner_id"]) != str(user.id):
        raise HTTPException(404, "Floor plan not found.")
    rows(client.table("floor_plan_documents").delete().eq("id", document["id"]).eq("owner_id", str(user.id)))
    return None


@router.get("/plans/{document_id}/invitations")
def list_invitations(document_id: str, request: Request, user=Depends(current_user)):
    user = require_verified(user)
    client = database(request)
    document = get_document(client, document_id)
    if str(document["owner_id"]) != str(user.id):
        raise HTTPException(404, "Floor plan not found.")
    invitations = rows(client.table("floor_plan_invitations")
                       .select("id,email,accepted_user_id,created_at")
                       .eq("document_id", document["id"]).is_("revoked_at", "null")
                       .order("created_at"))
    return [{"id": row["id"], "email": row["email"], "status": "connected" if row["accepted_user_id"] else "pending", "created_at": row["created_at"]} for row in invitations]


@router.post("/plans/{document_id}/invitations", status_code=201)
def add_invitation(document_id: str, payload: AddInvitation, request: Request, user=Depends(current_user)):
    user = require_verified(user)
    client = database(request)
    document = get_document(client, document_id)
    if str(document["owner_id"]) != str(user.id):
        raise HTTPException(404, "Floor plan not found.")
    if payload.email == verified_email(user):
        raise HTTPException(409, "You already own this plan.")
    existing = one(client.table("floor_plan_invitations").select("id,accepted_user_id,revoked_at")
                   .eq("document_id", document["id"]).eq("email", payload.email))
    if existing:
        if existing["revoked_at"] is None:
            raise HTTPException(409, "That email already has access.")
        rows(client.table("floor_plan_invitations").update({
            "accepted_user_id": None, "invited_by": str(user.id), "created_at": datetime.now(timezone.utc).isoformat(), "revoked_at": None,
        }).eq("id", existing["id"]))
        invitation_id = existing["id"]
    else:
        invitation_id = str(uuid4())
        rows(client.table("floor_plan_invitations").insert({
            "id": invitation_id, "document_id": document["id"], "email": payload.email,
            "invited_by": str(user.id),
        }))
    created = one(client.table("floor_plan_invitations").select("id,email,accepted_user_id,created_at")
                  .eq("id", invitation_id))
    if not created:
        raise HTTPException(500, "Could not add this email.")
    return {"id": created["id"], "email": created["email"], "status": "pending", "created_at": created["created_at"]}


@router.delete("/plans/{document_id}/invitations/{invitation_id}", status_code=204)
def revoke_invitation(document_id: str, invitation_id: str, request: Request, user=Depends(current_user)):
    user = require_verified(user)
    client = database(request)
    document = get_document(client, document_id)
    if str(document["owner_id"]) != str(user.id):
        raise HTTPException(404, "Floor plan not found.")
    try:
        invitation_id = str(UUID(invitation_id))
    except (ValueError, TypeError):
        raise HTTPException(404, "Invitation not found.")
    invitation = one(client.table("floor_plan_invitations").select("id")
                     .eq("id", invitation_id).eq("document_id", document["id"]).is_("revoked_at", "null"))
    if not invitation:
        raise HTTPException(404, "Invitation not found.")
    rows(client.table("floor_plan_invitations").update({
        "revoked_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", invitation_id).eq("document_id", document["id"]).is_("revoked_at", "null"))
    return None
