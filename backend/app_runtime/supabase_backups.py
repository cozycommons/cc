"""Optional, manager-only backups to Supabase Storage's S3-compatible API."""

import hashlib
import json
import logging
import math
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import httpx

from .core import slug

log = logging.getLogger(__name__)

MIB = 1024 * 1024
DEFAULT_CHUNK_SIZE = 32 * MIB
MAX_CHUNK_SIZE = 40 * MIB
MAX_OBJECT_SIZE = 45 * MIB
DEFAULT_MAX_ARCHIVE_SIZE = 64 * MIB
MAX_ARCHIVE_SIZE = 512 * MIB
MAX_METADATA_SIZE = MIB
MAX_REMOTE_SNAPSHOTS = 20
MAX_REMOTE_PARTS = MAX_ARCHIVE_SIZE // MIB
REMOTE_RETRY = 5 * 60
BACKUP_PREFIX = "apps"
ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")
SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")


class StorageBackupError(RuntimeError):
    """A safe, non-sensitive remote backup error."""


@dataclass(frozen=True)
class StorageBackupSettings:
    url: str
    anon_key: str = field(repr=False)
    email: str = field(repr=False)
    password: str = field(repr=False)
    user_id: str
    bucket: str
    region: str
    chunk_size: int
    max_archive_size: int
    remote_retain: int
    prune_enabled: bool

    @classmethod
    def load(cls, environ=None):
        environ = os.environ if environ is None else environ
        names = {
            "url": "APPS_BACKUP_SUPABASE_URL",
            "anon_key": "APPS_BACKUP_SUPABASE_ANON_KEY",
            "email": "APPS_BACKUP_SUPABASE_EMAIL",
            "password": "APPS_BACKUP_SUPABASE_PASSWORD",
            "user_id": "APPS_BACKUP_SUPABASE_USER_ID",
        }
        values = {key: environ.get(name, "") for key, name in names.items()}
        configured = any(values.values())
        if not configured:
            return None
        if any(not value for value in values.values()):
            raise ValueError("All APPS_BACKUP_SUPABASE_* identity settings are required")
        if not re.fullmatch(r"https://[a-z0-9-]+\.supabase\.co", values["url"]):
            raise ValueError("APPS_BACKUP_SUPABASE_URL must be an exact hosted Supabase origin")
        if not values["anon_key"].startswith("eyJ"):
            raise ValueError("APPS_BACKUP_SUPABASE_ANON_KEY must be the legacy JWT anon key for S3 session auth")
        if "\n" in values["email"] or "\r" in values["email"] or "\n" in values["password"] or "\r" in values["password"]:
            raise ValueError("Supabase backup identity settings must be single-line values")
        try:
            from uuid import UUID

            if str(UUID(values["user_id"])) != values["user_id"]:
                raise ValueError()
        except ValueError:
            raise ValueError("APPS_BACKUP_SUPABASE_USER_ID must be a canonical UUID") from None

        bucket = environ.get("APPS_BACKUP_BUCKET", "cc-apps-backups")
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,61}[a-z0-9]", bucket) or ".." in bucket:
            raise ValueError("APPS_BACKUP_BUCKET must be a valid lowercase bucket name")
        region = environ.get("APPS_BACKUP_REGION", "us-west-2")
        if not re.fullmatch(r"[a-z0-9-]{1,32}", region):
            raise ValueError("APPS_BACKUP_REGION must be a valid region name")
        try:
            chunk_size = int(environ.get("APPS_BACKUP_CHUNK_MB", "32")) * MIB
            max_archive_size = int(environ.get("APPS_BACKUP_MAX_ARCHIVE_MB", "64")) * MIB
            remote_retain = int(environ.get("APPS_BACKUP_REMOTE_RETAIN", "7"))
        except ValueError:
            raise ValueError("Backup chunk size, archive limit and retention must be integers") from None
        if not 1 <= chunk_size <= MAX_CHUNK_SIZE:
            raise ValueError("APPS_BACKUP_CHUNK_MB must be between 1 and 40")
        if not MIB <= max_archive_size <= MAX_ARCHIVE_SIZE:
            raise ValueError("APPS_BACKUP_MAX_ARCHIVE_MB must be between 1 and 512")
        if not 1 <= remote_retain <= 365:
            raise ValueError("APPS_BACKUP_REMOTE_RETAIN must be between 1 and 365")
        prune = environ.get("APPS_BACKUP_PRUNE_ENABLED", "false").lower()
        if prune not in {"true", "false"}:
            raise ValueError("APPS_BACKUP_PRUNE_ENABLED must be true or false")
        return cls(
            values["url"],
            values["anon_key"],
            values["email"],
            values["password"],
            values["user_id"],
            bucket,
            region,
            chunk_size,
            max_archive_size,
            remote_retain,
            prune == "true",
        )

    @property
    def project_ref(self):
        return urlparse(self.url).hostname.split(".", 1)[0]

    @property
    def s3_endpoint(self):
        return f"https://{self.project_ref}.storage.supabase.co/storage/v1/s3"


class SessionAuth:
    """Refresh a short-lived, RLS-scoped user JWT without exposing it to callers."""

    def __init__(self, settings, client=None, clock=time.monotonic):
        self.settings = settings
        self.http = client or httpx.Client(timeout=httpx.Timeout(15))
        self.clock = clock
        self.lock = threading.Lock()
        self.token = None
        self.expires_at = 0

    def access_token(self):
        with self.lock:
            if self.token and self.clock() < self.expires_at:
                return self.token
            try:
                response = self.http.post(
                    self.settings.url + "/auth/v1/token?grant_type=password",
                    headers={"apikey": self.settings.anon_key},
                    json={"email": self.settings.email, "password": self.settings.password},
                )
                if response.status_code != 200:
                    raise StorageBackupError("Supabase backup identity authentication failed")
                data = response.json()
                user = data.get("user") or {}
                token = data.get("access_token")
                expires_in = data.get("expires_in")
                if user.get("id") != self.settings.user_id or not isinstance(token, str) or not token:
                    raise StorageBackupError("Supabase backup identity did not match its configured UUID")
                if not isinstance(expires_in, (int, float)) or expires_in <= 60:
                    raise StorageBackupError("Supabase returned an invalid backup session lifetime")
            except StorageBackupError:
                raise
            except Exception:
                raise StorageBackupError("Supabase backup identity authentication failed") from None
            self.token = token
            self.expires_at = self.clock() + expires_in - 60
            return self.token


class SupabaseStorage:
    def __init__(self, settings, auth=None, s3_factory=None, clock=time.time):
        self.settings = settings
        self.auth = auth or SessionAuth(settings)
        self.s3_factory = s3_factory
        self.clock = clock

    def client(self):
        try:
            if self.s3_factory:
                return self.s3_factory(
                    self.settings.project_ref,
                    self.settings.anon_key,
                    self.auth.access_token(),
                )
            import boto3
            from botocore.config import Config

            return boto3.client(
                "s3",
                endpoint_url=self.settings.s3_endpoint,
                region_name=self.settings.region,
                aws_access_key_id=self.settings.project_ref,
                aws_secret_access_key=self.settings.anon_key,
                aws_session_token=self.auth.access_token(),
                config=Config(
                    signature_version="s3v4",
                    s3={"addressing_style": "path"},
                    retries={"max_attempts": 3, "mode": "standard"},
                    connect_timeout=10,
                    read_timeout=60,
                ),
            )
        except StorageBackupError:
            raise
        except Exception:
            raise StorageBackupError("Could not initialize Supabase Storage client") from None


class RemoteBackups:
    """Copies complete local snapshots and restores only validated remote objects."""

    def __init__(self, storage, state, store, clock=time.time):
        self.storage = storage
        self.settings = storage.settings
        self.root = Path(state) / "backups"
        self.store = store
        self.clock = clock
        self.client_lock = threading.Lock()

    def _client(self):
        with self.client_lock:
            return self.storage.client()

    def _key(self, app, backup_id, suffix):
        return f"{BACKUP_PREFIX}/{slug(app)}/{backup_id}/{suffix}"

    def _call(self, client, method, **kwargs):
        try:
            return getattr(client, method)(**kwargs)
        except StorageBackupError:
            raise
        except Exception:
            # SDK exceptions can include request details; never propagate or log them.
            raise StorageBackupError("Supabase Storage request failed") from None

    def _put_immutable(self, client, key, data, content_type):
        try:
            result = client.get_object(Bucket=self.settings.bucket, Key=key)
        except Exception as exc:
            response = getattr(exc, "response", {})
            error = response.get("Error", {}) if isinstance(response, dict) else {}
            if error.get("Code") not in {"NoSuchKey", "NotFound", "404"}:
                raise StorageBackupError("Supabase Storage request failed") from None
        else:
            try:
                body = result["Body"]
                try:
                    existing = body.read(len(data) + 1)
                finally:
                    close = getattr(body, "close", None)
                    if close:
                        close()
            except Exception:
                raise StorageBackupError("Supabase Storage request failed") from None
            if existing != data:
                raise StorageBackupError("A different immutable remote object already uses this key")
            return

        self._call(
            client,
            "put_object",
            Bucket=self.settings.bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )

    @staticmethod
    def _json_bytes(value):
        return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()

    @staticmethod
    def _read_json(body):
        try:
            return json.loads(body)
        except (TypeError, ValueError):
            raise StorageBackupError("Remote backup metadata is invalid") from None

    def _remote_manifest(self, client, app, backup_id):
        key = self._key(app, backup_id, "manifest.json")
        try:
            result = client.get_object(Bucket=self.settings.bucket, Key=key)
        except Exception as exc:
            response = getattr(exc, "response", {})
            code = response.get("Error", {}).get("Code") if isinstance(response, dict) else None
            if code in {"NoSuchKey", "NotFound", "404"}:
                return None
            raise StorageBackupError("Supabase Storage request failed") from None
        try:
            body = result["Body"]
            try:
                raw = body.read(MAX_METADATA_SIZE + 1)
            finally:
                close = getattr(body, "close", None)
                if close:
                    close()
            if len(raw) > MAX_METADATA_SIZE:
                raise StorageBackupError("Remote backup manifest exceeds its size limit")
            return self._read_json(raw)
        except StorageBackupError:
            raise
        except Exception:
            raise StorageBackupError("Supabase Storage request failed") from None

    def upload(self, folder):
        folder = Path(folder)
        local_manifest = folder / "manifest.json"
        if not local_manifest.is_file() or local_manifest.is_symlink():
            raise StorageBackupError("Local backup manifest is missing")
        with local_manifest.open("rb") as stream:
            local_manifest_bytes = stream.read(MAX_METADATA_SIZE + 1)
        if len(local_manifest_bytes) > MAX_METADATA_SIZE:
            raise StorageBackupError("Local backup manifest exceeds its size limit")
        local = self._read_json(local_manifest_bytes)
        app, backup_id = local.get("app"), local.get("id")
        if not isinstance(app, str) or not ID_PATTERN.fullmatch(str(backup_id)):
            raise StorageBackupError("Local backup identity is invalid")
        slug(app)
        archive = folder / "workspace.tgz"
        registry_path = folder / "registry.json"
        if not archive.is_file() or archive.is_symlink() or not registry_path.is_file() or registry_path.is_symlink():
            raise StorageBackupError("Local snapshot is missing required archive or registry metadata")
        if archive.stat().st_size > self.settings.max_archive_size:
            raise StorageBackupError("Workspace archive exceeds APPS_BACKUP_MAX_ARCHIVE_MB")
        if registry_path.stat().st_size > MAX_METADATA_SIZE:
            raise StorageBackupError("Registry metadata exceeds its size limit")
        with registry_path.open("rb") as stream:
            registry = stream.read(MAX_METADATA_SIZE + 1)
        if not registry or len(registry) > MAX_METADATA_SIZE:
            raise StorageBackupError("Registry metadata exceeds its size limit")
        registry_json = self._read_json(registry)
        if registry_json.get("format") != "apps-registry-v1":
            raise StorageBackupError("Registry metadata format is not supported")

        client = self._client()
        existing = self._remote_manifest(client, app, backup_id)
        archive_hash = hashlib.sha256()
        archive_size = 0
        parts = []
        with archive.open("rb") as stream:
            number = 0
            while True:
                remaining = self.settings.max_archive_size - archive_size
                chunk = stream.read(min(self.settings.chunk_size, remaining + 1))
                if not chunk:
                    break
                archive_size += len(chunk)
                if archive_size > self.settings.max_archive_size:
                    raise StorageBackupError("Workspace archive exceeds APPS_BACKUP_MAX_ARCHIVE_MB")
                if number >= math.ceil(self.settings.max_archive_size / self.settings.chunk_size):
                    raise StorageBackupError("Workspace archive exceeds the configured size limit")
                chunk_hash = hashlib.sha256(chunk).hexdigest()
                archive_hash.update(chunk)
                parts.append({"number": number, "size_bytes": len(chunk), "sha256": chunk_hash})
                if existing is None:
                    self._put_immutable(
                        client,
                        self._key(app, backup_id, f"workspace/{number:06d}.part"),
                        chunk,
                        "application/octet-stream",
                    )
                number += 1
        if not parts:
            raise StorageBackupError("Workspace archive is empty")
        registry_hash = hashlib.sha256(registry).hexdigest()
        remote = {
            "schema_version": 1,
            "id": backup_id,
            "app": app,
            "created": local.get("created"),
            "kind": local.get("kind", "manual"),
            "format": local.get("format"),
            "workspace": {
                "size_bytes": archive_size,
                "sha256": archive_hash.hexdigest(),
                "chunk_size_bytes": self.settings.chunk_size,
                "parts": parts,
            },
            "registry": {"size_bytes": len(registry), "sha256": registry_hash},
        }
        if not self._valid_manifest(remote, app, backup_id):
            raise StorageBackupError("Generated remote backup manifest is invalid")
        if existing is not None:
            if existing != remote:
                raise StorageBackupError("A different immutable remote snapshot already uses this ID")
            return remote

        self._put_immutable(
            client,
            self._key(app, backup_id, "registry.json"),
            registry,
            "application/json",
        )
        # The manifest is the commit marker and is always written last.
        self._put_immutable(
            client,
            self._key(app, backup_id, "manifest.json"),
            self._json_bytes(remote),
            "application/json",
        )
        if self.settings.prune_enabled:
            self.prune(app)
        return remote

    def _valid_manifest(self, manifest, app, backup_id):
        try:
            if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
                return False
            if manifest.get("id") != backup_id or manifest.get("app") != app:
                return False
            if (
                manifest.get("format") != "workspace-v1"
                or not isinstance(manifest.get("created"), (int, float))
                or isinstance(manifest.get("created"), bool)
                or not math.isfinite(manifest["created"])
            ):
                return False
            workspace = manifest["workspace"]
            registry = manifest["registry"]
            size = workspace["size_bytes"]
            chunk_size = workspace["chunk_size_bytes"]
            parts = workspace["parts"]
            if (
                not isinstance(size, int)
                or isinstance(size, bool)
                or size <= 0
                or size > self.settings.max_archive_size
            ):
                return False
            if (
                not isinstance(chunk_size, int)
                or isinstance(chunk_size, bool)
                or not 1 <= chunk_size <= MAX_CHUNK_SIZE
            ):
                return False
            if not SHA256_PATTERN.fullmatch(workspace["sha256"]):
                return False
            if not isinstance(parts, list) or not 1 <= len(parts) <= MAX_REMOTE_PARTS:
                return False
            if len(parts) != math.ceil(size / chunk_size):
                return False
            actual_size = 0
            for expected, part in enumerate(parts):
                if (
                    not isinstance(part.get("number"), int)
                    or isinstance(part["number"], bool)
                    or part["number"] != expected
                ):
                    return False
                if (
                    not isinstance(part.get("size_bytes"), int)
                    or isinstance(part["size_bytes"], bool)
                    or not 1 <= part["size_bytes"] <= chunk_size
                ):
                    return False
                if not SHA256_PATTERN.fullmatch(part.get("sha256", "")):
                    return False
                if expected < len(parts) - 1 and part["size_bytes"] != chunk_size:
                    return False
                actual_size += part["size_bytes"]
            if actual_size != size:
                return False
            if (
                not isinstance(registry.get("size_bytes"), int)
                or isinstance(registry["size_bytes"], bool)
                or not 1 <= registry["size_bytes"] <= MAX_METADATA_SIZE
            ):
                return False
            if registry.get("format", "apps-registry-v1") != "apps-registry-v1":
                return False
            return bool(SHA256_PATTERN.fullmatch(registry.get("sha256", "")))
        except (KeyError, TypeError, AttributeError):
            return False

    def _list_manifests(self, client, app):
        prefix = f"{BACKUP_PREFIX}/{slug(app)}/"
        page = self._call(
            client,
            "list_objects_v2",
            Bucket=self.settings.bucket,
            Prefix=prefix,
            Delimiter="/",
            MaxKeys=MAX_REMOTE_SNAPSHOTS + 1,
        )
        prefixes = page.get("CommonPrefixes", [])
        if page.get("IsTruncated") or len(prefixes) > MAX_REMOTE_SNAPSHOTS:
            raise StorageBackupError("Remote backup inventory exceeds its configured limit")
        found = []
        for item in prefixes:
            key_prefix = item.get("Prefix", "")
            backup_id = key_prefix[len(prefix):].strip("/")
            if not ID_PATTERN.fullmatch(backup_id):
                continue
            manifest = self._remote_manifest(client, app, backup_id)
            if self._valid_manifest(manifest, app, backup_id):
                found.append(manifest)
        return found

    def list(self, app):
        client = self._client()
        return sorted(self._list_manifests(client, app), key=lambda item: (item["created"], item["id"]), reverse=True)

    def prune(self, app):
        if not self.settings.prune_enabled:
            return
        client = self._client()
        snapshots = sorted(
            self._list_manifests(client, app),
            key=lambda item: (item["created"], item["id"]),
            reverse=True,
        )
        for item in snapshots[self.settings.remote_retain:]:
            backup_id = item["id"]
            # Delete the commit marker first so a partial cleanup is never
            # presented as a restorable snapshot.
            self._call(client, "delete_object", Bucket=self.settings.bucket, Key=self._key(app, backup_id, "manifest.json"))
            for part in item["workspace"]["parts"]:
                self._call(client, "delete_object", Bucket=self.settings.bucket,
                           Key=self._key(app, backup_id, f"workspace/{part['number']:06d}.part"))
            self._call(client, "delete_object", Bucket=self.settings.bucket, Key=self._key(app, backup_id, "registry.json"))

    def download(self, app, backup_id, destination):
        slug(app)
        if not ID_PATTERN.fullmatch(backup_id):
            raise StorageBackupError("Remote backup ID is invalid")
        client = self._client()
        manifest = self._remote_manifest(client, app, backup_id)
        if not self._valid_manifest(manifest, app, backup_id):
            raise StorageBackupError("Remote backup is missing or its manifest is invalid")

        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = destination.parent / (".restore-" + uuid.uuid4().hex)
        staging.mkdir(mode=0o700)
        try:
            whole = hashlib.sha256()
            total = 0
            with (staging / "workspace.tgz").open("xb") as output:
                for part in manifest["workspace"]["parts"]:
                    result = self._call(
                        client,
                        "get_object",
                        Bucket=self.settings.bucket,
                        Key=self._key(app, backup_id, f"workspace/{part['number']:06d}.part"),
                    )
                    body = result["Body"]
                    piece_hash = hashlib.sha256()
                    piece_size = 0
                    try:
                        while True:
                            block = body.read(min(1024 * 1024, part["size_bytes"] - piece_size + 1))
                            if not block:
                                break
                            piece_size += len(block)
                            if piece_size > part["size_bytes"]:
                                raise StorageBackupError("Remote workspace chunk exceeds its declared size")
                            piece_hash.update(block)
                            whole.update(block)
                            output.write(block)
                    finally:
                        close = getattr(body, "close", None)
                        if close:
                            close()
                    if piece_size != part["size_bytes"] or piece_hash.hexdigest() != part["sha256"]:
                        raise StorageBackupError("Remote workspace chunk failed checksum verification")
                    total += piece_size
            workspace = manifest["workspace"]
            if total != workspace["size_bytes"] or whole.hexdigest() != workspace["sha256"]:
                raise StorageBackupError("Remote workspace archive failed checksum verification")
            registry_response = self._call(
                client, "get_object", Bucket=self.settings.bucket,
                Key=self._key(app, backup_id, "registry.json"),
            )
            body = registry_response["Body"]
            try:
                registry = body.read(MAX_METADATA_SIZE + 1)
            finally:
                close = getattr(body, "close", None)
                if close:
                    close()
            if (
                len(registry) > MAX_METADATA_SIZE
                or len(registry) != manifest["registry"]["size_bytes"]
                or hashlib.sha256(registry).hexdigest() != manifest["registry"]["sha256"]
            ):
                raise StorageBackupError("Remote registry metadata failed checksum verification")
            registry_json = self._read_json(registry)
            if registry_json.get("format") != "apps-registry-v1":
                raise StorageBackupError("Remote registry metadata format is not supported")
            (staging / "registry.json").write_bytes(registry)
            (staging / "manifest.json").write_bytes(self._json_bytes(manifest))
            (staging / "remote.json").write_text(json.dumps({"status": "complete", "verified_at": self.clock()}))
            if destination.exists() or destination.is_symlink():
                raise StorageBackupError("A local snapshot already occupies the restore destination")
            os.replace(staging, destination)
            return manifest
        except StorageBackupError:
            raise
        except Exception:
            raise StorageBackupError("Remote backup download or staging failed") from None
        finally:
            if staging.exists():
                import shutil

                shutil.rmtree(staging, ignore_errors=True)


class RemoteBackupWorker:
    """Retries offsite copies after the local snapshot has completed."""

    def __init__(self, remote, store, clock=time.time):
        self.remote = remote
        self.store = store
        self.root = remote.root
        self.clock = clock

    @staticmethod
    def _write_state(folder, state):
        temporary = folder / "remote.tmp"
        temporary.write_text(json.dumps(state, sort_keys=True))
        temporary.replace(folder / "remote.json")

    def tick(self):
        if not self.root.exists():
            return
        for folder in sorted(self.root.iterdir()):
            if not folder.is_dir() or folder.is_symlink() or not ID_PATTERN.fullmatch(folder.name):
                continue
            app = None
            attempts = 0
            try:
                local = json.loads((folder / "manifest.json").read_text())
                app = local.get("app")
                if not isinstance(app, str) or local.get("id") != folder.name or local.get("format") != "workspace-v1":
                    continue
                slug(app)
                if not (folder / "registry.json").is_file():
                    continue
                record = self.store.get(app)
                if (
                    not record
                    or record.get("backup_pending")
                    or record.get("status") not in {"running", "stopped"}
                ):
                    continue
                state_path = folder / "remote.json"
                state = json.loads(state_path.read_text()) if state_path.is_file() else {}
                if state.get("status") == "complete":
                    continue
                if state.get("retry_at", 0) > self.clock():
                    continue
                attempts = int(state.get("attempts", 0)) + 1
                self._write_state(folder, {"status": "uploading", "attempts": attempts})
                self.remote.upload(folder)
                self._write_state(folder, {
                    "status": "complete",
                    "attempts": attempts,
                    "completed_at": self.clock(),
                })
            except Exception:
                try:
                    self._write_state(folder, {
                        "status": "error",
                        "attempts": attempts,
                        "retry_at": self.clock() + REMOTE_RETRY,
                        "error": "Off-host backup failed; local snapshot retained and retry scheduled",
                    })
                except Exception:
                    pass
                log.error("Off-host snapshot upload failed for app %s backup %s", app or "unknown", folder.name)

    def run(self, stop):
        while not stop.is_set():
            try:
                self.tick()
            except Exception:
                log.error("Off-host backup worker unavailable; retrying")
            stop.wait(30)
