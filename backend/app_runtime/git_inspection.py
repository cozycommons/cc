GIT_INSPECTION_SCRIPT = r"""
import json
import os
import pathlib
import re
import select
import signal
import stat
import subprocess
import sys
import time

MAX_DEPTH = 8
MAX_DIRECTORIES = 1200
MAX_ENTRIES_PER_DIRECTORY = 500
MAX_REPOSITORIES = 12
MAX_STATUS_ENTRIES = 64
MAX_STATUS_OUTPUT = 24 * 1024
MAX_DIFF_FILES = 16
MAX_DIFF_BYTES = 12 * 1024
MAX_TOTAL_DIFF_BYTES = 96 * 1024
MAX_RESPONSE_BYTES = 256 * 1024
MAX_PATH_LENGTH = 512
MAX_COMMAND_SECONDS = 0.75
MAX_TOTAL_SECONDS = 10
MAX_METADATA_DIRECTORIES = 1200
MAX_METADATA_ENTRIES = 16000

SKIP_DIRECTORIES = {
    ".cache", ".next", ".venv", "__pycache__", "build", "dist",
    "node_modules", "target", "vendor", "venv",
}
SENSITIVE_PATH = re.compile(
    r"(^|/)(?:\.env(?:\..*)?|\.aws|\.ssh|\.netrc|\.npmrc|\.pypirc|"
    r"credentials?(?:[._-].*)?|secrets?(?:[._-].*)?|"
    r"[^/]*(?:token|secret|credential|password|private[-_]?key|"
    r"id_rsa|id_ed25519)[^/]*)(?:/|$)|"
    r"\.(?:pem|key|p12|pfx|jks|keystore)$",
    re.IGNORECASE,
)
SECRET_ASSIGNMENT = re.compile(
    r"(?i)(\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|"
    r"client[_-]?secret|password|passwd|secret|credential|private[_-]?key)"
    r"\b\s*[:=]\s*)(?:\"[^\"\n]*\"|'[^'\n]*'|[^\s#;,]+)"
)
TOKEN_VALUE = re.compile(
    r"\b(?:gh[pousr]_[A-Za-z0-9_]{16,}|github_pat_[A-Za-z0-9_]{16,}|"
    r"sk_(?:live|test)_[A-Za-z0-9]{16,}|xox[baprs]-[A-Za-z0-9-]{16,}|"
    r"AKIA[0-9A-Z]{16})\b"
)
PRIVATE_KEY = re.compile(
    r"-----BEGIN [^-]*(?:PRIVATE KEY|SECRET)[^-]*-----.*?"
    r"-----END [^-]*(?:PRIVATE KEY|SECRET)[^-]*-----",
    re.DOTALL,
)
GIT = "/usr/bin/git"
GIT_ENV = {
    "HOME": "/nonexistent",
    "LANG": "C",
    "LC_ALL": "C",
    "PATH": "/usr/bin:/bin",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_NO_LAZY_FETCH": "1",
    "GIT_PAGER": "cat",
    "PAGER": "cat",
    "GIT_ATTR_NOSYSTEM": "1",
}
GIT_PREFIX = [
    GIT,
    "--no-pager",
    "-c", "core.hooksPath=/dev/null",
    "-c", "core.fsmonitor=false",
    "-c", "core.attributesFile=/dev/null",
    "-c", "core.untrackedCache=false",
    "-c", "core.pager=cat",
    "-c", "diff.external=",
    "--literal-pathspecs",
]

try:
    root_arg = pathlib.Path(sys.argv[1])
    if root_arg.is_symlink():
        raise OSError()
    root = root_arg.resolve(strict=True)
    if not root.is_dir():
        raise OSError()
except (IndexError, OSError, RuntimeError):
    print(json.dumps({"repositories": [], "error": "Workspace is unavailable"}))
    raise SystemExit(0)

deadline = time.monotonic() + MAX_TOTAL_SECONDS
total_diff_bytes = 0
total_diff_files = 0
active_git_processes = set()

def inspection_alarm(signum, frame):
    for process_id in tuple(active_git_processes):
        try:
            os.kill(process_id, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except PermissionError:
            pass
    raise TimeoutError("Git inspection deadline exceeded")


signal.signal(signal.SIGALRM, inspection_alarm)
signal.alarm(MAX_TOTAL_SECONDS + 1)


def read_regular(path, limit):
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > limit:
            return None
        output = bytearray()
        while len(output) <= limit:
            chunk = os.read(descriptor, min(4096, limit + 1 - len(output)))
            if not chunk:
                return bytes(output)
            output.extend(chunk)
        return None
    finally:
        os.close(descriptor)


def inside(path, base=root):
    return path == base or base in path.parents


def safe_text(value, limit=MAX_PATH_LENGTH, preserve_newlines=False):
    pieces = []
    size = 0
    for char in value:
        if preserve_newlines and char in "\n\r\t":
            piece = char
        elif char.isprintable():
            piece = char
        else:
            piece = "\\u{:04x}".format(ord(char))
        encoded_size = len(piece.encode("utf-8"))
        if size + encoded_size > limit:
            break
        pieces.append(piece)
        size += encoded_size
    return "".join(pieces)


def terminate(process):
    try:
        process.terminate()
    except ProcessLookupError:
        pass
    except PermissionError:
        pass
    try:
        process.wait(timeout=0.15)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        except PermissionError:
            pass
        process.wait()


def run_git(repository, arguments, limit=8192, timeout=MAX_COMMAND_SECONDS):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return b"", "timeout", None
    command = GIT_PREFIX + ["-C", os.fspath(repository)] + arguments
    process = None
    try:
        previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGALRM})
        try:
            process = subprocess.Popen(
                command,
                cwd=repository,
                env=GIT_ENV,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            active_git_processes.add(process.pid)
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
    except OSError:
        if process is not None:
            active_git_processes.discard(process.pid)
            terminate(process)
            process.stdout.close()
        return b"", "unavailable", None
    output = bytearray()
    command_deadline = min(deadline, time.monotonic() + timeout)
    try:
        while True:
            remaining = command_deadline - time.monotonic()
            if remaining <= 0:
                terminate(process)
                return bytes(output), "timeout", None
            ready, _, _ = select.select([process.stdout], [], [], min(remaining, 0.05))
            if ready:
                chunk = os.read(process.stdout.fileno(), min(8192, limit + 1 - len(output)))
                if not chunk:
                    break
                output.extend(chunk)
                if len(output) > limit:
                    terminate(process)
                    return bytes(output[:limit]), "output", None
            elif process.poll() is not None:
                continue
        code = process.wait(timeout=max(0.01, command_deadline - time.monotonic()))
        return bytes(output), "ok" if code == 0 else "failed", code
    except (OSError, subprocess.TimeoutExpired, ValueError):
        terminate(process)
        return bytes(output), "failed", None
    finally:
        active_git_processes.discard(process.pid)
        process.stdout.close()


def safe_repository(repository):
    marker = repository / ".git"
    if marker.is_symlink():
        return False
    if marker.is_dir():
        git_directory = marker.resolve()
    elif marker.is_file():
        try:
            content = read_regular(marker, 4096)
            if content is None:
                return False
            content = content.decode("utf-8", errors="strict")
            if not content.startswith("gitdir: "):
                return False
            git_directory = (repository / content[8:].strip()).resolve()
        except (OSError, UnicodeError, RuntimeError):
            return False
    else:
        return False
    if not inside(git_directory) or not git_directory.is_dir():
        return False
    if (git_directory / "config").is_symlink():
        return False
    common_file = git_directory / "commondir"
    if common_file.is_symlink():
        return False
    common_directory = git_directory
    if common_file.is_file():
        try:
            content = read_regular(common_file, 4096)
            if content is None:
                return False
            common_directory = (
                git_directory / content.decode("utf-8", errors="strict").strip()
            ).resolve()
        except (OSError, UnicodeError, RuntimeError):
            return False
    if not inside(common_directory) or not common_directory.is_dir():
        return False
    config_paths = {
        common_directory / "config",
        git_directory / "config",
        git_directory / "config.worktree",
    }
    for config_path in config_paths:
        if not os.path.lexists(config_path):
            continue
        try:
            config_bytes = read_regular(config_path, 64 * 1024)
            if config_bytes is None:
                return False
            config_text = config_bytes.decode("utf-8", errors="strict")
            if re.search(
                r"(?im)^\s*\[\s*(?:include(?:if)?|filter)(?:\s|\])",
                config_text,
            ):
                return False
        except (OSError, UnicodeError, RuntimeError):
            return False
    pending = [git_directory, common_directory] if git_directory != common_directory else [git_directory]
    checked = set()
    scanned_directories = 0
    scanned_entries = 0
    while pending:
        if time.monotonic() >= deadline:
            return False
        directory = pending.pop()
        try:
            resolved_directory = directory.resolve(strict=True)
        except (OSError, RuntimeError):
            return False
        if resolved_directory in checked:
            continue
        if not inside(resolved_directory):
            return False
        checked.add(resolved_directory)
        scanned_directories += 1
        if scanned_directories > MAX_METADATA_DIRECTORIES:
            return False
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    if time.monotonic() >= deadline:
                        return False
                    scanned_entries += 1
                    if scanned_entries > MAX_METADATA_ENTRIES or entry.is_symlink():
                        return False
                    if entry.is_dir(follow_symlinks=False):
                        pending.append(pathlib.Path(entry.path))
        except OSError:
            return False
    objects = common_directory / "objects"
    info = objects / "info"
    alternates = info / "alternates"
    if objects.is_symlink() or info.is_symlink() or alternates.is_symlink():
        return False
    if alternates.is_file():
        try:
            alternates_content = read_regular(alternates, 16 * 1024)
            if alternates_content is None:
                return False
            lines = alternates_content.decode("utf-8", errors="strict").splitlines()
            for line in lines:
                target = pathlib.Path(line)
                if not target.is_absolute():
                    target = objects / target
                if not inside(target.resolve()):
                    return False
        except (OSError, UnicodeError, RuntimeError):
            return False
    return True


def discover():
    pending = [(root, 0)]
    found = []
    scanned = 0
    truncated = False
    while pending:
        if (
            scanned >= MAX_DIRECTORIES
            or len(found) >= MAX_REPOSITORIES
            or time.monotonic() >= deadline
        ):
            truncated = True
            break
        directory, depth = pending.pop()
        scanned += 1
        children = []
        try:
            with os.scandir(directory) as entries:
                for index, entry in enumerate(entries):
                    if time.monotonic() >= deadline:
                        truncated = True
                        break
                    if index >= MAX_ENTRIES_PER_DIRECTORY:
                        truncated = True
                        break
                    if entry.name == ".git":
                        if entry.is_dir(follow_symlinks=False) or entry.is_file(follow_symlinks=False):
                            found.append(directory)
                        continue
                    if (
                        depth < MAX_DEPTH
                        and entry.name not in SKIP_DIRECTORIES
                        and entry.is_dir(follow_symlinks=False)
                    ):
                        children.append(pathlib.Path(entry.path))
        except OSError:
            truncated = True
        pending.extend((child, depth + 1) for child in sorted(children, key=os.fspath, reverse=True))
    return found, truncated


def display_path(raw_path):
    value = os.fsdecode(raw_path)
    if SENSITIVE_PATH.search(value.replace(os.sep, "/")):
        return "[sensitive path omitted]", True
    return safe_text(value), False


def inspect_repository(repository):
    global total_diff_bytes, total_diff_files
    try:
        relative = repository.relative_to(root).as_posix() or "."
    except ValueError:
        return None
    result = {
        "path": safe_text(relative),
        "branch": None,
        "detached": False,
        "commit": None,
        "changes": [],
        "diffs": [],
        "omitted_diffs": 0,
        "truncated": False,
        "error": None,
    }
    if not safe_repository(repository):
        result["error"] = "Repository metadata is outside the workspace or unsupported"
        return result
    top, state, code = run_git(repository, ["rev-parse", "--show-toplevel"], limit=4096)
    if state != "ok":
        result["error"] = "Repository could not be inspected"
        return result
    try:
        resolved_top = pathlib.Path(os.fsdecode(top).strip()).resolve(strict=True)
    except (OSError, RuntimeError):
        result["error"] = "Repository could not be inspected"
        return result
    if not inside(resolved_top) or resolved_top != repository.resolve():
        result["error"] = "Repository metadata is outside the workspace or unsupported"
        return result
    branch, state, code = run_git(
        repository, ["symbolic-ref", "--quiet", "--short", "HEAD"], limit=4096
    )
    if state == "ok":
        result["branch"] = safe_text(os.fsdecode(branch).strip(), 256)
    else:
        result["detached"] = True
    commit, state, code = run_git(
        repository, ["rev-parse", "--verify", "--quiet", "HEAD"], limit=4096
    )
    if state == "ok":
        full_hash = os.fsdecode(commit).strip()
        if re.fullmatch(r"[0-9a-fA-F]{40,64}", full_hash):
            subject, subject_state, _ = run_git(
                repository, ["log", "-1", "--format=%s", "HEAD"], limit=4096
            )
            result["commit"] = {
                "sha": full_hash[:12],
                "subject": safe_text(os.fsdecode(subject).strip(), 256)
                if subject_state == "ok" else "",
            }
    status, state, code = run_git(
        repository,
        [
            "status", "--porcelain=v1", "-z", "--untracked-files=all",
            "--ignore-submodules=all", "--no-renames",
        ],
        limit=MAX_STATUS_OUTPUT,
    )
    if state != "ok":
        result["error"] = "Git status timed out or exceeded inspection limits"
        return result
    entries = [entry for entry in status.split(b"\0") if entry]
    if len(entries) > MAX_STATUS_ENTRIES:
        entries = entries[:MAX_STATUS_ENTRIES]
        result["truncated"] = True
    if len(status) >= MAX_STATUS_OUTPUT:
        result["truncated"] = True
    tracked_paths = []
    for entry in entries:
        if len(entry) < 4:
            result["truncated"] = True
            continue
        code_text = os.fsdecode(entry[:2])
        raw_path = entry[3:]
        path, sensitive = display_path(raw_path)
        result["changes"].append({
            "status": safe_text(code_text, 2),
            "path": path,
            "untracked": code_text == "??",
            "sensitive": sensitive,
        })
        if code_text != "??" and not sensitive:
            tracked_paths.append((raw_path, path))
    for raw_path, display in tracked_paths:
        if total_diff_files >= MAX_DIFF_FILES or total_diff_bytes >= MAX_TOTAL_DIFF_BYTES:
            result["truncated"] = True
            result["omitted_diffs"] += 1
            continue
        try:
            path_value = os.fsdecode(raw_path)
            working_path = repository / path_value
            resolved_path = working_path.resolve(strict=False)
            if not inside(resolved_path, repository.resolve()) or working_path.is_symlink():
                result["omitted_diffs"] += 1
                continue
            if working_path.exists() and working_path.stat().st_size > 128 * 1024:
                result["omitted_diffs"] += 1
                continue
        except (OSError, RuntimeError, ValueError):
            result["omitted_diffs"] += 1
            continue
        pathspec = os.fsdecode(raw_path)
        numstat, state, _ = run_git(
            repository,
            [
                "diff", "--numstat", "--no-ext-diff", "--no-textconv",
                "--no-color", "--no-renames", "HEAD", "--", pathspec,
            ],
            limit=4096,
            timeout=0.5,
        )
        if state != "ok":
            result["omitted_diffs"] += 1
            result["truncated"] = result["truncated"] or state in {"timeout", "output"}
            continue
        fields = numstat.split(b"\t", 2)
        if len(fields) < 3 or fields[0] == b"-" or fields[1] == b"-":
            result["omitted_diffs"] += 1
            continue
        try:
            if int(fields[0]) + int(fields[1]) > 1200:
                result["omitted_diffs"] += 1
                continue
        except ValueError:
            result["omitted_diffs"] += 1
            continue
        available = min(MAX_DIFF_BYTES, MAX_TOTAL_DIFF_BYTES - total_diff_bytes)
        diff, state, _ = run_git(
            repository,
            [
                "diff", "--no-ext-diff", "--no-textconv", "--no-color",
                "--no-renames", "--unified=3", "HEAD", "--", pathspec,
            ],
            limit=available,
            timeout=0.75,
        )
        if state != "ok":
            result["omitted_diffs"] += 1
            result["truncated"] = result["truncated"] or state in {"timeout", "output"}
            continue
        text = os.fsdecode(diff)
        if "\0" in text:
            result["omitted_diffs"] += 1
            continue
        text = PRIVATE_KEY.sub("[redacted private key]", text)
        text = SECRET_ASSIGNMENT.sub(r"\1[redacted]", text)
        text = TOKEN_VALUE.sub("[redacted token]", text)
        text = safe_text(text, available, preserve_newlines=True)
        if not text:
            continue
        result["diffs"].append({"path": display, "text": text})
        total_diff_bytes += len(text.encode("utf-8"))
        total_diff_files += 1
    return result


repositories, discovery_truncated = discover()
report = {"repositories": [], "truncated": discovery_truncated}
for repository in repositories:
    if time.monotonic() >= deadline:
        report["truncated"] = True
        break
    report["repositories"].append(inspect_repository(repository))
while True:
    encoded = json.dumps(report, ensure_ascii=True, separators=(",", ":")).encode()
    if len(encoded) <= MAX_RESPONSE_BYTES:
        break
    report["truncated"] = True
    changed = False
    for repository in reversed(report["repositories"]):
        if repository and repository["diffs"]:
            repository["diffs"].pop()
            repository["omitted_diffs"] += 1
            changed = True
            break
    if not changed:
        for repository in reversed(report["repositories"]):
            if repository and repository["changes"]:
                repository["changes"].pop()
                repository["truncated"] = True
                changed = True
                break
    if not changed:
        if len(report["repositories"]) > 1:
            report["repositories"].pop()
            continue
        report = {"repositories": [], "truncated": True}
        encoded = json.dumps(report, ensure_ascii=True, separators=(",", ":")).encode()
        break
print(encoded.decode("utf-8"))
"""

MAX_RESPONSE_BYTES = 256 * 1024
INSPECTION_WALL_TIMEOUT = "12s"
INSPECTION_TIMEOUT = 15
