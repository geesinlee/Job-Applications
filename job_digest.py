#!/usr/bin/env python3
"""Job Applications — daily LinkedIn job discovery digest.

Standalone script (stdlib + requests, like tracker_daily.py). Intended to run
on pi-4 via a systemd timer at 02:00 SGT.

Pipeline:
  1. Authenticate with Gmail API via OAuth2 (GmailAccountManager)
  2. Query Gmail for LinkedIn job-alert emails since last run
  3. Parse job listings from each email (parse_linkedin_email)
  4. De-duplicate against tracker.json (URL exact + company+title fuzzy)
  5. Apply lightweight keyword pre-filter against Reference_CV.md
  6. Write daily Markdown digest to $JOB_APP_ARTEFACTS_DIR/digests/YYYY-MM-DD.md
  7. Send summary email via SMTP (GMAIL_APP_PASSWORD)
  8. Move processed LinkedIn emails to Trash via Gmail API
  9. Update last-run timestamp
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import re
import smtplib
import sys
from datetime import date, datetime, timezone, timedelta
from email.message import EmailMessage
from pathlib import Path

import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv optional; env vars may be set by systemd

from gmail_auth import GmailAccountManager
from email_parser import JobCard, parse_linkedin_email

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_SRC_DIR = Path(__file__).resolve().parent

BASE_DIR = Path(os.environ.get("JOB_APP_BASE_DIR", str(_SRC_DIR)))
ARTEFACTS_DIR = Path(os.environ.get("JOB_APP_ARTEFACTS_DIR", str(BASE_DIR)))
TRACKER_PATH = Path(os.environ.get("JOB_APP_TRACKER_PATH", str(BASE_DIR / "tracker.json")))
PROFILE_PATH = Path(os.environ.get("JOB_APP_PROFILE_PATH", str(BASE_DIR / "profile.json")))
REFERENCE_CV_PATH = Path(os.environ.get(
    "JOB_APP_REFERENCE_CV_PATH",
    str(ARTEFACTS_DIR / "Base CV" / "Reference_CV.md"),
))

GMAIL_ACCOUNTS_CONFIG = os.environ.get("GMAIL_ACCOUNTS_CONFIG", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
JOB_DIGEST_RECIPIENT = os.environ.get("JOB_DIGEST_RECIPIENT", "geesin.lee@gmail.com")

DIGEST_DIR = ARTEFACTS_DIR / "digests"
LAST_RUN_FILE = ARTEFACTS_DIR / ".job_digest_last_run"
LOG_PATH = Path(os.environ.get("JOB_DIGEST_LOG_PATH", str(_SRC_DIR / "job_digest.log")))

GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"

# Levenshtein distance threshold for fuzzy title matching (company is exact match)
LEV_THRESHOLD = 3

# Pre-filter senior-title keywords (case-insensitive)
SENIOR_KEYWORDS = {
    "senior", "director", "vp", "vice president", "partner", "head",
    "lead", "principal", "chief", "cto", "ceo", "cfo", "cro", "cso",
    "vp-", "svp", "evp", "avp", "distinguished", "staff",
}

# Pre-filter location keywords (case-insensitive)
LOCATION_KEYWORDS = {
    "singapore", "sg", "apac", "asean", "asia pacific", "asia-pacific",
    "south east asia", "southeast asia",
}

logger = logging.getLogger("job_digest")


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _log(message: str) -> None:
    """Append a timestamped message to the digest log file."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"[{timestamp}] {message}"
    try:
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass  # best-effort logging
    logger.info(message)


# ---------------------------------------------------------------------------
# Tracker loading
# ---------------------------------------------------------------------------

def load_tracker(path: Path) -> dict:
    """Load tracker.json; return empty schema on any read error.

    Conservative: if tracker is unreadable, treat all jobs as "new" rather
    than silently skipping them.
    """
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        _log(f"WARNING: tracker.json read failure at {path}, treating all jobs as new")
        return {"schema_version": "1.0", "applications": []}


# ---------------------------------------------------------------------------
# De-duplication
# ---------------------------------------------------------------------------

def _levenshtein(s1: str, s2: str) -> int:
    """Compute Levenshtein edit distance between two strings."""
    if len(s1) < len(s2):
        return _levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]


def deduplicate_jobs(jobs: list[JobCard], tracker: dict) -> dict:
    """De-duplicate parsed jobs against tracker records.

    Returns {"new": [...], "already_tracked": [...]}.
    A job is "already tracked" if:
      - Its URL exactly matches a tracker record's jd_source_url, or
      - Its URL exactly matches any URL found in the tracker applications, or
      - Its company exactly matches (case-insensitive) AND its title is within
        Levenshtein distance <= LEV_THRESHOLD of a tracker record's role_title.
    """
    tracked_urls: set[str] = set()
    tracked_combos: list[tuple[str, str]] = []  # (company_lower, title_lower)

    for app in tracker.get("applications", []):
        # Collect known URLs from tracker records
        for url_field in ("jd_source_url", "jd_path"):
            url_val = app.get(url_field)
            if url_val and url_val.startswith("http"):
                tracked_urls.add(url_val)
        # Also check outputs for any saved URLs
        for output_entries in (app.get("outputs", {}) or {}).values():
            if isinstance(output_entries, list):
                for entry in output_entries:
                    if isinstance(entry, dict):
                        url_val = entry.get("url") or entry.get("jd_source_url")
                        if url_val:
                            tracked_urls.add(url_val)
        # Fuzzy combo
        company = (app.get("company") or "").lower().strip()
        title = (app.get("role_title") or "").lower().strip()
        if company and title:
            tracked_combos.append((company, title))

    new_jobs: list[JobCard] = []
    already_tracked: list[JobCard] = []

    for job in jobs:
        # URL exact match
        if job.url in tracked_urls:
            already_tracked.append(job)
            continue

        # Fuzzy company+title match
        job_company = job.company.lower().strip()
        job_title = job.title.lower().strip()
        is_dup = False
        for tc, tt in tracked_combos:
            if job_company == tc and _levenshtein(job_title, tt) <= LEV_THRESHOLD:
                is_dup = True
                break
        if is_dup:
            already_tracked.append(job)
            continue

        new_jobs.append(job)

    return {"new": new_jobs, "already_tracked": already_tracked}


# ---------------------------------------------------------------------------
# Pre-filter (Reference CV keywords)
# ---------------------------------------------------------------------------

def load_prefilter_keywords(reference_cv_path: Path) -> dict:
    """Extract senior titles, locations, skills, and industries from Reference_CV.md.

    Returns a dict with keys: senior_titles, locations, skills, industries.
    Falls back to basic keyword-only pre-filter if the file is missing.
    """
    result: dict[str, set[str]] = {
        "senior_titles": set(SENIOR_KEYWORDS),
        "locations": set(LOCATION_KEYWORDS),
        "skills": set(),
        "industries": set(),
    }

    if not reference_cv_path.exists():
        _log(f"WARNING: Reference_CV.md not found at {reference_cv_path}, using basic keywords only")
        return result

    try:
        text = reference_cv_path.read_text(encoding="utf-8").lower()
    except Exception:
        _log(f"WARNING: Failed to read Reference_CV.md at {reference_cv_path}")
        return result

    # Extract skills from Technical Skills section
    # The CV format is: - **Category:** item, item, item
    # Colon may be inside or outside the bold markers
    skills_match = re.search(
        r"##\s*technical skills\s*\n(.+?)(?:\n---|\n##|\Z)", text, re.DOTALL | re.IGNORECASE,
    )
    if skills_match:
        for line in skills_match.group(1).split("\n"):
            # Match: - **Category:** items  OR  - **Category** items
            skill_line = re.match(r"^\s*[-*]\s*\*\*(.+?)\*\*:?\s*(.*)", line.strip())
            if skill_line:
                items_str = skill_line.group(2).strip()
                if not items_str:
                    continue
                items = items_str.split(",")
                for item in items:
                    clean = re.sub(r"\(.+?\)", "", item).strip()
                    if clean and len(clean) > 1:
                        result["skills"].add(clean)
                        # Also add individual words for broader matching
                        for word in clean.split():
                            if len(word) > 3:
                                result["skills"].add(word)

    # Extract industries/verticals from Professional Summary and Core Competencies
    industry_keywords = [
        "public sector", "government", "telco", "telecommunications", "iot",
        "cybersecurity", "cloud", "automation", "ai", "salesforce", "ipaaS",
        "data integration", "digital transformation", "smart city",
        "enterprise sales", "consulting", "account management",
    ]
    for kw in industry_keywords:
        if kw in text:
            result["industries"].add(kw)

    # Extract specific company names / account names as keywords
    account_keywords = re.findall(
        r"\b(MTI|MAS|GovTech|IMDA|Synapxe|JTC|HTX|IDA|Smart Nation|MDDI)\b", text, re.IGNORECASE,
    )
    for kw in account_keywords:
        result["industries"].add(kw.lower())

    return result


def prefilter_jobs(jobs: list[JobCard], keywords: dict) -> dict:
    """Apply lightweight keyword pre-filter against Reference CV keywords.

    A job passes the pre-filter if ANY of:
      - Title contains a senior/director/VP/partner/head/lead keyword
      - Location mentions Singapore/APAC
      - Title or snippet contains a skill or industry keyword

    Returns {"surfaced": [...], "below_threshold": [...]}.
    """
    senior_titles = keywords.get("senior_titles", SENIOR_KEYWORDS)
    locations = keywords.get("locations", LOCATION_KEYWORDS)
    skills = keywords.get("skills", set())
    industries = keywords.get("industries", set())

    surfaced: list[JobCard] = []
    below_threshold: list[JobCard] = []

    for job in jobs:
        title_lower = job.title.lower()
        snippet_lower = (job.snippet or "").lower()
        location_lower = (job.location or "").lower()
        combined_text = f"{title_lower} {snippet_lower} {location_lower}"

        is_surfaced = False

        # Check senior title keywords
        for kw in senior_titles:
            if kw in title_lower:
                is_surfaced = True
                break

        # Check location keywords
        if not is_surfaced:
            for kw in locations:
                if kw in location_lower or kw in combined_text:
                    is_surfaced = True
                    break

        # Check skill/industry keywords
        if not is_surfaced:
            for kw in skills | industries:
                if kw in combined_text:
                    is_surfaced = True
                    break

        if is_surfaced:
            surfaced.append(job)
        else:
            below_threshold.append(job)

    return {"surfaced": surfaced, "below_threshold": below_threshold}


# ---------------------------------------------------------------------------
# Digest Markdown
# ---------------------------------------------------------------------------

def write_digest_markdown(
    digest_dir: Path,
    date_str: str,
    surfaced: list[JobCard],
    below_threshold: list[JobCard],
    stats: dict,
) -> Path:
    """Write the daily Markdown digest file and return its path."""
    digest_dir.mkdir(parents=True, exist_ok=True)
    filepath = digest_dir / f"{date_str}.md"

    lines = [f"# Job Discoveries — {date_str}", ""]

    # Surfaced section
    lines.append("## Surfaced for Review")
    lines.append("")
    if surfaced:
        for job in surfaced:
            lines.append(f"### {job.company} — {job.title}")
            lines.append(f"- **Location:** {job.location or 'N/A'}")
            lines.append(f"- **URL:** {job.url}")
            lines.append(f"- **Snippet:** {job.snippet or 'N/A'}")
            lines.append(f"- **Category:** surfaced")
            lines.append("")
            lines.append("---")
            lines.append("")
    else:
        lines.append("*(No jobs surfaced today)*")
        lines.append("")

    # Stats line
    lines.append(
        f"*({stats.get('processed', 0)} jobs processed, "
        f"{stats.get('surfaced', 0)} surfaced, "
        f"{stats.get('below_threshold', 0)} below threshold, "
        f"{stats.get('already_tracked', 0)} already tracked)*"
    )
    lines.append("")
    lines.append("---")
    lines.append("")

    # Below threshold section
    lines.append("## Below Threshold")
    lines.append("")
    if below_threshold:
        for job in below_threshold:
            lines.append(f"### {job.company} — {job.title}")
            lines.append(f"- **Location:** {job.location or 'N/A'}")
            lines.append(f"- **URL:** {job.url}")
            lines.append(f"- **Snippet:** {job.snippet or 'N/A'}")
            lines.append(f"- **Reason:** Below pre-filter threshold")
            lines.append("")
    else:
        lines.append("*(No jobs below threshold)*")
        lines.append("")

    filepath.write_text("\n".join(lines), encoding="utf-8")
    return filepath


# ---------------------------------------------------------------------------
# Gmail API
# ---------------------------------------------------------------------------

def _extract_html_body(msg_data: dict) -> str | None:
    """Extract HTML from a Gmail message payload (base64 decode, handle multipart)."""
    payload = msg_data.get("payload", {})
    mime_type = payload.get("mimeType", "")

    # Helper: decode a base64 data payload
    def _decode_data(data: str) -> str:
        # Gmail uses URL-safe base64 without padding
        padded = data + "=" * (4 - len(data) % 4) if len(data) % 4 else data
        return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")

    # If multipart, recurse to find HTML part
    if mime_type.startswith("multipart/"):
        parts = payload.get("parts", [])
        for part in parts:
            if part.get("mimeType", "") == "text/html":
                data = part.get("body", {}).get("data")
                if data:
                    return _decode_data(data)
        # Fallback: search nested parts
        for part in parts:
            if part.get("mimeType", "").startswith("multipart/"):
                # Recurse into nested multipart
                nested = _extract_html_body({"payload": part})
                if nested:
                    return nested
        # Last resort: try text/plain
        for part in parts:
            if part.get("mimeType", "") == "text/plain":
                data = part.get("body", {}).get("data")
                if data:
                    return _decode_data(data)
        return None

    # Single-part HTML
    if mime_type == "text/html":
        data = payload.get("body", {}).get("data")
        if data:
            return _decode_data(data)

    # Single-part plain text (fallback)
    if mime_type == "text/plain":
        data = payload.get("body", {}).get("data")
        if data:
            return _decode_data(data)

    return None


def _get_email_date(msg_data: dict) -> str:
    """Extract date from Gmail message headers, return ISO-8601 date string."""
    headers = msg_data.get("payload", {}).get("headers", [])
    for header in headers:
        if header.get("name", "").lower() == "date":
            date_str = header.get("value", "")
            try:
                # Parse RFC 2822 date
                from email.utils import parsedate_to_datetime
                dt = parsedate_to_datetime(date_str)
                return dt.strftime("%Y-%m-%d")
            except Exception:
                pass
            # Fallback: try to extract YYYY-MM-DD
            m = re.search(r"(\d{4}-\d{2}-\d{2})", date_str)
            if m:
                return m.group(1)
    return date.today().isoformat()


def query_linkedin_emails(
    mgr: GmailAccountManager,
    account: str,
    after_date: str,
) -> list[dict]:
    """Query Gmail API for LinkedIn job-alert emails since after_date.

    Returns a list of {id, date, html} dicts.
    """
    token = mgr.get_access_token(account)
    if not token:
        _log(f"ERROR: Failed to get access token for account '{account}'")
        return []

    headers = {"Authorization": f"Bearer {token}"}

    # Search for LinkedIn job alert emails
    query = f"from:notifications@linkedin.com after:{after_date}"
    list_url = f"{GMAIL_API_BASE}/messages?q={requests.utils.quote(query)}&maxResults=50"

    try:
        resp = requests.get(list_url, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        _log(f"ERROR: Gmail list query failed: {e}")
        return []

    messages = data.get("messages", [])
    if not messages:
        return []

    # Fetch each message
    results: list[dict] = []
    for msg_summary in messages:
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

    return results


def trash_emails(
    mgr: GmailAccountManager,
    account: str,
    message_ids: list[str],
) -> int:
    """Move emails to Trash via Gmail API. Returns count of successfully trashed."""
    token = mgr.get_access_token(account)
    if not token:
        _log("ERROR: Failed to get access token for trash operation")
        return 0

    headers = {"Authorization": f"Bearer {token}"}
    trashed = 0

    for msg_id in message_ids:
        try:
            url = f"{GMAIL_API_BASE}/messages/{msg_id}/trash"
            resp = requests.post(url, headers=headers, timeout=10)
            resp.raise_for_status()
            trashed += 1
        except requests.RequestException as e:
            _log(f"WARNING: Failed to trash email {msg_id}: {e}")
            continue

    return trashed


# ---------------------------------------------------------------------------
# Email notification
# ---------------------------------------------------------------------------

def _format_digest_email(surfaced: list[JobCard], stats: dict, date_str: str) -> tuple[str, str]:
    """Format email subject and body for the digest notification."""
    surfaced_count = len(surfaced)
    subject = f"Job Discoveries — {date_str}: {surfaced_count} new roles"

    lines = [f"Job Discoveries for {date_str}", ""]

    lines.append("🔥 Top Matches:")
    if surfaced:
        for i, job in enumerate(surfaced, 1):
            lines.append(f"{i}. {job.company} — {job.title}")
    else:
        lines.append("(none)")
    lines.append("")

    lines.append(
        f"📊 Stats: {stats.get('processed', 0)} processed, "
        f"{surfaced_count} surfaced, "
        f"{stats.get('below_threshold', 0)} below threshold, "
        f"{stats.get('already_tracked', 0)} already tracked"
    )
    lines.append("")
    lines.append(f'Review in Claude Desktop: review_daily_discoveries("{date_str}")')

    return subject, "\n".join(lines)


def _send_digest_email(subject: str, body: str) -> bool:
    """Send the digest via Gmail SMTP + App Password. Returns True on success."""
    if not (JOB_DIGEST_RECIPIENT and GMAIL_APP_PASSWORD):
        _log("WARNING: JOB_DIGEST_RECIPIENT or GMAIL_APP_PASSWORD not set, skipping email")
        return False

    msg = EmailMessage()
    msg["From"] = JOB_DIGEST_RECIPIENT
    msg["To"] = JOB_DIGEST_RECIPIENT
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as smtp:
            smtp.starttls()
            smtp.login(JOB_DIGEST_RECIPIENT, GMAIL_APP_PASSWORD)
            smtp.send_message(msg)
        return True
    except Exception as e:
        _log(f"ERROR: Failed to send digest email: {e}")
        return False


def _send_alert_email(subject: str, body: str) -> bool:
    """Send an alert email (e.g. auth failure) via SMTP. Returns True on success."""
    if not (JOB_DIGEST_RECIPIENT and GMAIL_APP_PASSWORD):
        return False

    msg = EmailMessage()
    msg["From"] = JOB_DIGEST_RECIPIENT
    msg["To"] = JOB_DIGEST_RECIPIENT
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as smtp:
            smtp.starttls()
            smtp.login(JOB_DIGEST_RECIPIENT, GMAIL_APP_PASSWORD)
            smtp.send_message(msg)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Last-run timestamp
# ---------------------------------------------------------------------------

def _read_last_run() -> str | None:
    """Read the last-run timestamp file. Returns ISO date string or None."""
    if not LAST_RUN_FILE.exists():
        return None
    try:
        return LAST_RUN_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        return None


def _write_last_run(date_str: str) -> None:
    """Write the last-run timestamp file."""
    try:
        LAST_RUN_FILE.parent.mkdir(parents=True, exist_ok=True)
        LAST_RUN_FILE.write_text(date_str, encoding="utf-8")
    except OSError as e:
        _log(f"WARNING: Failed to write last-run timestamp: {e}")


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def main() -> int:
    """Run the daily job discovery digest pipeline."""
    parser = argparse.ArgumentParser(description="Daily LinkedIn job discovery digest")
    parser.add_argument("--dry-run", action="store_true",
                        help="Authenticate and query Gmail but do not write digest, send email, or trash emails")
    args = parser.parse_args()

    today = date.today().isoformat()
    _log(f"=== Job digest starting for {today} {'(DRY RUN)' if args.dry_run else ''} ===")

    # 1. Authenticate with Gmail API
    if not GMAIL_ACCOUNTS_CONFIG:
        _log("ERROR: GMAIL_ACCOUNTS_CONFIG env var not set")
        _send_alert_email(
            "Job Digest Auth Failure",
            f"Job digest failed: GMAIL_ACCOUNTS_CONFIG not set on {today}",
        )
        return 1

    mgr = GmailAccountManager(GMAIL_ACCOUNTS_CONFIG)
    # Use the first configured account
    if not mgr.accounts:
        _log("ERROR: No Gmail accounts configured")
        _send_alert_email(
            "Job Digest Auth Failure",
            f"Job digest failed: No Gmail accounts configured on {today}",
        )
        return 1

    account = next(iter(mgr.accounts))
    _log(f"Using Gmail account: {account}")

    token = mgr.get_access_token(account)
    if not token:
        _log("ERROR: Gmail API auth failure")
        _send_alert_email(
            "Job Digest Auth Failure",
            f"Job digest failed: Could not obtain access token on {today}",
        )
        return 1

    # 2. Determine query window
    last_run = _read_last_run()
    if last_run:
        after_date = last_run
    else:
        after_date = (date.today() - timedelta(days=30)).isoformat()
    _log(f"Querying LinkedIn emails after {after_date}")

    # 3. Query Gmail for LinkedIn job-alert emails
    emails = query_linkedin_emails(mgr, account, after_date)
    _log(f"Found {len(emails)} LinkedIn emails")

    if args.dry_run:
        print(f"DRY RUN: Gmail API access OK. Found {len(emails)} emails since {after_date}.")
        print("No digest written, no email sent, no emails trashed.")
        return 0

    if not emails:
        # No emails found: write empty digest, no email, no trash
        stats = {"processed": 0, "surfaced": 0, "below_threshold": 0, "already_tracked": 0}
        write_digest_markdown(DIGEST_DIR, today, [], [], stats)
        _write_last_run(today)
        _log(f"Job digest complete (no emails): {stats}")
        return 0

    # 4. Parse job listings from each email
    all_jobs: list[JobCard] = []
    email_ids: list[str] = []
    for email_info in emails:
        try:
            jobs = parse_linkedin_email(
                html=email_info.get("html"),
                source_email_id=email_info["id"],
                source_date=email_info.get("date", today),
            )
            all_jobs.extend(jobs)
            email_ids.append(email_info["id"])
        except Exception as e:
            _log(f"WARNING: Failed to parse email {email_info.get('id', '?')}: {e}")
            continue

    _log(f"Parsed {len(all_jobs)} total job cards from {len(email_ids)} emails")

    # 5. De-duplicate against tracker.json
    tracker = load_tracker(TRACKER_PATH)
    dedup_result = deduplicate_jobs(all_jobs, tracker)
    new_jobs = dedup_result["new"]
    already_tracked = dedup_result["already_tracked"]
    _log(f"Dedup: {len(new_jobs)} new, {len(already_tracked)} already tracked")

    # 6. Apply keyword pre-filter
    keywords = load_prefilter_keywords(REFERENCE_CV_PATH)
    filter_result = prefilter_jobs(new_jobs, keywords)
    surfaced = filter_result["surfaced"]
    below_threshold = filter_result["below_threshold"]
    _log(f"Pre-filter: {len(surfaced)} surfaced, {len(below_threshold)} below threshold")

    # 7. Write digest
    stats = {
        "processed": len(all_jobs),
        "surfaced": len(surfaced),
        "below_threshold": len(below_threshold),
        "already_tracked": len(already_tracked),
    }
    digest_path = write_digest_markdown(DIGEST_DIR, today, surfaced, below_threshold, stats)
    _log(f"Digest written to {digest_path}")

    # 8. Send summary email
    subject, body = _format_digest_email(surfaced, stats, today)
    sent = _send_digest_email(subject, body)
    _log(f"Email sent: {sent}")

    # 9. Move processed LinkedIn emails to Trash
    trashed = trash_emails(mgr, account, email_ids)
    _log(f"Trashed {trashed}/{len(email_ids)} emails")

    # 10. Update last-run timestamp
    _write_last_run(today)

    _log(f"=== Job digest complete: {stats} ===")
    return 0


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    sys.exit(main())