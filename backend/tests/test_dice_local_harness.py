import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from runtime_policy import LOCAL_SUPABASE_URL, initialize_runtime_policy
from tests.dice_test_database import is_isolated_dice_test_database


BACKEND_DIR = Path(__file__).resolve().parents[1]
IMPORT_MAIN = (
    "import sys; "
    f"sys.path.insert(0, {str(BACKEND_DIR)!r}); "
    "import main; "
    "print(main.SUPABASE_URL)"
)
IMPORT_SCHEDULER_SETTING = (
    "import sys; "
    f"sys.path.insert(0, {str(BACKEND_DIR)!r}); "
    "import main; "
    "print(main._is_scheduler_enabled())"
)


def harness_env(supabase_url):
    return {
        **os.environ,
        "DICE_LOCAL_HARNESS": "true",
        "SUPABASE_URL": supabase_url,
        "SUPABASE_SERVICE_KEY": "synthetic-local-service-key",
        "OPENROUTER_API_KEY": "disabled-for-local-dice-testing",
        "ENABLE_SCHEDULER": "false",
    }


def test_local_harness_policy_disables_unsafe_capabilities():
    load_calls = []
    policy = initialize_runtime_policy(
        {
            "DICE_LOCAL_HARNESS": "true",
            "ENABLE_SCHEDULER": "true",
        },
        lambda: load_calls.append(True),
    )

    assert load_calls == []
    assert policy.is_dice_sandbox is True
    assert policy.scheduler_enabled is False
    assert policy.allow_cache_warmup is False
    assert policy.allow_external_side_effects is False


def test_regular_runtime_policy_preserves_configured_capabilities():
    environment = {}

    def load_environment():
        environment["ENABLE_SCHEDULER"] = "true"

    policy = initialize_runtime_policy(environment, load_environment)

    assert policy.is_dice_sandbox is False
    assert policy.scheduler_enabled is True
    assert policy.allow_cache_warmup is True
    assert policy.allow_external_side_effects is True


def test_local_harness_policy_requires_exact_loopback_supabase_url():
    policy = initialize_runtime_policy(
        {"DICE_LOCAL_HARNESS": "true"},
        lambda: None,
    )

    policy.require_safe_supabase_url(LOCAL_SUPABASE_URL)

    for unsafe_url in (None, "http://localhost:54321", "https://example.supabase.co"):
        try:
            policy.require_safe_supabase_url(unsafe_url)
        except RuntimeError as error:
            assert f"SUPABASE_URL={LOCAL_SUPABASE_URL}" in str(error)
        else:
            raise AssertionError(f"accepted unsafe Supabase URL: {unsafe_url!r}")


def test_local_harness_ignores_dotenv_credentials(tmp_path):
    (tmp_path / ".env.local").write_text(
        "SUPABASE_URL=https://example.supabase.co\n"
        "SUPABASE_SERVICE_KEY=fake-production-key\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, "-c", IMPORT_MAIN],
        cwd=tmp_path,
        env=harness_env("http://127.0.0.1:54321"),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "http://127.0.0.1:54321"


def test_local_harness_rejects_non_loopback_supabase_url(tmp_path):
    result = subprocess.run(
        [sys.executable, "-c", IMPORT_MAIN],
        cwd=tmp_path,
        env=harness_env("https://example.supabase.co"),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "DICE_LOCAL_HARNESS requires SUPABASE_URL=http://127.0.0.1:54321" in result.stderr


def test_local_harness_forces_scheduler_off(tmp_path):
    env = harness_env("http://127.0.0.1:54321")
    env["ENABLE_SCHEDULER"] = "true"

    result = subprocess.run(
        [sys.executable, "-c", IMPORT_SCHEDULER_SETTING],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False"


def test_regular_runtime_reads_scheduler_setting_from_dotenv(tmp_path):
    (tmp_path / ".env.local").write_text(
        "ENABLE_SCHEDULER=true\n"
        "SUPABASE_URL=http://127.0.0.1:54321\n"
        "SUPABASE_SERVICE_KEY=synthetic-test-key\n",
        encoding="utf-8",
    )
    env = {
        **os.environ,
        "DICE_LOCAL_HARNESS": "",
        "ENABLE_SCHEDULER": "false",
        "SUPABASE_URL": "http://127.0.0.1:54321",
        "SUPABASE_SERVICE_KEY": "synthetic-test-key",
        "OPENROUTER_API_KEY": "disabled-for-test",
    }

    result = subprocess.run(
        [sys.executable, "-c", IMPORT_SCHEDULER_SETTING],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "True"


def test_fixture_is_loaded_after_the_canonical_schema():
    reset_script = (
        BACKEND_DIR.parent / "scripts" / "reset-local-dice-db.sh"
    ).read_text(encoding="utf-8")

    assert "psql \"$DB_URL\" --set ON_ERROR_STOP=1 --file supabase/dice-seed.sql" in reset_script
    assert '--single-transaction --file "$migration"' in reset_script
    assert reset_script.index("done\npsql") < reset_script.index("supabase/dice-seed.sql")


def test_synthetic_referee_can_open_the_seeded_tournament_bankroll():
    seed = (BACKEND_DIR.parent / "supabase" / "dice-seed.sql").read_text(encoding="utf-8")

    assert (
        "('30000000-0000-0000-0000-000000000001', "
        "'10000000-0000-0000-0000-000000000001')"
    ) in seed


def test_seed_contains_replayable_duo_ladder_runs():
    seed = (BACKEND_DIR.parent / "supabase" / "dice-seed.sql").read_text(encoding="utf-8")

    assert "dice-duo-long-" in seed
    assert "dice-duo-short-" in seed
    assert "dice-duo-provisional-a-" in seed
    assert "expected 12 Dice profiles" in (
        BACKEND_DIR.parent / "scripts" / "reset-local-dice-db.sh"
    ).read_text(encoding="utf-8")


def test_sandbox_includes_compact_and_legacy_photo_fixtures():
    repository = BACKEND_DIR.parent
    seed = (repository / "supabase" / "dice-seed.sql").read_text(encoding="utf-8")

    assert "'/dice-dev/gallery-table.svg'" in seed
    assert "'/dice-dev/gallery-compact/display.webp'" in seed
    for variant in ("original", "display.webp", "thumb.webp"):
        assert (repository / "frontend" / "public" / "dice-dev" / "gallery-compact" / variant).is_file()


def test_feature_access_storage_is_service_role_only():
    migration = (
        BACKEND_DIR / "migrations" / "0042_dice_profile_feature_access.sql"
    ).read_text(encoding="utf-8")

    assert "revoke all on table public.dice_feature_access from anon, authenticated;" in migration
    assert "grant all on table public.dice_feature_access to service_role;" in migration
    assert "to authenticated" not in migration


def test_live_referee_retirement_migration_normalizes_and_prevents_false_rows():
    if not is_isolated_dice_test_database(os.environ):
        pytest.skip("requires an allowlisted isolated PostgreSQL database")
    migration = BACKEND_DIR / "migrations" / "0078_dice_live_referee_flag_retirement.sql"
    result = subprocess.run(
        ["psql", os.environ["DB_URL"], "-X", "-v", "ON_ERROR_STOP=1"],
        cwd=BACKEND_DIR.parent,
        input=f"""
begin;
alter table public.dice_feature_access
  drop constraint dice_feature_access_released_check;
alter table public.dice_feature_access alter column enabled set default false;
delete from public.dice_feature_access
where user_id in (
  '10000000-0000-0000-0000-000000000001',
  '10000000-0000-0000-0000-000000000002'
);
insert into public.dice_feature_access (user_id, feature, enabled)
values ('10000000-0000-0000-0000-000000000001', 'dice_live_referee', false);
\\i {migration}
insert into public.dice_feature_access (user_id, feature)
values ('10000000-0000-0000-0000-000000000002', 'dice_live_referee');
do $$
begin
  if (select enabled from public.dice_feature_access
      where user_id = '10000000-0000-0000-0000-000000000001') is not true then
    raise exception 'historical false row was not normalized';
  end if;
  if (select enabled from public.dice_feature_access
      where user_id = '10000000-0000-0000-0000-000000000002') is not true then
    raise exception 'new row did not receive the released default';
  end if;
end
$$;
do $$
begin
  begin
    update public.dice_feature_access set enabled = false
    where user_id = '10000000-0000-0000-0000-000000000001';
    raise exception 'retired false state was accepted';
  exception when check_violation then
    null;
  end;
end
$$;
rollback;
""",
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_backend_launcher_preserves_only_an_absolute_external_venv():
    launcher = (
        BACKEND_DIR.parent / "scripts" / "start-local-dice-backend.sh"
    ).read_text(encoding="utf-8")

    assert '[[ "$BACKEND_VENV_DIR" != /* ]]' in launcher
    assert 'clean_env+=("BACKEND_VENV_DIR=$BACKEND_VENV_DIR")' in launcher
    assert '"PORT=$backend_port"' in launcher
    assert 'frontend_port="${DICE_FRONTEND_PORT:-8080}"' in launcher
    assert '"CORS_EXTRA_ORIGINS=http://localhost:$frontend_port,http://127.0.0.1:$frontend_port"' in launcher
    assert "DICE_LIVE_REFEREE_ENABLED" not in launcher


def test_backend_launcher_rejects_an_injection_shaped_frontend_port():
    launcher = BACKEND_DIR.parent / "scripts" / "start-local-dice-backend.sh"
    env = {
        **os.environ,
        "DICE_FRONTEND_PORT": "8083,https://attacker.example",
        "CORS_EXTRA_ORIGINS": "https://attacker.example",
    }

    result = subprocess.run(
        ["bash", launcher],
        cwd=BACKEND_DIR.parent,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == "DICE_FRONTEND_PORT must be an integer from 1024 through 65535.\n"


def test_browser_qa_lifecycle_preserves_database_and_tracks_owned_processes():
    lifecycle = (BACKEND_DIR.parent / "scripts" / "dice-browser-qa.sh").read_text(
        encoding="utf-8"
    )

    assert "start|status|scenario|fuzz|stop" in lifecycle
    assert "start_new_session=True" in lifecycle
    assert "source_fingerprint" in lifecycle
    assert '[[ -f "$repo_dir/$path" ]] || continue' in lifecycle
    assert 'hash-object "$repo_dir/$path" 2>/dev/null' in lifecycle
    assert "ps -o lstart=" in lifecycle
    assert "/dice/me/features/dice_live_referee" in lifecycle
    assert '{"enabled":false}' in lifecycle
    assert '"opted_in": True, "effective": True' in lifecycle
    assert "/dice/live/games" in lifecycle
    assert "this command will not reset it" in lifecycle
    assert "dice-dev.sh reset" not in lifecycle
    assert "dice-dev.sh stop" not in lifecycle
    assert 'DICE_QA_BACKEND_PORT:-8000' in lifecycle
    assert 'DICE_QA_FRONTEND_PORT:-8080' in lifecycle
    assert '${repo_key}-${backend_port}-${frontend_port}' in lifecycle
    assert lifecycle.count("current_owned_pid backend") >= 3
    assert 'http://localhost:$frontend_port' in lifecycle
    for linux_only_dependency in ("/proc/", "command -v ss", "setsid"):
        assert linux_only_dependency not in lifecycle


def test_frontend_launcher_allows_only_an_explicit_loopback_api_override():
    launcher = (
        BACKEND_DIR.parent / "scripts" / "start-local-dice-frontend.sh"
    ).read_text(encoding="utf-8")

    assert 'dice_backend_url="${VITE_API_URL:-http://localhost:8000}"' in launcher
    assert "^http://(localhost|127\\.0\\.0\\.1):[0-9]+$" in launcher
    assert 'DICE_FRONTEND_PORT:-8080' in launcher


def test_browser_qa_can_build_a_completed_rating_replay_scenario():
    repository = BACKEND_DIR.parent
    lifecycle = (repository / "scripts" / "dice-browser-qa.sh").read_text(encoding="utf-8")
    scenario = (repository / "scripts" / "dice-live-scenario.py").read_text(encoding="utf-8")

    assert "does not own a current-source browser QA stack" in lifecycle
    assert 'export VITE_API_URL="http://localhost:$backend_port"' in lifecycle
    assert "dice-live-scenario.py" in lifecycle
    assert '"ranked": False' in scenario
    assert "individual_elo_backfill" in scenario
    assert "duo_replay" in scenario
    assert "unranked_restore" in scenario
    assert 'game_id not in entry["game_ids"]' in scenario
    assert 'game_id in entry["game_ids"]' in scenario
    assert 'unranked["ranked"] is not False' in scenario
    assert "profiles_restored != profiles_before" in scenario
    assert '"rating_deviation", "elo_model_version"' in scenario


def test_sandbox_scenario_allows_ready_to_finish_play_to_continue():
    path = BACKEND_DIR.parent / "scripts" / "dice-live-scenario.py"
    spec = importlib.util.spec_from_file_location("dice_live_scenario", path)
    assert spec is not None and spec.loader is not None
    scenario = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scenario)

    assert scenario.ready_to_finish((5, 0), 5, 1)
    assert scenario.ready_to_finish((6, 5), 5, 1)
    assert scenario.ready_to_finish((25, 23), 5, 2)
    assert not scenario.ready_to_finish((5, 5), 5, 1)


def test_repository_documents_unix_developer_tooling_contract():
    instructions = (BACKEND_DIR.parent / "AGENTS.md").read_text(encoding="utf-8")

    assert "Ubuntu (including WSL2 and Codespaces)" in instructions
    assert "macOS" in instructions
    assert "Bash 3.2" in instructions
    assert "Do not commit Linux-only" in instructions
    assert "Do not add PowerShell" in instructions


def test_migration_contract_preflight_runs_on_supported_platform():
    script = BACKEND_DIR.parent / "scripts" / "check-dice-migration-contract.sh"
    contract = (
        BACKEND_DIR / "migrations" / "DICE_SCHEMA_CONTRACT_VERSION"
    ).read_text(encoding="utf-8").strip()

    result = subprocess.run(
        ["bash", script],
        cwd=BACKEND_DIR.parent,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert contract in result.stdout
    assert "-printf" not in script.read_text(encoding="utf-8")


def test_regression_entrypoint_is_safe_and_covers_source_and_sandbox_paths():
    script = BACKEND_DIR.parent / "scripts" / "test-dice-regressions.sh"
    source = script.read_text(encoding="utf-8")

    result = subprocess.run(
        ["bash", script, "--help"],
        cwd=BACKEND_DIR.parent,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "source|sandbox|all" in result.stdout
    assert "unset DB_URL" in source
    assert "127.0.0.1:54322/postgres" in source
    assert "create database" in source
    assert "drop database if exists" in source
    assert "DICE_TEST_DATABASE=1" in source
    assert 'backend/tests/test_dice*.py' in source
    assert "src/dice sandboxConfig.test.js src/runtimeConfig.test.js" in source
    assert source.count('"$repo_dir/scripts/dice-browser-qa.sh" scenario') == 4


def test_destructive_database_tests_require_an_allowlisted_isolated_database():
    marker = {"DICE_TEST_DATABASE": "1"}

    assert is_isolated_dice_test_database({
        **marker,
        "DB_URL": "postgresql://postgres:postgres@127.0.0.1:54322/dummi_regression_501_1234",
    })
    assert is_isolated_dice_test_database({
        "GITHUB_ACTIONS": "true",
        "DB_URL": "postgresql://postgres:postgres@localhost:5432/dummi_test",
    })
    assert not is_isolated_dice_test_database({
        **marker,
        "DB_URL": "postgresql://postgres:postgres@127.0.0.1:54322/postgres",
    })
    assert not is_isolated_dice_test_database({
        **marker,
        "DB_URL": "postgresql://postgres:postgres@example.com:5432/dummi_test",
    })
    assert not is_isolated_dice_test_database({
        **marker,
        "DB_URL": "postgresql://postgres:postgres@127.0.0.1:54322/dummi_regression_501_1234?host=example.com",
    })


def test_codespace_stays_private_and_starts_the_synthetic_harness():
    config = json.loads(
        (BACKEND_DIR.parent / ".devcontainer" / "devcontainer.json").read_text(
            encoding="utf-8"
        )
    )

    assert config["portsAttributes"]["8080"]["visibility"] == "private"
    assert config["otherPortsAttributes"]["onAutoForward"] == "ignore"
    assert "ghcr.io/devcontainers/features/sshd:1" in config["features"]
    assert config["postStartCommand"] == "scripts/start-dice-codespace.sh"

    launcher = (
        BACKEND_DIR.parent / "scripts" / "start-dice-codespace.sh"
    ).read_text(encoding="utf-8")
    assert '"${CODESPACES:-}" != "true"' in launcher
    assert "scripts/dice-dev.sh setup" in launcher
    assert "scripts/dice-dev.sh codespace" in launcher
    assert "/tmp/dice-codespace.log" in launcher
    assert "start_new_session=True" in launcher


def test_local_harness_disables_sms_even_with_ambient_twilio_secrets(monkeypatch):
    from types import SimpleNamespace

    from dice import notifications

    class UnexpectedSupabaseUse:
        def table(self, _name):
            raise AssertionError("local harness must not query SMS recipients")

    runtime_policy = initialize_runtime_policy(
        {"DICE_LOCAL_HARNESS": "true"},
        lambda: None,
    )
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "ambient-secret")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "ambient-secret")
    monkeypatch.setenv("TWILIO_PHONE_NUMBER", "+15555555555")

    notifications.notify_ranked_game(
        UnexpectedSupabaseUse(),
        SimpleNamespace(ranked=True),
        runtime_policy,
    )


def test_dice_notification_link_uses_the_service_site_url(monkeypatch):
    from types import SimpleNamespace

    from dice import notifications

    monkeypatch.setattr(notifications, "SITE_URL", "https://cozycommons.dev")
    game = SimpleNamespace(
        id="game-123",
        winner_team=1,
        team1_score=21,
        team2_score=18,
        players=[
            SimpleNamespace(team=1, display_name="Alice"),
            SimpleNamespace(team=2, display_name="Bob"),
        ],
    )

    message = notifications._build_message(game)

    assert message.endswith("https://cozycommons.dev/dice/game/game-123")
