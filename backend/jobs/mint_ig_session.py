"""One-time helper: mint an Instagram session for the @beli_eats watcher.

Instagram challenges fresh password logins from hosting IPs (the "check your
email" code step), so the watcher reuses a saved session instead of logging
in with the password on every run.

Run once from your own machine (a trusted, residential IP is best):

    cd backend
    BELI_EATS_IG_USERNAME=<burner> BELI_EATS_IG_PASSWORD=<pw> \\
        python -m jobs.mint_ig_session

(Or enter the username/password interactively when prompted.)

If Instagram emails a verification code, complete it in the Instagram app,
then re-run this script. On success it prints a BELI_EATS_IG_SESSION value —
paste it into the backend's Coolify environment variables and redeploy.
The session stays valid for months; re-mint only if the watcher starts
failing with login errors.
"""

from __future__ import annotations

import base64
import getpass
import os
import sys
import tempfile


def main() -> int:
    try:
        import instaloader
    except ImportError:
        print("error: instaloader is not installed (pip install -r requirements.txt)")
        return 1

    ig_user = os.environ.get("BELI_EATS_IG_USERNAME") or input("IG username: ").strip()
    ig_pass = os.environ.get("BELI_EATS_IG_PASSWORD") or getpass.getpass("IG password: ")
    if not ig_user or not ig_pass:
        print("error: username and password are required")
        return 1

    loader = instaloader.Instaloader(
        quiet=True,
        download_pictures=False,
        download_videos=False,
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=False,
        save_metadata=False,
    )
    try:
        loader.login(ig_user, ig_pass)
    except instaloader.TwoFactorAuthRequiredException:
        code = input("2FA code: ").strip()
        try:
            loader.two_factor_login(code)
        except Exception as e:
            print(f"error: 2FA login failed: {e}")
            return 1
    except Exception as e:
        print(f"error: login failed: {e}")
        if "Checkpoint required" in str(e):
            print(
                "\nInstagram flagged this login as suspicious. To clear it:\n"
                "  1. In your Mac browser, log into the burner account at instagram.com\n"
                "  2. Complete the challenge (\"This was me\" / verify it's you)\n"
                "  3. Re-run this script — the login should go through, and the\n"
                "     saved session means you won't have to do this again."
            )
        else:
            print(
                "If Instagram asked for an email verification code, complete it in "
                "the Instagram app (or the account's email), then re-run this script."
            )
        return 1

    with tempfile.NamedTemporaryFile(
        prefix="ig_session_", suffix=".session", delete=False
    ) as f:
        session_path = f.name
    loader.save_session_to_file(session_path)
    with open(session_path, "rb") as f:
        session_b64 = base64.b64encode(f.read()).decode()
    os.unlink(session_path)

    print("\nLogin OK. Paste this into Coolify as the BELI_EATS_IG_SESSION")
    print("environment variable on the backend app, then redeploy:\n")
    print(f"BELI_EATS_IG_SESSION={session_b64}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
