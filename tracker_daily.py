#!/usr/bin/env python3
"""Job Applications — daily tracker digest job.

Standalone script (stdlib only, no FastMCP). Intended to run on pi-4 via
`job-applications-tracker.timer` (daily 07:00, see design.md § pi-4 Systemd
Units). Independent of the MCP server process and any Mac/Claude session.

Steps:
  1. Load tracker.json
  2. Flag pending follow-ups whose due_date has passed as "overdue"
  3. Save tracker.json, rsync it (+ profile.json) to the NAS share as backup
  4. Compile a digest (active applications by stage, overdue follow-ups,
     follow-ups due in the next 7 days)
  5. Email the digest via smtplib (Gmail App Password — same pattern as
     pi-3's GeBiz alerts, see GeBiz-Awards/notify.py)
  6. Log the run to tracker_daily.log
"""

import json
import os
import smtplib
import subprocess
import sys
from datetime import date, datetime, timezone
from email.message import EmailMessage
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv optional; env vars may be set by systemd EnvironmentFile

_SRC_DIR = Path(__file__).resolve().parent

BASE_DIR = Path(os.environ.get("JOB_APP_BASE_DIR", str(_SRC_DIR)))
TRACKER_PATH = Path(os.environ.get("JOB_APP_TRACKER_PATH", str(BASE_DIR / "tracker.json")))
PROFILE_PATH = Path(os.environ.get("JOB_APP_PROFILE_PATH", str(BASE_DIR / "profile.json")))
NAS_SYNC_PATH = os.environ.get("NAS_SYNC_PATH", "")
DIGEST_EMAIL = os.environ.get("DIGEST_EMAIL", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
LOG_PATH = Path(os.environ.get("JOB_APP_TRACKER_LOG_PATH", str(_SRC_DIR / "tracker_daily.log")))

TERMINAL_STAGES = {"accepted", "rejected", "withdrawn"}


def _load_tracker(path: Path) -> dict:
    if not path.exists():
        return {"applications": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _save_tracker(path: Path, tracker: dict) -> None:
    path.write_text(json.dumps(tracker, ensure_ascii=False, indent=2), encoding="utf-8")


def _flag_overdue_followups(tracker: dict, today: str) -> int:
    """Mark pending follow-ups with due_date < today as 'overdue'. Mutates
    tracker in place. Returns the count of follow-ups newly flagged."""
    flagged = 0
    for app in tracker.get("applications", []):
        for followup in app.get("followups", []):
            if followup["status"] == "pending" and followup["due_date"] < today:
                followup["status"] = "overdue"
                flagged += 1
    return flagged


def _compile_digest(tracker: dict, today: str) -> dict:
    """Build the digest dict: active applications by stage, overdue
    follow-ups, and follow-ups due within the next 7 days."""
    from datetime import timedelta

    horizon = (date.fromisoformat(today) + timedelta(days=7)).isoformat()

    active_by_stage: dict[str, list[dict]] = {}
    overdue_followups = []
    due_soon = []

    for app in tracker.get("applications", []):
        stage = app.get("stage", "new")
        if stage not in TERMINAL_STAGES:
            active_by_stage.setdefault(stage, []).append({
                "company": app.get("company"),
                "role_title": app.get("role_title"),
            })

        for followup in app.get("followups", []):
            entry = {
                "company": app.get("company"),
                "role_title": app.get("role_title"),
                "action_type": followup["action_type"],
                "due_date": followup["due_date"],
            }
            if followup["status"] == "overdue":
                overdue_followups.append(entry)
            elif followup["status"] == "pending" and followup["due_date"] <= horizon:
                due_soon.append(entry)

    overdue_followups.sort(key=lambda f: f["due_date"])
    due_soon.sort(key=lambda f: f["due_date"])

    return {
        "active_by_stage": active_by_stage,
        "active_count": sum(len(v) for v in active_by_stage.values()),
        "overdue_followups": overdue_followups,
        "due_soon": due_soon,
    }


def _format_digest_email(digest: dict, today: str) -> tuple[str, str]:
    """Return (subject, body) for the daily digest email."""
    active_count = digest["active_count"]
    overdue_count = len(digest["overdue_followups"])
    subject = f"Job Applications Daily — {today} | {active_count} active, {overdue_count} overdue"

    lines = [f"Job Applications Daily Digest — {today}", ""]

    lines.append(f"ACTIVE APPLICATIONS ({active_count})")
    if digest["active_by_stage"]:
        for stage, apps in digest["active_by_stage"].items():
            lines.append(f"  {stage}:")
            for a in apps:
                lines.append(f"    - {a['company']} ({a['role_title']})")
    else:
        lines.append("  (none)")
    lines.append("")

    lines.append(f"OVERDUE FOLLOW-UPS ({overdue_count})")
    if digest["overdue_followups"]:
        for f in digest["overdue_followups"]:
            lines.append(f"  - {f['company']} ({f['role_title']}): {f['action_type']} was due {f['due_date']}")
    else:
        lines.append("  (none)")
    lines.append("")

    lines.append(f"DUE IN NEXT 7 DAYS ({len(digest['due_soon'])})")
    if digest["due_soon"]:
        for f in digest["due_soon"]:
            lines.append(f"  - {f['company']} ({f['role_title']}): {f['action_type']} due {f['due_date']}")
    else:
        lines.append("  (none)")

    return subject, "\n".join(lines)


def _send_digest_email(subject: str, body: str) -> bool:
    """Send the digest via Gmail SMTP + App Password. Returns True on
    success, False if not configured or delivery failed."""
    if not (DIGEST_EMAIL and GMAIL_APP_PASSWORD):
        return False
    msg = EmailMessage()
    msg["From"] = DIGEST_EMAIL
    msg["To"] = DIGEST_EMAIL
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as smtp:
            smtp.starttls()
            smtp.login(DIGEST_EMAIL, GMAIL_APP_PASSWORD)
            smtp.send_message(msg)
        return True
    except Exception:
        return False


def _sync_to_nas() -> bool:
    """rsync tracker.json + profile.json to the NAS share. Fire-and-forget
    backup; returns False silently if NAS_SYNC_PATH is unset or rsync fails."""
    if not NAS_SYNC_PATH:
        return False
    try:
        result = subprocess.run(
            ["rsync", "-a", str(TRACKER_PATH), str(PROFILE_PATH), NAS_SYNC_PATH],
            check=False, capture_output=True, timeout=30,
        )
        return result.returncode == 0
    except Exception:
        return False


def _log(message: str) -> None:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {message}\n")


def main() -> int:
    today = date.today().isoformat()
    tracker = _load_tracker(TRACKER_PATH)

    flagged = _flag_overdue_followups(tracker, today)
    _save_tracker(TRACKER_PATH, tracker)
    synced = _sync_to_nas()

    digest = _compile_digest(tracker, today)
    subject, body = _format_digest_email(digest, today)
    sent = _send_digest_email(subject, body)

    _log(
        f"active={digest['active_count']} overdue={len(digest['overdue_followups'])} "
        f"newly_flagged={flagged} nas_synced={synced} email_sent={sent}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
