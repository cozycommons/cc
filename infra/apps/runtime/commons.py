#!/usr/bin/env python3
"""Publish this app's ports via its bounded platform capability."""

import argparse
import json
import os
import urllib.request

parser = argparse.ArgumentParser()
commands = parser.add_subparsers(dest="command", required=True)
expose = commands.add_parser("expose")
expose.add_argument("port", type=int)
names = expose.add_mutually_exclusive_group(required=True)
names.add_argument("--default", action="store_true")
names.add_argument("--name")
expose.add_argument("--public", action="store_true")
unexpose = commands.add_parser("unexpose")
unexpose.add_argument("name")
args = parser.parse_args()
name = "default" if getattr(args, "default", False) else args.name
url = (
    os.environ["COMMONS_CONTROL_URL"]
    + "/api/apps/"
    + os.environ["COMMONS_APP"]
    + "/routes/"
    + name
)
payload = (
    json.dumps({"port": args.port, "public": args.public}).encode()
    if args.command == "expose"
    else None
)
request = urllib.request.Request(
    url,
    data=payload,
    method="PUT" if payload else "DELETE",
    headers={
        "Authorization": "Bearer " + os.environ["COMMONS_APP_TOKEN"],
        "Content-Type": "application/json",
    },
)
with urllib.request.urlopen(request, timeout=30) as response:
    print(response.read().decode())
