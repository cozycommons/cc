"""Real PostgreSQL checks for Partiful connector links (0019).

Synthetic disposable databases on the allowlisted test server; never Partiful calls.
Locally: DICE_TEST_DATABASE=1 DB_URL=postgresql://postgres:postgres@127.0.0.1:54322/dummi_regression_<n>_<n>.
"""
from uuid import uuid4

import pytest

import migration_runner
from tests.migration_harness import REPO, checkout_release, disposable_migration_database, migration_database  # noqa: F401

PRE_LINK_RELEASE = "e8602a6105f61910191d6adea987c9169bb302d5"  # main with Resy connector (#201, 0018), before 0019
CONTRACT = (REPO / "backend/migrations/beli_schema_contract.sql").read_text()
COLUMNS = "id,label,refresh_token_enc,uid_enc,token_hash,token_prefix,created_at"


@pytest.fixture(scope="module")
def partiful_database():
    with disposable_migration_database() as database:
        database.sql(migration_runner.render(["beli"]))
        yield database


@pytest.fixture
def db(partiful_database):
    partiful_database.sql("TRUNCATE public.partiful_accounts CASCADE;")
    return partiful_database


def user(db):
    identity = str(uuid4())
    db.sql(f"INSERT INTO auth.users(id) VALUES ('{identity}');")
    return identity


def account(db, owner=None):
    identity = str(uuid4())
    db.sql(f"""SET ROLE service_role;
        INSERT INTO public.partiful_accounts(id,refresh_token_enc,uid_enc,token_hash,token_prefix,owner_user_id)
        VALUES ('{identity}','synthetic-refresh','synthetic-uid','{uuid4().hex}','ccp_test',
                {f"'{owner}'" if owner else 'NULL'});""")
    return identity


def link(db, account_id, user_id):
    return db.sql(f"SET ROLE service_role; SELECT public.partiful_link_account('{account_id}','{user_id}');").stdout.strip()


def owner(db, account_id):
    return db.sql(f"SELECT owner_user_id FROM public.partiful_accounts WHERE id='{account_id}';").stdout.strip() or None


def test_schema_19_attests_and_replays(db):
    assert db.sql("SELECT max(version) FROM public.beli_schema_migrations;").stdout.strip() == "90"
    assert "Applying " not in db.sql(migration_runner.render(["beli"])).stdout
    db.sql(CONTRACT)


def test_link_refuses_another_owner_moves_your_own_link_and_keeps_the_session(db):
    sam, alex = user(db), user(db)
    first, second = account(db), account(db)
    session = f"SELECT refresh_token_enc, uid_enc, token_hash FROM public.partiful_accounts WHERE id='{first}';"
    before = db.sql(session).stdout
    assert link(db, first, sam) == "linked" and owner(db, first) == sam
    assert db.sql(session).stdout == before  # the stored refresh token is never touched
    assert link(db, first, sam) == "already_linked"
    assert link(db, first, alex) == "other_owner" and owner(db, first) == sam
    assert link(db, second, sam) == "linked"
    assert owner(db, first) is None and owner(db, second) == sam
    assert link(db, str(uuid4()), sam) == "missing"


def test_one_account_per_user_and_user_deletion_unlinks(db):
    sam = user(db)
    first, second = account(db, owner=sam), account(db)
    duplicate = db.sql(f"UPDATE public.partiful_accounts SET owner_user_id='{sam}' WHERE id='{second}';", check=False)
    assert duplicate.returncode != 0 and "partiful_accounts_owner_user_id_key" in duplicate.stderr
    db.sql(f"DELETE FROM auth.users WHERE id='{sam}';")
    assert owner(db, first) is None  # the Partiful account and its token survive
    assert db.sql("SELECT count(*) FROM public.partiful_accounts;").stdout.strip() == "2"


@pytest.mark.parametrize("role", ["anon", "authenticated"])
@pytest.mark.parametrize("statement", [
    "SELECT * FROM public.partiful_accounts",
    "SELECT owner_user_id FROM public.partiful_accounts",
    "UPDATE public.partiful_accounts SET owner_user_id=NULL",
    "SELECT public.partiful_link_account(gen_random_uuid(), gen_random_uuid())",
])
def test_browser_roles_are_denied(db, role, statement):
    denied = db.sql(f"SET ROLE {role}; {statement};", check=False)
    assert denied.returncode != 0 and "permission denied" in denied.stderr


@pytest.mark.parametrize("tamper", [
    "GRANT SELECT (owner_user_id) ON public.partiful_accounts TO anon;",
    "GRANT UPDATE ON public.partiful_accounts TO authenticated;",
    "ALTER TABLE public.partiful_accounts DISABLE ROW LEVEL SECURITY;",
    "REVOKE UPDATE ON public.partiful_accounts FROM service_role;",
    "GRANT EXECUTE ON FUNCTION public.partiful_link_account(uuid,uuid) TO PUBLIC;",
    "ALTER FUNCTION public.partiful_link_account(uuid,uuid) SECURITY DEFINER;",
    "DROP INDEX public.partiful_accounts_owner_user_id_key;",
])
def test_release_contract_rejects_unsafe_links(db, tamper):
    result = db.sql("BEGIN; " + tamper + "\n" + CONTRACT, check=False)
    assert result.returncode != 0 and "Beli schema contract:" in result.stderr
    db.sql(CONTRACT)  # The failed session rolled the tampering back.


def test_upgrade_keeps_existing_accounts_unlinked(migration_database, tmp_path):  # noqa: F811
    database = migration_database
    database.release(checkout_release(PRE_LINK_RELEASE, tmp_path / "previous"))
    identity = str(uuid4())
    database.sql(f"""INSERT INTO public.partiful_accounts(id,label,refresh_token_enc,uid_enc,token_hash,token_prefix)
        VALUES ('{identity}','synthetic','enc-refresh','enc-uid','synthetic-hash','ccp_test');""")
    before = database.sql(f"SELECT {COLUMNS} FROM public.partiful_accounts;").stdout
    assert "Applying 0019_beli_partiful_account_owner.sql" in database.release().stdout
    assert database.sql(f"SELECT {COLUMNS} FROM public.partiful_accounts;").stdout == before
    assert database.sql("SELECT count(*) FROM public.partiful_accounts WHERE owner_user_id IS NOT NULL;").stdout.strip() == "0"
    assert "Applying " not in database.release().stdout
