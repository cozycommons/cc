"""Real PostgreSQL checks for ESPN connector links and receipts (0089), lineup approval claims (0090) and
proven account claims (0091).

Synthetic disposable databases on the allowlisted test server; never ESPN calls.
Locally: DICE_TEST_DATABASE=1 DB_URL=postgresql://postgres:postgres@127.0.0.1:54322/dummi_regression_<n>_<n>.
"""
from uuid import uuid4

import pytest

import migration_runner
from tests.migration_harness import REPO, checkout_release, disposable_migration_database, migration_database  # noqa: F401

PRE_LINK_RELEASE = "9b84d2ccacd2e60687390817e27855046cad49af"  # main with Partiful connector (#204, 0019), before 0089
PRE_PROVEN_RELEASE = "576fb96b8a489e98a017983ab7dd941b7ffc1006"  # main with the Beli account page (#212, #213), before 0091
CONTRACT = (REPO / "backend/migrations/beli_schema_contract.sql").read_text()


@pytest.fixture(scope="module")
def espn_database():
    with disposable_migration_database() as database:
        database.sql(migration_runner.render(["beli"]))
        yield database


@pytest.fixture
def db(espn_database):
    espn_database.sql("TRUNCATE public.espn_agent_receipts, public.espn_accounts CASCADE;")  # cascades to proposals
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


def claim_proven(db, account_id, user_id):
    return db.sql(f"SET ROLE service_role; SELECT public.espn_claim_account_proven('{account_id}','{user_id}');"
                  ).stdout.strip()


def proven(db, account_id):
    return db.sql(f"SELECT owner_proven FROM public.espn_accounts WHERE id='{account_id}';").stdout.strip()


def pending_edit(db, account_id, table="espn_roster_edits"):
    columns = {"espn_roster_edits": ("team_id,drop_player_id,preview", "7,105,'synthetic edit'"),
               "espn_trade_proposals": ("team_id,counterparty_team_id,give_player_ids,receive_player_ids,preview",
                                        "7,8,'[105]','[201]','synthetic trade'")}[table]
    return db.sql(f"""SET ROLE service_role; INSERT INTO public.{table}(account_id,league_id,season,{columns[0]},
        status,expires_at) VALUES ('{account_id}',999,2027,{columns[1]},'pending',now() + interval '30 minutes')
        RETURNING id;""").stdout.split()[0]


def status(db, table, row_id):
    return db.sql(f"SELECT status FROM public.{table} WHERE id='{row_id}';").stdout.strip()


def receipt(user_id, key="approve-1"):
    return f"""SET ROLE service_role; INSERT INTO public.espn_agent_receipts(user_id,idempotency_key,payload,target)
        VALUES ('{user_id}','{key}','{{}}','{{}}')"""


def test_schema_attests_and_replays(db):
    assert db.sql("SELECT max(version) FROM public.beli_schema_migrations;").stdout.strip() == "91"
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


def test_a_proven_claim_takes_over_an_unproven_owner_and_expires_their_proposals(db):
    sam, kim = user(db), user(db)
    team = account(db)
    assert link(db, team, kim) == "linked" and proven(db, team) == "f"  # typed cookies or a cce_ token
    edit, trade = pending_edit(db, team), pending_edit(db, team, "espn_trade_proposals")
    assert claim_proven(db, team, sam) == "taken_over"
    assert owner(db, team) == sam and proven(db, team) == "t"
    assert status(db, "espn_roster_edits", edit) == "expired" and status(db, "espn_trade_proposals", trade) == "expired"
    assert claim_proven(db, team, kim) == "other_owner" and link(db, team, kim) == "other_owner"
    assert owner(db, team) == sam
    assert claim_proven(db, team, sam) == "already_linked" and proven(db, team) == "t"


def test_a_proven_claim_links_an_unowned_row_and_moves_your_own_link(db):
    sam = user(db)
    first, second = account(db), account(db)
    assert link(db, first, sam) == "linked"
    mine = pending_edit(db, first)
    assert claim_proven(db, first, sam) == "already_linked" and proven(db, first) == "t"
    assert status(db, "espn_roster_edits", mine) == "pending"  # your own proposals stay
    assert claim_proven(db, second, sam) == "linked"
    assert owner(db, first) is None and owner(db, second) == sam and proven(db, second) == "t"
    assert link(db, first, sam) == "linked" and proven(db, first) == "f"  # an unproven move starts unproven
    assert claim_proven(db, str(uuid4()), sam) == "missing"


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
    "SELECT public.espn_claim_account_proven(gen_random_uuid(), gen_random_uuid())",
    "UPDATE public.espn_accounts SET owner_proven=true",
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
    "GRANT EXECUTE ON FUNCTION public.espn_claim_account_proven(uuid,uuid) TO authenticated;",
    "ALTER FUNCTION public.espn_claim_account_proven(uuid,uuid) SECURITY DEFINER;",
    "ALTER TABLE public.espn_accounts DROP COLUMN owner_proven;",
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


def test_upgrade_marks_existing_links_unproven(migration_database, tmp_path):  # noqa: F811
    database = migration_database
    database.release(checkout_release(PRE_PROVEN_RELEASE, tmp_path / "previous"))
    sam, identity = user(database), str(uuid4())
    database.sql(f"""INSERT INTO public.espn_accounts(id,label,league_id,season,espn_s2_enc,swid_enc,token_hash,token_prefix,
        owner_user_id) VALUES ('{identity}','synthetic',999,2027,'enc-s2','enc-swid','synthetic-hash','cce_test','{sam}');""")
    assert "Applying 0091_beli_espn_proven_owner.sql" in database.release().stdout
    assert owner(database, identity) == sam and proven(database, identity) == "f"
    assert "Applying " not in database.release().stdout
