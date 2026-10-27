"""Real verified-email grants and RLS behavior on the loopback Dice Supabase stack."""
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from postgrest.exceptions import APIError
from supabase import create_client

from floor_planner.routes import router


@pytest.fixture
def local_floor_planner_api():
    if os.environ.get("FLOOR_PLANNER_INTEGRATION") != "1":
        pytest.skip("Set FLOOR_PLANNER_INTEGRATION=1 to use the loopback Supabase stack.")
    root = Path(__file__).resolve().parents[2]
    status = subprocess.run([str(root / "scripts/dice-supabase.sh"), "status", "--workdir", str(root), "-o", "json"],
                            check=True, capture_output=True, text=True)
    settings = json.loads(status.stdout)
    assert settings["API_URL"] in {"http://127.0.0.1:54321", "http://localhost:54321"}
    replay = subprocess.run([sys.executable, str(root / "backend/migration_runner.py"), "--family", "floor_planner"],
                            cwd=root, check=True, env=dict(os.environ, SUPABASE_DB_URL=settings["DB_URL"]),
                            capture_output=True, text=True)
    assert "Applying 0001_floor_planner_documents.sql" not in replay.stdout
    assert "Applying 0002_floor_planner_scans.sql" not in replay.stdout

    service = create_client(settings["API_URL"], settings["SERVICE_ROLE_KEY"])
    accounts = []
    documents = []
    app = FastAPI()
    app.state.floor_planner_supabase = service

    @app.middleware("http")
    async def private_no_store(request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/floor-planner/"):
            response.headers["Cache-Control"] = "private, no-store"
        return response

    app.include_router(router, prefix="/floor-planner")
    with TestClient(app) as api:
        yield api, service, settings, accounts, documents
    if documents:
        service.table("floor_plan_documents").delete().in_("id", documents).execute()
    for user_id in accounts:
        service.auth.admin.delete_user(user_id)


def create_account(service, settings, accounts, email):
    user = service.auth.admin.create_user({"email": email, "password": "floor-planner-test-password", "email_confirm": True}).user
    accounts.append(str(user.id))
    client = create_client(settings["API_URL"], settings["ANON_KEY"])
    session = client.auth.sign_in_with_password({"email": email, "password": "floor-planner-test-password"}).session
    client.postgrest.auth(session.access_token)
    return {"Authorization": f"Bearer {session.access_token}"}, client


def test_email_invites_private_public_revision_and_revocation(local_floor_planner_api):
    api, service, settings, accounts, documents = local_floor_planner_api
    token = uuid4().hex
    owner_email = f"floor-owner-{token}@floor-planner.local"
    recipient_email = f"later-{token}@floor-planner.local"
    owner, owner_client = create_account(service, settings, accounts, owner_email)
    outsider, outsider_client = create_account(service, settings, accounts, f"outside-{token}@floor-planner.local")
    anonymous_client = create_client(settings["API_URL"], settings["ANON_KEY"])
    assert api.get("/floor-planner/plans").status_code == 200
    assert api.get("/floor-planner/plans/no-such-plan").status_code == 404

    scene = {"version": 2, "title": "Untitled plan", "units": "inches", "rooms": [], "elements": [], "viewport": None}
    created = api.post("/floor-planner/plans", headers=owner, json={"title": "Sketch", "template": "blank", "scene": scene})
    assert created.status_code == 201, created.text
    plan = created.json()
    documents.append(plan["id"])
    assert plan["visibility"] == "private" and plan["is_owner"] is True
    assert "Cache-Control" in created.headers and "no-store" in created.headers["Cache-Control"]
    assert api.get(f"/floor-planner/plans/{plan['id']}").status_code == 404
    assert owner_client.table("floor_plan_documents").select("id,scene").eq("id", plan["id"]).execute().data
    assert anonymous_client.table("floor_plan_documents").select("id,scene").eq("id", plan["id"]).execute().data == []
    assert outsider_client.table("floor_plan_documents").select("id,scene").eq("id", plan["id"]).execute().data == []
    with pytest.raises(APIError):
        owner_client.table("floor_plan_documents").update({"title": "Browser write"}).eq("id", plan["id"]).execute()
    with pytest.raises(APIError):
        owner_client.rpc("floor_planner_update_document", {}).execute()

    invitation = api.post(f"/floor-planner/plans/{plan['id']}/invitations", headers=owner, json={"email": recipient_email})
    assert invitation.status_code == 201, invitation.text
    invitation_id = invitation.json()["id"]
    assert invitation.json()["status"] == "pending"
    assert api.get(f"/floor-planner/plans/{plan['id']}/invitations").status_code == 401
    assert api.get("/floor-planner/plans", headers=owner).json()["mine"][0]["id"] == plan["id"]

    recipient, recipient_client = create_account(service, settings, accounts, recipient_email)
    opened = api.get(f"/floor-planner/plans/{plan['id']}", headers=recipient)
    assert opened.status_code == 200 and opened.json()["access"] == "editor"
    shared = api.get("/floor-planner/plans", headers=recipient).json()["shared"]
    assert [item["id"] for item in shared] == [plan["id"]]
    assert recipient_email not in json.dumps(shared)
    assert api.get(f"/floor-planner/plans/{plan['id']}/invitations", headers=recipient).status_code == 404
    assert recipient_client.table("floor_plan_documents").select("id,scene").eq("id", plan["id"]).execute().data
    with pytest.raises(APIError):
        recipient_client.table("floor_plan_invitations").select("email").eq("document_id", plan["id"]).execute()
    with pytest.raises(APIError):
        recipient_client.table("floor_plan_invitations").insert({"document_id": plan["id"], "email": "bad@floor-planner.local"}).execute()
    assert api.patch(f"/floor-planner/plans/{plan['id']}", headers=recipient,
                     json={"expected_revision": 1, "title": "Not owner"}).status_code == 403

    edit_scene = scene | {"elements": [{"id": "line-1", "type": "line", "x1": 0, "y1": 0, "x2": 12, "y2": 12}]}
    first_save = api.patch(f"/floor-planner/plans/{plan['id']}", headers=recipient,
                           json={"expected_revision": 1, "scene": edit_scene})
    assert first_save.status_code == 200 and first_save.json()["revision"] == 2
    stale = api.patch(f"/floor-planner/plans/{plan['id']}", headers=recipient,
                      json={"expected_revision": 1, "scene": edit_scene})
    assert stale.status_code == 409

    owner_view = api.get(f"/floor-planner/plans/{plan['id']}", headers=owner).json()
    public = api.patch(f"/floor-planner/plans/{plan['id']}", headers=owner,
                       json={"expected_revision": owner_view["revision"], "visibility": "public"})
    assert public.status_code == 200 and public.json()["revision"] == 3
    anonymous = api.get(f"/floor-planner/plans/{plan['id']}")
    assert anonymous.status_code == 200 and anonymous.json()["can_edit"] is False
    gallery = api.get("/floor-planner/plans").json()["public"]
    assert plan["id"] in [item["id"] for item in gallery]
    assert recipient_email not in json.dumps(gallery) and "owner_id" not in json.dumps(gallery)
    assert [item["id"] for item in api.get("/floor-planner/plans", headers=recipient).json()["shared"]] == [plan["id"]]
    assert anonymous_client.table("floor_plan_documents").select("id,scene").eq("id", plan["id"]).execute().data
    assert outsider_client.table("floor_plan_documents").select("id,scene").eq("id", plan["id"]).execute().data

    removed = api.delete(f"/floor-planner/plans/{plan['id']}/invitations/{invitation_id}", headers=owner)
    assert removed.status_code == 204
    denied = api.patch(f"/floor-planner/plans/{plan['id']}", headers=recipient,
                       json={"expected_revision": 3, "scene": edit_scene})
    assert denied.status_code == 404
    assert recipient_client.table("floor_plan_documents").select("id,scene").eq("id", plan["id"]).execute().data
    assert api.delete(f"/floor-planner/plans/{plan['id']}", headers=recipient).status_code == 404
    rpc = service.rpc("floor_planner_update_document", {
        "p_document_id": plan["id"], "p_actor_id": accounts[1], "p_actor_email": recipient_email,
        "p_expected_revision": 3, "p_changes": {"scene": edit_scene},
    }).execute().data
    assert rpc["status"] == "forbidden"
    assert api.delete(f"/floor-planner/plans/{plan['id']}", headers=owner).status_code == 204

    private_created = api.post("/floor-planner/plans", headers=owner,
                               json={"title": "Private access check", "template": "blank", "scene": scene})
    assert private_created.status_code == 201, private_created.text
    private_plan = private_created.json()
    documents.append(private_plan["id"])
    private_invitation = api.post(f"/floor-planner/plans/{private_plan['id']}/invitations", headers=owner,
                                  json={"email": recipient_email})
    assert private_invitation.status_code == 201, private_invitation.text
    assert api.get(f"/floor-planner/plans/{private_plan['id']}", headers=recipient).status_code == 200
    assert recipient_client.table("floor_plan_documents").select("id,scene").eq("id", private_plan["id"]).execute().data
    assert api.delete(f"/floor-planner/plans/{private_plan['id']}/invitations/{private_invitation.json()['id']}",
                      headers=owner).status_code == 204
    assert recipient_client.table("floor_plan_documents").select("id,scene").eq("id", private_plan["id"]).execute().data == []
    assert api.delete(f"/floor-planner/plans/{private_plan['id']}", headers=recipient).status_code == 404
    assert api.delete(f"/floor-planner/plans/{private_plan['id']}", headers=owner).status_code == 204
