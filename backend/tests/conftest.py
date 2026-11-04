import os
import pytest
from tests.dice_test_database import is_isolated_dice_test_database


def pytest_sessionstart(session):
    if os.environ.get("DICE_REQUIRE_DATABASE_TESTS") == "1" and not is_isolated_dice_test_database(os.environ):
        raise pytest.UsageError("Required Dice database tests need an allowlisted isolated DB_URL")


def pytest_sessionfinish(session, exitstatus):
    if os.environ.get("DICE_REQUIRE_DATABASE_TESTS") == "1":
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        skipped = reporter.stats.get("skipped", []) if reporter else []
        if any("test_dice" in report.nodeid or "test_migration" in report.nodeid for report in skipped):
            reporter.write_sep("=", "Required Dice or migration tests unexpectedly skipped")
            session.exitstatus = pytest.ExitCode.TESTS_FAILED


@pytest.fixture(autouse=True)
def _reset_espn_shared_state():
    """ESPN pacing, 429 cooldown and read caches are process-wide; start each test clean."""
    from espn import espn_client, scoreboard

    espn_client.reset_shared_state()
    scoreboard.reset_cache()
    yield
