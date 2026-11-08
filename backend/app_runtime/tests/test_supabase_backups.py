import hashlib
import io
import json

import pytest

from app_runtime.core import Store
from app_runtime.supabase_backups import (
    DEFAULT_MAX_ARCHIVE_SIZE,
    MAX_REMOTE_SNAPSHOTS,
    MAX_OBJECT_SIZE,
    RemoteBackupWorker,
    RemoteBackups,
    SessionAuth,
    StorageBackupError,
    StorageBackupSettings,
)


USER_ID = "12345678-1234-5678-1234-567812345678"
PASSWORD = "synthetic-password-not-a-secret"
ANON_KEY = "eyJsynthetic-anon-key"


def settings(**overrides):
    values = {
        "url": "https://backup-project.supabase.co",
        "anon_key": ANON_KEY,
        "email": "apps-backup@example.test",
        "password": PASSWORD,
        "user_id": USER_ID,
        "bucket": "cc-apps-backups",
        "region": "us-west-2",
        "chunk_size": 4,
        "max_archive_size": DEFAULT_MAX_ARCHIVE_SIZE,
        "remote_retain": 2,
        "prune_enabled": False,
    }
    values.update(overrides)
    return StorageBackupSettings(**values)


class FakeBody(io.BytesIO):
    pass


class MissingObject(Exception):
    response = {"Error": {"Code": "NoSuchKey"}}


class MemoryS3:
    def __init__(self):
        self.objects = {}
        self.puts = []
        self.deletes = []
        self.fail_after_put = None

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise MissingObject()
        return {"Body": FakeBody(self.objects[Key])}

    def put_object(self, Bucket, Key, Body, **kwargs):
        if Key in self.objects:
            raise RuntimeError("RLS INSERT-only policy rejected an overwrite")
        data = Body if isinstance(Body, bytes) else Body.read()
        self.objects[Key] = data
        self.puts.append(Key)
        if Key == self.fail_after_put:
            self.fail_after_put = None
            raise RuntimeError("synthetic ambiguous success")
        return {}

    def list_objects_v2(self, Bucket, Prefix, Delimiter="/", **kwargs):
        prefixes = set()
        for key in self.objects:
            if not key.startswith(Prefix):
                continue
            suffix = key[len(Prefix):]
            if "/" in suffix:
                prefixes.add(Prefix + suffix.split("/", 1)[0] + "/")
        return {"CommonPrefixes": [{"Prefix": value} for value in sorted(prefixes)], "IsTruncated": False}

    def delete_object(self, Bucket, Key):
        self.deletes.append(Key)
        self.objects.pop(Key, None)


class FakeStorage:
    def __init__(self, config, client):
        self.settings = config
        self._fake = client

    def client(self):
        return self._fake


def snapshot(root, app="trip", backup_id="a" * 32, archive=b"abcdefghijk"):
    folder = root / "backups" / backup_id
    folder.mkdir(parents=True)
    (folder / "workspace.tgz").write_bytes(archive)
    registry = {
        "format": "apps-registry-v1",
        "created": 100.0,
        "apps": [{"name": app, "owner": USER_ID, "members": {USER_ID: "owner"}, "routes": {}}],
    }
    (folder / "registry.json").write_text(json.dumps(registry))
    (folder / "manifest.json").write_text(json.dumps({
        "id": backup_id, "app": app, "created": 100.0, "kind": "automatic", "format": "workspace-v1",
    }))
    return folder


def test_storage_settings_are_opt_in_bounded_and_redacted():
    assert StorageBackupSettings.load({}) is None
    with pytest.raises(ValueError, match="All APPS_BACKUP_SUPABASE"):
        StorageBackupSettings.load({"APPS_BACKUP_SUPABASE_URL": "https://backup.supabase.co"})
    config = StorageBackupSettings.load({
        "APPS_BACKUP_SUPABASE_URL": "https://backup-project.supabase.co",
        "APPS_BACKUP_SUPABASE_ANON_KEY": ANON_KEY,
        "APPS_BACKUP_SUPABASE_EMAIL": "apps-backup@example.test",
        "APPS_BACKUP_SUPABASE_PASSWORD": PASSWORD,
        "APPS_BACKUP_SUPABASE_USER_ID": USER_ID,
    })
    assert config.bucket == "cc-apps-backups"
    assert config.chunk_size == 32 * 1024 * 1024
    assert config.max_archive_size == DEFAULT_MAX_ARCHIVE_SIZE
    assert config.remote_retain == 7 and not config.prune_enabled
    assert config.project_ref == "backup-project"
    assert config.s3_endpoint == "https://backup-project.storage.supabase.co/storage/v1/s3"
    assert PASSWORD not in repr(config) and ANON_KEY not in repr(config)
    with pytest.raises(ValueError, match="between 1 and 40"):
        StorageBackupSettings.load({
            "APPS_BACKUP_SUPABASE_URL": "https://backup-project.supabase.co",
            "APPS_BACKUP_SUPABASE_ANON_KEY": ANON_KEY,
            "APPS_BACKUP_SUPABASE_EMAIL": "apps-backup@example.test",
            "APPS_BACKUP_SUPABASE_PASSWORD": PASSWORD,
            "APPS_BACKUP_SUPABASE_USER_ID": USER_ID,
            "APPS_BACKUP_CHUNK_MB": "41",
        })


def test_session_auth_caches_then_reauthenticates_without_logging_password(caplog):
    class Response:
        status_code = 200

        def __init__(self, token):
            self.token = token

        def json(self):
            return {"user": {"id": USER_ID}, "access_token": self.token, "expires_in": 120}

    class Client:
        def __init__(self):
            self.calls = []

        def post(self, url, headers, json):
            self.calls.append((url, headers, json))
            return Response(f"session-{len(self.calls)}")

    now = [0.0]
    http = Client()
    auth = SessionAuth(settings(), client=http, clock=lambda: now[0])
    assert auth.access_token() == "session-1"
    assert auth.access_token() == "session-1"
    now[0] = 61
    assert auth.access_token() == "session-2"
    assert len(http.calls) == 2
    assert PASSWORD == http.calls[0][2]["password"]

    class Rejected:
        status_code = 401

    class RejectedClient:
        def post(self, *args, **kwargs):
            return Rejected()

    with pytest.raises(StorageBackupError, match="authentication failed") as error:
        SessionAuth(settings(), client=RejectedClient()).access_token()
    assert PASSWORD not in str(error.value)
    assert PASSWORD not in caplog.text


def test_upload_chunks_archive_and_writes_manifest_last_then_downloads_verified(tmp_path):
    config = settings()
    client = MemoryS3()
    remote = RemoteBackups(FakeStorage(config, client), tmp_path, Store(tmp_path / "registry.sqlite3"))
    folder = snapshot(tmp_path)

    uploaded = remote.upload(folder)
    assert [key.rsplit("/", 1)[-1] for key in client.puts][-1] == "manifest.json"
    assert len(uploaded["workspace"]["parts"]) == 3
    assert [part["size_bytes"] for part in uploaded["workspace"]["parts"]] == [4, 4, 3]
    assert max(map(len, client.objects.values())) <= MAX_OBJECT_SIZE
    assert remote.list("trip") == [uploaded]

    destination = tmp_path / "backups" / ("b" * 32)
    downloaded = remote.download("trip", "a" * 32, destination)
    assert downloaded == uploaded
    assert (destination / "workspace.tgz").read_bytes() == b"abcdefghijk"
    assert json.loads((destination / "registry.json").read_text())["apps"][0]["owner"] == USER_ID
    assert json.loads((destination / "remote.json").read_text())["status"] == "complete"


def test_retry_is_idempotent_and_different_content_cannot_overwrite_snapshot(tmp_path):
    config = settings()
    client = MemoryS3()
    remote = RemoteBackups(FakeStorage(config, client), tmp_path, Store(tmp_path / "registry.sqlite3"))
    folder = snapshot(tmp_path)
    first = remote.upload(folder)
    put_count = len(client.puts)
    assert remote.upload(folder) == first
    assert len(client.puts) == put_count

    (folder / "workspace.tgz").write_bytes(b"changed")
    with pytest.raises(StorageBackupError, match="immutable remote snapshot"):
        remote.upload(folder)
    assert len(client.puts) == put_count

def test_partial_upload_retry_skips_identical_objects_under_insert_only_policy(tmp_path):
    config = settings()
    client = MemoryS3()
    remote = RemoteBackups(FakeStorage(config, client), tmp_path, Store(tmp_path / "registry.sqlite3"))
    folder = snapshot(tmp_path)
    registry_key = f"apps/trip/{'a' * 32}/registry.json"
    client.fail_after_put = registry_key

    with pytest.raises(StorageBackupError, match="request failed"):
        remote.upload(folder)

    assert registry_key in client.objects
    assert f"apps/trip/{'a' * 32}/manifest.json" not in client.objects
    previous_puts = list(client.puts)
    uploaded = remote.upload(folder)

    assert client.puts == previous_puts + [f"apps/trip/{'a' * 32}/manifest.json"]
    assert remote.list("trip") == [uploaded]


def test_partial_upload_retry_rejects_mismatched_existing_object(tmp_path):
    config = settings()
    client = MemoryS3()
    remote = RemoteBackups(FakeStorage(config, client), tmp_path, Store(tmp_path / "registry.sqlite3"))
    folder = snapshot(tmp_path)
    chunk_key = f"apps/trip/{'a' * 32}/workspace/000000.part"
    client.objects[chunk_key] = b"different"

    with pytest.raises(StorageBackupError, match="different immutable remote object"):
        remote.upload(folder)

    assert chunk_key in client.objects
    assert f"apps/trip/{'a' * 32}/manifest.json" not in client.objects


def test_upload_refuses_archive_over_configured_limit(tmp_path):
    config = settings(max_archive_size=8)
    client = MemoryS3()
    remote = RemoteBackups(FakeStorage(config, client), tmp_path, Store(tmp_path / "registry.sqlite3"))
    folder = snapshot(tmp_path, archive=b"123456789")

    with pytest.raises(StorageBackupError, match="APPS_BACKUP_MAX_ARCHIVE_MB"):
        remote.upload(folder)

    assert not client.objects


def test_manifest_body_errors_are_sanitized(tmp_path):
    class SecretBody:
        def __init__(self, failure):
            self.failure = failure

        def read(self, size):
            if self.failure == "read":
                raise RuntimeError("synthetic-secret-marker from provider body")
            return b"{}"

        def close(self):
            if self.failure == "close":
                raise RuntimeError("synthetic-secret-marker from provider close")

    class BodyClient:
        def __init__(self, failure):
            self.failure = failure

        def get_object(self, **kwargs):
            return {"Body": SecretBody(self.failure)}

    remote = RemoteBackups(
        FakeStorage(settings(), MemoryS3()),
        tmp_path,
        Store(tmp_path / "registry.sqlite3"),
    )
    for failure in ("read", "close"):
        with pytest.raises(StorageBackupError) as error:
            remote._remote_manifest(BodyClient(failure), "trip", "a" * 32)
        assert "synthetic-secret-marker" not in str(error.value)


def test_inventory_stops_at_configured_snapshot_count(tmp_path):
    config = settings()
    remote = RemoteBackups(
        FakeStorage(config, MemoryS3()),
        tmp_path,
        Store(tmp_path / "registry.sqlite3"),
    )

    class OversizedListing:
        def list_objects_v2(self, **kwargs):
            assert kwargs["MaxKeys"] == MAX_REMOTE_SNAPSHOTS + 1
            return {"CommonPrefixes": [], "IsTruncated": True}

    with pytest.raises(StorageBackupError, match="inventory exceeds its configured limit"):
        remote._list_manifests(OversizedListing(), "trip")

def test_download_rejects_manifest_over_archive_ceiling_before_staging(tmp_path):
    config = settings()
    client = MemoryS3()
    remote = RemoteBackups(FakeStorage(config, client), tmp_path, Store(tmp_path / "registry.sqlite3"))
    backup_id = "a" * 32
    manifest = {
        "schema_version": 1,
        "id": backup_id,
        "app": "trip",
        "created": 100,
        "format": "workspace-v1",
        "workspace": {
            "size_bytes": config.max_archive_size + 1,
            "sha256": "a" * 64,
            "chunk_size_bytes": 4,
            "parts": [{"number": 0, "size_bytes": config.max_archive_size + 1, "sha256": "a" * 64}],
        },
        "registry": {"size_bytes": 1, "sha256": "b" * 64},
    }
    client.objects[f"apps/trip/{backup_id}/manifest.json"] = json.dumps(manifest).encode()
    destination = tmp_path / "backups" / backup_id

    with pytest.raises(StorageBackupError, match="manifest is invalid"):
        remote.download("trip", backup_id, destination)

    assert not destination.exists()
    assert not list(destination.parent.glob(".restore-*"))



def test_download_rejects_corrupt_chunks_without_publishing_staged_snapshot(tmp_path):
    config = settings()
    client = MemoryS3()
    remote = RemoteBackups(FakeStorage(config, client), tmp_path, Store(tmp_path / "registry.sqlite3"))
    remote.upload(snapshot(tmp_path))
    key = f"apps/trip/{'a' * 32}/workspace/000000.part"
    client.objects[key] = b"bad!"
    destination = tmp_path / "backups" / ("b" * 32)
    with pytest.raises(StorageBackupError, match="checksum verification"):
        remote.download("trip", "a" * 32, destination)
    assert not destination.exists()
    assert not list(destination.parent.glob(".restore-*"))


def test_registry_export_contains_only_safe_owner_membership_and_routes(tmp_path):
    store = Store(tmp_path / "registry.sqlite3")
    store.put({
        "name": "trip",
        "members": {USER_ID: "owner", "friend": "contributor"},
        "routes": {"default": {"port": 3000, "public": False, "viewers": True}},
        "app_token_hash": "synthetic-hash",
    })
    store.put({
        "name": "legacy",
        "members": {"legacy-owner": "owner"},
        "routes": {},
        "db_password": "legacy-database-secret",
    })
    store.put({"id": "job", "app": "trip", "output": "private shell output"}, "jobs")
    store.put({"id": "operation", "result": {"session_token": "in-memory-only"}}, "operations")

    output = store.backup_registry(123.0)
    encoded = json.dumps(output)
    assert output["format"] == "apps-registry-v1"
    assert [item["name"] for item in output["apps"]] == ["trip"]
    assert output["apps"][0]["owner"] == USER_ID
    assert output["apps"][0]["members"]["friend"] == "contributor"
    assert output["apps"][0]["routes"]["default"]["port"] == 3000
    for forbidden in ["legacy-database-secret", "private shell output", "session_token", "synthetic-hash"]:
        assert forbidden not in encoded


def test_worker_persists_generic_failure_and_retries_without_deleting_local_copy(tmp_path, caplog):
    store = Store(tmp_path / "registry.sqlite3")
    store.put({"name": "trip", "status": "running"})
    folder = snapshot(tmp_path)
    now = [100.0]

    class FailingRemote:
        root = tmp_path / "backups"

        def upload(self, path):
            raise RuntimeError("synthetic credential value must not appear in logs")

    worker = RemoteBackupWorker(FailingRemote(), store, clock=lambda: now[0])
    worker.tick()
    state = json.loads((folder / "remote.json").read_text())
    assert state["status"] == "error"
    assert "credential value" not in state["error"]
    assert folder.joinpath("workspace.tgz").exists()
    assert "credential value" not in caplog.text
    assert "remote.json" in caplog.text or "Off-host snapshot upload failed" in caplog.text

    class WorkingRemote:
        root = tmp_path / "backups"

        def upload(self, path):
            return {}

    worker.remote = WorkingRemote()
    now[0] += 301
    worker.tick()
    assert json.loads((folder / "remote.json").read_text())["status"] == "complete"
