"""Registry, authorization and route configuration for the local prototype."""

import hashlib
import json
import re
import sqlite3
import threading
from pathlib import Path

RESERVED = {
    "admin",
    "apps",
    "api",
    "auth",
    "www",
    "mail",
    "smtp",
    "ftp",
    "proxy",
    "status",
    "static",
    "assets",
    "mcp",
    "localhost",
    "default",
}
ROLES = {"viewer": 1, "contributor": 2, "owner": 3}


def slug(value: str) -> str:
    if (
        not re.fullmatch(r"[a-z][a-z0-9-]{0,29}", value)
        or value.endswith("-")
        or "--" in value
        or value in RESERVED
    ):
        raise ValueError(
            "Use 1–30 lowercase letters/digits/hyphens, starting with a letter; platform names and -- are reserved"
        )
    return value


def service_name(value: str) -> str:
    return value if value == "default" else slug(value)


def hostname(app: str, service: str, settings=None) -> str:
    slug(app)
    service_name(service)
    return app + ("" if service == "default" else "--" + service) + "." + (settings.domain if settings else "localhost")


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Store:
    def __init__(self, path: Path):
        self.lock = threading.RLock()
        self._app_locks = {}
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS apps (name TEXT PRIMARY KEY, body TEXT NOT NULL)"
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, body TEXT NOT NULL)"
        )
        self.db.execute("CREATE TABLE IF NOT EXISTS operations (id TEXT PRIMARY KEY, body TEXT NOT NULL)")
        self.db.commit()

    def app_lock(self, name):
        """Serialize changes to one app without blocking registry readers."""
        with self.lock:
            return self._app_locks.setdefault(name, threading.RLock())

    def all(self, table="apps"):
        assert table in {"apps", "jobs", "operations"}
        with self.lock:
            return [
                json.loads(row[0])
                for row in self.db.execute(f"SELECT body FROM {table}")
            ]

    def get(self, name, table="apps"):
        assert table in {"apps", "jobs", "operations"}
        key = "name" if table == "apps" else "id"
        with self.lock:
            row = self.db.execute(
                f"SELECT body FROM {table} WHERE {key}=?", (name,)
            ).fetchone()
            return json.loads(row[0]) if row else None

    def put(self, record, table="apps"):
        assert table in {"apps", "jobs", "operations"}
        key = "name" if table == "apps" else "id"
        with self.lock:
            self.db.execute(
                f"INSERT OR REPLACE INTO {table} VALUES (?,?)",
                (record[key], json.dumps(record)),
            )
            self.db.commit()
    def backup_registry(self, created):
        """Return a consistent, allow-listed registry export without secrets or job data."""
        with self.lock:
            rows = self.db.execute("SELECT body FROM apps ORDER BY name").fetchall()
        apps = []
        for (body,) in rows:
            try:
                record = json.loads(body)
                if "db_password" in record:
                    # Legacy externally managed databases are not covered by workspace backups.
                    continue
                name = slug(record["name"])
                members = {
                    user: role
                    for user, role in record.get("members", {}).items()
                    if isinstance(user, str) and role in ROLES
                }
                owners = [user for user, role in members.items() if role == "owner"]
                routes = {}
                for service, route in record.get("routes", {}).items():
                    service_name(service)
                    port = route.get("port")
                    if (
                        type(port) is int
                        and 1024 <= port <= 65535
                        and type(route.get("public")) is bool
                        and type(route.get("viewers", False)) is bool
                    ):
                        routes[service] = {
                            "port": port,
                            "public": route["public"],
                            "viewers": route.get("viewers", False),
                        }
                apps.append(
                    {
                        "name": name,
                        "owner": owners[0] if len(owners) == 1 else None,
                        "members": members,
                        "routes": routes,
                    }
                )
            except (KeyError, TypeError, ValueError, AttributeError):
                continue
        return {"format": "apps-registry-v1", "created": created, "apps": apps}


def role_for(record, identity):
    if identity.startswith("app:"):
        return "contributor" if identity == "app:" + record["name"] else None
    return record["members"].get(identity)


def allowed(record, identity, required="viewer"):
    return ROLES.get(role_for(record, identity), 0) >= ROLES[required]


# App containers reach the manager only to publish their own ports. Every other
# manager path stays off this listener, which other containers on the proxy's
# networks can also reach.
CAPABILITY_ROUTE = [
    " @capability {",
    "  method PUT DELETE",
    "  path_regexp ^/api-control/api/apps/[a-z0-9-]+/routes/[a-z0-9-]+$",
    " }",
    " handle @capability {",
    "  uri strip_prefix /api-control",
    "  reverse_proxy manager:9000",
    " }",
]


def proxy_config(records, settings=None):
    if settings and settings.hosted:
        return hosted_proxy_config(records, settings)
    lines = [
        "{",
        " auto_https off",
        " admin localhost:2019",
        "}",
        "http://admin.localhost {",
        " reverse_proxy manager:9000",
        "}",
    ]
    for record in sorted(records, key=lambda x: x["name"]):
        app = slug(record["name"])
        for name, route in sorted(record["routes"].items()):
            host = hostname(app, name)
            port = int(route["port"])
            if not 1024 <= port <= 65535:
                raise ValueError("Port must be between 1024 and 65535")
            lines.extend(
                [
                    f"http://{host} {{",
                    " route {",
                    "  forward_auth manager:9000 {",
                    f"   uri /authorize/{app}/{name}",
                    "   header_up -Upgrade",
                    "   header_up -Connection",
                    "  }",
                    f"  reverse_proxy cc-apps-local-{app}:{port} {{",
                    "   header_up -Authorization",
                    "   header_up -Proxy-Authorization",
                    "   header_up -X-Forwarded-User",
                    "  }",
                    " }",
                    "}",
                ]
            )
    lines.extend(
        [
            ":80 {",
            *CAPABILITY_ROUTE,
            " handle {",
            '  respond "No published route" 404',
            " }",
            "}",
        ]
    )
    return "\n".join(lines) + "\n"


def hosted_proxy_config(records, settings):
    lines = ['{', ' admin localhost:2019', '}',
             f'{settings.portal} {{', ' reverse_proxy manager:9000', '}']
    for record in sorted(records, key=lambda x: x['name']):
        app = slug(record['name'])
        for name, route in sorted(record['routes'].items()):
            host = hostname(app, name, settings)
            port = int(route['port'])
            if not 1024 <= port <= 65535:
                raise ValueError('Port must be between 1024 and 65535')
            lines.extend([
                f'{host} {{',
                ' route {',
                '  handle /_commons/* {', '   reverse_proxy manager:9000', '  }',
                '  handle {',
                '   request_header -X-Commons-App-Cookie',
                '   forward_auth manager:9000 {',
                f'    uri /authorize/{app}/{name}',
                '    header_up -Upgrade', '    header_up -Connection',
                '    copy_headers X-Commons-App-Cookie>Cookie', '   }',
                f'   reverse_proxy {settings.prefix}{app}:{port} {{',
                '    header_up -X-Commons-App-Cookie',
                '    header_up -Authorization', '    header_up -Proxy-Authorization',
                '    header_up -X-Forwarded-User', '   }', '  }', ' }', '}',
            ])
    lines.extend(['http://proxy {', *CAPABILITY_ROUTE, ' respond 404', '}',
                  ':80 {', ' respond 404', '}'])
    return '\n'.join(lines) + '\n'
