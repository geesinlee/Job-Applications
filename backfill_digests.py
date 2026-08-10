#!/usr/bin/env python3
"""Backfill LinkedIn job discovery digests from historical Gmail emails.

One-time script to fetch ALL LinkedIn job-alert emails, parse them, deduplicate,
pre-filter, and write per-date digest files. Also trashes emails older than a
configurable cutoff date.

Does NOT:
  - Touch .job_digest_last_run (daily cron owns that)
  - Auto-ingest into tracker (user reviews via Claude Desktop)
  - Send summary emails

Supports --dry-run to preview without writing files or trashing emails.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from collections import defaultdict
from pathlib import Path

import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv optional; env vars may be set externally

from gmail_auth import GmailAccountManager
from email_parser import JobCard, parse_linkedin_email
from job_digest import (
    deduplicate_jobs,
    prefilter_jobs,
    load_prefilter_keywords,
    load_tracker,
    write_digest_markdown,
    trash_emails,
    _extract_html_body,
    _get_email_date,
    _log,
    GMAIL_API_BASE,
    DIGEST_DIR,
    TRACKER_PATH,
    REFERENCE_CV_PATH,
    GMAIL_ACCOUNTS_CONFIG,
)

logger = logging.getLogger("backfill_digests")


# ---------------------------------------------------------------------------
# Gmail fetch with pagination
# ---------------------------------------------------------------------------

def fetch_all_linkedin_emails(
    mgr: GmailAccountManager,
    account: str,
    after_date: str,
    before_date: str | None = None,
) -> list[dict]:
    """Fetch ALL LinkedIn job-alert emails from Gmail, paginating through results.

    Args:
        mgr: GmailAccountManager instance.
        account: Gmail account key.
        after_date: ISO date string (e.g. "2026-01-01"). Uses Gmail's after: operator.
                    Note: after:2026/01/01 means "on or after Jan 1".
        before_date: ISO date string (e.g. "2026-08-01"). None means no upper bound.
                     Note: before:2026/08/01 means "before Aug 1" (up to July 31).

    Returns:
        List of {"id": str, "date": str, "html": str | None} dicts.
    """
    token = mgr.get_access_token(account)
    if not token:
        _log("ERROR: Failed to get access token for backfill")
        return []

    headers = {"Authorization": f"Bearer {token}"}

    # Build Gmail query — convert ISO dates to YYYY/MM/DD for Gmail
    # Note: NOT using in:anywhere — we only want emails still in inbox,
    # not ones already trashed. Pre-June emails found here will be trashed
    # by the backfill script.
    after_gmail = after_date.replace("-", "/")
    query = (
        f"(from:jobalerts-noreply@linkedin.com OR from:jobs-noreply@linkedin.com) "
        f"after:{after_gmail}"
    )
    if before_date:
        before_gmail = before_date.replace("-", "/")
        query += f" before:{before_gmail}"

    all_messages: list[dict] = []
    page_token = None

    # Paginate through all results
    while True:
        url = f"{GMAIL_API_BASE}/messages?q={requests.utils.quote(query)}&maxResults=100"
        if page_token:
            url += f"&pageToken={page_token}"

        try:
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 429:
                _log("WARNING: Gmail API rate limit hit, waiting 5s...")
                time.sleep(5)
                continue
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            _log(f"ERROR: Gmail list query failed: {e}")
            break

        messages = data.get("messages", [])
        all_messages.extend(messages)
        _log(f"Fetched page: {len(messages)} messages (total: {len(all_messages)})")

        page_token = data.get("nextPageToken")
        if not page_token:
            break

        # Small delay between pages to be gentle on the API
        time.sleep(0.5)

    if not all_messages:
        _log("No LinkedIn emails found in the specified date range")
        return []

    _log(f"Total LinkedIn email IDs found: {len(all_messages)}")

    # Fetch each message's full content
    results: list[dict] = []
    for i, msg_summary in enumerate(all_messages):
        msg_id = msg_summary["id"]
        try:
            msg_url = f"{GMAIL_API_BASE}/messages/{msg_id}?format=full"
            msg_resp = requests.get(msg_url, headers=headers, timeout=15)
            msg_resp.raise_for_status()
            msg_data = msg_resp.json()

            html = _extract_html_body(msg_data)
            email_date = _get_email_date(msg_data)

            results.append({
                "id": msg_id,
                "date": email_date,
                "html": html,
            })
        except requests.RequestException as e:
            _log(f"WARNING: Failed to fetch email {msg_id}: {e}")
            continue
        except Exception as e:
            _log(f"WARNING: Failed to process email {msg_id}: {e}")
            continue

        # Rate-limit: small delay every 50 messages
        if (i + 1) % 50 == 0:
            _log(f"Processed {i + 1}/{len(all_messages)} emails...")
            time.sleep(0.1)

    return results


# ---------------------------------------------------------------------------
# Cross-email deduplication
# ---------------------------------------------------------------------------

def deduplicate_across_emails(jobs: list[JobCard]) -> list[JobCard]:
    """Remove duplicate jobs across multiple emails by URL.

    When the same URL appears in multiple emails, keep the JobCard with the
    most complete information (longest snippet, or longest company name if
    snippets are equal length, or earliest source_date as tiebreaker).
    """
    by_url: dict[str, JobCard] = {}

    for job in jobs:
        url_key = job.url
        existing = by_url.get(url_key)

        if existing is None:
            by_url[url_key] = job
            continue

        # Prefer the entry with more information
        # 1. Longer snippet = more info
        if len(job.snippet or "") > len(existing.snippet or ""):
            by_url[url_key] = job
        # 2. Longer company name (if snippets equal length)
        elif len(job.snippet or "") == len(existing.snippet or "") and len(job.company) > len(existing.company):
            by_url[url_key] = job
        # 3. Earlier date as tiebreaker
        elif len(job.snippet or "") == len(existing.snippet or "") and len(job.company) == len(existing.company):
            if job.source_date < existing.source_date:
                by_url[url_key] = job

    return list(by_url.values())


# ---------------------------------------------------------------------------
# Group by date
# ---------------------------------------------------------------------------

def group_jobs_by_date(jobs: list[JobCard]) -> dict[str, list[JobCard]]:
    """Group deduplicated jobs by their source_date (YYYY-MM-DD).

    Returns a dict mapping date string to list of JobCards, sorted by date ascending.
    """
    by_date: dict[str, list[JobCard]] = defaultdict(list)
    for job in jobs:
        by_date[job.source_date].append(job)

    # Return sorted dict
    return dict(sorted(by_date.items()))


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def main() -> int:
    """Run the backfill pipeline."""
    parser = argparse.ArgumentParser(
        description="Backfill LinkedIn job digest files from historical emails"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch and parse emails but do not write digests or trash emails")
    parser.add_argument("--after", default="2026-01-01",
                        help="Fetch emails after this date (default: 2026-01-01)")
    parser.add_argument("--before", default=None,
                        help="Fetch emails before this date (default: no upper bound)")
    parser.add_argument("--trash-before", default="2026-06-01",
                        help="Trash emails older than this date (default: 2026-06-01). "
                             "Set to empty string to disable trashing.")
    args = parser.parse_args()

    _log(f"=== Backfill starting {'(DRY RUN)' if args.dry_run else ''} ===")
    _log(f"After: {args.after}, Before: {args.before or 'none'}, Trash-before: {args.trash_before or 'disabled'}")

    # 1. Authenticate with Gmail
    if not GMAIL_ACCOUNTS_CONFIG:
        _log("ERROR: GMAIL_ACCOUNTS_CONFIG env var not set")
        return 1

    mgr = GmailAccountManager(GMAIL_ACCOUNTS_CONFIG)
    if not mgr.accounts:
        _log("ERROR: No Gmail accounts configured")
        return 1

    account = next(iter(mgr.accounts))
    _log(f"Using Gmail account: {account}")

    token = mgr.get_access_token(account)
    if not token:
        _log("ERROR: Gmail API auth failure")
        return 1

    # 2. Fetch all LinkedIn emails
    emails = fetch_all_linkedin_emails(mgr, account, args.after, args.before)
    _log(f"Fetched {len(emails)} emails total")

    if not emails:
        print("No LinkedIn emails found in the specified date range.")
        return 0

    # 3. Parse each email into JobCards
    all_jobs: list[JobCard] = []
    parsed_ok_ids: list[str] = []      # email IDs that produced jobs
    skipped_ids: list[str] = []         # email IDs that yielded 0 jobs
    failed_ids: list[str] = []          # email IDs that threw exceptions
    email_dates: dict[str, str] = {}   # email_id -> date string

    for email_info in emails:
        email_dates[email_info["id"]] = email_info.get("date", "")
        try:
            jobs = parse_linkedin_email(
                html=email_info.get("html"),
                source_email_id=email_info["id"],
                source_date=email_info.get("date", ""),
            )
            if jobs:
                all_jobs.extend(jobs)
                parsed_ok_ids.append(email_info["id"])
            else:
                skipped_ids.append(email_info["id"])
                _log(f"INFO: Email {email_info['id']} ({email_info.get('date', '?')}) yielded 0 jobs")
        except Exception as e:
            failed_ids.append(email_info["id"])
            _log(f"WARNING: Failed to parse email {email_info['id']}: {e}")
            continue

    _log(f"Parsed {len(all_jobs)} total job cards from {len(parsed_ok_ids)} emails")

    # 4. Cross-email deduplication (same URL = same job)
    unique_jobs = deduplicate_across_emails(all_jobs)
    cross_dupes = len(all_jobs) - len(unique_jobs)
    _log(f"Cross-email dedup: {len(unique_jobs)} unique jobs ({cross_dupes} duplicates removed)")

    # 5. Deduplicate against tracker.json
    tracker = load_tracker(TRACKER_PATH)
    dedup_result = deduplicate_jobs(unique_jobs, tracker)
    new_jobs = dedup_result["new"]
    already_tracked = dedup_result["already_tracked"]
    _log(f"Tracker dedup: {len(new_jobs)} new, {len(already_tracked)} already tracked")

    # 6. Pre-filter for relevance
    keywords = load_prefilter_keywords(REFERENCE_CV_PATH)
    filter_result = prefilter_jobs(new_jobs, keywords)
    surfaced = filter_result["surfaced"]
    below_threshold = filter_result["below_threshold"]
    _log(f"Pre-filter: {len(surfaced)} surfaced, {len(below_threshold)} below threshold")

    # 7. Group by date and write digest files
    all_filtered = surfaced + below_threshold
    jobs_by_date = group_jobs_by_date(all_filtered)

    digest_dates_written: list[str] = []
    for date_str, date_jobs in jobs_by_date.items():
        date_surfaced = [j for j in date_jobs if j in surfaced]
        date_below = [j for j in date_jobs if j in below_threshold]
        stats = {
            "processed": len(date_jobs),
            "surfaced": len(date_surfaced),
            "below_threshold": len(date_below),
            "already_tracked": len([j for j in already_tracked if j.source_date == date_str]),
        }

        if args.dry_run:
            print(f"DRY RUN: Would write digest for {date_str}: "
                  f"{len(date_surfaced)} surfaced, {len(date_below)} below threshold")
        else:
            path = write_digest_markdown(DIGEST_DIR, date_str, date_surfaced, date_below, stats)
            _log(f"Wrote digest: {path}")
        digest_dates_written.append(date_str)

    # 8. Trash old emails (before trash_before date)
    ids_to_trash: list[str] = []
    trash_before = args.trash_before
    if not trash_before:
        _log("Trashing disabled (--trash-before empty)")
    else:
        # Only trash emails that parsed successfully AND are before the cutoff date
        ids_to_trash = [
            eid for eid in parsed_ok_ids
            if email_dates.get(eid, "") < trash_before
        ]
        _log(f"Emails eligible for trashing (before {trash_before}): {len(ids_to_trash)}")

        if ids_to_trash:
            if args.dry_run:
                print(f"DRY RUN: Would trash {len(ids_to_trash)} emails older than {trash_before}")
            else:
                trashed = trash_emails(mgr, account, ids_to_trash)
                _log(f"Trashed {trashed}/{len(ids_to_trash)} old emails")
        else:
            _log("No emails to trash")

    # 9. Summary
    summary = f"""
Backfill Summary {'(DRY RUN)' if args.dry_run else ''}
=====================================
Emails fetched:          {len(emails)}
Emails parsed OK:        {len(parsed_ok_ids)}
Emails no jobs:          {len(skipped_ids)}
Emails parse failed:     {len(failed_ids)}
Total JobCards:           {len(all_jobs)}
After cross-email dedup: {len(unique_jobs)} ({cross_dupes} duplicates removed)
After tracker dedup:
  New jobs:              {len(new_jobs)}
  Already tracked:       {len(already_tracked)}
Surfaced (relevant):     {len(surfaced)}
Below threshold:          {len(below_threshold)}
Digest dates written:    {len(digest_dates_written)}
Emails trashed:          {len(ids_to_trash) if trash_before else 0}
"""
    print(summary)
    _log(f"=== Backfill complete {'(DRY RUN)' if args.dry_run else ''} ===")
    return 0


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    sys.exit(main())