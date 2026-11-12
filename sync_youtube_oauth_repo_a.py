"""Renew YouTube OAuth and save secrets ONLY in Nipun33333/REPO-A.

Use your private Desktop OAuth client JSON named client_secret.json in the
same local folder as this script. Run on your own PC:
    python sync_youtube_oauth_repo_a.py

No other GitHub repository is read or modified. Never commit or share tokens.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

REPO = "Nipun33333/REPO-A"
CLIENT_FILE = Path(__file__).resolve().parent / "client_secret.json"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def gh(*args: str, secret: str | None = None) -> str:
    cli = shutil.which("gh")
    if not cli:
        raise SystemExit("GitHub CLI is missing. Install gh and run gh auth login.")
    try:
        proc = subprocess.run(
            [cli, *args],
            input=secret,
            text=True,
            capture_output=True,
            timeout=75,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise SystemExit("GitHub CLI command failed or timed out.") from None
    if proc.returncode:
        raise SystemExit(
            "GitHub CLI command failed. Check gh auth login and Actions Secrets "
            "write access to REPO-A. No secret values are printed."
        )
    return proc.stdout.strip()


def main() -> None:
    if not CLIENT_FILE.is_file():
        raise SystemExit("Place client_secret.json next to this script. No secrets were changed.")
    try:
        data = json.loads(CLIENT_FILE.read_text(encoding="utf-8"))
        client = data["installed"]
        client_id = client["client_id"].strip()
        client_secret = client["client_secret"].strip()
        if not client_id or not client_secret:
            raise ValueError("empty credentials")
    except (ValueError, TypeError, KeyError, OSError):
        raise SystemExit("The file is not a valid Desktop OAuth JSON.") from None

    gh("auth", "status", "--hostname", "github.com")
    found = gh("repo", "view", REPO, "--json", "nameWithOwner", "--jq", ".nameWithOwner")
    if found.lower() != REPO.lower():
        raise SystemExit("Repository verification failed. No secrets were changed.")

    print("Opening Google OAuth for YouTube. Choose the intended channel owner account.")
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_FILE), SCOPES)
    try:
        creds = flow.run_local_server(
            host="localhost", port=0, prompt="consent",
            access_type="offline", open_browser=True,
        )
        if not creds.refresh_token:
            raise ValueError("Missing refresh token")
        creds.refresh(Request())
        if not creds.valid or not creds.token:
            raise ValueError("Invalid access token")
    except Exception:
        raise SystemExit("Google OAuth validation failed. No secrets were changed.") from None

    for name, secret in (
        ("YOUTUBE_CLIENT_ID", client_id),
        ("YOUTUBE_CLIENT_SECRET", client_secret),
        ("YOUTUBE_REFRESH_TOKEN", creds.refresh_token),
    ):
        gh("secret", "set", name, "--repo", REPO, "--app", "actions", secret=secret)
        print(f"Updated REPO-A: {name}")
    print("REPO-A OAuth secrets updated. No other repository was modified.")
    print("Test with Actions > Check YouTube OAuth > Run workflow.")


if __name__ == "__main__":
    main()
