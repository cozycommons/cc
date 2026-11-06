import importlib.util
from pathlib import Path
import subprocess

import pytest

spec = importlib.util.spec_from_file_location(
    "restore_workspace",
    Path(__file__).resolve().parents[3] / "infra/apps/runtime/restore_workspace.py",
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.fixture
def workspace(tmp_path):
    path = tmp_path / "workspace"
    path.mkdir()
    (path / "current.txt").write_text("current data")
    (path / ".git").mkdir()
    (path / ".git/config").write_text("current git")
    return path


def archive(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "restored.txt").write_text("backup data")
    (source / ".hidden").write_text("hidden data")
    (source / "link").symlink_to("restored.txt")
    target = tmp_path / "workspace.tgz"
    subprocess.run(["tar", "czf", str(target), "-C", str(source), "."], check=True)
    return target


@pytest.mark.parametrize("kind", ["missing", "corrupt", "truncated"])
def test_bad_archive_preserves_current_workspace(workspace, tmp_path, kind):
    target = tmp_path / "workspace.tgz"
    if kind == "corrupt":
        target.write_bytes(b"not an archive")
    elif kind == "truncated":
        target = archive(tmp_path)
        target.write_bytes(target.read_bytes()[:-16])
    with pytest.raises(subprocess.CalledProcessError):
        module.restore(workspace, target)
    assert (workspace / "current.txt").read_text() == "current data"
    assert (workspace / ".git/config").read_text() == "current git"
    assert not list(workspace.glob(".commons-restore-*"))


def test_success_replaces_workspace_including_hidden_files(workspace, tmp_path):
    module.restore(workspace, archive(tmp_path))
    assert {p.name for p in workspace.iterdir()} == {"restored.txt", ".hidden", "link"}
    assert (workspace / "link").is_symlink()
    assert (workspace / "link").read_text() == "backup data"


def test_replacement_failure_rolls_back(workspace, tmp_path, monkeypatch):
    target = archive(tmp_path)
    rename = Path.rename
    installed = []

    def fail_second_install(path, destination):
        if path.parent.name == "incoming":
            installed.append(path.name)
            if len(installed) == 2:
                raise OSError("synthetic rename failure")
        return rename(path, destination)

    monkeypatch.setattr(Path, "rename", fail_second_install)
    with pytest.raises(OSError, match="synthetic rename"):
        module.restore(workspace, target)
    assert {p.name for p in workspace.iterdir()} == {"current.txt", ".git"}
    assert (workspace / "current.txt").read_text() == "current data"
    assert (workspace / ".git/config").read_text() == "current git"
