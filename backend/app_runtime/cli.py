"""Thin CLI for the local prototype's platform operations."""

import argparse
import json

from .client import call, segment


def main():
    parser = argparse.ArgumentParser(prog="commons")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list")
    create = commands.add_parser("create")
    create.add_argument("app")
    for name in ["start", "stop", "restart", "recreate", "backup", "backups"]:
        commands.add_parser(name).add_argument("app")
    grant = commands.add_parser("grant")
    grant.add_argument("app")
    grant.add_argument("user")
    grant.add_argument("role", choices=["viewer", "contributor", "none"])
    expose = commands.add_parser("expose")
    expose.add_argument("app")
    expose.add_argument("port", type=int)
    expose.add_argument("--name", default="default")
    expose.add_argument("--public", action="store_true")
    unexpose = commands.add_parser("unexpose")
    unexpose.add_argument("app")
    unexpose.add_argument("name", default="default", nargs="?")
    execute = commands.add_parser("exec")
    execute.add_argument("app")
    execute.add_argument("shell_command")
    execute.add_argument("--timeout", type=int, default=120)
    job = commands.add_parser("job")
    job.add_argument("app")
    job.add_argument("id")
    restore = commands.add_parser("restore")
    restore.add_argument("app")
    restore.add_argument("id")
    restore.add_argument("--confirm-replace-data", action="store_true", required=True)
    args = parser.parse_args()
    base = "/api/apps/" + segment(getattr(args, "app", ""))
    if args.command == "list":
        result = call("GET", "/api/apps")
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
            {"port": args.port, "public": args.public},
        )
    elif args.command == "unexpose":
        result = call("DELETE", base + "/routes/" + segment(args.name))
    elif args.command == "exec":
        result = call(
            "POST",
            base + "/exec",
            {"command": args.shell_command, "timeout": args.timeout},
        )
    elif args.command == "job":
        result = call("GET", base + "/jobs/" + segment(args.id))
    elif args.command == "backups":
        result = call("GET", base + "/backups")
    elif args.command == "backup":
        result = call("POST", base + "/backups")
    else:
        result = call(
            "POST",
            base + "/backups/" + segment(args.id) + "/restore",
            {"confirm_replace_data": True},
        )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
