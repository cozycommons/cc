"""Thin CLI for the local prototype's platform operations."""

import argparse
import json
import base64
import hashlib
from pathlib import Path
from urllib.parse import urlencode

from .client import call, segment


def main():
    parser = argparse.ArgumentParser(prog="commons")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list").add_argument("--details", action="store_true")
    create = commands.add_parser("create")
    create.add_argument("app")
    for name in ["start", "stop", "restart", "recreate", "backups"]:
        commands.add_parser(name).add_argument("app")
    backup = commands.add_parser("backup")
    backup.add_argument("app")
    backup.add_argument("--idempotency-key", required=True)
    grant = commands.add_parser("grant")
    grant.add_argument("app")
    grant.add_argument("user")
    grant.add_argument("role", choices=["viewer", "contributor", "none"])
    expose = commands.add_parser("expose")
    expose.add_argument("app")
    expose.add_argument("port", type=int)
    expose.add_argument("--name", default="default")
    audience = expose.add_mutually_exclusive_group()
    audience.add_argument("--viewers", action="store_true")
    audience.add_argument("--public", action="store_true")
    unexpose = commands.add_parser("unexpose")
    unexpose.add_argument("app")
    unexpose.add_argument("name", default="default", nargs="?")
    execute = commands.add_parser("exec")
    execute.add_argument("app")
    execute.add_argument("shell_command")
    execute.add_argument("--timeout", type=int, default=120)
    execute.add_argument("--idempotency-key")
    job = commands.add_parser("job")
    job.add_argument("app")
    job.add_argument("id")
    job.add_argument("--after", type=int, default=0)
    job.add_argument("--cancel", action="store_true")
    for name in ['upload', 'download']:
        transfer = commands.add_parser(name)
        transfer.add_argument('app')
        transfer.add_argument('source')
        transfer.add_argument('destination')
    restore = commands.add_parser("restore")
    restore.add_argument("app")
    restore.add_argument("id")
    restore.add_argument("--idempotency-key", required=True)
    restore.add_argument("--confirm-replace-data", action="store_true", required=True)
    args = parser.parse_args()
    base = "/api/apps/" + segment(getattr(args, "app", ""))
    if args.command == "list":
        result = call("GET", "/api/apps?details=true" if args.details else "/api/apps")
    elif args.command == "create":
        result = call("POST", "/api/apps", {"name": args.app})
    elif args.command in {"start", "stop", "restart", "recreate"}:
        result = call("POST", base + "/lifecycle/" + args.command)
    elif args.command == "grant":
        result = call(
            "PUT", base + "/members/" + segment(args.user), {"role": args.role}
        )
    elif args.command == "expose":
        result = call(
            "PUT",
            base + "/routes/" + segment(args.name),
            {"port": args.port, "public": args.public, "viewers": args.viewers},
        )
    elif args.command == "unexpose":
        result = call("DELETE", base + "/routes/" + segment(args.name))
    elif args.command == "exec":
        result = call(
            "POST",
            base + "/exec",
            {"command": args.shell_command, "timeout": args.timeout, "idempotency_key": args.idempotency_key},
        )
    elif args.command == "job":
        path = base + "/jobs/" + segment(args.id)
        if args.cancel:
            call('POST', path + '/cancel')
        result = call("GET", path + '?after=' + str(args.after))
    elif args.command in {'upload', 'download'}:
        if args.command == 'upload':
            source = Path(args.source)
            if source.stat().st_size > 16 * 1024 * 1024:
                parser.error('Transfer exceeds 16 MiB; split using shell')
            content = source.read_bytes()
            path = base + '/transfer?' + urlencode({'path': args.destination, 'sha256': hashlib.sha256(content).hexdigest()})
            result = call('PUT', path, content=content)
        else:
            result = call('GET', base + '/transfer?' + urlencode({'path': args.source}))
            content = base64.b64decode(result.pop('content_base64'))
            Path(args.destination).write_bytes(content)
    elif args.command == "backups":
        result = call("GET", base + "/backups")
    elif args.command == "backup":
        result = call("POST", base + "/backups", {"idempotency_key": args.idempotency_key})
    else:
        result = call(
            "POST",
            base + "/backups/" + segment(args.id) + "/restore",
            {"confirm_replace_data": True, "idempotency_key": args.idempotency_key},
        )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
