"""Run one fixed toolchain operation on untrusted input in a disposable container.

This is the only code that starts the toolchain. It runs in the trusted
worker, never in the Commons API. Input and output cross the boundary as tar
streams on stdin/stdout, so the container gets no host mount, and the output
is parsed in memory with path, type, count and size checks before anything
reads it.

Lifetime does not depend on this process surviving. The entrypoint kills its
own operation at TOOLCHAIN_DEADLINE and the daemon removes the exited
container (--rm), so a worker that is SIGKILLed mid-job (compute does that at
its deadline) still leaves nothing running.
"""
import io
import os
import subprocess
import tarfile
import threading
import uuid
from dataclasses import dataclass
from pathlib import PurePosixPath

IMAGE = "cc-arcade-toolchain:dev"
OPERATIONS = {"export", "import"}
TAR_OVERHEAD = 1024  # header plus padding per entry, at most


class SandboxError(RuntimeError):
    pass


@dataclass(frozen=True)
class Limits:
    """Per-run limits. Defaults fit a large Flash game on a 4-core worker."""
    cpus: float = 2.0
    memory_mb: int = 1536  # whole container, JVM heap is 70% of it; no swap
    pids: int = 256  # JVM threads count against this
    scratch_mb: int = 512  # tmpfs for input, JPEXS output and HOME
    timeout_seconds: int = 300
    max_output_bytes: int = 256 * 1024 * 1024
    max_output_files: int = 20_000
    max_log_bytes: int = 64 * 1024

    @property
    def max_stream_bytes(self) -> int:
        return self.max_output_bytes + 2 * self.max_output_files * TAR_OVERHEAD + 10 * 512


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
        "--env", f"TOOLCHAIN_DEADLINE={limits.timeout_seconds}",
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
    """Regular files only; links, devices, duplicates and escaping names are rejected outright."""
    files: dict[str, bytes] = {}
    entries = total = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
            for member in archive:
                entries += 1  # directories included, so headers alone cannot pile up
                if entries > 2 * limits.max_output_files:
                    raise SandboxError("toolchain output exceeds its limits")
                name = member.name.removeprefix("./")
                if member.isdir() and name in {"", "."}:
                    continue
                name = safe_name(name.rstrip("/") if member.isdir() else name)
                if member.isdir():
                    continue
                if not member.isreg():
                    raise SandboxError(f"output entry is not a regular file: {name}")
                if name in files:
                    raise SandboxError(f"duplicate output entry: {name}")
                total += member.size
                if len(files) >= limits.max_output_files or total > limits.max_output_bytes:
                    raise SandboxError("toolchain output exceeds its limits")
                handle = archive.extractfile(member)
                files[name] = handle.read() if handle else b""
    except (tarfile.TarError, ValueError) as error:
        raise SandboxError(f"unreadable toolchain output: {error}") from None
    return files


def _remove(name: str) -> None:
    try:
        subprocess.run(["docker", "rm", "--force", name], capture_output=True, timeout=30, check=False)
    except subprocess.TimeoutExpired:
        pass  # the container's own deadline still ends it


def run(operation: str, arguments: list[str], files: dict[str, bytes], limits: Limits = Limits(),
        image: str | None = None, runtime: str | None = None) -> Result:
    image = image or os.environ.get("CC_ARCADE_TOOLCHAIN_IMAGE", IMAGE)
    runtime = runtime or os.environ.get("CC_ARCADE_TOOLCHAIN_RUNTIME") or None
    name = f"cc-arcade-toolchain-{uuid.uuid4().hex}"
    command = docker_command(name, operation, arguments, limits, image, runtime)
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    tail = bytearray()
    expired, overflow = threading.Event(), threading.Event()

    def drain_log() -> None:  # keep only the last max_log_bytes; never buffer the rest
        while chunk := process.stderr.read(64 * 1024):
            tail.extend(chunk)
            del tail[:-limits.max_log_bytes]

    def stop(reason: threading.Event) -> None:
        reason.set()
        process.kill()
        _remove(name)

    reader = threading.Thread(target=drain_log, daemon=True)
    timer = threading.Timer(limits.timeout_seconds, stop, (expired,))
    reader.start()
    timer.start()
    output = bytearray()
    try:
        try:
            process.stdin.write(pack(files))
            process.stdin.close()
        except BrokenPipeError:
            pass  # the container ended early; its exit status explains why
        while chunk := process.stdout.read(1024 * 1024):
            output += chunk
            if len(output) > limits.max_stream_bytes:
                stop(overflow)
                break
        process.wait()
    finally:
        timer.cancel()
        if process.poll() is None:
            process.kill()
            process.wait()
        _remove(name)
        reader.join(timeout=5)
    text = bytes(tail).decode("utf-8", "replace").replace("\r\n", "\n")
    if expired.is_set() or process.returncode == 124:
        raise SandboxError(f"toolchain exceeded {limits.timeout_seconds} s")
    if overflow.is_set():
        raise SandboxError("toolchain output exceeds its limits")
    if process.returncode == 137:
        raise SandboxError("toolchain was killed (memory or time limit)")
    if process.returncode != 0:
        raise SandboxError(f"toolchain failed with exit code {process.returncode}: {text[-2000:]}")
    return Result(unpack(bytes(output), limits), text)
