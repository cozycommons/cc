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


def role_for(record, identity):
    if identity.startswith("app:"):
        return "contributor" if identity == "app:" + record["name"] else None
    return record["members"].get(identity)


def allowed(record, identity, required="viewer"):
    return ROLES.get(role_for(record, identity), 0) >= ROLES[required]


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
            " handle_path /api-control/* {",
            "  reverse_proxy manager:9000",
            " }",
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
    lines.extend(['http://proxy {', ' handle_path /api-control/* {',
                  '  reverse_proxy manager:9000', ' }', ' respond 404', '}',
                  ':80 {', ' respond 404', '}'])
    return '\n'.join(lines) + '\n'
