# LinkedIn Job Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automated daily ingestion of LinkedIn job-alert emails from Gmail, de-duplication, pre-filtering, and surfacing curated discoveries via Claude Desktop and email digest.

**Architecture:** Standalone `job_digest.py` (like `tracker_daily.py`) runs at 2am via systemd timer on pi-4. It authenticates with Gmail API via OAuth2 (reusing Contact-Mgmt's `AccountManager` pattern), parses LinkedIn emails, de-duplicates against tracker.json, applies a keyword pre-filter, and writes a daily Markdown digest. Two new MCP tools (`review_daily_discoveries`, `ingest_from_discovery`) provide interactive review via Claude Desktop. Full LLM-based scoring happens on-demand via existing `score_match`.

**Tech Stack:** Python 3.11+, FastMCP >=2.0,<3, Google Gmail API (via `requests` + OAuth2 refresh token flow), BeautifulSoup4 (HTML email parsing), smtplib (digest email), stdlib (json, datetime, re, pathlib)

---

## File Structure

| File | Responsibility | Status |
|------|---------------|--------|
| `gmail_auth.py` | Gmail OAuth2 token management (AccountManager pattern from Contact-Mgmt) | NEW |
| `gmail_auth_setup.py` | One-time browser consent flow for Gmail OAuth2 | NEW |
| `email_parser.py` | Parse LinkedIn job-alert emails (digest + single formats) | NEW |
| `job_digest.py` | Main pipeline: query Gmail → parse → de-dup → pre-filter → write digest → email → trash | NEW |
| `job_applications_mcp_server.py` | Add 2 new MCP tools: `review_daily_discoveries`, `ingest_from_discovery` | MODIFY |
| `gmail_accounts.json` | Account metadata (email, category, credentials_file path) | NEW |
| `creds/gmail-personal.json` | Per-account OAuth2 secrets (client_id, client_secret, refresh_token) | NEW (gitignored) |
| `test_gmail_auth.py` | Tests for OAuth2 token refresh and caching | NEW |
| `test_email_parser.py` | Tests for LinkedIn email HTML parsing | NEW |
| `test_job_digest.py` | Integration tests for de-dup, pre-filter, digest writing, email sending | NEW |
| `deploy/pi-4/job-applications-digest.service` | Systemd unit for job_digest.py | NEW |
| `deploy/pi-4/job-applications-digest.timer` | Systemd timer (02:00 SGT daily) | NEW |
| `requirements.txt` | Add `google-auth` (not used — we use raw `requests` for token flow) | NO CHANGE |
| `.gitignore` | Add `creds/`, `digests/`, `gmail_accounts.json` patterns | MODIFY |
| `.env.example` | Add `GMAIL_ACCOUNTS_CONFIG`, `JOB_DIGEST_RECIPIENT` | MODIFY |

---

### Task 1: Gmail OAuth2 Module (`gmail_auth.py`)

**Files:**
- Create: `gmail_auth.py`
- Test: `test_gmail_auth.py`

- [ ] **Step 1: Write failing tests for GmailAccountManager**

Create `test_gmail_auth.py`:

```python
"""Tests for gmail_auth module — OAuth2 token management."""
import json
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from gmail_auth import AccountConfig, GmailAccountManager, SCOPES


class TestAccountConfig:
    def test_from_dict_with_all_fields(self):
        data = {
            "email": "test@gmail.com",
            "category": "personal",
            "credentials_file": "/path/to/creds.json",
        }
        cfg = AccountConfig.from_dict("personal", data)
        assert cfg.key == "personal"
        assert cfg.email == "test@gmail.com"
        assert cfg.category == "personal"
        assert cfg.credentials_file == "/path/to/creds.json"

    def test_from_dict_defaults(self):
        data = {"email": "test@gmail.com"}
        cfg = AccountConfig.from_dict("work", data)
        assert cfg.category == "personal"  # default
        assert cfg.credentials_file == ""

    def test_invalid_category_falls_back_to_personal(self):
        data = {"email": "test@gmail.com", "category": "invalid"}
        cfg = AccountConfig.from_dict("x", data)
        assert cfg.category == "personal"


class TestGmailAccountManager:
    def test_scopes_include_gmail_readonly_and_modify(self):
        assert "https://www.googleapis.com/auth/gmail.readonly" in SCOPES
        assert "https://www.googleapis.com/auth/gmail.modify" in SCOPES

    def test_load_config_creates_accounts(self, tmp_path):
        creds_dir = tmp_path / "creds"
        creds_dir.mkdir()
        creds_file = creds_dir / "personal.json"
        creds_file.write_text(json.dumps({
            "client_id": "test-id",
            "client_secret": "test-secret",
            "refresh_token": "test-refresh-token",
        }))
        config = {
            "accounts": {
                "personal": {
                    "email": "test@gmail.com",
                    "category": "personal",
                    "credentials_file": str(creds_file),
                }
            }
        }
        config_path = tmp_path / "gmail_accounts.json"
        config_path.write_text(json.dumps(config))

        mgr = GmailAccountManager(str(config_path))
        assert "personal" in mgr.accounts
        assert mgr.accounts["personal"].email == "test@gmail.com"
        assert mgr.accounts["personal"].client_id == "test-id"
        assert mgr.accounts["personal"].refresh_token == "test-refresh-token"

    def test_get_access_token_refreshes(self, tmp_path):
        creds_dir = tmp_path / "creds"
        creds_dir.mkdir()
        creds_file = creds_dir / "personal.json"
        creds_file.write_text(json.dumps({
            "client_id": "test-id",
            "client_secret": "test-secret",
            "refresh_token": "test-refresh-token",
        }))
        config = {
            "accounts": {
                "personal": {
                    "email": "test@gmail.com",
                    "category": "personal",
                    "credentials_file": str(creds_file),
                }
            }
        }
        config_path = tmp_path / "gmail_accounts.json"
        config_path.write_text(json.dumps(config))

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "ya29.test-token",
            "expires_in": 3600,
        }
        mock_response.raise_for_status = MagicMock()

        mgr = GmailAccountManager(str(config_path))
        with patch("gmail_auth.requests.post", return_value=mock_response):
            token = mgr.get_access_token("personal")

        assert token == "ya29.test-token"

    def test_get_access_token_uses_cache(self, tmp_path):
        creds_dir = tmp_path / "creds"
        creds_dir.mkdir()
        creds_file = creds_dir / "personal.json"
        creds_file.write_text(json.dumps({
            "client_id": "test-id",
            "client_secret": "test-secret",
            "refresh_token": "test-refresh-token",
        }))
        config = {
            "accounts": {
                "personal": {
                    "email": "test@gmail.com",
                    "category": "personal",
                    "credentials_file": str(creds_file),
                }
            }
        }
        config_path = tmp_path / "gmail_accounts.json"
        config_path.write_text(json.dumps(config))

        mgr = GmailAccountManager(str(config_path))

        # First call — refreshes token
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "ya29.test-token",
            "expires_in": 3600,
        }
        mock_response.raise_for_status = MagicMock()

        with patch("gmail_auth.requests.post", return_value=mock_response) as mock_post:
            token1 = mgr.get_access_token("personal")
            # Second call — should use cached token, NOT call post again
            token2 = mgr.get_access_token("personal")
            assert mock_post.call_count == 1

        assert token1 == token2 == "ya29.test-token"

    def test_get_access_token_raises_on_missing_account(self, tmp_path):
        config_path = tmp_path / "gmail_accounts.json"
        config_path.write_text(json.dumps({"accounts": {}}))
        mgr = GmailAccountManager(str(config_path))
        with pytest.raises(ValueError, match="Account 'nonexistent' not found"):
            mgr.get_access_token("nonexistent")

    def test_missing_config_file_logs_warning(self, tmp_path):
        mgr = GmailAccountManager(str(tmp_path / "nonexistent.json"))
        assert len(mgr.accounts) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/gslee/Projects/Job-Applications && python3 -m pytest test_gmail_auth.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gmail_auth'`

- [ ] **Step 3: Implement `gmail_auth.py`**

Create `gmail_auth.py` — adapted from Contact-Mgmt's `google_contacts/auth.py`. Same two-layer credential pattern, but with Gmail scopes and `GmailAccountManager` class name:

```python
"""Gmail OAuth2 authentication and multi-account token management.

Adapted from Contact-Mgmt's google_contacts/auth.py.
Uses the same two-layer credential file pattern:
  - gmail_accounts.json: account metadata (email, category, credentials_file path)
  - creds/*.json: per-account OAuth2 secrets (client_id, client_secret, refresh_token)

Access tokens are held in memory only — never persisted to disk.
Refresh tokens are read from per-account JSON files on startup.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

VALID_CATEGORIES = {"personal", "work"}
TOKEN_URL = "https://oauth2.googleapis.com/token"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
]


@dataclass
class AccountConfig:
    key: str
    email: str
    category: str
    client_id: str
    client_secret: str
    refresh_token: str
    credentials_file: str = ""

    @classmethod
    def from_dict(cls, key: str, data: dict) -> AccountConfig:
        return cls(
            key=key,
            email=data.get("email", ""),
            category=data.get("category", "personal") if data.get("category", "personal") in VALID_CATEGORIES else "personal",
            client_id=data.get("client_id", ""),
            client_secret=data.get("client_secret", ""),
            refresh_token=data.get("refresh_token", ""),
            credentials_file=data.get("credentials_file", ""),
        )


class GmailAccountManager:
    """Loads account config and manages OAuth2 access tokens for Gmail API."""

    def __init__(self, config_path: str):
        self.accounts: dict[str, AccountConfig] = {}
        self._tokens: dict[str, dict] = {}  # account_key -> {"token": str, "expires_at": float}
        self._load_config(config_path)

    def _load_config(self, config_path: str) -> None:
        path = Path(config_path)
        if not path.exists():
            logger.warning(f"Gmail config file not found: {config_path}")
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Failed to read Gmail config: {e}")
            return

        for key, acct_data in data.get("accounts", {}).items():
            # Load credentials from separate file if specified
            creds_file = acct_data.get("credentials_file", "")
            if creds_file:
                try:
                    creds = json.loads(Path(creds_file).read_text(encoding="utf-8"))
                    acct_data.update(creds)
                except (json.JSONDecodeError, OSError) as e:
                    logger.error(f"Failed to load credentials for '{key}': {e}")
                    continue
            self.accounts[key] = AccountConfig.from_dict(key, acct_data)

        logger.info(f"Loaded {len(self.accounts)} Gmail account(s): {list(self.accounts.keys())}")

    def get_access_token(self, account: str) -> str:
        """Get a valid access token for the given account, refreshing if needed.

        Raises ValueError if the account is not configured.
        """
        if account not in self.accounts:
            raise ValueError(f"Account '{account}' not found. Configured: {list(self.accounts.keys())}")

        # Check cache
        cached = self._tokens.get(account)
        if cached and cached["expires_at"] > time.time():
            return cached["token"]

        # Refresh
        cfg = self.accounts[account]
        resp = requests.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": cfg.client_id,
                "client_secret": cfg.client_secret,
                "refresh_token": cfg.refresh_token,
            },
            timeout=15,
        )
        resp.raise_for_status()
        token_data = resp.json()

        access_token = token_data["access_token"]
        expires_in = token_data.get("expires_in", 3600)
        expires_at = time.time() + expires_in - 60  # 60s safety margin

        self._tokens[account] = {"token": access_token, "expires_at": expires_at}
        logger.info(f"Refreshed Gmail access token for '{account}' (expires in {int(expires_in)}s)")
        return access_token

    def category_for(self, account: str) -> str:
        """Return the category for an account key."""
        if account not in self.accounts:
            raise ValueError(f"Account '{account}' not found")
        return self.accounts[account].category

    def account_for_category(self, category: str) -> str | None:
        """Return the first account key matching the given category, or None."""
        for key, cfg in self.accounts.items():
            if cfg.category == category:
                return key
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/gslee/Projects/Job-Applications && python3 -m pytest test_gmail_auth.py -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/gslee/Projects/Job-Applications
git add gmail_auth.py test_gmail_auth.py
git commit -m "feat: add Gmail OAuth2 module (gmail_auth.py) for job digest

Adapted from Contact-Mgmt's AccountManager pattern. Two-layer
credential files, in-memory token caching, Gmail readonly+modify scopes."
```

---

### Task 2: Gmail OAuth Setup Script (`gmail_auth_setup.py`)

**Files:**
- Create: `gmail_auth_setup.py`

- [ ] **Step 1: Write the setup script**

Create `gmail_auth_setup.py` — one-time browser consent flow, adapted from Contact-Mgmt's `google_auth_setup.py`:

```python
#!/usr/bin/env python3
"""One-time Gmail OAuth2 setup script.

Runs the browser consent flow to obtain a refresh token for Gmail API access.
Adapted from Contact-Mgmt's google_auth_setup.py.

Usage:
    python3 gmail_auth_setup.py --account personal --client-id XXX --client-secret YYY

After consent, saves {client_id, client_secret, refresh_token} to
creds/<account>.json and prints a snippet for gmail_accounts.json.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import requests

TOKEN_URL = "https://oauth2.googleapis.com/token"
REDIRECT_URI = "http://localhost"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
]


def build_auth_url(client_id: str) -> str:
    scope_str = " ".join(SCOPES)
    return (
        f"https://accounts.google.com/o/oauth2/v2/auth?"
        f"client_id={client_id}&redirect_uri={REDIRECT_URI}&"
        f"response_type=code&scope={scope_str}&access_type=offline&prompt=consent"
    )


def exchange_code(code: str, client_id: str, client_secret: str) -> dict:
    resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": REDIRECT_URI,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def main() -> int:
    parser = argparse.ArgumentParser(description="Gmail OAuth2 setup — obtain refresh token")
    parser.add_argument("--account", required=True, help="Account key (e.g., 'personal')")
    parser.add_argument("--client-id", required=True, help="Google OAuth2 client ID")
    parser.add_argument("--client-secret", required=True, help="Google OAuth2 client secret")
    args = parser.parse_args()

    auth_url = build_auth_url(args.client_id)
    print("\n" + "=" * 70)
    print("GMAIL OAUTH2 SETUP")
    print("=" * 70)
    print(f"\nAccount: {args.account}")
    print(f"Scopes: {', '.join(SCOPES)}")
    print(f"\n1. Open this URL in your browser:\n\n   {auth_url}\n")
    print("2. Grant consent to the Gmail API scopes.")
    print("3. After consent, Google redirects to a URL that won't load.")
    print("   Copy the FULL redirect URL from your browser address bar.\n")

    redirect_url = input("4. Paste the redirect URL here: ").strip()
    if not redirect_url:
        print("ERROR: No redirect URL provided.")
        return 1

    # Extract the code parameter
    if "code=" not in redirect_url:
        print("ERROR: URL does not contain a 'code' parameter.")
        return 1
    code = redirect_url.split("code=")[1].split("&")[0]

    print("\nExchanging authorization code for tokens...")
    try:
        token_data = exchange_code(code, args.client_id, args.client_secret)
    except requests.HTTPError as e:
        print(f"ERROR: Token exchange failed: {e}")
        print(f"Response: {e.response.text}")
        return 1

    refresh_token = token_data.get("refresh_token")
    if not refresh_token:
        print("ERROR: No refresh_token in response. Did you use prompt=consent?")
        return 1

    # Save credentials
    creds_dir = Path(__file__).resolve().parent / "creds"
    creds_dir.mkdir(exist_ok=True)
    creds_file = creds_dir / f"{args.account}.json"

    creds_data = {
        "client_id": args.client_id,
        "client_secret": args.client_secret,
        "refresh_token": refresh_token,
    }
    creds_file.write_text(json.dumps(creds_data, indent=2), encoding="utf-8")
    # Restrict permissions
    creds_file.chmod(0o600)

    print(f"\n✅ Credentials saved to {creds_file}")
    print(f"\nAdd this to gmail_accounts.json:")
    print(json.dumps({
        "accounts": {
            args.account: {
                "email": "geesin@gmail.com",
                "category": "personal",
                "credentials_file": str(creds_file),
            }
        }
    }, indent=2))
    print("\n✅ Setup complete!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Test the setup script displays help**

Run: `cd /Users/gslee/Projects/Job-Applications && python3 gmail_auth_setup.py --help`
Expected: Shows usage info with --account, --client-id, --client-secret args

- [ ] **Step 3: Commit**

```bash
cd /Users/gslee/Projects/Job-Applications
git add gmail_auth_setup.py
git commit -m "feat: add Gmail OAuth2 setup script (gmail_auth_setup.py)

One-time browser consent flow to obtain refresh token for Gmail API.
Adapted from Contact-Mgmt's google_auth_setup.py with Gmail scopes."
```

---

### Task 3: LinkedIn Email Parser (`email_parser.py`)

**Files:**
- Create: `email_parser.py`
- Test: `test_email_parser.py`

- [ ] **Step 1: Write failing tests for email parser**

Create `test_email_parser.py` with test fixtures for both digest and single-job email formats:

```python
"""Tests for email_parser — LinkedIn job-alert email HTML parsing."""
import pytest

from email_parser import parse_linkedin_email, JobCard


# --- Test fixtures (anonymised HTML snippets) ---

DIGEST_HTML = """
<html><body>
<div style="font-family:Arial;">
  <h2>10 jobs matching your search for "Account Executive Singapore"</h2>
  <div class="job-card">
    <a href="https://www.linkedin.com/jobs/view/4001234567">Client Partner - Public Sector</a>
    <span class="company">Thoughtworks</span>
    <span class="location">Singapore</span>
    <p class="snippet">Enterprise Sales &amp; Client Partner executive with 20+ years of consultative solutioning...</p>
  </div>
  <div class="job-card">
    <a href="https://www.linkedin.com/jobs/view/4009876543">Director, Government &amp; Public Sector</a>
    <span class="company">PwC</span>
    <span class="location">Singapore</span>
    <p class="snippet">Market-facing leader with deep government relationships...</p>
  </div>
</div>
</body></html>
"""

SINGLE_JOB_HTML = """
<html><body>
<div style="font-family:Arial;">
  <h2>New job for you</h2>
  <div class="job-card">
    <a href="https://www.linkedin.com/jobs/view/4005555555">Account Executive - APAC</a>
    <span class="company">Workato</span>
    <span class="location">Singapore</span>
    <p class="snippet">Own and manage strategic accounts across Singapore government...</p>
  </div>
</div>
</body></html>
"""

EMPTY_HTML = "<html><body><p>No jobs here</p></body></html>"

MALFORMED_HTML = "<html><body><div>Some broken content without job cards</div></body></html>"


class TestParseDigestEmail:
    def test_extracts_multiple_jobs_from_digest(self):
        result = parse_linkedin_email(DIGEST_HTML, email_id="msg123", email_date="2026-08-06")
        assert len(result) == 2
        assert result[0].title == "Client Partner - Public Sector"
        assert result[0].company == "Thoughtworks"
        assert result[0].location == "Singapore"
        assert result[0].url == "https://www.linkedin.com/jobs/view/4001234567"
        assert result[0].source_email_id == "msg123"
        assert result[0].source_date == "2026-08-06"

    def test_extracts_second_job(self):
        result = parse_linkedin_email(DIGEST_HTML, email_id="msg123", email_date="2026-08-06")
        assert result[1].title == "Director, Government & Public Sector"
        assert result[1].company == "PwC"

    def test_snippet_truncated_to_200_chars(self):
        result = parse_linkedin_email(DIGEST_HTML, email_id="msg123", email_date="2026-08-06")
        for job in result:
            assert len(job.snippet) <= 200


class TestParseSingleJobEmail:
    def test_extracts_single_job(self):
        result = parse_linkedin_email(SINGLE_JOB_HTML, email_id="msg456", email_date="2026-08-06")
        assert len(result) == 1
        assert result[0].title == "Account Executive - APAC"
        assert result[0].company == "Workato"
        assert result[0].source_email_id == "msg456"


class TestParseEdgeCases:
    def test_empty_email_returns_empty_list(self):
        result = parse_linkedin_email(EMPTY_HTML, email_id="msg789", email_date="2026-08-06")
        assert result == []

    def test_malformed_email_returns_empty_list(self):
        result = parse_linkedin_email(MALFORMED_HTML, email_id="msg000", email_date="2026-08-06")
        assert result == []

    def test_null_location_handled(self):
        html = """
        <html><body>
        <div class="job-card">
            <a href="https://www.linkedin.com/jobs/view/4001111111">Remote Role</a>
            <span class="company">TestCo</span>
            <p class="snippet">A remote position</p>
        </div>
        </body></html>
        """
        result = parse_linkedin_email(html, email_id="m1", email_date="2026-08-06")
        assert len(result) == 1
        assert result[0].location is None or result[0].location == ""

    def test_missing_snippet_defaults_to_empty_string(self):
        html = """
        <html><body>
        <div class="job-card">
            <a href="https://www.linkedin.com/jobs/view/4002222222">No Snippet Role</a>
            <span class="company">TestCo</span>
            <span class="location">Singapore</span>
        </div>
        </body></html>
        """
        result = parse_linkedin_email(html, email_id="m2", email_date="2026-08-06")
        assert len(result) == 1
        assert result[0].snippet == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/gslee/Projects/Job-Applications && python3 -m pytest test_email_parser.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'email_parser'`

- [ ] **Step 3: Implement `email_parser.py`**

Create `email_parser.py`:

```python
"""LinkedIn job-alert email parser.

Extracts structured job data from LinkedIn job-alert email HTML.
Supports two formats:
  - Digest: "X jobs matching your search for Y" — multiple job cards
  - Single: "New job for you" / "Recommended job" — single role notification

Parsing strategy: BeautifulSoup on HTML body. LinkedIn uses consistent card
layouts. We look for <a> tags with /jobs/view/ or /jobs/search/ URLs, then
extract surrounding card containers for title, company, location, snippet.

Fallback: If parsing fails for an email, log a warning and return an empty
list (don't block the pipeline).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

LINKEDIN_JOB_URL_PATTERN = re.compile(
    r"https?://www\.linkedin\.com/jobs/(view|search)/\d+"
)

MAX_SNIPPET_LENGTH = 200


@dataclass
class JobCard:
    title: str
    company: str
    location: str | None
    url: str
    snippet: str
    source_email_id: str
    source_date: str


def _truncate_snippet(text: str, max_len: int = MAX_SNIPPET_LENGTH) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len].rsplit(" ", 1)[0] + "..."


def _extract_job_cards(soup: BeautifulSoup, email_id: str, email_date: str) -> list[JobCard]:
    """Extract job cards from LinkedIn email HTML."""
    jobs: list[JobCard] = []

    # Find all links that point to LinkedIn job URLs
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if not LINKEDIN_JOB_URL_PATTERN.match(href):
            continue

        title = link.get_text(strip=True)
        if not title:
            continue

        # Walk up to find the card container
        card = link
        for _ in range(5):  # Look up to 5 levels up for a card container
            parent = card.parent
            if parent is None:
                break
            parent_text = parent.get_text(strip=True)
            # A card container should have substantially more text than just the title
            if len(parent_text) > len(title) + 10:
                card = parent
                break
            card = parent

        # Extract company, location, snippet from the card
        card_text = card.get_text(separator="\n", strip=True)
        card_lines = [line.strip() for line in card_text.split("\n") if line.strip()]

        # Company is usually the line after the title, or in a span with class "company"
        company = ""
        company_el = card.find("span", class_="company")
        if company_el:
            company = company_el.get_text(strip=True)
        elif len(card_lines) > 1:
            # Fallback: try to find company by proximity to title
            for i, line in enumerate(card_lines):
                if line == title and i + 1 < len(card_lines):
                    company = card_lines[i + 1]
                    break

        # Location
        location = None
        location_el = card.find("span", class_="location")
        if location_el:
            location = location_el.get_text(strip=True)
        else:
            # Fallback: look for common location patterns
            for line in card_lines:
                if any(kw in line for kw in ["Singapore", "APAC", "Remote", "Hybrid", "On-site"]):
                    location = line
                    break

        # Snippet
        snippet = ""
        snippet_el = card.find("p", class_="snippet")
        if snippet_el:
            snippet = snippet_el.get_text(strip=True)
        else:
            # Fallback: use remaining text after title and company
            remaining = [l for l in card_lines if l != title and l != company and l != (location or "")]
            if remaining:
                snippet = " ".join(remaining)

        jobs.append(JobCard(
            title=title,
            company=company or "Unknown",
            location=location,
            url=href,
            snippet=_truncate_snippet(snippet),
            source_email_id=email_id,
            source_date=email_date,
        ))

    return jobs


def parse_linkedin_email(html: str, email_id: str, email_date: str) -> list[JobCard]:
    """Parse a LinkedIn job-alert email HTML and return a list of JobCards.

    Args:
        html: Full HTML content of the email body
        email_id: Gmail message ID (for Trash operations and reference)
        email_date: ISO-8601 date string (email send date)

    Returns:
        List of JobCard objects. Empty list if no jobs found or parsing fails.
    """
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception as e:
        logger.warning(f"Failed to parse email {email_id}: {e}")
        return []

    try:
        jobs = _extract_job_cards(soup, email_id, email_date)
        if jobs:
            logger.info(f"Parsed {len(jobs)} job(s) from email {email_id}")
        else:
            logger.info(f"No jobs found in email {email_id}")
        return jobs
    except Exception as e:
        logger.warning(f"Error extracting jobs from email {email_id}: {e}")
        return []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/gslee/Projects/Job-Applications && python3 -m pytest test_email_parser.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/gslee/Projects/Job-Applications
git add email_parser.py test_email_parser.py
git commit -m "feat: add LinkedIn email parser (email_parser.py)

Parses digest and single-job formats from LinkedIn job-alert emails.
Extracts title, company, location, URL, snippet from HTML.
Graceful fallback on parse failures."
```

---

### Task 4: Daily Job Digest Script (`job_digest.py`)

**Files:**
- Create: `job_digest.py`
- Test: `test_job_digest.py`

- [ ] **Step 1: Write failing tests for the digest pipeline**

Create `test_job_digest.py`:

```python
"""Tests for job_digest — daily Gmail ingestion pipeline."""
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from job_digest import (
    load_tracker,
    deduplicate_jobs,
    prefilter_jobs,
    write_digest_markdown,
    load_prefilter_keywords,
)


# --- Fixtures ---

SAMPLE_TRACKER = {
    "schema_version": "1.0",
    "applications": [
        {
            "id": "abc-123",
            "company": "Thoughtworks",
            "role_title": "Client Partner",
            "jd_source_url": "https://www.linkedin.com/jobs/view/4001234567",
            "stage": "new",
        }
    ],
}

SAMPLE_JOBS = [
    # Already tracked (URL match)
    {"title": "Client Partner", "company": "Thoughtworks", "location": "Singapore",
     "url": "https://www.linkedin.com/jobs/view/4001234567", "snippet": "Enterprise sales role..."},
    # New job (not tracked)
    {"title": "Account Executive", "company": "Workato", "location": "Singapore",
     "url": "https://www.linkedin.com/jobs/view/4009999999", "snippet": "Own and manage strategic accounts..."},
    # Already tracked (fuzzy title match)
    {"title": "Client Partner - PH&LS", "company": "Thoughtworks", "location": "Singapore",
     "url": "https://www.linkedin.com/jobs/view/4008888888", "snippet": "Healthcare and public sector..."},
    # Irrelevant (wrong location, junior level)
    {"title": "Junior Developer", "company": "Some Startup", "location": "Remote",
     "url": "https://www.linkedin.com/jobs/view/4007777777", "snippet": "Entry-level programming role..."},
]


class TestDeduplicateJobs:
    def test_url_exact_match_is_tracked(self):
        result = deduplicate_jobs(SAMPLE_JOBS, SAMPLE_TRACKER)
        # URL match on Thoughtworks Client Partner
        tracked_urls = [j["url"] for j in result["already_tracked"]]
        assert "https://www.linkedin.com/jobs/view/4001234567" in tracked_urls

    def test_fuzzy_title_match_is_tracked(self):
        result = deduplicate_jobs(SAMPLE_JOBS, SAMPLE_TRACKER)
        # "Client Partner - PH&LS" at Thoughtworks should fuzzy-match
        tracked_companies = [j["company"] for j in result["already_tracked"]]
        assert "Thoughtworks" in tracked_companies

    def test_new_job_not_tracked(self):
        result = deduplicate_jobs(SAMPLE_JOBS, SAMPLE_TRACKER)
        new_urls = [j["url"] for j in result["new"]]
        assert "https://www.linkedin.com/jobs/view/4009999999" in new_urls

    def test_counts_add_up(self):
        result = deduplicate_jobs(SAMPLE_JOBS, SAMPLE_TRACKER)
        total = len(result["new"]) + len(result["already_tracked"])
        assert total == len(SAMPLE_JOBS)

    def test_empty_tracker_marks_all_new(self):
        empty_tracker = {"schema_version": "1.0", "applications": []}
        result = deduplicate_jobs(SAMPLE_JOBS, empty_tracker)
        assert len(result["new"]) == len(SAMPLE_JOBS)
        assert len(result["already_tracked"]) == 0


class TestPrefilterJobs:
    def test_singapore_jobs_pass(self):
        keywords = load_prefilter_keywords(Path(__file__).parent / "Base CV" / "Reference_CV.md")
        jobs = [
            {"title": "Account Executive", "company": "Workato", "location": "Singapore",
             "url": "https://example.com/1", "snippet": "Enterprise sales role"},
        ]
        result = prefilter_jobs(jobs, keywords)
        assert len(result["surfaced"]) == 1
        assert len(result["below_threshold"]) == 0

    def test_remote_junior_role_filtered(self):
        keywords = load_prefilter_keywords(Path(__file__).parent / "Base CV" / "Reference_CV.md")
        jobs = [
            {"title": "Junior Developer", "company": "Startup", "location": "Remote",
             "url": "https://example.com/2", "snippet": "Entry-level programming"},
        ]
        result = prefilter_jobs(jobs, keywords)
        assert len(result["surfaced"]) == 0
        assert len(result["below_threshold"]) == 1

    def test_senior_title_passes_without_singapore(self):
        keywords = load_prefilter_keywords(Path(__file__).parent / "Base CV" / "Reference_CV.md")
        jobs = [
            {"title": "Director of Sales", "company": "TechCorp", "location": "London",
             "url": "https://example.com/3", "snippet": "Senior sales leadership"},
        ]
        result = prefilter_jobs(jobs, keywords)
        assert len(result["surfaced"]) == 1  # "Director" is a senior keyword


class TestWriteDigestMarkdown:
    def test_creates_digest_file(self, tmp_path):
        digest_dir = tmp_path / "digests"
        digest_dir.mkdir()
        date_str = "2026-08-06"
        surfaced = [
            {"title": "Account Executive", "company": "Workato", "location": "Singapore",
             "url": "https://www.linkedin.com/jobs/view/4009999999", "snippet": "Own and manage strategic accounts"},
        ]
        below_threshold = [
            {"title": "Junior Developer", "company": "Startup", "location": "Remote",
             "url": "https://www.linkedin.com/jobs/view/4007777777", "snippet": "Entry-level programming"},
        ]
        stats = {"total_processed": 4, "surfaced": 1, "below_threshold": 1, "already_tracked": 2}

        path = write_digest_markdown(digest_dir, date_str, surfaced, below_threshold, stats)
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "Workato" in content
        assert "Account Executive" in content
        assert "Below Threshold" in content
        assert "4 jobs processed" in content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/gslee/Projects/Job-Applications && python3 -m pytest test_job_digest.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'job_digest'`

- [ ] **Step 3: Implement `job_digest.py`**

Create `job_digest.py` — the main pipeline script. This is the largest file. Key functions:

```python
#!/usr/bin/env python3
"""Job Applications — daily job digest pipeline.

Standalone script (stdlib + requests + beautifulsoup4). Runs on pi-4 via
job-applications-digest.timer (daily 02:00). Independent of the MCP server.

Steps:
  1. Authenticate with Gmail API via OAuth2 (refresh token flow)
  2. Query Gmail for LinkedIn job-alert emails since last run
  3. Parse job listings from each email
  4. De-duplicate against tracker.json
  5. Apply lightweight keyword pre-filter against Reference_CV.md
  6. Write daily Markdown digest to digests/YYYY-MM-DD.md
  7. Send summary email via SMTP
  8. Move processed LinkedIn emails to Trash
"""

from __future__ import annotations

import json
import os
import re
import smtplib
import sys
from datetime import date, datetime, timezone
from email.message import EmailMessage
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import requests
from bs4 import BeautifulSoup

from email_parser import parse_linkedin_email, JobCard
from gmail_auth import GmailAccountManager

_SRC_DIR = Path(__file__).resolve().parent

BASE_DIR = Path(os.environ.get("JOB_APP_BASE_DIR", str(_SRC_DIR)))
TRACKER_PATH = Path(os.environ.get("JOB_APP_TRACKER_PATH", str(BASE_DIR / "tracker.json")))
ARTEFACTS_DIR = Path(os.environ.get("JOB_APP_ARTEFACTS_DIR", str(BASE_DIR)))
DIGEST_DIR = ARTEFACTS_DIR / "digests"
PROFILE_PATH = Path(os.environ.get("JOB_APP_PROFILE_PATH", str(BASE_DIR / "profile.json")))
REFERENCE_CV_PATH = BASE_DIR / "Base CV" / "Reference_CV.md"
GMAIL_ACCOUNTS_CONFIG = os.environ.get("GMAIL_ACCOUNTS_CONFIG", str(_SRC_DIR / "gmail_accounts.json"))
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
DIGEST_EMAIL = os.environ.get("JOB_DIGEST_RECIPIENT", "geesin.lee@gmail.com")  # SMTP sender (official work account)
LOG_PATH = Path(os.environ.get("JOB_APP_TRACKER_LOG_PATH", str(_SRC_DIR / "job_digest.log")))

SENIOR_KEYWORDS = re.compile(
    r"director|vp|vice president|partner|head|lead|senior|principal|chief|c-level|c-suite|manager",
    re.IGNORECASE,
)
LOCATION_KEYWORDS = re.compile(r"singapore|apac|asia pacific", re.IGNORECASE)
LAST_RUN_FILE = DIGEST_DIR / ".last_run"

# --- Logging ---

def _log(message: str) -> None:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {message}\n")

# --- Tracker ---

def load_tracker(path: Path) -> dict:
    if not path.exists():
        return {"applications": []}
    return json.loads(path.read_text(encoding="utf-8"))

# --- De-duplication ---

def _levenshtein(s1: str, s2: str) -> int:
    """Simple Levenshtein distance for fuzzy title matching."""
    if len(s1) < len(s2):
        return _levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)
    prev_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = prev_row[j + 1] + 1
            deletions = curr_row[j] + 1
            substitutions = prev_row[j] + (c1 != c2)
            curr_row.append(min(insertions, deletions, substitutions))
        prev_row = curr_row
    return prev_row[-1]


def deduplicate_jobs(jobs: list[dict], tracker: dict) -> dict:
    """De-duplicate jobs against tracker.json.

    Returns {"new": [...], "already_tracked": [...]}
    """
    tracked_urls = set()
    tracked_entries = []
    for app in tracker.get("applications", []):
        url = app.get("jd_source_url", "")
        if url:
            tracked_urls.add(url)
        tracked_entries.append({
            "company": (app.get("company") or "").lower(),
            "role_title": (app.get("role_title") or "").lower(),
            "url": url,
        })

    new_jobs = []
    already_tracked = []

    for job in jobs:
        url = job.get("url", "")
        company_lower = (job.get("company") or "").lower()
        title_lower = (job.get("title") or "").lower()

        # Stage 1: URL exact match
        if url in tracked_urls:
            already_tracked.append(job)
            continue

        # Stage 2: Company+Title fuzzy match
        is_tracked = False
        for entry in tracked_entries:
            if entry["company"] == company_lower and _levenshtein(title_lower, entry["role_title"]) <= 3:
                already_tracked.append(job)
                is_tracked = True
                break

        if not is_tracked:
            new_jobs.append(job)

    return {"new": new_jobs, "already_tracked": already_tracked}

# --- Pre-filter ---

def load_prefilter_keywords(reference_cv_path: Path) -> dict:
    """Load keywords from Reference_CV.md for pre-filtering.

    Returns dict with keys: senior_titles, locations, skills, industries
    """
    if not reference_cv_path.exists():
        return {"senior_titles": SENIOR_KEYWORDS, "locations": LOCATION_KEYWORDS, "skills": [], "industries": []}

    cv_text = reference_cv_path.read_text(encoding="utf-8").lower()

    # Extract skills and industries from the CV text
    # Look for the Technical Skills section
    skills = []
    industries = ["public sector", "government", "telco", "telecommunications", "iot",
                  "saas", "consulting", "healthcare", "life sciences"]

    # Simple keyword extraction from Technical Skills section
    skills_section = re.search(r"technical skills(.*?)(?:\n---|\n##|\Z)", cv_text, re.DOTALL)
    if skills_section:
        skills_text = skills_section.group(1)
        # Extract individual skill terms
        for line in skills_text.split("\n"):
            line = line.strip().lstrip("-*• ").rstrip(",")
            if line and len(line) > 2:
                skills.extend([w.strip() for w in line.split(",")])

    # Also extract from Core Competencies section
    comp_section = re.search(r"core competencies(.*?)(?:\n---|\n##|\Z)", cv_text, re.DOTALL)
    if comp_section:
        comp_text = comp_section.group(1)
        for line in comp_text.split("\n"):
            line = line.strip().lstrip("-*• ").rstrip(",")
            if line and len(line) > 5:
                skills.append(line)

    return {
        "senior_titles": SENIOR_KEYWORDS,
        "locations": LOCATION_KEYWORDS,
        "skills": skills,
        "industries": industries,
    }


def prefilter_jobs(jobs: list[dict], keywords: dict) -> dict:
    """Apply lightweight keyword pre-filter to categorise jobs.

    Returns {"surfaced": [...], "below_threshold": [...]}
    """
    surfaced = []
    below_threshold = []

    for job in jobs:
        title = job.get("title", "")
        company = job.get("company", "")
        location = job.get("location", "") or ""
        snippet = job.get("snippet", "")

        text = f"{title} {company} {location} {snippet}".lower()

        # A job passes the pre-filter if ANY of:
        # 1. Title contains senior keywords
        # 2. Location mentions Singapore/APAC
        # 3. Text contains skill/industry keywords from Reference CV
        passes = False

        if keywords["senior_titles"].search(title):
            passes = True
        elif keywords["locations"].search(text):
            passes = True
        else:
            # Check skill/industry keywords
            for kw in keywords.get("skills", []):
                if kw.lower() in text:
                    passes = True
                    break
            if not passes:
                for ind in keywords.get("industries", []):
                    if ind in text:
                        passes = True
                        break

        if passes:
            surfaced.append(job)
        else:
            below_threshold.append(job)

    return {"surfaced": surfaced, "below_threshold": below_threshold}

# --- Digest Writing ---

def write_digest_markdown(
    digest_dir: Path,
    date_str: str,
    surfaced: list[dict],
    below_threshold: list[dict],
    stats: dict,
) -> Path:
    """Write the daily Markdown digest file.

    Returns the path to the written file.
    """
    digest_dir.mkdir(parents=True, exist_ok=True)
    path = digest_dir / f"{date_str}.md"

    lines = [f"# Job Discoveries — {date_str}", ""]

    if surfaced:
        lines.append("## Surfaced for Review\n")
        for job in surfaced:
            lines.append(f"### {job.get('company', 'Unknown')} — {job.get('title', 'Unknown')}")
            lines.append(f"- **Location:** {job.get('location', 'Not specified')}")
            lines.append(f"- **URL:** {job.get('url', 'N/A')}")
            lines.append(f"- **Snippet:** {job.get('snippet', 'No description available')}")
            lines.append(f"- **Category:** surfaced")
            lines.append("")
            lines.append("---")
            lines.append("")

    lines.append(f"*{stats['total_processed']} jobs processed, {stats['surfaced']} surfaced, {stats['below_threshold']} below threshold, {stats['already_tracked']} already tracked.*")
    lines.append("")

    if below_threshold:
        lines.append("---\n")
        lines.append("## Below Threshold\n")
        for job in below_threshold:
            lines.append(f"### {job.get('company', 'Unknown')} — {job.get('title', 'Unknown')}")
            lines.append(f"- **Location:** {job.get('location', 'Not specified')}")
            lines.append(f"- **URL:** {job.get('url', 'N/A')}")
            lines.append(f"- **Snippet:** {job.get('snippet', 'No description available')}")
            lines.append(f"- **Reason:** Below pre-filter threshold (no senior keywords, Singapore/APAC location, or skill/industry match)")
            lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
    return path

# --- Gmail API ---

def query_linkedin_emails(mgr: GmailAccountManager, account: str, after_date: str) -> list[dict]:
    """Query Gmail API for LinkedIn job-alert emails since after_date.

    Returns list of dicts with 'id', 'date', 'html' keys.
    """
    token = mgr.get_access_token(account)

    # Gmail API query: from LinkedIn, after the specified date
    query = f"from:notifications@linkedin.com OR from:jobs-noreply@linkedin.com after:{after_date}"

    resp = requests.get(
        "https://gmail.googleapis.com/gmail/v1/users/me/messages",
        headers={"Authorization": f"Bearer {token}"},
        params={"q": query, "maxResults": 50},
        timeout=30,
    )
    resp.raise_for_status()
    messages = resp.json().get("messages", [])

    result = []
    for msg in messages:
        msg_id = msg["id"]
        # Get full message
        msg_resp = requests.get(
            f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg_id}",
            headers={"Authorization": f"Bearer {token}"},
            params={"format": "full"},
            timeout=30,
        )
        msg_resp.raise_for_status()
        msg_data = msg_resp.json()

        # Extract date from headers
        headers = {h["name"]: h["value"] for h in msg_data.get("payload", {}).get("headers", [])}
        date_str = headers.get("Date", "")
        # Parse date to ISO format
        try:
            from email.utils import parsedate_to_datetime
            email_date = parsedate_to_datetime(date_str).strftime("%Y-%m-%d")
        except Exception:
            email_date = after_date  # Fallback

        # Extract HTML body
        html_body = _extract_html_body(msg_data)
        if html_body:
            result.append({
                "id": msg_id,
                "date": email_date,
                "html": html_body,
            })

    return result


def _extract_html_body(msg_data: dict) -> str | None:
    """Extract HTML body from a Gmail message."""
    payload = msg_data.get("payload", {})

    # Check for HTML content in the main payload
    if "parts" in payload:
        for part in payload["parts"]:
            if part.get("mimeType") == "text/html":
                data = part.get("body", {}).get("data", "")
                if data:
                    import base64
                    return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            # Recurse into nested parts
            if "parts" in part:
                html = _extract_html_body({"payload": part})
                if html:
                    return html
    elif payload.get("mimeType") == "text/html":
        data = payload.get("body", {}).get("data", "")
        if data:
            import base64
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

    return None


def trash_emails(mgr: GmailAccountManager, account: str, message_ids: list[str]) -> int:
    """Move emails to Trash via Gmail API. Returns count of successfully trashed emails."""
    token = mgr.get_access_token(account)
    trashed = 0
    for msg_id in message_ids:
        try:
            resp = requests.post(
                f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg_id}/trash",
                headers={"Authorization": f"Bearer {token}"},
                timeout=15,
            )
            if resp.ok:
                trashed += 1
            else:
                _log(f"Failed to trash email {msg_id}: {resp.status_code}")
        except Exception as e:
            _log(f"Error trashing email {msg_id}: {e}")
    return trashed

# --- Email Digest ---

def _send_digest_email(subject: str, body: str) -> bool:
    """Send the digest via Gmail SMTP + App Password."""
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
    except Exception as e:
        _log(f"Failed to send digest email: {e}")
        return False


def _format_digest_email(surfaced: list[dict], stats: dict, date_str: str) -> tuple[str, str]:
    """Return (subject, body) for the digest email."""
    subject = f"Job Discoveries — {date_str}: {len(surfaced)} new roles"
    lines = [f"Job Discoveries for {date_str}", ""]
    if surfaced:
        lines.append("🔥 Top Matches:")
        for i, job in enumerate(surfaced, 1):
            lines.append(f"  {i}. {job.get('company', 'Unknown')} — {job.get('title', 'Unknown')}")
    else:
        lines.append("No new roles surfaced today.")
    lines.append("")
    lines.append(f"📊 Stats: {stats['total_processed']} processed, {stats['surfaced']} surfaced, {stats['below_threshold']} below threshold, {stats['already_tracked']} already tracked")
    lines.append("")
    lines.append(f'Review in Claude Desktop: review_daily_discoveries("{date_str}")')
    return subject, "\n".join(lines)

# --- Main Pipeline ---

def main() -> int:
    """Run the daily job digest pipeline."""
    _log("job_digest.py starting")

    # 0. Create digest directory
    DIGEST_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Load last run date
    if LAST_RUN_FILE.exists():
        after_date = LAST_RUN_FILE.read_text(encoding="utf-8").strip()
    else:
        # First run: look back 7 days
        from datetime import timedelta
        after_date = (date.today() - timedelta(days=7)).isoformat()

    today = date.today().isoformat()

    # 2. Authenticate with Gmail API
    try:
        mgr = GmailAccountManager(GMAIL_ACCOUNTS_CONFIG)
        account = mgr.account_for_category("personal")
        if not account:
            _log("ERROR: No 'personal' Gmail account configured")
            return 1
    except Exception as e:
        _log(f"ERROR: Gmail auth failed: {e}")
        # Try to send alert email via SMTP (doesn't need Gmail API)
        _send_digest_email(
            "Job Discoveries ERROR — Gmail auth failed",
            f"Gmail authentication failed: {e}\n\nCheck gmail_accounts.json and creds/ directory."
        )
        return 1

    # 3. Query Gmail for LinkedIn emails
    try:
        emails = query_linkedin_emails(mgr, account, after_date)
    except Exception as e:
        _log(f"ERROR: Gmail query failed: {e}")
        return 1

    _log(f"Found {len(emails)} LinkedIn email(s) since {after_date}")

    # 4. Parse jobs from emails
    all_jobs: list[dict] = []
    parsed_email_ids: list[str] = []
    for email in emails:
        try:
            jobs = parse_linkedin_email(email["html"], email["id"], email["date"])
            all_jobs.extend([j.__dict__ for j in jobs])
            parsed_email_ids.append(email["id"])
        except Exception as e:
            _log(f"WARNING: Failed to parse email {email['id']}: {e}")

    _log(f"Extracted {len(all_jobs)} job(s) from {len(parsed_email_ids)} email(s)")

    # 5. De-duplicate against tracker
    tracker = load_tracker(TRACKER_PATH)
    deduped = deduplicate_jobs(all_jobs, tracker)
    new_jobs = deduped["new"]
    already_tracked = deduped["already_tracked"]

    # 6. Apply pre-filter
    keywords = load_prefilter_keywords(REFERENCE_CV_PATH)
    filtered = prefilter_jobs(new_jobs, keywords)
    surfaced = filtered["surfaced"]
    below_threshold = filtered["below_threshold"]

    # 7. Write digest
    stats = {
        "total_processed": len(all_jobs),
        "surfaced": len(surfaced),
        "below_threshold": len(below_threshold),
        "already_tracked": len(already_tracked),
    }
    digest_path = write_digest_markdown(DIGEST_DIR, today, surfaced, below_threshold, stats)
    _log(f"Wrote digest to {digest_path}")

    # 8. Send email digest
    subject, body = _format_digest_email(surfaced, stats, today)
    sent = _send_digest_email(subject, body)
    _log(f"Email digest sent: {sent}")

    # 9. Trash processed emails
    if parsed_email_ids:
        trashed = trash_emails(mgr, account, parsed_email_ids)
        _log(f"Trashed {trashed}/{len(parsed_email_ids)} email(s)")
    else:
        _log("No emails to trash")

    # 10. Update last run timestamp
    LAST_RUN_FILE.write_text(today, encoding="utf-8")

    _log(f"job_digest.py complete: {stats}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/gslee/Projects/Job-Applications && python3 -m pytest test_job_digest.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/gslee/Projects/Job-Applications
git add job_digest.py test_job_digest.py
git commit -m "feat: add daily job digest pipeline (job_digest.py)

Gmail API → parse → de-dup → pre-filter → write digest → email → trash.
Standalone script, runs at 02:00 via systemd timer on pi-4."
```

---

### Task 5: Two New MCP Tools (`review_daily_discoveries`, `ingest_from_discovery`)

**Files:**
- Modify: `job_applications_mcp_server.py` (add 2 tools at end of file, before `if __name__`)

- [ ] **Step 1: Add `review_daily_discoveries` tool to `job_applications_mcp_server.py`**

Add near the end of the file (before `if __name__`):

```python
@mcp.tool()
def review_daily_discoveries(date: str = "") -> dict:
    """Review daily job discoveries from the LinkedIn email digest.

    Returns the day's curated job cards surfaced by the 2am digest job.
    Use this each morning to see new job opportunities, then use
    score_match on individual jobs, and ingest_from_discovery to add
    them to the tracker.

    Args:
        date: ISO date string (e.g., "2026-08-06"). Defaults to today.
    """
    from datetime import date as _date

    if not date:
        date = _date.today().isoformat()

    digest_dir = ARTEFACTS_DIR / "digests"
    digest_path = digest_dir / f"{date}.md"

    if not digest_path.exists():
        return {"ok": False, "error": "no_digest_found", "date": date,
                "hint": f"No digest file found for {date}. The job digest script may not have run yet."}

    content = digest_path.read_text(encoding="utf-8")

    # Parse the markdown into structured data
    jobs = []
    current_job = None
    for line in content.split("\n"):
        if line.startswith("### ") and "Below Threshold" not in line:
            # Job header: "### Company — Title"
            header = line.lstrip("# ").strip()
            if " — " in header:
                company, title = header.split(" — ", 1)
            else:
                company, title = "", header
            current_job = {"company": company.strip(), "title": title.strip(), "category": "surfaced"}
            jobs.append(current_job)
        elif line.startswith("### ") and "Below Threshold" in line:
            current_job = None  # Skip below-threshold section in primary review
        elif current_job is not None:
            line = line.strip()
            if line.startswith("- **Location:**"):
                current_job["location"] = line.replace("- **Location:**", "").strip()
            elif line.startswith("- **URL:**"):
                current_job["url"] = line.replace("- **URL:**", "").strip()
            elif line.startswith("- **Snippet:**"):
                current_job["snippet"] = line.replace("- **Snippet:**", "").strip()
            elif line.startswith("- **Category:**"):
                current_job["category"] = line.replace("- **Category:**", "").strip()

    return {
        "ok": True,
        "date": date,
        "jobs": jobs,
        "total": len(jobs),
        "hint": "Use score_match on individual jobs for full LLM-based matching, then ingest_from_discovery to add to tracker."
    }


@mcp.tool()
def ingest_from_discovery(company: str, date: str) -> dict:
    """Ingest a discovered job from the daily digest into the tracker.

    Finds the job in the digest file for the given date, creates a tracker
    entry (stage=new), and writes JD.md to the company folder.

    Args:
        company: Company name (must match a job in the digest for that date).
        date: ISO date string matching the digest file (e.g., "2026-08-06").
    """
    from datetime import date as _date

    digest_dir = ARTEFACTS_DIR / "digests"
    digest_path = digest_dir / f"{date}.md"

    if not digest_path.exists():
        return {"ok": False, "error": "no_digest_found", "date": date}

    content = digest_path.read_text(encoding="utf-8")

    # Parse to find the matching job
    current_job = None
    jobs = []
    for line in content.split("\n"):
        if line.startswith("### "):
            header = line.lstrip("# ").strip()
            if " — " in header:
                comp, title = header.split(" — ", 1)
            else:
                comp, title = "", header
            current_job = {"company": comp.strip(), "title": title.strip()}
            jobs.append(current_job)
        elif current_job is not None:
            line = line.strip()
            if line.startswith("- **Location:**"):
                current_job["location"] = line.replace("- **Location:**", "").strip()
            elif line.startswith("- **URL:**"):
                current_job["url"] = line.replace("- **URL:**", "").strip()
            elif line.startswith("- **Snippet:**"):
                current_job["snippet"] = line.replace("- **Snippet:**", "").strip()

    # Find matching job (case-insensitive company match)
    company_lower = company.lower()
    match = None
    for job in jobs:
        if job["company"].lower() == company_lower:
            match = job
            break

    if not match:
        available = [j["company"] for j in jobs]
        return {"ok": False, "error": "job_not_found", "company": company,
                "available_companies": available}

    # Check if already in tracker
    tracker = _load_tracker(TRACKER_PATH)
    for app in tracker.get("applications", []):
        if app.get("company", "").lower() == company_lower:
            return {"ok": False, "error": "already_tracked", "company": company,
                    "existing_id": app.get("id"), "existing_stage": app.get("stage")}

    # Create tracker entry and JD.md using existing patterns
    app_id = str(uuid.uuid4())[:8]
    company_dir = ARTEFACTS_DIR / match["company"]
    company_dir.mkdir(parents=True, exist_ok=True)

    # Write JD.md
    jd_content = f"# {match['title']}\n\n"
    jd_content += f"**Company:** {match['company']}\n"
    jd_content += f"**Location:** {match.get('location', 'Not specified')}\n"
    jd_content += f"**Source:** LinkedIn job discovery ({date})\n"
    if match.get("url"):
        jd_content += f"**URL:** {match['url']}\n"
    jd_content += f"\n{match.get('snippet', 'No description available.')}\n"

    jd_path = company_dir / "JD.md"
    jd_path.write_text(jd_content, encoding="utf-8")

    # Create tracker entry
    new_app = {
        "id": app_id,
        "company": match["company"],
        "role_title": match["title"],
        "role_slug": match["title"].lower().replace(" ", "-").replace("/", "-")[:50],
        "date_created": _date.today().isoformat(),
        "stage": "new",
        "jd_path": str(jd_path),
        "jd_source_url": match.get("url", ""),
        "history": [{"stage": "new", "at": _date.today().isoformat()}],
        "followups": [],
        "outputs": {},
        "submitted": {},
    }
    tracker["applications"].append(new_app)
    _save_tracker(TRACKER_PATH, tracker)

    return {
        "ok": True,
        "application_id": app_id,
        "company": match["company"],
        "role_title": match["title"],
        "jd_path": str(jd_path),
        "hint": "Use score_match for full LLM-based matching, then save_match_score to record results."
    }
```

- [ ] **Step 2: Test the new tools manually via Claude Desktop**

After deploying, open Claude Desktop and try:
1. `review_daily_discoveries("2026-08-06")` — should return the digest for that date
2. `ingest_from_discovery("Thoughtworks", "2026-08-06")` — should create a tracker entry

- [ ] **Step 3: Commit**

```bash
cd /Users/gslee/Projects/Job-Applications
git add job_applications_mcp_server.py
git commit -m "feat: add review_daily_discoveries and ingest_from_discovery MCP tools

review_daily_discoveries: read digest file and return structured job cards.
ingest_from_discovery: create tracker entry + JD.md from digest data."
```

---

### Task 6: Systemd Deployment Units

**Files:**
- Create: `deploy/pi-4/job-applications-digest.service`
- Create: `deploy/pi-4/job-applications-digest.timer`

- [ ] **Step 1: Create the service unit**

Create `deploy/pi-4/job-applications-digest.service`:

```ini
[Unit]
Description=Job Applications Daily Job Digest Run
After=network.target nfs-client.target
RequiresMountsFor=/mnt/job-app-data

[Service]
WorkingDirectory=/home/gs/Projects/Job-Applications
ExecStart=/home/gs/Projects/Job-Applications/venv/bin/python \
          job_digest.py
EnvironmentFile=/home/gs/Projects/Job-Applications/.env
```

- [ ] **Step 2: Create the timer unit**

Create `deploy/pi-4/job-applications-digest.timer`:

```ini
[Unit]
Description=Job Applications Daily Job Digest

[Timer]
OnCalendar=*-*-* 02:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

- [ ] **Step 3: Commit**

```bash
cd /Users/gslee/Projects/Job-Applications
git add deploy/pi-4/job-applications-digest.service deploy/pi-4/job-applications-digest.timer
git commit -m "feat: add systemd units for daily job digest (02:00 timer)

Matches existing tracker.timer pattern. Runs job_digest.py daily at 02:00 SGT."
```

---

### Task 7: Gitignore and Env Updates

**Files:**
- Modify: `.gitignore`
- Modify: `.env.example`

- [ ] **Step 1: Update `.gitignore`**

Add these lines to `.gitignore`:

```
# Job digest output files
digests/

# Gmail OAuth2 credentials
creds/
client_secret_*.json

# Gmail account config (contains email, not secrets — but let's be safe)
gmail_accounts.json

# Job digest log
job_digest.log
```

- [ ] **Step 2: Update `.env.example`**

Add these lines to `.env.example`:

```
# Job digest (job_digest.py)
GMAIL_ACCOUNTS_CONFIG=gmail_accounts.json
# SMTP recipient — the official work account that SENDS digest emails.
# The Gmail API reader account (geesin@gmail.com) is configured in gmail_accounts.json.
JOB_DIGEST_RECIPIENT=geesin.lee@gmail.com
```

- [ ] **Step 3: Commit**

```bash
cd /Users/gslee/Projects/Job-Applications
git add .gitignore .env.example
git commit -m "chore: add gitignore/env entries for job digest feature

Digests dir, Gmail creds, and digest env vars."
```

---

### Task 8: Integration Test and Deployment

**Files:**
- No new files; manual deployment to pi-4

- [ ] **Step 1: Run the full test suite locally**

Run: `cd /Users/gslee/Projects/Job-Applications && python3 -m pytest -v`
Expected: All tests PASS (existing + new)

- [ ] **Step 2: Do a dry run of job_digest.py locally**

Set up a minimal `gmail_accounts.json` and creds file for testing. Run:
```bash
cd /Users/gslee/Projects/Job-Applications
python3 job_digest.py
```
Expected: Gmail auth error is expected (no real credentials yet), but the script should fail gracefully with a log message and exit code 1.

- [ ] **Step 3: Deploy to pi-4**

```bash
rsync -av --exclude venv --exclude .env --exclude __pycache__ --exclude tracker.json --exclude profile.json \
  ./ gs@gs-pi-4.local:~/Projects/Job-Applications/
```

- [ ] **Step 4: Set up Gmail OAuth credentials on pi-4**

Follow the instructions in spec section 5.10 to:
1. Create Google Cloud project / enable Gmail API
2. Create OAuth2 credentials
3. Run `gmail_auth_setup.py` on the Mac (browser consent)
4. Copy `creds/gmail-personal.json` to pi-4
5. Create `gmail_accounts.json` on pi-4

- [ ] **Step 5: Enable the systemd timer on pi-4**

```bash
ssh gs@gs-pi-4.local
cd ~/Projects/Job-Applications
python3 -m venv venv  # if not exists
venv/bin/pip install -r requirements.txt
cp .env.example .env  # then edit with real values
systemctl --user daemon-reload
systemctl --user enable job-applications-digest.timer
systemctl --user start job-applications-digest.timer
systemctl --user status job-applications-digest.timer
```

- [ ] **Step 6: Verify the timer fires correctly**

Run a manual test:
```bash
ssh gs@gs-pi-4.local
systemctl --user start job-applications-digest.service
systemctl --user status job-applications-digest.service
cat /mnt/job-app-data/digests/$(date +%Y-%m-%d).md
```

Expected: Digest file created, email sent, LinkedIn emails trashed.

- [ ] **Step 7: Update docs**

Update `docs/CURRENT_STATE.md` and `AGENTS.md` to reflect the new feature:
- New tools: `review_daily_discoveries`, `ingest_from_discovery`
- New file: `job_digest.py`, `gmail_auth.py`, `email_parser.py`
- New timer: `job-applications-digest.timer` (02:00 SGT)
- New dependency: Gmail API OAuth2

```bash
cd /Users/gslee/Projects/Job-Applications
git add docs/CURRENT_STATE.md AGENTS.md
git commit -m "docs: update CURRENT_STATE and AGENTS.md for job discovery feature"
```

---

## Spec Coverage Check

| Spec Section | Implemented In |
|---|---|
| 5.1 job_digest.py pipeline | Task 4 |
| 5.2 gmail_auth.py OAuth2 module | Task 1 |
| 5.3 email_parser.py | Task 3 |
| 5.4 Two MCP tools | Task 5 |
| 5.5 Daily Markdown digest format | Task 4 (write_digest_markdown) |
| 5.6 Email digest | Task 4 (_format_digest_email, _send_digest_email) |
| 5.7 De-duplication logic | Task 4 (deduplicate_jobs) |
| 5.8 Match scoring (pre-filter) | Task 4 (prefilter_jobs, load_prefilter_keywords) |
| 5.9 Deployment (systemd units) | Task 6 |
| 5.10 Gmail OAuth setup | Task 2 (gmail_auth_setup.py) |
| 6 Data flow | Tasks 1-4 (pipeline), Task 5 (MCP tools) |
| 7 Error handling | Task 4 (graceful fallbacks in job_digest.py) |
| 8 Testing | Tasks 1, 3, 4 (test files) |
| 9 Security | Task 7 (gitignore, creds/) |
| 10 File structure | All tasks |
| 11 Out of scope | Not implemented (by design) |