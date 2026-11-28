"""Arcade state through real PostgREST, with migration-created tables and functions."""
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from supabase import create_client

from arcade.store import Store
from tests.dice_test_database import is_isolated_dice_test_database

pytestmark = pytest.mark.skipif(
    not is_isolated_dice_test_database(os.environ) or not os.getenv("DICE_TEST_REST_URL"),
    reason="isolated database and PostgREST required",
)


@pytest.fixture
def players():
    # Same isolated stack and service-role JWT as the repository's API integration tests.
    client = create_client(os.environ["DICE_TEST_REST_URL"], os.environ["SECRET_KEY"])
    users = [str(uuid4()), str(uuid4())]
    sql = "INSERT INTO auth.users(id) VALUES " + ",".join(f"('{user}')" for user in users) + ";"
    def execute(statement):
        return subprocess.run(["psql", os.environ["DB_URL"], "-X", "-v", "ON_ERROR_STOP=1", "-Atq"],
                              input=statement, text=True, capture_output=True, check=True, timeout=30).stdout.strip()
    execute(sql)
    try:
        yield client, users, execute
    finally:
        execute("DELETE FROM auth.users WHERE id IN (" + ",".join(f"'{user}'" for user in users) + ");")


def test_profiles_persist_without_local_paths_and_remain_private(players, monkeypatch):
    client, (alice, bob), sql = players
    monkeypatch.delenv("ARCADE_STATE_PATH", raising=False)
    state = Store(client)
    settings = state.profile(alice)["settings"]
    assert settings["frame_rate"] == 60
    settings["das_ms"] = 150
    state.save_profile(alice, settings)
    assert Store(client).profile(alice)["settings"]["das_ms"] == 150
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from types import SimpleNamespace
    from arcade.routes import router, current_user
    app = FastAPI()
    app.state.mcp_supabase = client
    app.include_router(router, prefix="/arcade")
    app.dependency_overrides[current_user] = lambda: SimpleNamespace(id=alice)
    response = TestClient(app).get("/arcade/profile")
    assert response.status_code == 200
    assert response.json()["das_ms"] == 150
    assert state.profile(bob)["settings"]["das_ms"] == 200
    # Unknown older fields get defaults without discarding saved handling.
    client.table("arcade_profiles").update({"settings":{"das_ms":133}}).eq("user_id",alice).execute()
    assert state.profile(alice)["settings"]["frame_rate"] == 60
    assert state.profile(alice)["settings"]["das_ms"] == 133
    assert sql("SET ROLE service_role; SELECT public.arcade_readiness();") == "t"
    for role in ("anon", "authenticated"):
        assert sql(f"SELECT has_table_privilege('{role}','public.arcade_profiles','SELECT');") == "f"
        assert sql(f"SELECT has_function_privilege('{role}','public.arcade_start_run(uuid,uuid)','EXECUTE');") == "f"


def test_tabs_and_owners_keep_independent_runs(players):
    client, (alice,bob), sql = players
    state = Store(client)
    tabs = [state.session(state.launch(owner)["token"]) for owner in (alice,alice,bob)]
    ids = [state.start_run(session) for session in tabs]
    for session, score in zip(tabs,(5,9,13)):
        state.save_run(session,{"score":score}, "<record/>")
    assert {row["id"]:row["metrics"]["score"] for row in state.runs(alice)} == {ids[0]:5,ids[1]:9}
    assert {row["id"]:row["metrics"]["score"] for row in state.runs(bob)} == {ids[2]:13}
    assert all(row["complete"] for row in state.runs(alice))
    assert all("record" not in row for row in state.runs(alice))
    with pytest.raises(ValueError):
        state.save_run({**tabs[0],"user_id":bob},{"score":999})
    assert state.runs(alice)[0]["metrics"]["score"] in (5,9)


def test_overlapping_callbacks_merge_metrics_and_expired_sessions_cannot_write(players):
    client, (alice,_), sql = players
    state = Store(client)
    issued = state.launch(alice)
    session = state.session(issued["token"])
    state.start_run(session)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda values: state.save_run(session,values), [{"lines":4},{"score":100}]))
    assert state.runs(alice)[0]["metrics"] == {"lines":4,"score":100}
    client.table("arcade_sessions").update({"expires_at":0}).eq("id",session["id"]).execute()
    assert state.session(issued["token"]) is None
    with pytest.raises(ValueError):
        state.start_run(session)
    with pytest.raises(ValueError):
        state.save_run(session,{"score":999})

def test_managed_package_uses_existing_storage_and_survives_fresh_cache(players):
    from types import SimpleNamespace
    from arcade.package_store import PackageStore, BUCKET
    from tests.test_arcade_package import package_bytes
    client, (alice,_), sql = players
    objects = {}
    class Bucket:
        def upload(self, key, content, file_options):
            objects[key] = content
        def download(self, key):
            return objects[key]
    class Storage:
        def from_(self, name):
            assert name == BUCKET
            return Bucket()
    class WithStorage:
        storage = Storage()
        def table(self, name):
            return client.table(name)
    repository = PackageStore(WithStorage())
    content = package_bytes()
    import hashlib
    digest = hashlib.sha256(content).hexdigest()
    try:
        repository.install(content, alice)
        assert repository.installed()
        fresh = PackageStore(WithStorage())
        assert fresh.current().file("main/movie.swf")[0].read_bytes() == b"game"
        assert sql("SELECT public.arcade_readiness();") == "t"
        assert sql("SELECT public FROM storage.buckets WHERE id='arcade-packages';") == "f"
        assert sql("SELECT has_table_privilege('authenticated','public.arcade_package','SELECT');") == "f"
    finally:
        sql("DELETE FROM public.arcade_package WHERE digest='" + digest + "';")


def test_package_import_requires_commons_admin_before_reading_body(players):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from types import SimpleNamespace
    from arcade.routes import router, current_user
    from arcade.package_store import PackageStore
    client, (alice,_), sql = players
    app = FastAPI()
    app.state.mcp_supabase = client
    app.state.analytics_supabase = SimpleNamespace(
        auth=SimpleNamespace(get_user=lambda token: SimpleNamespace(
            user=SimpleNamespace(id=alice,email_confirmed_at="2026-01-01",is_anonymous=False))))
    app.state.arcade_packages = PackageStore(client)
    app.include_router(router,prefix="/arcade")
    browser = TestClient(app)
    assert browser.post("/arcade/package",content=b"not a package").status_code == 401
    app.dependency_overrides[current_user] = lambda: SimpleNamespace(id=alice,email_confirmed_at="2026-01-01")
    assert browser.post("/arcade/package",content=b"not a package",
                        headers={"Authorization":"Bearer ordinary-user"}).status_code == 403
