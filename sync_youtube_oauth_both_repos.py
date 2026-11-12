"""Authorize one YouTube OAuth Desktop client and sync identical secrets to two repos.

Download this script to the folder containing your NEW client_secret.json.
Run on your own PC: python sync_youtube_oauth_both_repos.py

This program never prints, uploads to source control, or saves OAuth secrets
outside GitHub's encrypted Actions repository secrets. You must sign into
Google yourself. It updates only the three YouTube OAuth secrets in:
    Nipun33333/REPO-A
    Nipun33333/YTADGENT
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

REPOSITORIES = ("Nipun33333/REPO-A", "Nipun33333/YTADGENT")
ROOT = Path(__file__).resolve().parent
CLIENT_FILE = ROOT / "client_secret.json"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def github(*args: str, secret: str | None = None) -> str:
    executable = shutil.which("gh")
    if not executable:
        raise SystemExit("GitHub CLI not found. Install it and run gh auth login.")
    try:
        result = subprocess.run(
            [executable, *args],
            input=secret,
            text=True,
            capture_output=True,
            timeout=75,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise SystemExit("GitHub CLI could not complete the command.") from None
    if result.returncode != 0:
        # Avoid printing raw CLI stderr, which might include sensitive values.
        raise SystemExit(
            "GitHub command failed. Check gh auth login and Actions secrets "
            "write permission for both repositories."
        )
    return result.stdout.strip()


def main() -> None:
    if not CLIENT_FILE.is_file():
        raise SystemExit(
            "Place client_secret.json from your NEW Google Cloud Desktop OAuth "
            "client beside this script. No GitHub Secrets were changed."
        )
    try:
        payload = json.loads(CLIENT_FILE.read_text(encoding="utf-8"))
        desktop = payload["installed"]
        client_id = desktop["client_id"].strip()
        client_secret = desktop["client_secret"].strip()
        if not client_id or not client_secret:
            raise ValueError("missing field")
    except (OSError, KeyError, TypeError, ValueError):
        raise SystemExit(
            "This is not a valid Desktop OAuth client JSON file. "
            "No GitHub Secrets were changed."
        ) from None

    github("auth", "status", "--hostname", "github.com")
    for repo in REPOSITORIES:
        found = github("repo", "view", repo, "--json", "nameWithOwner", "--jq", ".nameWithOwner")
        if found.lower() != repo.lower():
            raise SystemExit(f"Repository access check failed: {repo}")

    print("Google OAuth consent will open in your browser.")
    print("Select the Google account authorized to upload to your intended YouTube channel.")
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_FILE), SCOPES)
    try:
        creds = flow.run_local_server(
            host="localhost", port=0, prompt="consent",
            access_type="offline", open_browser=True
        )
        if not creds.refresh_token:
            raise RuntimeError("No refresh token returned")
        creds.refresh(Request())
        if not creds.valid or not creds.token:
            raise RuntimeError("Invalid access token")
    except Exception:
        raise SystemExit(
            "Google OAuth refresh validation failed; no GitHub Secrets were changed."
        ) from None

    secrets = (
        ("YOUTUBE_CLIENT_ID", client_id),
        ("YOUTUBE_CLIENT_SECRET", client_secret),
        ("YOUTUBE_REFRESH_TOKEN", creds.refresh_token),
    )
    print("Google OAuth refresh verified. Updating BOTH repositories...")
    completed = []
    for repo in REPOSITORIES:
        for key, val in secrets:
            github("secret", "set", key, "--repo", repo, "--app", "actions", secret=val)
            print(f"Updated {repo}: {key}")
        completed.append(repo)
    print("All three OAuth secrets are now synced in both repositories.")
    print("Run 'Check YouTube OAuth' in REPO-A and in YTADGENT to confirm.")
    print("Do not post client_secret.json or any tokens in chat or GitHub code.")


if __name__ == "__main__":
    main()
