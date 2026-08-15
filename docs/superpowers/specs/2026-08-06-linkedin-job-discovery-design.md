# LinkedIn Job Discovery Feature — Design Spec

**Date:** 2026-08-06  
**Status:** Draft  
**Author:** Agent + User  
**Related:** Task 11 (`.kiro/specs/job-application-agent/tasks.md`), `Base CV/Reference_CV.md`

---

## 1. Overview

Automated daily ingestion of LinkedIn job-alert emails from Gmail, de-duplication against the existing tracker, match scoring against the candidate's reference CV, and surfacing curated job discoveries each morning via Claude Desktop (primary) and email digest (secondary). Processed emails are moved to Trash.

## 2. Goals

1. **Eliminate manual email scanning** — The 2am job reads all LinkedIn job-alert emails so you don't have to.
2. **De-duplicate automatically** — Jobs already in tracker.json are never re-surfaced.
3. **Score relevance** — Only jobs scoring ≥50 (overall match) appear in the daily review.
4. **Two-channel delivery** — Claude Desktop MCP tool for interactive review; email digest as passive heads-up.
5. **Clean inbox** — Processed LinkedIn emails are moved to Trash.

## 3. Decisions

| Decision | Choice | Rationale |
|----------|-------|-----------|
| Ingestion mechanism | Gmail API OAuth2 | Reuse Contact-Mgmt pattern; no App Password for read/modify |
| Output format | Daily Markdown file | Backing store + Obsidian archive; Claude Desktop is primary interface |
| Primary interface | Claude Desktop via MCP tools | Conversational review; `review_daily_discoveries` → pick → `ingest_from_discovery` |
| Secondary interface | Daily email digest | Passive heads-up like tracker_daily |
| Email cleanup | Move to Trash | Gmail auto-deletes Trash after 30 days |
| Scoring | Lightweight heuristic pre-filter at 2am + full LLM `score_match` on demand via Claude Desktop | No LLM calls in unattended 2am job; accurate scoring happens interactively |
| Match threshold | ≥50 overall score (applied interactively via `score_match`) | Pre-filter at 2am is coarse triage only; ≥50 threshold applies to full scoring |
| Deploy target | pi-4 | Already hosts job-applications MCP server; always-on; NFS mount |
| Schedule | 02:00 SGT daily | Before morning review; matches tracker_daily pattern |
| Reference CV | `Base CV/Reference_CV.md` | Single source of truth; all claims vetted |

## 4. Architecture

```
┌──────────────┐    ┌──────────────────┐    ┌───────────────────┐
│  Gmail API   │───▶│  job_digest.py    │───▶│ Daily Markdown    │
│  (OAuth2)    │    │  (2am timer)       │    │ digests/DATE.md  │
└──────────────┘    │                    │    └───────────────────┘
                    │  ┌──────────────┐  │    
                    │  │ tracker.json │  │    ┌───────────────────┐
                    │  │ (de-dup)     │  │───▶│ Email digest      │
                    │  └──────────────┘  │    │ (geesin.lee@...) │
                    │  ┌──────────────┐  │    └───────────────────┘
                    │  │ profile.json │  │
                    │  │ (scoring)    │  │    ┌───────────────────┐
                    │  └──────────────┘  │───▶│ Gmail Trash       │
                    │                    │    │ (processed emails)│
                    └──────────────────┘    └───────────────────┘
                              │                   
                    ┌─────────┴──────────┐    
                    │  MCP tools          │    
                    │  (review, ingest)   │    
                    └─────────┬──────────┘    
                              │                   
                    ┌─────────┴──────────┐    
                    │    Claude Desktop   │    
                    └────────────────────┘    
```

## 5. Components

### 5.1 `job_digest.py` — Daily Job Digest Script

Standalone script (like `tracker_daily.py`), runs as systemd timer on pi-4 at 02:00 SGT.

**Pipeline:**
1. Authenticate with Gmail API via OAuth2 (refresh token flow)
2. Query Gmail for LinkedIn job-alert emails since last run (`after:` timestamp)
3. Parse job listings from each email (extract: title, company, location, URL, snippet)
4. De-duplicate against tracker.json (URL-first, then company+title fuzzy match)
5. Score each unique job against profile.json using `score_match` context-prep logic
6. Filter by ≥50 overall match score
7. Write daily Markdown digest to `$JOB_APP_ARTEFACTS_DIR/digests/YYYY-MM-DD.md`
8. Send summary email to `geesin.lee@gmail.com` via SMTP (the official work account; `GMAIL_APP_PASSWORD` is for this account's SMTP, not the Gmail API reader)
9. Move processed LinkedIn emails to Trash via Gmail API

**Environment variables:**

| Var | Purpose | Source |
|-----|---------|--------|
| `JOB_APP_BASE_DIR` | Data root | Existing |
| `JOB_APP_TRACKER_PATH` | tracker.json location | Existing |
| `JOB_APP_PROFILE_PATH` | profile.json location | Existing |
| `GMAIL_ACCOUNTS_CONFIG` | Path to gmail_accounts.json | New (same pattern as Contact-Mgmt) |
| `GMAIL_APP_PASSWORD` | SMTP password for digest email (geesin.lee@gmail.com) | Existing (from tracker_daily) |
| `JOB_DIGEST_RECIPIENT` | Email recipient (SMTP target) | New (default: geesin.lee@gmail.com) |

### 5.2 `gmail_auth.py` — Gmail OAuth2 Module

Adapted from Contact-Mgmt's `google_contacts/auth.py`. Same two-layer pattern:

- `gmail_accounts.json` — account metadata (email, category, credentials_file path)
- `creds/*.json` — per-account OAuth2 secrets (client_id, client_secret, refresh_token)
- `GmailAccountManager` class with `get_access_token()` and in-memory token caching
- Scopes: `https://www.googleapis.com/auth/gmail.readonly` + `https://www.googleapis.com/auth/gmail.modify`
- `gmail_auth_setup.py` — one-time setup script for browser consent flow

**Key difference from Contact-Mgmt:** Uses `gmail.modify` scope (not just `contacts`) to support Trash operations.

### 5.3 `email_parser.py` — LinkedIn Email Parser

Extracts structured job data from LinkedIn job-alert email HTML.

**Supported email formats:**
- **Digest format:** "X jobs matching your search for Y" — contains multiple job cards
- **Single job format:** "New job for you" / "Recommended job" — single role notification

**Extracted fields per job:**
```json
{
  "title": "string",
  "company": "string",
  "location": "string | null",
  "url": "string (LinkedIn apply URL)",
  "snippet": "string (first 200 chars of description)",
  "source_email_id": "string (Gmail message ID for Trash)",
  "source_date": "ISO-8601 (email date)"
}
```

**Parsing strategy:** BeautifulSoup on HTML email body. LinkedIn uses consistent card layouts across their alert emails. Parse `<a>` tags with LinkedIn job URLs (`linkedin.com/jobs/view/` or `linkedin.com/jobs/search/`), extract card containers for title/company/location.

**Fallback:** If HTML parsing fails for an email, log a warning and skip that email (don't block the pipeline).

### 5.4 Two New MCP Tools

Added to `job_applications_mcp_server.py`:

#### `review_daily_discoveries(date: str) -> dict`

Returns the day's curated job discoveries for interactive review in Claude Desktop.

- `date` — ISO date string (e.g., "2026-08-06"). Defaults to today if empty.
- Reads `$JOB_APP_ARTEFACTS_DIR/digests/{date}.md`
- Returns structured list: title, company, location, match score, overall + sub-scores, URL, snippet
- If no digest file exists for that date, returns `{ok: False, error: "no_digest_found"}`

#### `ingest_from_discovery(company: str, date: str) -> dict`

Ingests a discovered job from the daily digest into the tracker, creating a full application record.

- `company` — Company name (must match a job in the digest)
- `date` — ISO date string matching the digest file
- Reads the digest file, finds the matching job entry
- Creates tracker record (stage=`new`), writes `JD.md` to the company folder using the snippet as JD text
- If `url` is present, also stores `jd_source_url`
- Returns `{ok: True, application_id: "...", company: "...", role_title: "..."}`

### 5.5 Daily Markdown Digest Format

File: `$JOB_APP_ARTEFACTS_DIR/digests/YYYY-MM-DD.md`

```markdown
# Job Discoveries — YYYY-MM-DD

## Company Name — Job Title (Score: NN)

- **Location:** City, Country
- **Match:** Overall NN | Skills NN | Experience NN | Industry NN
- **URL:** https://www.linkedin.com/jobs/view/...
- **Snippet:** First 200 chars of job description...

---

*(N jobs processed, M surfaced (≥50), K below threshold, D already tracked)*

---

## Below Threshold (hidden from review)

### Company Name — Job Title (Score: NN)
- **Location:** ...
- **URL:** ...
- **Reason:** Score below 50 threshold
```

The "Below Threshold" section is collapsed/hidden by default — available if the user asks Claude Desktop to show all jobs, but not in the primary review.

### 5.6 Email Digest

Sent via SMTP (same `GMAIL_APP_PASSWORD` pattern as `tracker_daily.py`):

```
To: geesin.lee@gmail.com
Subject: Job Discoveries — YYYY-MM-DD: N new roles

Job Discoveries for YYYY-MM-DD

🔥 Top Matches:
1. Company — Job Title (Score: 78)
2. Company — Job Title (Score: 65)

📊 Stats: 5 jobs processed, 2 surfaced (≥50), 1 below threshold, 2 already tracked

Review in Claude Desktop: review_daily_discoveries("YYYY-MM-DD")
```

### 5.7 De-duplication Logic

**Two-stage matching against tracker.json:**

1. **URL match** (exact): If the LinkedIn job URL already exists in any tracker entry's `jd_source_url`, skip.
2. **Company+Title fuzzy match**: If `company` + `role_title` in tracker.json is a close match (Levenshtein distance ≤ 3 on the title, exact company), flag as "already tracked" but still surface with a note.

**Result categories:**
- **New** — Not in tracker, score ≥50 → surfaced for review
- **Below threshold** — Not in tracker, score <50 → hidden section
- **Already tracked** — In tracker (URL or fuzzy match) → counted in stats, not surfaced

### 5.8 Match Scoring

**Two-phase scoring approach:**

**Phase 1 — Lightweight heuristic pre-filter (2am, unattended):**

`job_digest.py` applies a simple keyword-based filter to categorise jobs as "likely relevant" or "likely irrelevant". This is NOT a match score — it's a coarse triage that determines which jobs appear in the digest at all. Jobs that fail the pre-filter are still written to the digest file (in the "below threshold" section) but are hidden from the primary review.

Pre-filter criteria (all jobs must meet at least one):
- Title contains senior/director/VP/partner/head/lead keywords
- Location mentions Singapore or APAC
- Company or snippet contains keywords from Reference_CV.md skill/industry list
- Job is from LinkedIn (all are, by definition — this is a safety net)

**Phase 2 — Full LLM-based scoring via Claude Desktop (morning, interactive):**

When you review discoveries in Claude Desktop, the `review_daily_discoveries` tool returns jobs with their pre-filter category. You can then ask Claude to score individual jobs using the existing `score_match` tool, which uses your full `profile.json` + `Reference_CV.md` for rich, accurate scoring.

This means:
- The 2am job does NOT call any LLM API — it's purely rule-based triage
- The ≥50 threshold applies to the `score_match` result, not the pre-filter
- You see all potentially-relevant jobs in the morning; scoring happens on-demand

The digest file records the pre-filter category for each job (`surfaced` or `below_threshold`). When `score_match` is run interactively, the result is saved to the tracker entry as usual.

### 5.9 Deployment on pi-4

Two new systemd units following the existing pattern in `deploy/pi-4/`:

```
job-applications-digest.service  — one-shot, runs job_digest.py
job-applications-digest.timer    — OnCalendar=*-*-* 02:00:00, Persistent=true
```

**Dependencies:** `network.target`, `nfs-client.target`, `RequiresMountsFor=/mnt/job-app-data`

**New files to deploy:**
- `job_digest.py`
- `gmail_auth.py`
- `email_parser.py`
- `gmail_accounts.json` (config, not gitignored — contains only email metadata)
- `creds/gmail-personal.json` (gitignored — contains client_id, client_secret, refresh_token)

### 5.10 Gmail OAuth Setup

One-time setup required before first run. You've done this before for Contact-Mgmt — same pattern for `geesin@gmail.com` (the inbox where LinkedIn emails arrive).

**Scopes requested:**
- `https://www.googleapis.com/auth/gmail.readonly` — read emails
- `https://www.googleapis.com/auth/gmail.modify` — move to Trash, mark as read

**Setup steps:**

1. **Go to Google Cloud Console** → https://console.cloud.google.com
2. **Select or create a project** — You can reuse the Contact-Mgmt project or create a new one called "Job Applications"
3. **Enable Gmail API** → APIs & Services → Library → search "Gmail API" → Enable
4. **Configure OAuth consent screen** (if not already done for this project):
   - APIs & Services → OAuth consent screen
   - User type: External (or Internal if using a Google Workspace)
   - Add scope: `gmail.readonly` and `gmail.modify`
   - Add test user: `geesin@gmail.com` (the LinkedIn inbox account, NOT geesin.lee@gmail.com)
   - Publish (or keep in testing — both work for personal use)
5. **Create OAuth2 credentials**:
   - APIs & Services → Credentials → Create Credentials → OAuth client ID
   - Application type: Desktop app
   - Name: "Job Applications Gmail"
   - Download the JSON file → save as `client_secret_XXXX.json` (gitignored)
6. **Run the setup script**:
   ```bash
   cd ~/Projects/Job-Applications
   python3 gmail_auth_setup.py --account personal --client-id CLIENT_ID --client-secret CLIENT_SECRET
   ```
   This will:
   - Print an authorization URL
   - Open your browser (or you paste it manually)
   - After consent, Google redirects to `http://localhost?code=...`
   - Copy the full redirect URL from your browser address bar
   - Paste it into the script prompt
   - The script exchanges the code for a refresh token and saves it to `creds/gmail-personal.json`
7. **Create `gmail_accounts.json`**:
   ```json
   {
     "accounts": {
       "geesin": {
         "email": "geesin@gmail.com",
         "category": "personal",
         "credentials_file": "creds/geesin.json"
       }
     }
   }
   ```
   **Important:** This configures the Gmail API **reader** account (`geesin@gmail.com`) where LinkedIn job-alert emails arrive. The SMTP **sender** account (`geesin.lee@gmail.com`) is configured separately via `SMTP_*` env vars — do NOT use it here.
8. **Verify** by running `job_digest.py --dry-run` to confirm Gmail API access without writing anything.

**Troubleshooting:**
- If you see "This app isn't verified", click Advanced → Go to app (unsafe) — this is normal for personal-use apps in testing mode
- If the redirect URL doesn't load (expected — we use `http://localhost`), just copy the full URL from the address bar including the `code=` parameter
- The refresh token is long-lived; you only need to do this setup once

## 6. Data Flow — End to End

```
02:00 SGT — systemd timer fires job_digest.py
  │
  ├─ 1. Gmail API: query messages from:notifications@linkedin.com after:last_run
  │     (stores last_run timestamp in digest metadata)
  │
  ├─ 2. Parse each email → extract job cards (title, company, location, url, snippet)
  │
  ├─ 3. De-dup against tracker.json
  │     ├─ URL exact match → "already tracked"
  │     └─ Company+Title fuzzy match → "already tracked"
  │
  ├─ 4. Apply lightweight pre-filter against Reference_CV.md keywords
  │     ├─ Passes pre-filter → "surfaced" for review
  │     └─ Fails pre-filter → "below threshold" (still written, hidden from primary review)
  │
  ├─ 5. Write digest file: digests/2026-08-06.md
  │
  ├─ 6. Send summary email to geesin.lee@gmail.com (via SMTP, official work account)
  │
  └─ 7. Move processed emails to Trash via Gmail API
       (Gmail auto-deletes after 30 days)

Morning — User opens Claude Desktop
  │
  ├─ "Show me today's jobs"
  │    └─ review_daily_discoveries("2026-08-06")
  │         → returns curated job cards with pre-filter category
  │
  ├─ "Score the Thoughtworks one properly"
  │    └─ score_match + save_match_score (existing tools, full LLM scoring)
  │         → returns detailed match breakdown (overall + sub-scores)
  │         → only jobs scoring ≥50 are worth ingesting
  │
  ├─ "Ingest the Thoughtworks one"
  │    └─ ingest_from_discovery("Thoughtworks", "2026-08-06")
  │         → creates tracker entry, JD.md
  │
  ├─ "Re-score this one properly"
  │    └─ score_match + save_match_score (existing tools)
  │
  └─ "Skip the DXC one"
       └─ (no action needed — stays in digest for reference)
```

## 7. Error Handling

| Scenario | Handling |
|----------|----------|
| Gmail API auth failure | Log error, send alert email via SMTP (doesn't need Gmail API), exit with non-zero code |
| No LinkedIn emails found | Write empty digest (stats: 0 processed), no email sent, no Trash operations |
| Email parsing fails for one email | Log warning, skip that email, continue with others |
| tracker.json read failure | Log error, treat all jobs as "new" (conservative), write digest |
| profile.json / Reference_CV.md missing | Fall back to keyword-only scoring (no profile context) |
| Digest directory doesn't exist | Create `$JOB_APP_ARTEFACTS_DIR/digests/` on first run |
| Gmail Trash operation fails | Log warning, continue — digest still written, email still sent |
| `ingest_from_discovery` called for already-tracked job | Return `{ok: False, error: "already_tracked"}` |

## 8. Testing

- `test_email_parser.py` — unit tests for LinkedIn email HTML parsing (digest + single formats)
- `test_job_digest.py` — integration tests for the full pipeline (mocked Gmail API, real tracker.json)
- `test_gmail_auth.py` — unit tests for OAuth2 token refresh and caching
- Test fixtures: sample LinkedIn email HTML (anonymised) for both digest and single-job formats

## 9. Security

- **Gmail credentials** stored in `creds/` directory (gitignored, mode 600)
- **Gmail modify scope** limited to Trash operations — no email sending or label manipulation via API
- **Bearer token auth** on MCP server (existing) — digest files are local only
- **No JD content stored in digest** — only snippets (first 200 chars) and metadata. Full JD ingestion happens via `ingest_from_discovery` which uses existing `ingest_jd` logic

## 10. File Structure

```
Job-Applications/
├── job_applications_mcp_server.py   # +2 new MCP tools
├── job_digest.py                    # NEW — standalone daily digest script
├── gmail_auth.py                    # NEW — Gmail OAuth2 module
├── email_parser.py                  # NEW — LinkedIn email parser
├── gmail_auth_setup.py              # NEW — one-time OAuth setup script
├── gmail_accounts.json              # NEW — account metadata (not gitignored)
├── creds/                           # NEW — per-account OAuth2 secrets (gitignored)
│   └── gmail-personal.json
├── Base CV/
│   └── Reference_CV.md              # NEW — single source of truth CV
├── deploy/pi-4/
│   ├── job-applications-digest.service  # NEW
│   └── job-applications-digest.timer    # NEW
└── digests/                         # NEW — daily digest files (gitignored)
    ├── 2026-08-06.md
    ├── 2026-08-07.md
    └── ...
```

## 11. Out of Scope (Future Iterations)

- **`verify_jd_active()`** — Check if a JD is still live on the company's careers portal (Task 11 original scope, deferred)
- **Kanban board integration** — Daily Markdown files are the MVP; Obsidian Kanban can be added later
- **Full LLM scoring at 2am** — Heuristic pre-filter only for now; could add Gemini API call for richer scoring
- **Multi-account Gmail support** — Only `geesin@gmail.com` for reading LinkedIn emails for now; the AccountManager pattern supports future reader accounts. SMTP (sending) always uses `geesin.lee@gmail.com`.
- **Reply/apply tracking** — Tracking whether you applied to a surfaced job (use `ingest_from_discovery` + `update_stage` instead)