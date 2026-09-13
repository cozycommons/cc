#!/usr/bin/env python3
"""Copy an inventoried set of public Dice assets without overwriting conflicts.

Reads TARGET_SUPABASE_SERVICE_KEY only from the environment. Dry-run by default.
Source originals and every compact variant are retained; no database URLs are
rewritten here. Verify the resulting report before changing row references.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
import os
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

BUCKETS = {"dice-profile-photos", "dice-comment-photos"}

def object_url(origin, bucket, name, public=True):
    if bucket not in BUCKETS or any(x in {"", ".", ".."} for x in name.split("/")):
        raise ValueError("Unsafe asset path")
    return origin + "/storage/v1/object/" + ("public/" if public else "") + bucket + "/" + quote(name, safe="/")

def fetch(url, **kwargs):
    for attempt in range(7):
        try:
            with urlopen(Request(url, **kwargs), timeout=90) as response:
                return response.read()
        except HTTPError as error:
            if error.code not in {429, 502, 503, 504} or attempt == 6:
                raise
            delay = min(30, int(error.headers.get("Retry-After", 2 ** attempt)))
            error.close()
            time.sleep(max(1, delay))

def copy_object(item, source, target, key, apply=False):
    origin = fetch(object_url(source, item["bucket"], item["name"]))
    digest = sha256(origin).hexdigest()
    if len(origin) != int(item["size"]):
        raise ValueError("Source size changed since inventory: " + item["name"])
    destination = object_url(target, item["bucket"], item["name"])
    status = "identical"
    try:
        existing = fetch(destination)
        if sha256(existing).hexdigest() != digest:
            raise ValueError("Destination conflict: " + item["name"])
    except HTTPError as error:
        # Supabase public object reads report missing objects as either 400 or 404.
        body = error.read()
        if error.code not in {400, 404} or not any(x in body.lower() for x in [b"not found", b"not_found"]):
            raise RuntimeError("Destination read failed: HTTP " + str(error.code)) from None
        status = "missing"
        if apply:
            fetch(object_url(target, item["bucket"], item["name"], public=False),
                  method="POST", data=origin,
                  headers={"apikey": key, "Authorization": "Bearer " + key,
                           "Content-Type": item["mimetype"] or "application/octet-stream",
                           "Cache-Control": "max-age=31536000", "x-upsert": "false"})
            if sha256(fetch(destination)).hexdigest() != digest:
                raise ValueError("Uploaded asset verification failed: " + item["name"])
            status = "copied"
    return {"bucket": item["bucket"], "name": item["name"], "bytes": len(origin), "sha256": digest, "status": status}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--target-project", required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    target = "https://" + args.target_project + ".supabase.co"
    if manifest["target"] != target or manifest["source"] == target:
        parser.error("Explicit target does not match manifest, or equals source")
    if urlparse(manifest["source"]).scheme != "https" or not urlparse(manifest["source"]).hostname.endswith(".supabase.co"):
        parser.error("Source must be a Supabase HTTPS origin")
    key = os.environ.get("TARGET_SUPABASE_SERVICE_KEY", "")
    if args.apply and not key:
        parser.error("TARGET_SUPABASE_SERVICE_KEY is required")
    reports = []
    def copy(item):
        return copy_object(item, manifest["source"], target, key, args.apply)
    with ThreadPoolExecutor(max_workers=2) as pool:
        for result in pool.map(copy, manifest["objects"]):
            reports.append(result)
            args.report.write_text(json.dumps(reports, indent=2) + "\n")
            print(f"Verified {len(reports)}/{len(manifest['objects'])} ({result['status']})", flush=True)
    print(json.dumps({"objects": len(reports), "bytes": sum(x["bytes"] for x in reports), "copied": sum(x["status"] == "copied" for x in reports)}))

if __name__ == "__main__":
    main()
