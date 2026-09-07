import json
import os
import subprocess
import sys
from pathlib import Path

from runtime_policy import LOCAL_SUPABASE_URL, initialize_runtime_policy


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


def test_backend_launcher_preserves_only_an_absolute_external_venv():
    launcher = (
        BACKEND_DIR.parent / "scripts" / "start-local-dice-backend.sh"
    ).read_text(encoding="utf-8")

    assert '[[ "$BACKEND_VENV_DIR" != /* ]]' in launcher
    assert 'clean_env+=("BACKEND_VENV_DIR=$BACKEND_VENV_DIR")' in launcher
    assert "DICE_LIVE_REFEREE_ENABLED" not in launcher


def test_browser_qa_lifecycle_preserves_database_and_tracks_owned_processes():
    lifecycle = (BACKEND_DIR.parent / "scripts" / "dice-browser-qa.sh").read_text(
        encoding="utf-8"
    )

    assert "start|status|stop" in lifecycle
    assert "start_new_session=True" in lifecycle
    assert "dice_live_referee" in lifecycle
    assert "/dice/live/games" in lifecycle
    assert "this command will not reset it" in lifecycle
    assert "dice-dev.sh reset" not in lifecycle
    assert "dice-dev.sh stop" not in lifecycle
    for linux_only_dependency in ("/proc/", "command -v ss", "setsid"):
        assert linux_only_dependency not in lifecycle


def test_repository_documents_unix_developer_tooling_contract():
    instructions = (BACKEND_DIR.parent / "AGENTS.md").read_text(encoding="utf-8")

    assert "Ubuntu (including WSL2 and Codespaces)" in instructions
    assert "macOS" in instructions
    assert "Bash 3.2" in instructions
    assert "Do not commit Linux-only" in instructions
    assert "Do not add PowerShell" in instructions


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
