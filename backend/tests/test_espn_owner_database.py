"""Real PostgreSQL checks for ESPN connector links and receipts (0089) and lineup approval claims (0090).

Synthetic disposable databases on the allowlisted test server; never ESPN calls.
Locally: DICE_TEST_DATABASE=1 DB_URL=postgresql://postgres:postgres@127.0.0.1:54322/dummi_regression_<n>_<n>.
"""
from uuid import uuid4

import pytest

import migration_runner
from tests.migration_harness import REPO, checkout_release, disposable_migration_database, migration_database  # noqa: F401

PRE_LINK_RELEASE = "9b84d2ccacd2e60687390817e27855046cad49af"  # main with Partiful connector (#204, 0019), before 0089
CONTRACT = (REPO / "backend/migrations/beli_schema_contract.sql").read_text()


@pytest.fixture(scope="module")
def espn_database():
    with disposable_migration_database() as database:
        database.sql(migration_runner.render(["beli"]))
        yield database


@pytest.fixture
def db(espn_database):
    espn_database.sql("TRUNCATE public.espn_agent_receipts, public.espn_accounts CASCADE;")
    return espn_database


def user(db):
    identity = str(uuid4())
    db.sql(f"INSERT INTO auth.users(id) VALUES ('{identity}');")
    return identity


def account(db, owner=None):
    identity = str(uuid4())
    db.sql(f"""SET ROLE service_role;
        INSERT INTO public.espn_accounts(id,league_id,season,espn_s2_enc,swid_enc,token_hash,token_prefix,owner_user_id)
        VALUES ('{identity}',999,2027,'synthetic','synthetic','{uuid4().hex}','cce_test',
                {f"'{owner}'" if owner else 'NULL'});""")
    return identity


def link(db, account_id, user_id):
    return db.sql(f"SET ROLE service_role; SELECT public.espn_link_account('{account_id}','{user_id}');").stdout.strip()


def owner(db, account_id):
    return db.sql(f"SELECT owner_user_id FROM public.espn_accounts WHERE id='{account_id}';").stdout.strip() or None


def receipt(user_id, key="approve-1"):
    return f"""SET ROLE service_role; INSERT INTO public.espn_agent_receipts(user_id,idempotency_key,payload,target)
        VALUES ('{user_id}','{key}','{{}}','{{}}')"""


def test_schema_attests_and_replays(db):
    assert db.sql("SELECT max(version) FROM public.beli_schema_migrations;").stdout.strip() == "90"
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
    duplicate = db.sql(f"UPDATE public.espn_accounts SET owner_user_id='{sam}' WHERE id='{second}';", check=False)
    assert duplicate.returncode != 0 and "espn_accounts_owner_user_id_key" in duplicate.stderr
    db.sql(receipt(sam) + ";")
    db.sql(f"DELETE FROM auth.users WHERE id='{sam}';")
    assert owner(db, first) is None  # the Resy account and its token survive
    assert db.sql("SELECT count(*) FROM public.espn_agent_receipts;").stdout.strip() == "0"



def test_legacy_disconnect_still_deletes_a_linked_account(db):
    sam = user(db)
    linked = account(db, owner=sam)
    db.sql(f"SET ROLE service_role; DELETE FROM public.espn_accounts WHERE id='{linked}';")  # DELETE /espn/account
    assert db.sql("SELECT count(*) FROM public.espn_accounts;").stdout.strip() == "0"

def lineup_proposal(db, account_id):
    return db.sql(f"""SET ROLE service_role; INSERT INTO public.espn_lineup_runs(account_id,league_id,season,mode,status)
        VALUES ('{account_id}',999,2027,'dry_run','dry_run') RETURNING id;""").stdout.split()[0]


def claim(db, proposal_id, user_id, key):
    return db.sql(f"""SET ROLE service_role; INSERT INTO public.espn_lineup_approvals(proposal_id,user_id,idempotency_key)
        VALUES ('{proposal_id}','{user_id}','{key}') ON CONFLICT (proposal_id) DO NOTHING RETURNING 1;""").stdout.strip()


def test_a_lineup_proposal_is_claimed_once_across_keys_and_never_released(db):
    sam = user(db)
    proposal = lineup_proposal(db, account(db, owner=sam))
    db.sql(receipt(sam) + ";")
    db.sql(receipt(sam, "approve-2") + ";")
    assert claim(db, proposal, sam, "approve-1") == "1"
    assert claim(db, proposal, sam, "approve-2") == ""
    unreserved = db.sql(f"""SET ROLE service_role; INSERT INTO public.espn_lineup_approvals(proposal_id,user_id,idempotency_key)
        VALUES ('{lineup_proposal(db, account(db))}','{sam}','no-receipt');""", check=False)
    assert unreserved.returncode != 0 and "foreign key" in unreserved.stderr
    for statement in ("DELETE FROM public.espn_lineup_approvals", "UPDATE public.espn_lineup_approvals SET idempotency_key='x'"):
        denied = db.sql(f"SET ROLE service_role; {statement};", check=False)
        assert denied.returncode != 0 and "permission denied" in denied.stderr


def test_receipts_are_unique_need_a_target_and_are_never_deleted(db):
    sam = user(db)
    db.sql(receipt(sam) + ";")
    assert db.sql(receipt(sam) + " ON CONFLICT DO NOTHING RETURNING 1;").stdout.strip() == ""
    db.sql(f"SET ROLE service_role; UPDATE public.espn_agent_receipts SET result='{{}}' WHERE user_id='{sam}';")
    deleted = db.sql(f"SET ROLE service_role; DELETE FROM public.espn_agent_receipts WHERE user_id='{sam}';",
                     check=False)
    assert deleted.returncode != 0 and "permission denied" in deleted.stderr
    no_target = db.sql(f"""SET ROLE service_role; INSERT INTO public.espn_agent_receipts(user_id,idempotency_key,payload)
        VALUES ('{sam}','approve-2','{{}}');""", check=False)
    assert no_target.returncode != 0 and "not-null" in no_target.stderr
    empty = db.sql(receipt(sam, "") + ";", check=False)
    assert empty.returncode != 0 and "check constraint" in empty.stderr


@pytest.mark.parametrize("role", ["anon", "authenticated"])
@pytest.mark.parametrize("statement", [
    "SELECT * FROM public.espn_accounts",
    "SELECT owner_user_id FROM public.espn_accounts",
    "UPDATE public.espn_accounts SET owner_user_id=NULL",
    "SELECT * FROM public.espn_agent_receipts",
    "INSERT INTO public.espn_agent_receipts(user_id,idempotency_key,payload,target) "
    "VALUES (gen_random_uuid(),'k','{}','{}')",
    "SELECT public.espn_link_account(gen_random_uuid(), gen_random_uuid())",
    "SELECT * FROM public.espn_lineup_approvals",
])
def test_browser_roles_are_denied(db, role, statement):
    denied = db.sql(f"SET ROLE {role}; {statement};", check=False)
    assert denied.returncode != 0 and "permission denied" in denied.stderr


@pytest.mark.parametrize("tamper", [
    "GRANT SELECT ON public.espn_agent_receipts TO authenticated;",
    "GRANT SELECT (owner_user_id) ON public.espn_accounts TO anon;",
    "ALTER TABLE public.espn_agent_receipts DISABLE ROW LEVEL SECURITY;",
    "REVOKE UPDATE ON public.espn_agent_receipts FROM service_role;",
    "REVOKE UPDATE ON public.espn_accounts FROM service_role;",
    "GRANT DELETE ON public.espn_agent_receipts TO service_role;",
    "GRANT EXECUTE ON FUNCTION public.espn_link_account(uuid,uuid) TO PUBLIC;",
    "ALTER FUNCTION public.espn_link_account(uuid,uuid) SECURITY DEFINER;",
    "DROP INDEX public.espn_accounts_owner_user_id_key;",
    "GRANT DELETE ON public.espn_lineup_approvals TO service_role;",
    "ALTER TABLE public.espn_lineup_approvals DROP CONSTRAINT espn_lineup_approvals_pkey;",
])
def test_release_contract_rejects_unsafe_links(db, tamper):
    result = db.sql("BEGIN; " + tamper + "\n" + CONTRACT, check=False)
    assert result.returncode != 0 and "Beli schema contract:" in result.stderr
    db.sql(CONTRACT)  # The failed session rolled the tampering back.


def test_upgrade_keeps_existing_accounts_unlinked(migration_database, tmp_path):  # noqa: F811
    database = migration_database
    database.release(checkout_release(PRE_LINK_RELEASE, tmp_path / "previous"))
    identity = str(uuid4())
    database.sql(f"""INSERT INTO public.espn_accounts(id,label,league_id,season,espn_s2_enc,swid_enc,token_hash,token_prefix)
        VALUES ('{identity}','synthetic',999,2027,'enc-s2','enc-swid','synthetic-hash','cce_test');""")
    columns = ("id,label,league_id,season,espn_s2_enc,swid_enc,token_hash,token_prefix,"
               "lineup_automation_enabled,created_at")
    before = database.sql(f"SELECT {columns} FROM public.espn_accounts;").stdout
    assert "Applying 0089_beli_espn_account_owner.sql" in database.release().stdout
    assert database.sql(f"SELECT {columns} FROM public.espn_accounts;").stdout == before
    assert database.sql("SELECT count(*) FROM public.espn_accounts WHERE owner_user_id IS NOT NULL;").stdout.strip() == "0"
    assert "Applying " not in database.release().stdout
