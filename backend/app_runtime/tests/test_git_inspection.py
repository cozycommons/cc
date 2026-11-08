import json
import os
import subprocess
import sys
import time

from app_runtime.changes_page import render_changes_page
from app_runtime.git_inspection import GIT_INSPECTION_SCRIPT

GIT = "/usr/bin/git"


def git(repository, *arguments):
    environment = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    return subprocess.run(
        [GIT, "-C", str(repository), *arguments],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
    )


def repository(path):
    path.mkdir(parents=True)
    subprocess.run([GIT, "init", "--quiet", str(path)], check=True)
    git(path, "config", "user.name", "Apps inspection test")
    git(path, "config", "user.email", "apps-test@example.invalid")
    (path / "tracked.txt").write_text("before\n", encoding="utf-8")
    git(path, "add", "--", "tracked.txt")
    git(path, "commit", "--quiet", "-m", "initial")
    return path


def inspect(workspace, script=GIT_INSPECTION_SCRIPT):
    result = subprocess.run(
        [sys.executable, "-c", script, str(workspace)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=15,
    )
    return json.loads(result.stdout)


def test_tracked_diff_is_shown_but_untracked_and_sensitive_contents_are_not(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    repo = repository(workspace / "repo")
    (repo / "tracked.txt").write_text("before\nafter\n", encoding="utf-8")
    (repo / ".env").write_text("PLATFORM_SECRET=env-secret-marker\n", encoding="utf-8")
    git(repo, "add", "--", ".env")
    git(repo, "commit", "--quiet", "-m", "add environment file")
    (repo / ".env").write_text("PLATFORM_SECRET=changed-secret-marker\n", encoding="utf-8")
    (repo / "untracked.txt").write_text(
        "untracked-secret-marker\n", encoding="utf-8"
    )

    report = inspect(workspace)
    assert len(report["repositories"]) == 1
    result = report["repositories"][0]
    assert result["error"] is None
    assert any(diff["path"] == "tracked.txt" for diff in result["diffs"])
    assert any(
        change["untracked"] and change["path"] == "untracked.txt"
        for change in result["changes"]
    )
    assert any(
        change["sensitive"] and change["path"] == "[sensitive path omitted]"
        for change in result["changes"]
    )
    rendered = json.dumps(report)
    assert "untracked-secret-marker" not in rendered
    assert "env-secret-marker" not in rendered
    assert "changed-secret-marker" not in rendered
    assert ".env" not in rendered


def test_external_git_metadata_and_config_includes_fail_closed(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    repo = repository(workspace / "repo")
    outside = tmp_path / "outside-config"
    outside.write_text("[core]\n pager = cat\n", encoding="utf-8")
    config = repo / ".git" / "config"
    original_config = config.read_text(encoding="utf-8")
    config.write_text(
        original_config + f'\n[include]\n path = "{outside}"\n',
        encoding="utf-8",
    )

    result = inspect(workspace)["repositories"][0]
    assert result["error"] == "Repository metadata is outside the workspace or unsupported"
    assert str(outside) not in json.dumps(result)
    config.write_text(
        original_config + '\n[filter "external"]\n clean = external-helper\n',
        encoding="utf-8",
    )
    result = inspect(workspace)["repositories"][0]
    assert result["error"] == "Repository metadata is outside the workspace or unsupported"

def test_linked_worktree_filter_config_is_rejected(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    main = repository(workspace / "main")
    (main / ".gitattributes").write_text("*.txt filter=probe\n", encoding="utf-8")
    git(main, "add", "--", ".gitattributes")
    git(main, "commit", "--quiet", "-m", "configure attributes")
    git(main, "config", "extensions.worktreeConfig", "true")
    linked = workspace / "linked"
    git(main, "worktree", "add", "--quiet", "-b", "linked", str(linked))
    git(linked, "config", "--worktree", "filter.probe.clean", "external-helper")
    (linked / "tracked.txt").write_text("modified\n", encoding="utf-8")

    repositories = inspect(workspace)["repositories"]
    linked_result = next(result for result in repositories if result["path"] == "linked")
    assert linked_result["error"] == "Repository metadata is outside the workspace or unsupported"
    assert linked_result["diffs"] == []

def test_alarm_during_popen_registration_kills_the_git_process(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    repository(workspace / "repo")
    marker = tmp_path / "orphan-marker"
    fake_git = tmp_path / "fake-git"
    fake_git.write_text(
        f"#!{sys.executable}\n"
        "import pathlib, time\n"
        "time.sleep(0.25)\n"
        f"pathlib.Path({str(marker)!r}).write_text('survived')\n",
        encoding="utf-8",
    )
    fake_git.chmod(0o755)
    script = GIT_INSPECTION_SCRIPT.replace(
        'GIT = "/usr/bin/git"', f"GIT = {str(fake_git)!r}"
    )
    wrapper = (
        "\n_real_popen = subprocess.Popen\n"
        "def interrupt_after_spawn(*args, **kwargs):\n"
        "    process = _real_popen(*args, **kwargs)\n"
        "    os.kill(os.getpid(), signal.SIGALRM)\n"
        "    return process\n"
        "subprocess.Popen = interrupt_after_spawn\n\n"
    )
    script = script.replace("def run_git(", wrapper + "def run_git(", 1)

    report = inspect(workspace, script)
    assert report["repositories"][0]["error"] == "Repository could not be inspected"
    time.sleep(0.35)
    assert not marker.exists()


def test_external_object_alternates_are_rejected(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    repo = repository(workspace / "repo")
    outside = tmp_path / "outside-objects"
    outside.mkdir()
    alternates = repo / ".git" / "objects" / "info" / "alternates"
    alternates.write_text(str(outside) + "\n", encoding="utf-8")

    result = inspect(workspace)["repositories"][0]
    assert result["error"] == "Repository metadata is outside the workspace or unsupported"
    assert str(outside) not in json.dumps(result)


def test_git_paths_and_diff_text_are_escaped_in_html(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    repo = repository(workspace / "repo<script>")
    path = "tracked<script>.txt"
    (repo / path).write_text("before\n<script>alert(1)</script>\n", encoding="utf-8")
    git(repo, "add", "--", path)
    git(repo, "commit", "--quiet", "-m", "add markup path")
    (repo / path).write_text("before\n<script>alert(2)</script>\n", encoding="utf-8")

    report = inspect(workspace)
    page = render_changes_page("trip", result=report).body.decode()
    assert "<script>" not in page
    assert "&lt;script&gt;" in page
    assert "alert(2)" in page
