"""Scheduled job: run the @beli_eats auto-bookmark watcher for every opted-in account.

Run daily (e.g. a Coolify cron job):
    cd backend && python -m jobs.beli_eats_watch

Requires SUPABASE_URL / SUPABASE_SERVICE_KEY and BELI_CREDENTIALS_KEY.
Instagram access is best-effort (see beli.eats_watcher); when IG is
unreachable the job exits quietly with no changes.
"""

from __future__ import annotations

import logging
import os
import sys

from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from supabase import create_client  # noqa: E402

from beli import accounts  # noqa: E402
from beli.eats_watcher import (  # noqa: E402
    BeliEatsUnavailable,
    fetch_beli_eats_posts,
    format_digest,
    scan_account_for_posts,
)

logger = logging.getLogger(__name__)


def main() -> int:
    load_dotenv(dotenv_path=".env.local", override=True)
    supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])

    try:
        posts = fetch_beli_eats_posts()
    except BeliEatsUnavailable as e:
        print(f"Beli Eats watch: {e}. No changes made.")
        return 0

    res = (
        supabase.table("beli_accounts")
        .select("id,label,beli_id_enc,password_enc,token_hash,watcher_opt_in,last_eats_scan")
        .eq("watcher_opt_in", True)
        .execute()
    )
    rows = res.data or []
    if not rows:
        print("Beli Eats watch: no opted-in accounts. Nothing to do.")
        return 0

    for row in rows:
        try:
            account = {
                "id": row["id"],
                "label": row.get("label"),
                "beli_id": accounts.decrypt_secret(row["beli_id_enc"]),
                "password": accounts.decrypt_secret(row["password_enc"]),
            }
        except accounts.AccountError as e:
            print(f"Beli Eats watch ({row.get('label')}): {e}. Skipped.")
            continue
        digest = scan_account_for_posts({**account, "last_eats_scan": row.get("last_eats_scan")}, posts)
        print(format_digest(digest))
        if digest["newest_ts"]:
            supabase.table("beli_accounts").update(
                {"last_eats_scan": digest["newest_ts"]}
            ).eq("id", row["id"]).execute()
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(main())
