#!/usr/bin/env python3
"""One-time OAuth2 setup helper for Gmail API access.

Usage:
    python3 gmail_auth_setup.py --account personal --client-id XXX --client-secret YYY

This opens a browser for Google consent. After authorizing, copy the
redirect URL from the browser's address bar and paste it here. The
refresh token is saved to creds/<account>.json.
"""

import argparse
import json
import os
import sys
import webbrowser
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode

SCOPES = "https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.modify"
REDIRECT_URI = "http://localhost"


def exchange_code_for_tokens(client_id: str, client_secret: str, code: str) -> dict:
    """Exchange authorization code for access + refresh tokens."""
    import requests

    resp = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI,
    }, timeout=15)
    resp.raise_for_status()
    return resp.json()


def main():
    parser = argparse.ArgumentParser(description="Set up OAuth2 for a Gmail account")
    parser.add_argument("--account", required=True, help="Account key (e.g. personal, work)")
    parser.add_argument("--client-id", required=True, help="Google OAuth2 client ID")
    parser.add_argument("--client-secret", required=True, help="Google OAuth2 client secret")
    args = parser.parse_args()

    # Build auth URL
    params = {
        "client_id": args.client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",
        "prompt": "consent",
    }
    auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params, quote_via=quote)}"

    print(f"Opening browser for Google authorization (account: {args.account})...")
    print(f"If the browser doesn't open, visit:\n\n{auth_url}\n")
    webbrowser.open(auth_url)

    print("After authorizing, Google will redirect to a localhost URL that won't load.")
    print("Copy the FULL URL from your browser's address bar and paste it below.\n")
    redirect_url = input("Paste the redirect URL here: ").strip()

    # Extract code from the redirect URL
    if "?" not in redirect_url:
        print("ERROR: No query parameters found in the URL. Make sure you copied the full URL.")
        sys.exit(1)

    query = redirect_url.split("?", 1)[-1]
    parsed = parse_qs(query)

    if "code" not in parsed:
        print(f"ERROR: No authorization code found in URL. Error: {parsed.get('error', ['unknown'])}")
        sys.exit(1)

    auth_code = parsed["code"][0]

    # Exchange code for tokens
    try:
        tokens = exchange_code_for_tokens(args.client_id, args.client_secret, auth_code)
    except Exception as e:
        print(f"ERROR: Token exchange failed: {e}")
        sys.exit(1)

    if "refresh_token" not in tokens:
        print("ERROR: No refresh token received. You may need to re-authorize (prompt=consent forces this).")
        sys.exit(1)

    # Save credentials
    creds_dir = Path("creds")
    creds_dir.mkdir(exist_ok=True)
    creds_path = creds_dir / f"{args.account}.json"
    creds = {
        "client_id": args.client_id,
        "client_secret": args.client_secret,
        "refresh_token": tokens["refresh_token"],
    }
    creds_path.write_text(json.dumps(creds, indent=2))
    os.chmod(creds_path, 0o600)

    print(f"\nCredentials saved to {creds_path}")
    print(f"Refresh token: {tokens['refresh_token'][:20]}...")
    print(f"\nNow add this account to gmail_accounts.json:")
    print(json.dumps({
        "accounts": {
            args.account: {
                "email": "<your-email@gmail.com>",
                "category": args.account,
                "credentials_file": str(creds_path),
            }
        }
    }, indent=2))


if __name__ == "__main__":
    main()