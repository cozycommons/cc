"""Only the trusted manager can access Docker; app storage stays in its workspace."""

import json
import hashlib
import io
import tarfile
import uuid
import codecs

import docker

from .settings import Settings
from .tool_helpers import TRANSFER_LIMIT

PREFIX = "cc-apps-local-"
IMAGE = "cc-apps-runtime:local"


class Runtime:
    def __init__(self):
        settings = Settings.load()
        self.prefix, self.image = settings.prefix, settings.image
        self.client = docker.from_env()

    def container(self, name):
        return self.client.containers.get(self.prefix + name)

    def status(self, name):
        try:
            container = self.container(name)
            return "running" if container.status == "running" else "stopped"
        except docker.errors.NotFound:
            return "missing"

    def create(self, record, token):
        name = record["name"]
        network = self.client.networks.create(
            self.prefix + name, driver="bridge", labels={"cc.apps": name, "cc.apps.instance": self.prefix}
        )
        network.connect(self.prefix + "proxy", aliases=["proxy"])
        self.client.volumes.create(
            self.prefix + name + "-workspace", labels={"cc.apps": name, "cc.apps.instance": self.prefix}
        )
        self.create_container(record, token)
        initialized = self.container(name).exec_run(
            ["python", "/opt/initialize_repo.py"]
        )
        if initialized.exit_code:
            raise RuntimeError(
                "Could not initialize app repository: "
                + initialized.output.decode()[-1000:]
            )

    def create_container(self, record, token):
        name = record["name"]
        self.client.containers.run(
            self.image,
            name=self.prefix + name,
            detach=True,
            network=self.prefix + name,
            hostname=name,
            init=True,
            mem_limit="512m",
            nano_cpus=1_000_000_000,
            pids_limit=256,
            restart_policy={"Name": "unless-stopped"},
            security_opt=["no-new-privileges:true"],
            cap_drop=["NET_RAW"],
            volumes={
                self.prefix + name + "-workspace": {"bind": "/workspace", "mode": "rw"}
            },
            environment={
                "COMMONS_APP": name,
                "COMMONS_APP_TOKEN": token,
                "COMMONS_CONTROL_URL": "http://proxy/api-control",
            },
            labels={"cc.apps": name, "cc.apps.instance": self.prefix},
        )

    def reload_proxy(self):
        result = self.client.containers.get(self.prefix + "proxy").exec_run(
            [
                "caddy",
                "reload",
                "--config",
                "/proxy/Caddyfile",
                "--adapter",
                "caddyfile",
            ]
        )
        if result.exit_code:
            raise RuntimeError(
                "Proxy configuration rejected: " + result.output.decode()[-2000:]
            )

    def run(self, name, command, seconds, on_output, job_id=None):
        execution = self.client.api.exec_create(
            self.container(name).id,
            ["python", "-c", JOB_SCRIPT, job_id or uuid.uuid4().hex, str(seconds), command],
            workdir="/workspace",
        )
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        for chunk in self.client.api.exec_start(execution["Id"], stream=True):
            on_output(decoder.decode(chunk))
        on_output(decoder.decode(b"", final=True))
        return self.client.api.exec_inspect(execution["Id"])["ExitCode"]

    def cancel(self, name, job_id):
        # The marker also handles cancellation before the exec begins.
        result = self.container(name).exec_run([
            "python", "-c", "import pathlib,sys; pathlib.Path('/tmp/cc-job-'+sys.argv[1]+'.cancel').touch()", job_id])
        if result.exit_code:
            raise RuntimeError("Could not signal command cancellation")

    def inspect(self, name):
        try:
            container = self.container(name)
            container.reload()
            attrs = container.attrs
        except docker.errors.NotFound:
            return {"state": "missing", "usage": None, "diagnostic": "Container is missing"}
        state, host = attrs.get("State", {}), attrs.get("HostConfig", {})
        result = {
            "state": state.get("Status"), "exit_code": state.get("ExitCode"),
            "oom_killed": state.get("OOMKilled"), "started_at": state.get("StartedAt"),
            "finished_at": state.get("FinishedAt"), "restart_count": attrs.get("RestartCount"),
            "limits": {"cpu_cores": (host.get("NanoCpus") or 0) / 1e9 or None,
                       "memory_bytes": host.get("Memory") or None,
                       "pids": host.get("PidsLimit") or None},
            "usage": None, "diagnostic": None,
        }
        if state.get("Running"):
            try:
                stats = container.stats(stream=False)
                cpu, previous = stats.get("cpu_stats", {}), stats.get("precpu_stats", {})
                delta = cpu.get("cpu_usage", {}).get("total_usage", 0) - previous.get("cpu_usage", {}).get("total_usage", 0)
                system = cpu.get("system_cpu_usage", 0) - previous.get("system_cpu_usage", 0)
                result["usage"] = {"memory_bytes": stats.get("memory_stats", {}).get("usage"),
                    "pids": stats.get("pids_stats", {}).get("current"),
                    "cpu_percent": delta / system * cpu.get("online_cpus", 1) * 100 if system > 0 and delta >= 0 else None}
            except docker.errors.DockerException:
                result["diagnostic"] = "Usage sample unavailable"
        else:
            result["diagnostic"] = "Usage requires a running container"
        return result

    def transfer(self, name, path, content=None):
        if not path.startswith("/workspace/") or "\x00" in path:
            raise ValueError("Transfer requires an absolute /workspace/ file path")
        container = self.container(name)
        temporary = "cc-transfer-" + uuid.uuid4().hex
        if content is not None:
            if len(content) > TRANSFER_LIMIT:
                raise ValueError("Transfer exceeds 16 MiB; split the file using shell")
            archive = io.BytesIO()
            with tarfile.open(fileobj=archive, mode="w") as tar:
                info = tarfile.TarInfo(temporary)
                info.size, info.mode = len(content), 0o600
                tar.addfile(info, io.BytesIO(content))
            if not container.put_archive("/tmp", archive.getvalue()):
                raise RuntimeError("Upload staging failed")
        payload = json.dumps({"path": path, "temporary": temporary if content is not None else None,
                              "limit": TRANSFER_LIMIT})
        result = container.exec_run(["python", "-c", FILE_SCRIPT, payload])
        if result.exit_code:
            raise ValueError("Transfer failed: path must be a regular file inside /workspace, within 16 MiB")
        metadata = json.loads(result.output)
        if content is not None:
            return metadata
        chunks, _ = container.get_archive(metadata["path"])
        data = bytearray()
        for chunk in chunks:
            data.extend(chunk)
            if len(data) > TRANSFER_LIMIT + 1024 * 1024:
                raise ValueError("Download archive exceeds transfer limit")
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            members = tar.getmembers()
            if len(members) != 1 or not members[0].isfile() or members[0].size > TRANSFER_LIMIT:
                raise ValueError("Download requires one regular file within 16 MiB")
            content = tar.extractfile(members[0]).read(TRANSFER_LIMIT + 1)
        return {"content": content, "size_bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}

    def file(self, name, path, content=None):
        # Python runs inside the app; a symlink can only resolve within that container.
        if not path.startswith("/workspace/") or "\x00" in path:
            raise ValueError("File tools require an absolute /workspace/ path")
        script = """import json,pathlib,sys
x=json.loads(sys.argv[1]); p=pathlib.Path(x['path']).resolve()
if not p.is_relative_to('/workspace'): raise ValueError('Path escapes workspace')
if x['content'] is None:
 if p.stat().st_size>65536: raise ValueError('File exceeds 64 KiB; use shell for larger files')
 print(p.read_text(),end='')
else:
 p.parent.mkdir(parents=True,exist_ok=True); p.write_text(x['content'])
"""
        payload = json.dumps({"path": path, "content": content})
        if len(payload.encode()) > 100_000:
            raise ValueError("File payload too large")
        result = self.container(name).exec_run(["python", "-c", script, payload])
        if result.exit_code:
            raise ValueError(result.output.decode()[-1000:])
        return result.output.decode()

    def archive(self, name, backup_id, restore=False):
        command = (
            "python /opt/restore_workspace.py /backup/workspace.tgz"
            if restore
            else f"tar czf /state/backups/{backup_id}/workspace.tgz -C /workspace ."
        )
        volumes = {
            self.prefix + name + "-workspace": {
                "bind": "/workspace",
                "mode": "rw" if restore else "ro",
            }
        }
        if restore:
            # Mount platform state read-only; helper is never available to app commands.
            volumes[self.prefix + "state"] = {"bind": "/state", "mode": "ro"}
            command = command.replace(
                "/backup/workspace.tgz", f"/state/backups/{backup_id}/workspace.tgz"
            )
        else:
            volumes[self.prefix + "state"] = {"bind": "/state", "mode": "rw"}
        self.client.containers.run(
            self.image,
            ["bash", "-ec", command],
            entrypoint="",
            remove=True,
            network_mode="none",
            volumes=volumes,
            mem_limit="256m",
            pids_limit=64,
        )



# Runs only inside the Linux app container; no host process or filesystem access.
JOB_SCRIPT = r"""
import os, pathlib, signal, subprocess, sys, time
job, seconds, command = sys.argv[1:]
marker = pathlib.Path('/tmp/cc-job-' + job + '.cancel')
if marker.exists():
    marker.unlink()
    sys.exit(130)
process = subprocess.Popen(['bash', '-lc', command], start_new_session=True)
deadline = time.monotonic() + int(seconds)
reason = None
while process.poll() is None:
    if marker.exists(): reason = 130; break
    if time.monotonic() >= deadline: reason = 124; break
    time.sleep(.05)
def kill_group(sig):
    try: os.killpg(process.pid, sig)
    except ProcessLookupError: pass
kill_group(signal.SIGTERM)
if reason is not None:
    try: process.wait(timeout=5)
    except subprocess.TimeoutExpired: pass
kill_group(signal.SIGKILL)
process.wait()
marker.unlink(missing_ok=True)
sys.exit(reason if reason is not None else process.returncode)
"""

FILE_SCRIPT = r"""
import hashlib, json, os, pathlib, sys, tempfile
x = json.loads(sys.argv[1])
staged = pathlib.Path('/tmp') / x['temporary'] if x['temporary'] else None
target = None
try:
    p = pathlib.Path(x['path']).resolve()
    if not p.is_relative_to('/workspace') or p == pathlib.Path('/workspace'):
        raise ValueError('Outside workspace')
    if staged:
        content = staged.read_bytes()
        if len(content) > x['limit']: raise ValueError('Too large')
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, target = tempfile.mkstemp(prefix='.cc-upload-', dir=p.parent)
        with os.fdopen(fd, 'wb') as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.replace(target, p)
        print(json.dumps({'path': x['path'], 'size_bytes': len(content), 'sha256': hashlib.sha256(content).hexdigest()}))
    else:
        if not p.is_file() or p.stat().st_size > x['limit']: raise ValueError('Not a bounded regular file')
        print(json.dumps({'path': str(p)}))
finally:
    if staged: staged.unlink(missing_ok=True)
    if target: pathlib.Path(target).unlink(missing_ok=True)
"""
