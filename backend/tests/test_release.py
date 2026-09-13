import subprocess
from unittest.mock import Mock
import pytest
import release


def test_failed_migration_never_starts_http(monkeypatch):
    execute = Mock()
    monkeypatch.setattr(release.os, "execv", execute)
    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0])
    monkeypatch.setattr(release.subprocess, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        release.main()
    execute.assert_not_called()


def test_successful_migration_precedes_server(monkeypatch):
    calls = []
    monkeypatch.setattr(release.subprocess, "run", lambda args, **kwargs: calls.append(("migrate", args, kwargs)))
    monkeypatch.setattr(release.os, "execv", lambda *args: calls.append(("serve", args)))
    release.main()
    assert [call[0] for call in calls] == ["migrate", "serve"]
    assert calls[0][1][-2:] == ["--family", "all"]
    assert calls[0][2]["check"] is True
