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
        if any("test_dice" in report.nodeid for report in skipped):
            reporter.write_sep("=", "Required Dice tests unexpectedly skipped")
            session.exitstatus = pytest.ExitCode.TESTS_FAILED
