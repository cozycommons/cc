#!/usr/bin/env python3
"""Select project suites from a GitHub event's complete git diff."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess


FRONTEND_PROJECTS = ("crowdset", "dice", "design", "trips")
BACKEND_PROJECTS = ("beli", "commons", "dice", "espn", "partiful", "resy", "trips")
INTEGRATIONS = {"beli", "espn", "partiful", "resy"}
JOBS = ("frontend-tests", "backend-tests", "trips", "crowdset", "crowdset-container", "compute")
SHARED_BACKEND_INPUTS = {
    "package.json", "package-lock.json", "scripts/bootstrap-dice-test-db.sh",
    "scripts/reset-local-dice-db.sh", "scripts/supabase-test-scaffold.sql",
    "scripts/ci-rest-proxy.py", "scripts/lib/supabase-db-url.sh",
    "scripts/test-supabase-db-url.sh",
    "scripts/test-migration-upgrades.sh",
}


def backend_test_project(path):
    name = Path(path).name
    return next((p for p in BACKEND_PROJECTS if name == f"test_{p}.py" or name.startswith(f"test_{p}_")), None)


def select(paths, test_files):
    frontend, backend = set(), set()
    crowdset = False
    compute = False

    for path in paths:
        if path.endswith(".md") or path.startswith(("docs/", ".agents/")) or path in {"LICENSE", ".gitignore"}:
            continue
        if path.startswith("backend/compute/") or path == "backend/requirements-compute.txt":
            compute = True
            if not path.startswith("backend/compute/tests/"):
                crowdset = True
        elif path in {".github/images/crowdset-tests.Dockerfile", "scripts/test_crowdset_ci_image.py"} or path.startswith("backend/crowdset/") or path == "backend/requirements-crowdset.txt" or path.startswith(("scripts/crowdset-", "scripts/systemd/crowdset-")):
            crowdset = True
        elif path.startswith("frontend/"):
            project = next((p for p in FRONTEND_PROJECTS if path.startswith((f"frontend/src/{p}/", f"frontend/public/{p}/"))), None)
            frontend.update({project} if project else FRONTEND_PROJECTS)
        elif path.startswith("design/"):
            frontend.update(FRONTEND_PROJECTS)
        elif path.startswith("backend/ig_logger/"):
            backend.add("beli")
        elif path.startswith("backend/tests/test_") and backend_test_project(path):
            backend.add(backend_test_project(path))
        elif path.startswith("backend/"):
            project = next((p for p in BACKEND_PROJECTS if path.startswith(f"backend/{p}/")), None)
            if project:
                backend.add(project)
                if path in {"backend/dice/routes.py", "backend/dice/repository.py", "backend/dice/schemas.py"}:
                    backend.add("trips")
            elif path.startswith(("backend/dice_", "backend/jobs/dice_", "backend/scripts/dice_")):
                backend.add("dice")
            elif path.startswith("backend/jobs/espn_"):
                backend.add("espn")
            elif path.startswith("backend/migrations/") and "dice" in path.lower():
                # Trips reads canonical display fields from dice_profiles.
                backend.update({"dice", "trips"})
            elif path.startswith("backend/migrations/") and "beli" in path.lower():
                backend.update(INTEGRATIONS)
            else:
                backend.update(BACKEND_PROJECTS)
        elif path in SHARED_BACKEND_INPUTS:
            backend.update(BACKEND_PROJECTS)
        elif path.startswith(("scripts/", "supabase/")):
            name = Path(path).name
            if "trips" in name:
                backend.add("trips")
            elif "dice" in name:
                backend.add("dice")
            elif "commons" in name:
                backend.add("commons")
            elif path.startswith("supabase/"):
                backend.update(BACKEND_PROJECTS)
            else:
                frontend.update(FRONTEND_PROJECTS)
                backend.update(BACKEND_PROJECTS)
                compute = True
        else:
            # Shared checks cover unmapped infrastructure; media tests need a runtime input.
            frontend.update(FRONTEND_PROJECTS)
            backend.update(BACKEND_PROJECTS)
            compute = True

    frontend_tests = sorted(
        path.removeprefix("frontend/") for path in test_files
        if path.startswith("frontend/") and not path.startswith("frontend/e2e/")
        and re.search(r"\.(test|spec)\.[cm]?[jt]sx?$", path)
        and frontend and (
            not any(path.startswith(f"frontend/src/{p}/") for p in FRONTEND_PROJECTS)
            or any(path.startswith(f"frontend/src/{p}/") for p in frontend)
        )
    )
    backend_tests = sorted(
        path for path in test_files
        if path.startswith("backend/tests/") and re.search(r"(^test_.*|.*_test)\.py$", Path(path).name)
        and backend and (backend_test_project(path) is None or backend_test_project(path) in backend)
    )
    for selected, tests, label in ((frontend, frontend_tests, "frontend"), (backend, backend_tests, "backend")):
        if selected and not tests:
            raise ValueError(f"Selected {label} projects have no test files")
    return {
        "frontend-tests": bool(frontend),
        "backend-tests": bool(backend),
        "trips": "trips" in backend,
        "crowdset": crowdset,
        "compute": compute,
        # Both deployed frontend images compile the whole shared Vite application.
        "crowdset-container": crowdset or bool(frontend),
        "frontend_files": frontend_tests,
        "backend_files": backend_tests,
        "frontend_projects": sorted(frontend),
        "backend_projects": sorted(backend),
    }


def git_paths(*args):
    return subprocess.check_output(["git", *args]).decode().rstrip("\0").split("\0")


def changed_paths(event_name, event):
    if event_name == "pull_request":
        base, head = event["pull_request"]["base"]["sha"], event["pull_request"]["head"]["sha"]
        base = subprocess.check_output(["git", "merge-base", base, head], text=True).strip()
    elif event_name == "merge_group":
        base, head = event["merge_group"]["base_sha"], event["merge_group"]["head_sha"]
    elif event_name == "push":
        base, head = event["before"], event["after"]
        if base == "0" * 40:
            return git_paths("ls-files", "-z")
    else:
        raise ValueError(f"Unsupported CI event: {event_name}")
    # Treat a rename as a deletion plus addition so both project owners run.
    return [p for p in git_paths("diff", "--name-only", "--no-renames", "-z", base, head, "--") if p]


def check_gate(needs, jobs):
    if needs["changes"]["result"] != "success":
        raise ValueError("Project selection failed")
    outputs = needs["changes"]["outputs"]
    for job in jobs:
        selected = outputs.get(job)
        if selected not in {"true", "false"}:
            raise ValueError(f"Missing selection for {job}")
        expected = "success" if selected == "true" else "skipped"
        actual = needs[job]["result"]
        if actual != expected:
            raise ValueError(f"{job}: expected {expected}, got {actual}")
        print(f"{job}: {actual}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "run", "gate"))
    parser.add_argument("target", nargs="?", choices=("frontend", "backend"))
    args = parser.parse_args()
    if args.command == "plan":
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
        paths = changed_paths(os.environ["GITHUB_EVENT_NAME"], event)
        plan = select(paths, git_paths("ls-files", "-z"))
        print(json.dumps(plan, indent=2))
        with open(os.environ["GITHUB_OUTPUT"], "a") as output:
            for key, value in plan.items():
                output.write(f"{key}={json.dumps(value, separators=(',', ':'))}\n")
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as summary:
                summary.write("### Selected CI work\n\n")
                for job in JOBS:
                    summary.write(f"- {job}: {'run' if plan[job] else 'skip'}\n")
                summary.write(f"\nFrontend projects: {', '.join(plan['frontend_projects']) or 'none'}\n")
                summary.write(f"\nBackend projects: {', '.join(plan['backend_projects']) or 'none'}\n")
    elif args.command == "run":
        files = json.loads(os.environ["CI_TEST_FILES"])
        if not isinstance(files, list) or not files or not all(isinstance(p, str) and not p.startswith("-") for p in files):
            raise ValueError("Expected a nonempty list of selected test paths")
        if args.target == "frontend":
            subprocess.run(["npm", "test", "--", *files], cwd="frontend", check=True)
        elif args.target == "backend":
            subprocess.run(["backend/.venv/bin/python", "-m", "pytest", *files, "-q"], check=True)
        else:
            parser.error("run requires a target")
    elif args.command == "gate":
        if not args.target:
            parser.error("gate requires a target")
        jobs = ("frontend-tests",) if args.target == "frontend" else JOBS[1:]
        check_gate(json.loads(os.environ["CI_NEEDS"]), jobs)


if __name__ == "__main__":
    main()
