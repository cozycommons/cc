"""Isolated Flash toolchain: input gates, output parsing, changed-class rebuilds.

The last tests run the real sandbox image when it is built locally
(docker build -t cc-arcade-toolchain:dev backend/arcade/toolchain) and skip
otherwise. Every movie is synthetic; no original game file is involved.
"""
import io
import os
import shutil
import struct
import subprocess
import tarfile
import threading
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from pydantic import ValidationError

from arcade.toolchain import jobs, sandbox, swf

CLASSES = [("Greeter", "greet", "hello"), ("Farewell", "bye", "goodbye")]
GREETER, FAREWELL = "scripts/demo/Greeter.as", "scripts/demo/Farewell.as"


def test_header_check_accepts_movies_and_refuses_bombs_and_non_swf():
    movie = swf.demo_movie(CLASSES)
    assert swf.check(movie, 1 << 20, 1 << 20) == swf.Header("none", 10, len(movie))
    bomb = b"CWS\x0a" + struct.pack("<I", 1 << 31) + zlib.compress(bytes(1 << 20))
    with pytest.raises(swf.SwfRejected, match="declares"):
        swf.check(bomb, 1 << 20, 256 << 20)
    with pytest.raises(swf.SwfRejected, match="not a SWF"):
        swf.check(b"PK\x03\x04" + bytes(100), 1 << 20, 1 << 20)
    with pytest.raises(swf.SwfRejected, match="does not match"):
        swf.check(movie + b"tail", 1 << 20, 1 << 20)
    with pytest.raises(swf.SwfRejected, match="larger"):
        swf.check(movie, 10, 1 << 20)


def tar_of(*members):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for info, data in members:
            archive.addfile(info, io.BytesIO(data) if data is not None else None)
    return buffer.getvalue()


def entry(name, data=b"x", kind=tarfile.REGTYPE, link=""):
    info = tarfile.TarInfo(name)
    info.type, info.linkname = kind, link
    info.size = len(data) if kind == tarfile.REGTYPE else 0
    return info, data if kind == tarfile.REGTYPE else None


def test_output_parsing_rejects_escapes_links_and_excess():
    limits = sandbox.Limits(max_output_files=2, max_output_bytes=10)
    ok = tar_of(entry("./", kind=tarfile.DIRTYPE), entry("./scripts/", kind=tarfile.DIRTYPE),
                entry("./scripts/A.as", b"abc"))
    assert sandbox.unpack(ok, limits) == {"scripts/A.as": b"abc"}
    for bad in (entry("../escape.as"), entry("/etc/passwd"), entry("a/../../b"),
                entry("link", kind=tarfile.SYMTYPE, link="/etc/passwd"),
                entry("hard", kind=tarfile.LNKTYPE, link="scripts/A.as"),
                entry("fifo", kind=tarfile.FIFOTYPE)):
        with pytest.raises(sandbox.SandboxError):
            sandbox.unpack(tar_of(bad), limits)
    with pytest.raises(sandbox.SandboxError, match="limits"):
        sandbox.unpack(tar_of(entry("a", b"1"), entry("b", b"2"), entry("c", b"3")), limits)
    with pytest.raises(sandbox.SandboxError, match="limits"):
        sandbox.unpack(tar_of(entry("big", bytes(11))), limits)
    with pytest.raises(sandbox.SandboxError, match="unreadable"):
        sandbox.unpack(b"not a tar" * 100, limits)


def test_container_runs_without_network_privileges_or_host_mounts():
    command = sandbox.docker_command("job", "export", ["script"], sandbox.Limits(), "image:tag")
    joined = " ".join(command)
    for flag in ("--network none", "--read-only", "--cap-drop ALL", "--security-opt no-new-privileges",
                 "--user 65534:65534", "--memory 1536m", "--memory-swap 1536m", "--pids-limit 256",
                 "--pull never", "--log-driver none", "noexec"):
        assert flag in joined
    assert not {"-v", "--volume", "--mount", "--privileged"} & set(command)
    assert command[-3:] == ["image:tag", "export", "script"]
    with pytest.raises(ValueError):
        sandbox.docker_command("job", "sh", [], sandbox.Limits())


class FakeToolchain:
    """Stands in for the container: movies are keys for their classes' source."""

    def __init__(self, compile_imports=True):
        self.movies = {swf.demo_movie(CLASSES): {GREETER: b"hello\n", FAREWELL: b"goodbye\n"}}
        self.compile_imports = compile_imports
        self.imported = []

    def run(self, operation, arguments, files, limits):
        scripts = self.movies[files["movie.swf"]]
        if operation == "export":
            return sandbox.Result(dict(scripts), "Exported script 1/2 demo.AppError\n")
        self.imported.append(sorted(set(files) - {"movie.swf"}))
        output = swf.demo_movie(CLASSES + [("Build", "n", str(len(self.movies)))])
        updates = {path: data for path, data in files.items() if path != "movie.swf"}
        self.movies[output] = {**scripts, **(updates if self.compile_imports else {})}
        return sandbox.Result({"movie.swf": output}, "")


def test_rebuild_compiles_only_changed_classes(monkeypatch):
    fake = FakeToolchain()
    monkeypatch.setattr(sandbox, "run", fake.run)
    movie = swf.demo_movie(CLASSES)
    built = jobs.rebuild(movie, {GREETER: "hello, commons\r\n", FAREWELL: "goodbye\n"})
    assert fake.imported == [[GREETER]]
    assert (built.compiled, built.unchanged) == ([GREETER], [FAREWELL])
    assert fake.movies[built.movie][GREETER] == b"hello, commons\n"
    untouched = jobs.rebuild(movie, {FAREWELL: "goodbye\r\n"})
    assert untouched.movie == movie and untouched.compiled == [] and fake.imported == [[GREETER]]


def test_rebuild_refuses_silent_skips_and_new_classes(monkeypatch):
    fake = FakeToolchain(compile_imports=False)
    monkeypatch.setattr(sandbox, "run", fake.run)
    movie = swf.demo_movie(CLASSES)
    with pytest.raises(jobs.ToolchainError, match="did not compile"):
        jobs.rebuild(movie, {GREETER: "hello, commons\n"})
    with pytest.raises(jobs.ToolchainError, match="not in the movie"):
        jobs.rebuild(movie, {"scripts/demo/New.as": "x"})
    with pytest.raises(ValueError):
        jobs.rebuild(movie, {"scripts/../../etc/x.as": "x"})


def test_log_errors_ignore_progress_lines_naming_error_classes():
    log = "Exported script 4/9 Util.AppError, 00:00.1\nImporting Util/AppError.as\nSEVERE: Scope depth is unbalanced\n"
    assert jobs.problems(log) == ["SEVERE: Scope depth is unbalanced"]


def test_job_inputs_are_bounded_and_https_only():
    base = {"movie_url": "https://storage.example/sign/in", "result_url": "https://storage.example/sign/out"}
    assert jobs.RebuildInput(**base, scripts={GREETER: "x"}).scripts == {GREETER: "x"}
    assert jobs.DecompileInput(movie_url="http://127.0.0.1:9/in", result_url="http://localhost:9/out")
    for bad in ({**base, "movie_url": "http://storage.example/in", "scripts": {GREETER: "x"}},
                {**base, "movie_url": "file:///etc/passwd", "scripts": {GREETER: "x"}},
                {**base, "scripts": {"../x.as": "x"}},
                {**base, "scripts": {"scripts/x.sh": "x"}},
                {**base, "scripts": {GREETER: "x" * (jobs.MAX_SOURCE_BYTES + 1)}},
                {**base, "scripts": {GREETER: "x"}, "command": "sh"}):
        with pytest.raises(ValidationError):
            jobs.RebuildInput(**bad)
    with pytest.raises(ValidationError):
        jobs.DecompileInput(**base, kinds=["script", "exec"])


# --- Real sandbox ------------------------------------------------------------

def _image_ready():
    image = os.environ.get("CC_ARCADE_TOOLCHAIN_IMAGE", sandbox.IMAGE)
    if not shutil.which("docker"):
        return False
    return subprocess.run(["docker", "image", "inspect", image], capture_output=True).returncode == 0


needs_image = pytest.mark.skipif(not _image_ready(), reason="toolchain image not built")


@needs_image
def test_real_toolchain_decompiles_and_rebuilds_one_changed_class():
    movie = swf.demo_movie(CLASSES)
    parts = jobs.decompile(movie)
    assert set(parts) == {GREETER, FAREWELL}
    assert b'return "hello";' in parts[GREETER]
    edited = parts[GREETER].decode().replace('"hello"', '"hello, commons"')
    built = jobs.rebuild(movie, {GREETER: edited, FAREWELL: parts[FAREWELL].decode()})
    assert (built.compiled, built.unchanged) == ([GREETER], [FAREWELL])
    assert built.movie != movie
    again = jobs.decompile(built.movie)
    assert again[GREETER] == edited.encode()
    assert again[FAREWELL] == parts[FAREWELL]


@needs_image
def test_real_toolchain_rejects_a_broken_class_without_output():
    movie = swf.demo_movie(CLASSES)
    with pytest.raises((jobs.ToolchainError, sandbox.SandboxError)):
        jobs.rebuild(movie, {GREETER: "package demo { public class Greeter { function greet( { } }"})


class Storage(BaseHTTPRequestHandler):
    """Signed-URL stand-in: GET /in serves the movie, PUT /out keeps the result."""
    objects = {}

    def do_GET(self):
        body = self.objects[self.path]
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_PUT(self):
        self.objects[self.path] = self.rfile.read(int(self.headers["Content-Length"]))
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args):
        pass


@needs_image
def test_jobs_move_data_only_through_signed_urls():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Storage)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    root = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        Storage.objects = {"/in": swf.demo_movie(CLASSES)}
        out = jobs.run_decompile(jobs.DecompileInput(movie_url=f"{root}/in", result_url=f"{root}/parts"), None)
        with tarfile.open(fileobj=io.BytesIO(Storage.objects["/parts"]), mode="r:gz") as archive:
            greeter = archive.extractfile(GREETER).read().decode()
        assert out.files == 2
        edited = greeter.replace('"hello"', '"hi"')
        rebuilt = jobs.run_rebuild(jobs.RebuildInput(movie_url=f"{root}/in", result_url=f"{root}/movie",
                                                     scripts={GREETER: edited}), None)
        assert rebuilt.compiled == [GREETER]
        assert jobs.decompile(Storage.objects["/movie"])[GREETER] == edited.encode()
    finally:
        server.shutdown()
