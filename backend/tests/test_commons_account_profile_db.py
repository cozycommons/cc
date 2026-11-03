"""Real PostgreSQL checks for the Commons profile table, backfill and Dice mirror (0087).

Synthetic users in disposable databases on the allowlisted test server.
Locally: DICE_TEST_DATABASE=1 DB_URL=postgresql://postgres:postgres@127.0.0.1:54322/dummi_regression_<n>_<n>.
"""
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from commons_account.profile import default_profile
from tests.migration_harness import REPO, checkout_release, disposable_migration_database, migration_database  # noqa: F401

PRE_PROFILE_RELEASE = "97a87f08eb018c54a83ea3d3a4e962ede869faaa"  # main at Dice 0086
CONTRACT = (REPO / "backend/migrations/dice_schema_contract.sql").read_text()
COLUMNS = "display_name,avatar_url,venmo_username,venmo_owner_confirmed,venmo_confirmed_name"
LONG_AVATAR = "https://example.test/" + "a" * 3000

# (key, email, user metadata, Dice row or None, expected profile)
USERS = [
    ("dice_wins", "dice@example.test",
     {"full_name": "Google Name", "avatar_url": "https://google.example/g.png"},
     {"display_name": "Dice Name", "avatar_url": "https://dice.example/d.png"},
     ("Dice Name", "https://dice.example/d.png", None, False, None)),
    ("blank_dice_name", None, {"full_name": "Fallback Name"}, {"display_name": "   ", "avatar_url": None},
     ("Fallback Name", None, None, False, None)),
    ("long_dice_values", None, {"avatar_url": "https://google.example/l.png"},
     {"display_name": "  " + "x" * 100, "avatar_url": LONG_AVATAR},
     ("x" * 80, "https://google.example/l.png", None, False, None)),
    ("metadata_full_name", "full@example.test",
     {"full_name": "  Google Full  ", "name": "Short", "avatar_url": "https://google.example/f.png"}, None,
     ("Google Full", "https://google.example/f.png", None, False, None)),
    ("metadata_name", "name@example.test", {"name": "Only Name"}, None, ("Only Name", None, None, False, None)),
    ("email_only", "casey.example@example.test", {}, None, ("casey.example", None, None, False, None)),
    ("nothing", None, {}, None, ("Friend", None, None, False, None)),
    ("venmo_confirmed", None,
     {"full_name": "Alex", "venmo_username": "Alex-Smith",
      "venmo_username_provenance": {"owner_confirmed": True, "handle": "alex-smith", "display_name": "Alex Smith"}},
     None, ("Alex", None, "alex-smith", True, "Alex Smith")),
    ("venmo_rewritten_in_browser", None,
     {"full_name": "Blair", "venmo_username": "New-Handle",
      "venmo_username_provenance": {"owner_confirmed": True, "handle": "old-handle", "display_name": "Old Name"}},
     None, ("Blair", None, "new-handle", False, "Old Name")),
    ("venmo_not_confirmed", None,
     {"full_name": "Cam", "venmo_username": "cam_pays", "venmo_username_provenance": {"owner_confirmed": False}},
     None, ("Cam", None, "cam_pays", False, None)),
    ("venmo_confirmed_without_handle", None,
     {"full_name": "Dee", "venmo_username": "dee-venmo", "venmo_username_provenance": {"owner_confirmed": True}},
     None, ("Dee", None, "dee-venmo", True, None)),
    ("venmo_string_true", None,
     {"full_name": "Eli", "venmo_username": "eli-venmo",
      "venmo_username_provenance": {"owner_confirmed": "true", "handle": "eli-venmo"}},
     None, ("Eli", None, "eli-venmo", False, None)),
    ("venmo_url", None, {"full_name": "Fay", "venmo_username": " https://venmo.com/u/@Url_User?txn=1 "}, None,
     ("Fay", None, "url_user", False, None)),
    ("venmo_invalid", None,
     {"full_name": "Gus", "venmo_username": "ab", "venmo_username_provenance": {"owner_confirmed": True}},
     None, ("Gus", None, None, False, None)),
]


def literal(value):
    return "NULL" if value is None else "'" + str(value).replace("'", "''") + "'"


def seed_users(database, *, with_dice):
    ids = {}
    for key, email, metadata, dice, _ in USERS:
        if dice and not with_dice:
            continue
        ids[key] = str(uuid4())
        database.sql(f"""INSERT INTO auth.users(id,email,raw_user_meta_data)
            VALUES ('{ids[key]}',{literal(email)},{literal(json.dumps(metadata))}::jsonb);""")
        if dice:
            database.sql(f"""INSERT INTO public.dice_profiles(user_id,display_name,avatar_url)
                VALUES ('{ids[key]}',{literal(dice['display_name'])},{literal(dice['avatar_url'])});""")
    ids["anonymous"] = str(uuid4())
    database.sql(f"""INSERT INTO auth.users(id,is_anonymous,raw_user_meta_data)
        VALUES ('{ids['anonymous']}',true,'{{"full_name":"Guest"}}');""")
    return ids


def profile(database, user_id):
    row = database.sql(f"SELECT {COLUMNS} FROM public.commons_profiles WHERE user_id='{user_id}';").stdout.strip()
    if not row:
        return None
    name, avatar, venmo, confirmed, confirmed_name = row.split("|")
    return (name, avatar or None, venmo or None, confirmed == "t", confirmed_name or None)


def assert_backfill(database, ids):
    for key, email, metadata, dice, expected in USERS:
        if key not in ids:
            continue
        assert profile(database, ids[key]) == expected, key
        # own_profile creates rows with the same precedence as the backfill.
        user = SimpleNamespace(id=ids[key], email=email, user_metadata=metadata)
        python = default_profile(user, dice)
        assert tuple(python[name] for name in COLUMNS.split(",")) == expected, key
    assert profile(database, ids["anonymous"]) is None


@pytest.fixture(scope="module")
def fresh_database():
    with disposable_migration_database() as database:
        ids = seed_users(database, with_dice=False)
        database.release()
        yield database, ids


def service(database, statement, *, check=True):
    return database.sql("SET ROLE service_role; " + statement, check=check)


def test_fresh_install_backfills_from_account_metadata(fresh_database):
    database, ids = fresh_database
    assert database.sql("SELECT max(version) FROM public.dice_schema_migrations;").stdout.strip() == "87"
    assert_backfill(database, ids)
    assert service(database, "SELECT public.dice_release_readiness();").stdout.strip().endswith("t")
    assert "Applying " not in database.release().stdout
    database.sql(CONTRACT)


def test_upgrade_from_86_backfills_and_leaves_sources_untouched(migration_database, tmp_path):  # noqa: F811
    database = migration_database
    database.release(checkout_release(PRE_PROFILE_RELEASE, tmp_path / "previous"))
    assert database.sql("SELECT max(version) FROM public.dice_schema_migrations;").stdout.strip() == "86"
    ids = seed_users(database, with_dice=True)
    sources = ("SELECT id,email,raw_user_meta_data::text,raw_app_meta_data::text FROM auth.users ORDER BY id;"
               "SELECT to_jsonb(d)::text FROM public.dice_profiles d ORDER BY user_id;")
    before = database.sql(sources).stdout
    result = database.release()
    assert "Applying 0087_dice_commons_profiles.sql" in result.stdout
    assert database.sql(sources).stdout == before
    assert_backfill(database, ids)
    assert service(database, "SELECT public.dice_release_readiness();").stdout.strip().endswith("t")


def dice_profile(database, user_id):
    return database.sql(f"""SELECT display_name,coalesce(avatar_url,''),updated_at
        FROM public.dice_profiles WHERE user_id='{user_id}';""").stdout.strip()


def test_mirror_copies_only_changed_name_or_avatar_into_dice(fresh_database):
    database, _ = fresh_database
    player = str(uuid4())
    database.sql(f"""INSERT INTO auth.users(id) VALUES ('{player}');
        INSERT INTO public.dice_profiles(user_id,display_name,avatar_url,updated_at)
        VALUES ('{player}','Old Dice','https://dice.example/old.png','2026-01-01Z');""")
    service(database, f"""INSERT INTO public.commons_profiles(user_id,display_name,avatar_url)
        VALUES ('{player}','Old Dice','https://commons.example/differs.png');""")
    service(database, f"UPDATE public.commons_profiles SET venmo_username='new-venmo' WHERE user_id='{player}';")
    assert dice_profile(database, player).startswith("Old Dice|https://dice.example/old.png|2026-01-01")
    # Runs as service_role, which cannot execute the trigger function directly.
    service(database, f"UPDATE public.commons_profiles SET display_name='New Name' WHERE user_id='{player}';")
    name, avatar, updated = dice_profile(database, player).split("|")
    assert (name, avatar) == ("New Name", "https://dice.example/old.png") and not updated.startswith("2026-01-01")
    service(database, f"UPDATE public.commons_profiles SET avatar_url=NULL WHERE user_id='{player}';")
    assert dice_profile(database, player).startswith("New Name||")


def test_mirror_is_a_no_op_without_a_dice_row(fresh_database):
    database, ids = fresh_database
    user = ids["metadata_name"]
    service(database, f"UPDATE public.commons_profiles SET display_name='Trips Only' WHERE user_id='{user}';")
    assert profile(database, user)[0] == "Trips Only"
    assert database.sql(f"SELECT count(*) FROM public.dice_profiles WHERE user_id='{user}';").stdout.strip() == "0"


def test_account_deletion_removes_the_profile(fresh_database):
    database, _ = fresh_database
    user = str(uuid4())
    database.sql(f"INSERT INTO auth.users(id) VALUES ('{user}');")
    service(database, f"INSERT INTO public.commons_profiles(user_id,display_name) VALUES ('{user}','Gone');")
    database.sql(f"DELETE FROM auth.users WHERE id='{user}';")
    assert profile(database, user) is None


@pytest.mark.parametrize("value", ["'Has-Caps'", "'abc'", "'@handle'"])
def test_venmo_column_holds_only_canonical_handles(fresh_database, value):
    database, ids = fresh_database
    rejected = service(database, f"UPDATE public.commons_profiles SET venmo_username={value} "
                                 f"WHERE user_id='{ids['nothing']}';", check=False)
    assert rejected.returncode != 0 and "check constraint" in rejected.stderr


@pytest.mark.parametrize("name", ["''", "'   '", "repeat('x', 81)"])
def test_display_name_must_be_present_and_short(fresh_database, name):
    database, ids = fresh_database
    rejected = service(database, f"UPDATE public.commons_profiles SET display_name={name} "
                                 f"WHERE user_id='{ids['nothing']}';", check=False)
    assert rejected.returncode != 0 and "check constraint" in rejected.stderr


@pytest.mark.parametrize("role", ["anon", "authenticated"])
@pytest.mark.parametrize("statement", [
    "SELECT display_name FROM public.commons_profiles",
    "INSERT INTO public.commons_profiles(user_id,display_name) VALUES (gen_random_uuid(),'x')",
    "UPDATE public.commons_profiles SET display_name='x'",
    "DELETE FROM public.commons_profiles",
    "SELECT public.commons_profiles_readiness()",
    "SELECT public.dice_release_readiness()",
])
def test_browser_roles_are_denied(fresh_database, role, statement):
    database, ids = fresh_database
    # Even a signed-in user asking for their own row.
    denied = database.sql(f"SET ROLE {role}; SELECT set_config('request.jwt.claim.sub','{ids['email_only']}',false); "
                          f"{statement};", check=False)
    assert denied.returncode != 0 and "permission denied" in denied.stderr


@pytest.mark.parametrize("tamper", [
    "GRANT SELECT ON public.commons_profiles TO authenticated;",
    "GRANT SELECT (display_name) ON public.commons_profiles TO anon;",
    "GRANT UPDATE (venmo_username) ON public.commons_profiles TO authenticated;",
    "ALTER TABLE public.commons_profiles DISABLE ROW LEVEL SECURITY;",
    "REVOKE UPDATE ON public.commons_profiles FROM service_role;",
    "ALTER TABLE public.commons_profiles DISABLE TRIGGER commons_profiles_mirror_dice;",
    "DROP TRIGGER commons_profiles_mirror_dice ON public.commons_profiles;",
    "GRANT EXECUTE ON FUNCTION public.commons_profiles_mirror_dice() TO PUBLIC;",
    "DELETE FROM public.dice_schema_migrations WHERE version=87;",
])
def test_readiness_and_contract_reject_tampering(fresh_database, tamper):
    database, _ = fresh_database
    readiness = database.sql("BEGIN; " + tamper + " SET LOCAL ROLE service_role; SELECT public.dice_release_readiness();",
                             check=False)
    assert readiness.returncode != 0 and "Commons profiles:" in readiness.stderr
    contract = database.sql("BEGIN; " + tamper + "\n" + CONTRACT, check=False)
    assert contract.returncode != 0 and "Commons profiles:" in contract.stderr
    database.sql(CONTRACT)  # The failed sessions rolled the tampering back.
