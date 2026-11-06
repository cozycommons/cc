"""Only the trusted manager can access Docker; app storage stays in its workspace."""

import json

import docker

PREFIX = "cc-apps-local-"
IMAGE = "cc-apps-runtime:local"


class Runtime:
    def __init__(self):
        self.client = docker.from_env()

    def container(self, name):
        return self.client.containers.get(PREFIX + name)

    def status(self, name):
        try:
            container = self.container(name)
            return "running" if container.status == "running" else "stopped"
        except docker.errors.NotFound:
            return "missing"

    def create(self, record, token):
        name = record["name"]
        network = self.client.networks.create(
            PREFIX + name, driver="bridge", labels={"cc.apps": name}
        )
        network.connect(PREFIX + "proxy", aliases=["proxy"])
        self.client.volumes.create(
            PREFIX + name + "-workspace", labels={"cc.apps": name}
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
            IMAGE,
            name=PREFIX + name,
            detach=True,
            network=PREFIX + name,
            hostname=name,
            init=True,
            mem_limit="512m",
            nano_cpus=1_000_000_000,
            pids_limit=256,
            restart_policy={"Name": "unless-stopped"},
            security_opt=["no-new-privileges:true"],
            cap_drop=["NET_RAW"],
            volumes={
                PREFIX + name + "-workspace": {"bind": "/workspace", "mode": "rw"}
            },
            environment={
                "COMMONS_APP": name,
                "COMMONS_APP_TOKEN": token,
                "COMMONS_CONTROL_URL": "http://proxy/api-control",
            },
            labels={"cc.apps": name},
        )

    def reload_proxy(self):
        result = self.client.containers.get(PREFIX + "proxy").exec_run(
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

    def run(self, name, command, seconds, on_output):
        container = self.container(name)
        execution = self.client.api.exec_create(
            container.id,
            [
                "timeout",
                "--signal=TERM",
                "--kill-after=5s",
                str(seconds),
                "bash",
                "-lc",
                command,
            ],
            workdir="/workspace",
        )
        for chunk in self.client.api.exec_start(execution["Id"], stream=True):
            on_output(chunk.decode(errors="replace"))
        return self.client.api.exec_inspect(execution["Id"])["ExitCode"]

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
            "find /workspace -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +; tar xzf /backup/workspace.tgz -C /workspace"
            if restore
            else f"tar czf /state/backups/{backup_id}/workspace.tgz -C /workspace ."
        )
        volumes = {
            PREFIX + name + "-workspace": {
                "bind": "/workspace",
                "mode": "rw" if restore else "ro",
            }
        }
        if restore:
            # Mount platform state read-only; helper is never available to app commands.
            volumes[PREFIX + "state"] = {"bind": "/state", "mode": "ro"}
            command = command.replace(
                "/backup/workspace.tgz", f"/state/backups/{backup_id}/workspace.tgz"
            )
        else:
            volumes[PREFIX + "state"] = {"bind": "/state", "mode": "rw"}
        self.client.containers.run(
            IMAGE,
            ["bash", "-ec", command],
            entrypoint="",
            remove=True,
            network_mode="none",
            volumes=volumes,
            mem_limit="256m",
            pids_limit=64,
        )
