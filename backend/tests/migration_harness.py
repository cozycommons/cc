"""Rehearse release upgrades in disposable databases on the allowlisted test server."""
import io
import os
from pathlib import Path
import subprocess
import sys
import tarfile
from urllib.parse import urlparse, urlunparse
from uuid import uuid4

import pytest

from tests.dice_test_database import is_isolated_dice_test_database


REPO = Path(__file__).resolve().parents[2]


def checkout_release(ref, destination):
    commit = subprocess.check_output(
        ["git", "rev-parse", "--verify", "--end-of-options", ref + "^{commit}"], cwd=REPO, text=True
    ).strip()
    archive = subprocess.check_output([
        "git", "archive", commit, "backend/migration_runner.py", "backend/migrations",
        "backend/commons/migrations", "backend/trips/migrations",
    ], cwd=REPO)
    destination.mkdir()
    with tarfile.open(fileobj=io.BytesIO(archive)) as source:
        source.extractall(destination, filter="data")
    return destination / "backend"


class MigrationDatabase:
    def __init__(self, url):
        self.url = url

    def sql(self, statement, *, check=True):
        result = subprocess.run(
            ["psql", self.url, "-X", "-v", "ON_ERROR_STOP=1", "-At"],
            input=statement, text=True, capture_output=True, timeout=120,
        )
        if check:
            assert result.returncode == 0, result.stdout + result.stderr
        return result

    def release(self, backend=REPO / "backend", *, check=True):
        result = subprocess.run(
            [sys.executable, str(backend / "migration_runner.py"), "--family", "all"],
            env=dict(os.environ, SUPABASE_DB_URL=self.url),
            text=True, capture_output=True, timeout=120,
        )
        if check:
            assert result.returncode == 0, result.stdout + result.stderr
        return result


@pytest.fixture
def migration_database():
    if not is_isolated_dice_test_database(os.environ):
        pytest.skip("allowlisted isolated DB_URL required for migration rehearsals")
    parsed = urlparse(os.environ["DB_URL"])
    admin = MigrationDatabase(os.environ["DB_URL"])
    name = "cc_migration_" + uuid4().hex
    admin.sql(f'CREATE DATABASE "{name}";')
    database = MigrationDatabase(urlunparse(parsed._replace(path="/" + name)))
    try:
        database.sql((REPO / "scripts/supabase-test-scaffold.sql").read_text())
        yield database
    finally:
        admin.sql(f'DROP DATABASE "{name}" WITH (FORCE);')
