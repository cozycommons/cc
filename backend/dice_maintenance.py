"""One-shot Dice maintenance for a serialized Coolify scheduled task."""
import os
import argparse
from dotenv import load_dotenv
from supabase import create_client
from runtime_policy import initialize_runtime_policy
from jobs.dice_live_rating_repairs import repair_pending_live_ratings
from jobs.dice_rating_rebuild import rebuild_canonical_ratings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rebuild", action="store_true", help="Reconcile canonical ratings before draining repairs")
    args = parser.parse_args()
    policy = initialize_runtime_policy(os.environ, lambda: load_dotenv(".env.local", override=False))
    url = os.environ["SUPABASE_URL"]
    policy.require_safe_supabase_url(url)
    if policy.is_dice_sandbox:
        raise RuntimeError("Scheduled maintenance is disabled in the synthetic sandbox")
    client = create_client(url, os.environ["SUPABASE_SERVICE_KEY"])
    if args.rebuild:
        print("Canonical games reconciled:", rebuild_canonical_ratings(client))
    print("Pending live repairs processed:", repair_pending_live_ratings(client, raise_on_error=True))


if __name__ == "__main__":
    main()
