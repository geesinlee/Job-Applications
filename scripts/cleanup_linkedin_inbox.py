#!/usr/bin/env python3
"""One-time script to trash non-job-alert LinkedIn emails from geesin@gmail.com.

Trashes all emails from:linkedin EXCEPT from:jobalerts-noreply@linkedin.com
and from:jobs-noreply@linkedin.com (which are already handled by job_digest.py).

Uses Gmail API batch endpoint for speed (up to 100 per batch).
"""

import sys
import time
import os

# Load env from .env if available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from gmail_auth import GmailAccountManager
import requests


def batch_trash_emails(token: str, message_ids: list[str]) -> tuple[int, int]:
    """Trash emails using Gmail batch endpoint. Returns (trashed, failed)."""
    if not message_ids:
        return 0, 0

    # Gmail batch modify endpoint — add TRASH label, remove INBOX label
    url = "https://gmail.googleapis.com/gmail/v1/users/me/messages/batchModify"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "ids": message_ids,
        "addLabelIds": ["TRASH"],
        "removeLabelIds": ["INBOX"],
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        if resp.status_code == 204:
            return len(message_ids), 0
        else:
            print(f"  Batch modify failed: {resp.status_code} {resp.text[:200]}")
            return 0, len(message_ids)
    except Exception as e:
        print(f"  Batch modify error: {e}")
        return 0, len(message_ids)


def collect_all_message_ids(token: str, query: str) -> list[str]:
    """Collect all message IDs matching a query with pagination."""
    url = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
    headers = {"Authorization": f"Bearer {token}"}
    all_ids = []
    page_token = None

    while True:
        params = {"q": query, "maxResults": 500}
        if page_token:
            params["pageToken"] = page_token

        resp = requests.get(url, headers=headers, params=params, timeout=30)
        if resp.status_code != 200:
            print(f"ERROR: Gmail list query failed: {resp.status_code}")
            break

        data = resp.json()
        msgs = data.get("messages", [])
        all_ids.extend(m["id"] for m in msgs)

        page_token = data.get("nextPageToken")
        if not page_token:
            break

        print(f"  Collected {len(all_ids)} IDs so far...")

    return all_ids


def main():
    dry_run = "--dry-run" in sys.argv
    batch_size = 100  # Gmail batch modify limit

    mgr = GmailAccountManager("gmail_accounts.json")
    token = mgr.get_access_token("geesin")

    # Query for non-job-alert LinkedIn emails
    query = "from:linkedin in:inbox -from:jobalerts-noreply@linkedin.com -from:jobs-noreply@linkedin.com"

    print(f"Collecting message IDs for: {query}")
    message_ids = collect_all_message_ids(token, query)
    print(f"Total non-job-alert LinkedIn emails to process: {len(message_ids)}")

    if dry_run:
        print("DRY RUN — no emails will be trashed.")
        return

    if not message_ids:
        print("No emails to trash. Inbox is clean!")
        return

    total_trashed = 0
    total_failed = 0

    for i in range(0, len(message_ids), batch_size):
        batch = message_ids[i : i + batch_size]
        trashed, failed = batch_trash_emails(token, batch)
        total_trashed += trashed
        total_failed += failed

        if (i + batch_size) % 500 == 0 or i + batch_size >= len(message_ids):
            print(f"  Progress: {min(i + batch_size, len(message_ids))}/{len(message_ids)} — trashed={total_trashed}, failed={total_failed}")

        # Rate limit: pause every 10 batches (1000 emails)
        if (i // batch_size + 1) % 10 == 0:
            time.sleep(1)

    print(f"\nDone: trashed={total_trashed}, failed={total_failed}")

    # Verify
    remaining = collect_all_message_ids(token, query)
    print(f"Remaining non-job LinkedIn emails in inbox: {len(remaining)}")


if __name__ == "__main__":
    main()