"""Run one fixed toolchain operation on untrusted input in a disposable container.

This is the only code that starts the toolchain. It runs in the trusted
worker, never in the Commons API. Input and output cross the boundary as tar
streams on stdin/stdout, so the container gets no host mount, and the output
is parsed in memory with path, type, count and size checks before anything
reads it.
"""
import io
import os
import subprocess
import tarfile
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import PurePosixPath

IMAGE = "cc-arcade-toolchain:dev"
OPERATIONS = {"export", "import"}


class SandboxError(RuntimeError):
    pass


@dataclass(frozen=True)
class Limits:
    """Per-run limits. Defaults fit a large Flash game on a 4-core worker."""
    cpus: float = 2.0
    memory_mb: int = 1536  # also the swap ceiling: no swap
    pids: int = 256  # JVM threads count against this
    scratch_mb: int = 512  # tmpfs for input, JPEXS output and HOME
    timeout_seconds: int = 300
    max_output_bytes: int = 256 * 1024 * 1024
    max_output_files: int = 20_000
    max_log_bytes: int = 64 * 1024


@dataclass(frozen=True)
class Result:
    files: dict[str, bytes]
    log: str


def docker_command(name: str, operation: str, arguments: list[str], limits: Limits,
                   image: str = IMAGE, runtime: str | None = None) -> list[str]:
    if operation not in OPERATIONS:
        raise ValueError(f"unknown toolchain operation: {operation}")
    command = [
        "docker", "run", "--rm", "-i", "--name", name, "--pull", "never",
        "--network", "none", "--read-only", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges", "--user", "65534:65534",
        "--cpus", str(limits.cpus), "--memory", f"{limits.memory_mb}m",
        "--memory-swap", f"{limits.memory_mb}m", "--pids-limit", str(limits.pids),
        "--ulimit", "nofile=1024:1024", "--ulimit", "core=0",
        "--tmpfs", f"/tmp:rw,noexec,nosuid,nodev,size={limits.scratch_mb}m,mode=1777",
        # The daemon would otherwise keep a copy of everything the job prints.
        "--log-driver", "none",
        "--env", "HOME=/tmp/home",
    ]
    if runtime:  # for example runsc (gVisor) on a production worker
        command += ["--runtime", runtime]
    return [*command, image, operation, *arguments]


def pack(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for name, data in sorted(files.items()):
            info = tarfile.TarInfo(safe_name(name))
            info.size, info.mode, info.mtime = len(data), 0o644, 0
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def safe_name(name: str) -> str:
    path = PurePosixPath(name)
    if not name or path.is_absolute() or "\\" in name or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"unsafe archive path: {name!r}")
    return path.as_posix()


def unpack(data: bytes, limits: Limits) -> dict[str, bytes]:
    """Regular files only; links, devices and escaping names are rejected outright."""
    files: dict[str, bytes] = {}
    total = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
            for member in archive:
                name = member.name.removeprefix("./")
                if member.isdir() and name in {"", "."}:
                    continue
                name = safe_name(name.rstrip("/") if member.isdir() else name)
                if member.isdir():
                    continue
                if not member.isreg():
                    raise SandboxError(f"output entry is not a regular file: {name}")
                total += member.size
                if len(files) >= limits.max_output_files or total > limits.max_output_bytes:
                    raise SandboxError("toolchain output exceeds its limits")
                handle = archive.extractfile(member)
                files[name] = handle.read() if handle else b""
    except (tarfile.TarError, ValueError) as error:
        raise SandboxError(f"unreadable toolchain output: {error}") from None
    return files


def run(operation: str, arguments: list[str], files: dict[str, bytes], limits: Limits = Limits(),
        image: str | None = None, runtime: str | None = None) -> Result:
    image = image or os.environ.get("CC_ARCADE_TOOLCHAIN_IMAGE", IMAGE)
    runtime = runtime or os.environ.get("CC_ARCADE_TOOLCHAIN_RUNTIME") or None
    name = f"cc-arcade-toolchain-{uuid.uuid4().hex}"
    command = docker_command(name, operation, arguments, limits, image, runtime)
    # stdout is bounded by the container's tmpfs (the tar of its output
    # directory); stderr is not, so it goes to a file and only its tail is kept.
    with tempfile.TemporaryFile() as log:
        try:
            completed = subprocess.run(command, input=pack(files), stdout=subprocess.PIPE, stderr=log,
                                       timeout=limits.timeout_seconds, check=False)
        except subprocess.TimeoutExpired:
            raise SandboxError(f"toolchain exceeded {limits.timeout_seconds} s") from None
        finally:
            # Killing the docker client does not stop the container; remove it by name.
            subprocess.run(["docker", "rm", "--force", name], capture_output=True, check=False)
        log.seek(max(0, log.seek(0, io.SEEK_END) - limits.max_log_bytes))
        text = log.read().decode("utf-8", "replace").replace("\r\n", "\n")
    if completed.returncode == 137:
        raise SandboxError("toolchain was killed (memory limit)")
    if completed.returncode != 0:
        raise SandboxError(f"toolchain failed with exit code {completed.returncode}: {text[-2000:]}")
    if len(completed.stdout) > limits.max_output_bytes + 1024 * 1024:
        raise SandboxError("toolchain output exceeds its limits")
    return Result(unpack(completed.stdout, limits), text)
