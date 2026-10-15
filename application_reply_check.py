#!/usr/bin/env python3
"""Check Gmail (work account) for replies to open job applications.

Read-only: lists/reads messages, never modifies mail or application stages.
Usage: python3 application_reply_check.py [--days 1] [--account work]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import requests

from gmail_auth import GmailAccountManager

HERE = Path(__file__).resolve().parent
APPS_PATH = HERE / "data" / "open_applications.json"
REPORT_DIR = HERE / "artefacts" / "reply_checks"
API = "https://gmail.googleapis.com/gmail/v1/users/me"

CLASSES = [
    ("rejection", r"unfortunately|not (?:be )?moving forward|regret to|other candidates|will not be proceeding|not selected"),
    ("interview", r"interview|schedule a call|availability|next steps|speak with you|chat with"),
    ("received", r"received your application|thank you for applying|application received"),
]
ALIASES = {"Meta": ["meta", "facebook"], "Microsoft": ["microsoft"], "Salesforce": ["salesforce"]}


def classify(text: str) -> str:
    for label, pat in CLASSES:
        if re.search(pat, text, re.I):
            return label
    return "other"


def terms_for(company: str) -> list[str]:
    return [t.lower() for t in ALIASES.get(company, [company])]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=1)
    ap.add_argument("--account", default="work")
    ap.add_argument("--config", default=str(HERE / "gmail_accounts.json"))
    args = ap.parse_args()

    from src.tools._state import load_tracker
    
    payload = load_tracker()
    skip = {"withdrawn", "rejected", "closed_won"}
    apps = [a for a in payload.get("applications", []) 
            if a.get("stage") not in skip and "Orchestration Pilot" not in a.get("company", "")]
    
    mgr = GmailAccountManager(args.config)
    token = mgr.get_access_token(args.account)
    if not token:
        print(f"ALERT: Gmail auth failed for '{args.account}' - re-authenticate "
              "with gmail_auth_setup.py", file=sys.stderr)
        return 2
    hdr = {"Authorization": f"Bearer {token}"}

    hits = []
    for app in apps:
        for term in terms_for(app["company"]):
            ats = ("smartrecruiters.com OR myworkday.com OR greenhouse.io OR lever.co "
                   "OR icims.com OR workable.com OR ashbyhq.com OR successfactors.com "
                   "OR facebookmail.com OR careers OR recruiting OR talent")
            q = (f'newer_than:{args.days}d -in:sent -category:promotions -category:social '
                 f'(from:{term} OR subject:"{term}" OR (from:({ats}) "{term}"))')
            r = requests.get(f"{API}/messages", headers=hdr,
                             params={"q": q, "maxResults": 10}, timeout=30)
            r.raise_for_status()
            for m in r.json().get("messages", []):
                d = requests.get(
                    f"{API}/messages/{m['id']}", headers=hdr, timeout=30,
                    params={"format": "metadata", "metadataHeaders": ["From", "Subject", "Date"]},
                ).json()
                h = {x["name"]: x["value"] for x in d.get("payload", {}).get("headers", [])}
                text = f"{h.get('Subject', '')} {d.get('snippet', '')}"
                hits.append({
                    "company": app["company"], "role": app["role_title"],
                    "stage": app["stage"], "from": h.get("From", ""),
                    "subject": h.get("Subject", ""), "date": h.get("Date", ""),
                    "class": classify(text), "id": m["id"],
                })

    seen, uniq = set(), []
    for x in hits:
        if x["id"] not in seen:
            seen.add(x["id"])
            uniq.append(x)

    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    lines = [f"# Application reply check {stamp} (last {args.days}d, {len(apps)} open apps)", ""]
    if not uniq:
        lines.append("No relevant emails.")
    for x in uniq:
        lines.append(f"- **{x['company']}** ({x['stage']}) [{x['class']}] {x['subject']} - {x['from']} - {x['date']}")
    out = "\n".join(lines)
    print(out)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / f"{stamp}.md").write_text(out + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
