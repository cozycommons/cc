"""Real PostgreSQL checks for Resy connector links and receipts (0018).

Synthetic disposable databases on the allowlisted test server; never Resy calls.
Locally: DICE_TEST_DATABASE=1 DB_URL=postgresql://postgres:postgres@127.0.0.1:54322/dummi_regression_<n>_<n>.
"""
from uuid import uuid4

import pytest

import migration_runner
from tests.migration_harness import REPO, checkout_release, disposable_migration_database, migration_database  # noqa: F401

PRE_LINK_RELEASE = "846e1223eafdb9e848a25171c64f7eb625025512"  # main with Beli connector (#200, 0017), before 0018
CONTRACT = (REPO / "backend/migrations/beli_schema_contract.sql").read_text()


@pytest.fixture(scope="module")
def resy_database():
    with disposable_migration_database() as database:
        database.sql(migration_runner.render(["beli"]))
        yield database


@pytest.fixture
def db(resy_database):
    resy_database.sql("TRUNCATE public.resy_agent_receipts, public.resy_accounts CASCADE;")
    return resy_database


def user(db):
    identity = str(uuid4())
    db.sql(f"INSERT INTO auth.users(id) VALUES ('{identity}');")
    return identity


def account(db, owner=None):
    identity = str(uuid4())
    db.sql(f"""SET ROLE service_role;
        INSERT INTO public.resy_accounts(id,email_enc,password_enc,token_hash,token_prefix,owner_user_id)
        VALUES ('{identity}','synthetic','synthetic','{uuid4().hex}','ccr_test',
                {f"'{owner}'" if owner else 'NULL'});""")
    return identity


def link(db, account_id, user_id):
    return db.sql(f"SET ROLE service_role; SELECT public.resy_link_account('{account_id}','{user_id}');").stdout.strip()


def owner(db, account_id):
    return db.sql(f"SELECT owner_user_id FROM public.resy_accounts WHERE id='{account_id}';").stdout.strip() or None


def receipt(user_id, key="book-1"):
    return f"""SET ROLE service_role; INSERT INTO public.resy_agent_receipts(user_id,idempotency_key,payload,target)
        VALUES ('{user_id}','{key}','{{}}','{{}}')"""


def test_schema_attests_and_replays(db):
    assert db.sql("SELECT max(version) FROM public.beli_schema_migrations;").stdout.strip() == "21"
    assert "Applying " not in db.sql(migration_runner.render(["beli"])).stdout
    db.sql(CONTRACT)


def test_link_refuses_another_owner_and_moves_your_own_link(db):
    sam, alex = user(db), user(db)
    first, second = account(db), account(db)
    assert link(db, first, sam) == "linked" and owner(db, first) == sam
    assert link(db, first, sam) == "already_linked"
    assert link(db, first, alex) == "other_owner" and owner(db, first) == sam
    assert link(db, second, sam) == "linked"
    assert owner(db, first) is None and owner(db, second) == sam
    assert link(db, str(uuid4()), sam) == "missing"


def test_one_account_per_user_and_user_deletion_unlinks(db):
    sam = user(db)
    first, second = account(db, owner=sam), account(db)
    duplicate = db.sql(f"UPDATE public.resy_accounts SET owner_user_id='{sam}' WHERE id='{second}';", check=False)
    assert duplicate.returncode != 0 and "resy_accounts_owner_user_id_key" in duplicate.stderr
    db.sql(receipt(sam) + ";")
    db.sql(f"DELETE FROM auth.users WHERE id='{sam}';")
    assert owner(db, first) is None  # the Resy account and its token survive
    assert db.sql("SELECT count(*) FROM public.resy_agent_receipts;").stdout.strip() == "0"


def test_receipts_are_unique_need_a_target_and_are_never_deleted(db):
    sam = user(db)
    db.sql(receipt(sam) + ";")
    assert db.sql(receipt(sam) + " ON CONFLICT DO NOTHING RETURNING 1;").stdout.strip() == ""
    db.sql(f"SET ROLE service_role; UPDATE public.resy_agent_receipts SET result='{{}}' WHERE user_id='{sam}';")
    deleted = db.sql(f"SET ROLE service_role; DELETE FROM public.resy_agent_receipts WHERE user_id='{sam}';",
                     check=False)
    assert deleted.returncode != 0 and "permission denied" in deleted.stderr
    no_target = db.sql(f"""SET ROLE service_role; INSERT INTO public.resy_agent_receipts(user_id,idempotency_key,payload)
        VALUES ('{sam}','book-2','{{}}');""", check=False)
    assert no_target.returncode != 0 and "not-null" in no_target.stderr
    empty = db.sql(receipt(sam, "") + ";", check=False)
    assert empty.returncode != 0 and "check constraint" in empty.stderr


@pytest.mark.parametrize("role", ["anon", "authenticated"])
@pytest.mark.parametrize("statement", [
    "SELECT * FROM public.resy_accounts",
    "SELECT owner_user_id FROM public.resy_accounts",
    "UPDATE public.resy_accounts SET owner_user_id=NULL",
    "SELECT * FROM public.resy_agent_receipts",
    "INSERT INTO public.resy_agent_receipts(user_id,idempotency_key,payload,target) "
    "VALUES (gen_random_uuid(),'k','{}','{}')",
    "SELECT public.resy_link_account(gen_random_uuid(), gen_random_uuid())",
])
def test_browser_roles_are_denied(db, role, statement):
    denied = db.sql(f"SET ROLE {role}; {statement};", check=False)
    assert denied.returncode != 0 and "permission denied" in denied.stderr


@pytest.mark.parametrize("tamper", [
    "GRANT SELECT ON public.resy_agent_receipts TO authenticated;",
    "GRANT SELECT (owner_user_id) ON public.resy_accounts TO anon;",
    "ALTER TABLE public.resy_agent_receipts DISABLE ROW LEVEL SECURITY;",
    "REVOKE UPDATE ON public.resy_agent_receipts FROM service_role;",
    "REVOKE UPDATE ON public.resy_accounts FROM service_role;",
    "GRANT DELETE ON public.resy_agent_receipts TO service_role;",
    "GRANT EXECUTE ON FUNCTION public.resy_link_account(uuid,uuid) TO PUBLIC;",
    "ALTER FUNCTION public.resy_link_account(uuid,uuid) SECURITY DEFINER;",
    "DROP INDEX public.resy_accounts_owner_user_id_key;",
])
def test_release_contract_rejects_unsafe_links(db, tamper):
    result = db.sql("BEGIN; " + tamper + "\n" + CONTRACT, check=False)
    assert result.returncode != 0 and "Beli schema contract:" in result.stderr
    db.sql(CONTRACT)  # The failed session rolled the tampering back.


def test_upgrade_keeps_existing_accounts_unlinked(migration_database, tmp_path):  # noqa: F811
    database = migration_database
    database.release(checkout_release(PRE_LINK_RELEASE, tmp_path / "previous"))
    identity = str(uuid4())
    database.sql(f"""INSERT INTO public.resy_accounts(id,label,email_enc,password_enc,auth_token_enc,token_hash,token_prefix)
        VALUES ('{identity}','synthetic','enc-email','enc-pw','enc-auth','synthetic-hash','ccr_test');""")
    columns = "id,label,email_enc,password_enc,auth_token_enc,token_hash,token_prefix,created_at"
    before = database.sql(f"SELECT {columns} FROM public.resy_accounts;").stdout
    assert "Applying 0018_beli_resy_account_owner.sql" in database.release().stdout
    assert database.sql(f"SELECT {columns} FROM public.resy_accounts;").stdout == before
    assert database.sql("SELECT count(*) FROM public.resy_accounts WHERE owner_user_id IS NOT NULL;").stdout.strip() == "0"
    assert "Applying " not in database.release().stdout
