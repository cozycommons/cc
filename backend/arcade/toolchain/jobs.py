"""Decompile and rebuild SWFs through the sandbox, and their compute job declarations.

Rebuild follows the recipe proven on real games: export the original's
scripts, compile only the classes whose source differs, and leave every
other class's original bytecode alone. A full recompile is not safe because
the decompiler does not round-trip every method.

JPEXS's -importScript exits 0 and prints nothing both when it compiles a
class and when it silently skips one (for example a class the movie does not
contain). So a rebuild re-exports its output and checks every class itself.
"""
import hashlib
import io
import ipaddress
import tarfile
import urllib.request
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from compute import Job, Resources

from . import sandbox, swf

# JPEXS export kinds and the folder each one produces.
KINDS = {
    "script": "scripts", "text": "texts", "symbolClass": "symbolClass", "shape": "shapes",
    "morphshape": "morphshapes", "image": "images", "sound": "sounds", "font": "fonts",
    "binaryData": "binaryData",
}
TEXT_SUFFIXES = (".as", ".svg", ".txt", ".csv")
MAX_MOVIE_BYTES = 64 * 1024 * 1024
MAX_DECLARED_BYTES = 256 * 1024 * 1024
MAX_SOURCE_BYTES = 192 * 1024  # edited classes travel in the job payload (256 KiB cap)
MAX_RESULT_BYTES = 256 * 1024 * 1024
Kind = Literal["script", "text", "symbolClass", "shape", "morphshape", "image", "sound", "font", "binaryData"]


class ToolchainError(RuntimeError):
    pass


def _lf(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def problems(log: str) -> list[str]:
    """JPEXS reports most failures in its log with exit code 0.

    Progress lines name classes (a game class called AppError is enough), so
    they are never treated as errors.
    """
    return [line for line in log.splitlines()
            if ("error" in line.lower() or "SEVERE" in line or "Exception" in line)
            and not line.startswith(("Exported", "Exporting", "Importing"))]


def _run(operation: str, arguments: list[str], files: dict[str, bytes], limits: sandbox.Limits) -> dict[str, bytes]:
    result = sandbox.run(operation, arguments, files, limits)
    if found := problems(result.log):
        raise ToolchainError("JPEXS reported errors: " + " | ".join(found[:5]))
    return result.files


def _check(movie: bytes) -> None:
    try:
        swf.check(movie, MAX_MOVIE_BYTES, MAX_DECLARED_BYTES)
    except swf.SwfRejected as error:
        raise ToolchainError(str(error)) from None


def decompile(movie: bytes, kinds: tuple[str, ...] = ("script",), limits: sandbox.Limits = sandbox.Limits()) -> dict[str, bytes]:
    """Exported parts by path (scripts/demo/Greeter.as, images/3.png, ...); text parts use LF."""
    _check(movie)
    if not kinds or any(kind not in KINDS for kind in kinds):
        raise ToolchainError("unsupported export kind")
    files = _run("export", [",".join(sorted(set(kinds)))], {"movie.swf": movie}, limits)
    return {path: _lf(data) if path.endswith(TEXT_SUFFIXES) else data for path, data in files.items()}


@dataclass(frozen=True)
class Rebuild:
    movie: bytes
    compiled: list[str]  # classes compiled from the submitted source
    unchanged: list[str]  # submitted classes identical to the original, so not compiled


def _source_path(path: str) -> str:
    if not (path.startswith("scripts/") and path.endswith(".as")):
        raise ValueError(f"not a class source path: {path}")
    return sandbox.safe_name(path)


def rebuild(movie: bytes, sources: dict[str, str], limits: sandbox.Limits = sandbox.Limits()) -> Rebuild:
    """Compile the submitted classes that differ from the movie's own into a copy of it."""
    _check(movie)
    submitted = {_source_path(path): _lf(text.encode()) for path, text in sources.items()}
    original = decompile(movie, ("script",), limits)
    missing = sorted(path for path in submitted if path not in original)
    if missing:
        # -importScript would skip these silently; adding classes is not supported yet.
        raise ToolchainError(f"classes not in the movie: {', '.join(missing)}")
    changed = {path: text for path, text in submitted.items() if original[path] != text}
    unchanged = sorted(set(submitted) - set(changed))
    if not changed:
        return Rebuild(movie, [], unchanged)
    files = {"movie.swf": movie, **changed}
    output = _run("import", [], files, limits).get("movie.swf")
    if not output:
        raise ToolchainError("JPEXS produced no movie")
    _check(output)
    rebuilt = decompile(output, ("script",), limits)
    if set(rebuilt) != set(original):
        lost, added = sorted(set(original) - set(rebuilt)), sorted(set(rebuilt) - set(original))
        raise ToolchainError(f"rebuilt movie has different classes (missing {lost}, new {added})")
    # Text comparison: the classes decompile identically. That is the
    # check available; it is not a byte-for-byte bytecode comparison.
    skipped = sorted(path for path in changed if rebuilt.get(path) == original[path])
    if skipped:
        raise ToolchainError(f"JPEXS did not compile: {', '.join(skipped)}")
    drifted = sorted(path for path in original if path not in changed and rebuilt.get(path) != original[path])
    if drifted:
        raise ToolchainError(f"untouched classes changed: {', '.join(drifted)}")
    return Rebuild(output, sorted(changed), unchanged)


# --- Compute jobs ----------------------------------------------------------
# The Commons API authenticates the user, stores the upload in private
# Storage and submits a job whose payload carries short-lived signed URLs:
# one to read the movie, one to write the result. The worker therefore holds
# no Storage or database credential, and the sandbox holds nothing at all.

def _allowed_url(url: str) -> str:
    parts = urlsplit(url)
    host = parts.hostname or ""
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = host == "localhost"
    if not host:
        raise ValueError("transfer URLs need a host")
    if parts.scheme != "https" and not (parts.scheme == "http" and loopback):
        raise ValueError("transfer URLs must be HTTPS")
    return url


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    """A signed URL names one object; following a redirect would skip the URL check."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ToolchainError(f"transfer URL redirected ({code})")


_opener = urllib.request.build_opener(_NoRedirects)


class Transfer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    movie_url: str = Field(max_length=4096)
    result_url: str = Field(max_length=4096)

    _urls = field_validator("movie_url", "result_url")(_allowed_url)


class DecompileInput(Transfer):
    kinds: list[Kind] = Field(default=["script"], min_length=1)


class DecompileOutput(BaseModel):
    movie_sha256: str
    result_sha256: str
    files: int
    bytes: int


class RebuildInput(Transfer):
    scripts: dict[str, str] = Field(min_length=1, max_length=500)

    @field_validator("scripts")
    @classmethod
    def _bounded(cls, scripts: dict[str, str]) -> dict[str, str]:
        if sum(len(path) + len(text.encode()) for path, text in scripts.items()) > MAX_SOURCE_BYTES:
            raise ValueError("edited sources exceed the payload limit")
        for path in scripts:
            _source_path(path)
        return scripts


class RebuildOutput(BaseModel):
    movie_sha256: str
    result_sha256: str
    compiled: list[str]
    unchanged: list[str]


def fetch(url: str, limit: int = MAX_MOVIE_BYTES) -> bytes:
    with _opener.open(_allowed_url(url), timeout=60) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ToolchainError(f"input is larger than {limit} bytes")
    return data


def store(url: str, data: bytes, content_type: str) -> str:
    request = urllib.request.Request(_allowed_url(url), data=data, method="PUT",
                                     headers={"Content-Type": content_type, "x-upsert": "false"})
    with _opener.open(request, timeout=120):
        pass
    return hashlib.sha256(data).hexdigest()


def _archive(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for path, data in sorted(files.items()):
            info = tarfile.TarInfo(path)
            info.size, info.mode, info.mtime = len(data), 0o644, 0
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def run_decompile(value: DecompileInput, workdir) -> DecompileOutput:
    movie = fetch(value.movie_url)
    files = decompile(movie, tuple(value.kinds))
    result = _archive(files)
    if len(result) > MAX_RESULT_BYTES:
        raise ToolchainError("decompiled parts exceed the result limit")
    return DecompileOutput(movie_sha256=hashlib.sha256(movie).hexdigest(),
                           result_sha256=store(value.result_url, result, "application/gzip"),
                           files=len(files), bytes=sum(map(len, files.values())))


def run_rebuild(value: RebuildInput, workdir) -> RebuildOutput:
    movie = fetch(value.movie_url)
    built = rebuild(movie, value.scripts)
    return RebuildOutput(movie_sha256=hashlib.sha256(movie).hexdigest(),
                         result_sha256=store(value.result_url, built.movie, "application/x-shockwave-flash"),
                         compiled=built.compiled, unchanged=built.unchanged)


# Sandbox runs are bounded at 300 s each; a rebuild makes three of them.
# If compute kills the handler first (its deadline, a lost heartbeat, or slow
# transfers, whose timeouts are per socket operation), each container still
# ends at its own deadline and the daemon removes it.
JOBS = [
    Job(name="arcade.swf_decompile", version=1, handler=run_decompile,
        input=DecompileInput, output=DecompileOutput,
        resources=Resources(cpu=2, memory_mb=2048), timeout_seconds=420, max_attempts=1),
    Job(name="arcade.swf_rebuild", version=1, handler=run_rebuild,
        input=RebuildInput, output=RebuildOutput,
        resources=Resources(cpu=2, memory_mb=2048), timeout_seconds=1020, max_attempts=1),
]
