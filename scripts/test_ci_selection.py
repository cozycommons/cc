import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location("ci_selection", Path(__file__).with_name("ci-selection.py"))
ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci)

TEST_FILES = [
    *(f"frontend/src/{p}/App.test.jsx" for p in ci.FRONTEND_PROJECTS),
    "frontend/src/App.test.jsx",
    "frontend/src/contexts/Auth.test.jsx",
    "frontend/nginx.test.js",
    "frontend/e2e/dice-regressions.spec.js",
    *(f"backend/tests/test_{p}.py" for p in ci.BACKEND_PROJECTS),
    "backend/tests/test_migration_runner.py",
    "backend/tests/test_service_health.py",
]


class SelectionTests(unittest.TestCase):
    def test_compute_dependencies_and_test_only_changes(self):
        plan = ci.select(["backend/compute/worker.py"], TEST_FILES)
        self.assertEqual([j for j in ci.JOBS if plan[j]], ["crowdset", "crowdset-container", "compute"])
        plan = ci.select(["backend/compute/tests/test_compute.py"], TEST_FILES)
        self.assertEqual([j for j in ci.JOBS if plan[j]], ["compute"])

    def test_docs_only_skips_every_expensive_job(self):
        plan = ci.select(["README.md", "AGENTS.md", "docs/deployment.md", "backend/dice/TECH.md"], TEST_FILES)
        self.assertFalse(any(plan[job] for job in ci.JOBS))

    def test_each_frontend_project_runs_its_own_and_shared_tests(self):
        for project in ci.FRONTEND_PROJECTS:
            with self.subTest(project=project):
                plan = ci.select([f"frontend/src/{project}/App.jsx"], TEST_FILES)
                self.assertEqual(plan["frontend_projects"], [project])
                self.assertEqual(plan["frontend_files"], sorted([
                    "nginx.test.js", "src/App.test.jsx", "src/contexts/Auth.test.jsx", f"src/{project}/App.test.jsx",
                ]))
                self.assertTrue(plan["crowdset-container"])
                self.assertFalse(plan["crowdset"])
                self.assertFalse(plan["backend-tests"])

    def test_each_backend_project_runs_its_own_and_shared_tests(self):
        for project in ci.BACKEND_PROJECTS:
            directory = "ig_logger/sinks/beli" if project == "beli" else project
            with self.subTest(project=project):
                plan = ci.select([f"backend/{directory}/logic.py"], TEST_FILES)
                self.assertEqual(plan["backend_projects"], [project])
                self.assertEqual(plan["backend_files"], sorted([
                    f"backend/tests/test_{project}.py", "backend/tests/test_migration_runner.py", "backend/tests/test_service_health.py",
                ]))
                self.assertEqual(plan["trips"], project == "trips")
                self.assertFalse(plan["frontend-tests"])
                self.assertFalse(plan["crowdset"])

    def test_crowdset_backend_is_isolated(self):
        for path in ["backend/crowdset/video.py", "backend/crowdset/tests/test_video.py", "backend/crowdset/tests/requirements.txt", "backend/requirements-crowdset.txt", "scripts/crowdset-dev.sh"]:
            with self.subTest(path=path):
                plan = ci.select([path], TEST_FILES)
                self.assertEqual([j for j in ci.JOBS if plan[j]], ["crowdset", "crowdset-container"])

    def test_test_only_edits_select_the_project(self):
        plan = ci.select(["backend/tests/test_espn_lineup.py", "frontend/src/trips/ui.test.jsx"], TEST_FILES)
        self.assertEqual(plan["backend_projects"], ["espn"])
        self.assertEqual(plan["frontend_projects"], ["trips"])
        self.assertFalse(plan["trips"])

    def test_shared_frontend_dependencies_run_all_frontend_tests(self):
        for path in ["frontend/package-lock.json", "frontend/src/contexts/SupabaseContext.jsx", "frontend/vite.config.js", "frontend/src/App.jsx", "frontend/src/new-project/App.jsx", "design/dice/App.jsx"]:
            with self.subTest(path=path):
                plan = ci.select([path], TEST_FILES)
                self.assertEqual(plan["frontend_projects"], sorted(ci.FRONTEND_PROJECTS))
                self.assertFalse(plan["backend-tests"])

    def test_shared_backend_inputs_include_real_trips_integration(self):
        for path in ["backend/main.py", "backend/requirements.txt", "backend/tests/conftest.py", "backend/migration_runner.py", "scripts/bootstrap-dice-test-db.sh", "scripts/supabase-test-scaffold.sql", "package-lock.json", "supabase/config.toml"]:
            with self.subTest(path=path):
                plan = ci.select([path], TEST_FILES)
                self.assertEqual(plan["backend_projects"], sorted(ci.BACKEND_PROJECTS))
                self.assertTrue(plan["trips"])
                self.assertFalse(plan["crowdset"])

    def test_dice_profile_contract_changes_also_run_trips(self):
        for path in ["backend/dice/routes.py", "backend/dice/repository.py", "backend/dice/schemas.py"]:
            with self.subTest(path=path):
                plan = ci.select([path], TEST_FILES)
                self.assertEqual(plan["backend_projects"], ["dice", "trips"])
                self.assertTrue(plan["trips"])

    def test_migrations_jobs_and_scripts_select_their_owners(self):
        cases = {
            "backend/migrations/0081_dice_example.sql": ["dice", "trips"],
            "backend/migrations/DICE_SCHEMA_CONTRACT_VERSION": ["dice", "trips"],
            "backend/commons/migrations/0013_commons_example.sql": ["commons"],
            "backend/trips/migrations/0003_trips_example.sql": ["trips"],
            "backend/migrations/0008_beli_espn_lineup.sql": sorted(ci.INTEGRATIONS),
            "backend/jobs/dice_rating_rebuild.py": ["dice"],
            "backend/jobs/espn_lineup.py": ["espn"],
            "scripts/trips-dev.py": ["trips"],
            "scripts/start-local-dice-backend.sh": ["dice"],
            "scripts/verify-commons-schema.sh": ["commons"],
        }
        for path, expected in cases.items():
            with self.subTest(path=path):
                self.assertEqual(ci.select([path], TEST_FILES)["backend_projects"], expected)

    def test_ci_and_unmapped_infrastructure_skip_unrelated_media(self):
        for path in [".github/workflows/ci.yml", "scripts/ci-selection.py", "scripts/test_ci_selection.py", "scripts/new-build.sh", ".dockerignore", "new-runtime/config.json"]:
            with self.subTest(path=path):
                plan = ci.select([path], TEST_FILES)
                self.assertTrue(all(plan[job] for job in ci.JOBS if job != "crowdset"))
                self.assertFalse(plan["crowdset"])

    def test_media_runtime_changes_still_run_alongside_shared_inputs(self):
        for runtime in ["backend/crowdset/hosting.py", "backend/compute/worker.py", "backend/requirements-crowdset.txt", "scripts/systemd/crowdset-worker.service"]:
            for paths in ([runtime, ".github/workflows/ci.yml"], ["scripts/new-build.sh", runtime]):
                with self.subTest(paths=paths):
                    plan = ci.select(paths, TEST_FILES)
                    self.assertTrue(plan["crowdset"])
                    self.assertTrue(plan["crowdset-container"])

    def test_empty_diff_skips_but_missing_tests_fails(self):
        self.assertFalse(any(ci.select([], TEST_FILES)[job] for job in ci.JOBS))
        with self.assertRaises(ValueError):
            ci.select(["backend/dice/routes.py"], [])


class DiffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git("init", "-q", "-b", "main")
        self.git("config", "gc.auto", "0")
        self.git("config", "maintenance.auto", "false")
        self.git("config", "user.email", "ci@example.invalid")
        self.git("config", "user.name", "CI test")
        self.write("README.md")
        self.base = self.commit()
        # Git's -C keeps these history tests independent of the caller's checkout.
        original = subprocess.check_output
        self.command_patch = patch.object(ci.subprocess, "check_output", side_effect=lambda cmd, **kwargs: original(["git", "-C", str(self.root), *cmd[1:]], **kwargs))
        self.command_patch.start()
        self.addCleanup(self.command_patch.stop)

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.root), *args], check=True, capture_output=True, text=True).stdout.strip()

    def write(self, name):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(name)

    def commit(self):
        self.git("add", ".")
        self.git("commit", "-qm", "test")
        return self.git("rev-parse", "HEAD")

    def test_pr_excludes_unrelated_base_branch_changes(self):
        self.git("checkout", "-qb", "feature")
        self.write("frontend/src/dice/App.jsx")
        head = self.commit()
        self.git("checkout", "-q", "main")
        self.write("backend/trips/routes.py")
        base = self.commit()
        event = {"pull_request": {"base": {"sha": base}, "head": {"sha": head}}}
        self.assertEqual(ci.changed_paths("pull_request", event), ["frontend/src/dice/App.jsx"])

    def test_push_and_merge_group_include_deletions_and_both_rename_sides(self):
        self.write("frontend/src/dice/rename me.jsx")
        before = self.commit()
        target = self.root / "frontend/src/trips/renamed.jsx"
        target.parent.mkdir(parents=True)
        (self.root / "frontend/src/dice/rename me.jsx").rename(target)
        (self.root / "README.md").unlink()
        after = self.commit()
        for name, event in [
            ("push", {"before": before, "after": after}),
            ("merge_group", {"merge_group": {"base_sha": before, "head_sha": after}}),
        ]:
            with self.subTest(event=name):
                paths = ci.changed_paths(name, event)
                self.assertEqual(set(paths), {"README.md", "frontend/src/dice/rename me.jsx", "frontend/src/trips/renamed.jsx"})
                self.assertEqual(ci.select(paths, TEST_FILES)["frontend_projects"], ["dice", "trips"])

    def test_diff_is_not_truncated_at_api_path_limits(self):
        for n in range(350):
            self.write(f"docs/{n:04d}.md")
        self.write("frontend/src/dice/App.jsx")
        head = self.commit()
        paths = ci.changed_paths("push", {"before": self.base, "after": head})
        self.assertEqual(len(paths), 351)
        self.assertTrue(ci.select(paths, TEST_FILES)["frontend-tests"])

    def test_missing_base_fails_instead_of_skipping(self):
        with self.assertRaises(subprocess.CalledProcessError):
            ci.changed_paths("push", {"before": "1" * 40, "after": self.base})

    def test_plan_and_gate_commands_use_github_output_format(self):
        self.write("frontend/src/dice/App.test.jsx")
        head = self.commit()
        event_path = self.root / "event.json"
        event_path.write_text(json.dumps({"before": self.base, "after": head}))
        output_path = self.root / "output.txt"
        summary_path = self.root / "summary.md"
        env = dict(os.environ, GITHUB_EVENT_NAME="push", GITHUB_EVENT_PATH=str(event_path),
                   GITHUB_OUTPUT=str(output_path), GITHUB_STEP_SUMMARY=str(summary_path))
        script = str(Path(ci.__file__).resolve())
        result = subprocess.run(["python3", script, "plan"], cwd=self.root, env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        outputs = dict(line.split("=", 1) for line in output_path.read_text().splitlines())
        self.assertEqual(outputs["frontend-tests"], "true")
        self.assertEqual(outputs["backend-tests"], "false")
        self.assertEqual(json.loads(outputs["frontend_files"]), ["src/dice/App.test.jsx"])
        self.assertIn("Frontend projects: dice", summary_path.read_text())
        env["CI_NEEDS"] = json.dumps({"changes": {"result": "success", "outputs": outputs},
                                      "frontend-tests": {"result": "success"}})
        result = subprocess.run(["python3", script, "gate", "frontend"], cwd=self.root, env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


class GateTests(unittest.TestCase):
    def test_only_deliberately_unselected_jobs_may_skip(self):
        for selected, result, passes in [
            ("true", "success", True), ("false", "skipped", True),
            ("true", "skipped", False), ("true", "failure", False),
            ("true", "cancelled", False), (None, "skipped", False),
        ]:
            with self.subTest(selected=selected, result=result):
                needs = {"changes": {"result": "success", "outputs": {"trips": selected}}, "trips": {"result": result}}
                with contextlib.redirect_stdout(io.StringIO()):
                    if passes:
                        ci.check_gate(needs, ["trips"])
                    else:
                        with self.assertRaises(ValueError):
                            ci.check_gate(needs, ["trips"])

    def test_selection_failure_blocks_merge(self):
        with self.assertRaises(ValueError):
            ci.check_gate({"changes": {"result": "failure"}}, [])


if __name__ == "__main__":
    unittest.main()
