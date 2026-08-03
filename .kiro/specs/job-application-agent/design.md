# Technical Design Document — Job Application Agent

## Overview

The Job Application Agent is a Python/FastMCP server that extends the existing
`job_applications_mcp_server.py` into a complete lifecycle system. It is structured
as a **single-file MCP server** with a split deployment model: pi-4 owns the tracker
state and runs the MCP server as a systemd service; the NAS hosts artefact storage
(company folders, generated documents). The Mac runs transiently during active Claude
sessions only.

### Deployment Model (Fleet-Aligned)

Per the fleet hardware spec (`fleet-rationalization/docs/fleet-hardware-spec.md`)
and design spec §3:

| Device | Role | What it runs | Always-on? |
|--------|------|-------------|-----------|
| **pi-4** (`gs-pi-4`, aarch64, 1844 MB) | Tracker host + daily runner | `job-applications-tracker.service` + `job-applications-tracker.timer` (systemd, runs daily at 07:00) — reads `tracker.json`, checks overdue follow-ups, emails digest; also hosts `job-applications-mcp.service` (FastMCP HTTP :8086, always-on) owning `tracker.json` + `profile.json`; syncs to NAS after every write | 24/7 ✅ |
| **NAS** (`rv-cloud.local`, x86_64, 8 GB) | Artefact storage | NAS share (`job-app-data/`) holds company folders: JD.md, CV files, research.md, exports | 24/7 ✅ |
| **Mac** | Claude client + dev | Runs server in stdio mode during active session only; reads/writes artefacts via NAS mount | On-demand only |

**Why this split:**

- The tracker (`tracker.json`, `profile.json`) is small, low-RAM, pure-Python — a perfect fit for pi-4's aarch64 with 1844 MB. No Docker needed; systemd unit like the existing `linkedin-bot.service`.
- Artefact files (CV PDFs, DOCX exports, research documents) can be large. They belong on the NAS for disk space, not on pi-4's SD card.
- The Mac never runs an always-on service. pi-3 (armv7l 32-bit, 921 MB) cannot run `weasyprint`, `python-docx`, or FastMCP reliably.

```
Mac (Claude session, stdio — transient)
    │ calls tools via MCP stdio
    ▼
job_applications_mcp_server.py (Mac, transient)
    │ tracker ops → HTTP :8086 on pi-4  (over LAN / Tailscale)
    │ artefact reads/writes → NAS mount (/Volumes/NAS/job-app-data)
    │
    ├──────────────────────────────────────┐
    ▼                                      ▼
pi-4 gs-pi-4 :8086                   NAS rv-cloud.local
job-applications-mcp.service          /share/job-app-data/
  tracker.json  ──rsync on write──►    {Company}/JD.md
  profile.json                         {Company}/CV_tailored.md
                                        {Company}/research.md
                                        {Company}/gap_analysis.md
                                        {Company}/Cover_Letter.md
                                        {Company}/learning_program.md
                                        [.pdf / .docx exports]
```

**Sync model:** pi-4 is the write authority for `tracker.json` and `profile.json`.
After every mutating tool call, pi-4 runs `rsync tracker.json profile.json` to the NAS share as a backup. Artefact files (Markdown, PDF, DOCX) are written directly to the NAS mount.

**Daily tracker job (no Mac required):** a `job-applications-tracker.timer` fires daily at 07:00 on pi-4. The corresponding `.service` runs `tracker_daily.py` — a standalone script (not the MCP server) that:
1. Reads `tracker.json`
2. Flags any pending follow-ups as `overdue` where `due_date < today`
3. Compiles a daily digest (active applications by stage, overdue follow-ups, upcoming due dates)
4. Sends the digest by email via `smtplib` (same pattern as pi-3's GeBiz alerts, using Gmail App Password from `.env`)

This runs entirely on pi-4, independent of any Mac session or Claude interaction.

### Key Design Decisions

1. **pi-4 owns the tracker.** `tracker.json` and `profile.json` live on pi-4's local filesystem, managed by a systemd service — no Docker, matching the existing `linkedin-bot.service` pattern.

2. **NAS owns artefacts.** Company folders and all generated documents are written directly to the NAS share (mounted on the Mac, accessible from pi-4 via NFS/SMB or rsync push).

3. **Single codebase, two modes.** The same `job_applications_mcp_server.py` runs in `stdio` (Mac, dev) or `http` (pi-4, always-on) mode via `MCP_MODE` env var.

4. **Stateless tools, stateful pi-4.** Every tool reads/writes state on each call. The pi-4 service is the single write authority; the Mac stdio mode in dev connects to the same `tracker.json` on pi-4's filesystem.

5. **AI does the intelligence.** Match scoring, gap analysis, and document generation are context preparation tools — they assemble inputs and return structured prompts. Claude performs the LLM reasoning.

6. **Backward compatibility.** Existing company folders are supported without migration.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Claude (Kiro / Desktop)                      │
│         Mac — stdio (transient, on-demand only)                  │
└───────────────────────────┬─────────────────────────────────────┘
                            │ MCP stdio (Mac session, on-demand)
                            │   OR
                            │ MCP HTTP :8086 (pi-4, always-on)
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│              job_applications_mcp_server.py  (FastMCP)           │
│                                                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │  JD Ingestor │  │   Tracker    │  │   Profile Manager    │   │
│  │  (§ 4.1)     │  │   (§ 4.3)    │  │   (§ 4.2)            │   │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────┘   │
│         │                 │                      │               │
│  ┌──────▼───────┐  ┌──────▼───────┐  ┌──────────▼───────────┐   │
│  │  Path        │  │ tracker.json │  │  profile.json        │   │
│  │  Resolver    │  │  (pi-4 local)│  │  (pi-4 local)        │   │
│  │  (§ 4.4)     │  └──────┬───────┘  └──────────────────────┘   │
│  └──────┬───────┘         │ rsync on write                       │
│         │                 ▼                                       │
│  ┌──────▼────────────────────────────────────────────────────┐  │
│  │           NAS Share: job-app-data/  (§ 5)                  │  │
│  │  tracker.json (backup)  profile.json (backup)              │  │
│  │  {Company}/JD.md  research.md  gap_analysis.md             │  │
│  │  CV_tailored.md  cv_diff_summary.md  Cover_Letter.md       │  │
│  │  learning_program.md  pitch.md  [.pdf / .docx exports]     │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │              Export Engine  (§ 4.5)                       │    │
│  │   Markdown → PDF (weasyprint)  [runs on NAS container]    │    │
│  │   Markdown → DOCX (python-docx)[runs on NAS container]    │    │
│  └──────────────────────────────────────────────────────────┘    │
└─────────────────────────┬───────────────────────────────────────┘
                          │ MCP next_steps (context-prep)
          ┌───────────────┼───────────────┐
          ▼               ▼               ▼
   ai-assistant      gebiz-awards      sgdi / contacts
   :8081 (NAS)       :8085 (NAS)      :8082-8084 (NAS)
```

### pi-4 Systemd Units

Two units on pi-4 (user-level, linger on — same pattern as pi-3's GeBiz timers):

**`job-applications-mcp.service`** — always-on MCP HTTP server
```ini
[Unit]
Description=Job Applications MCP Server
After=network.target

[Service]
WorkingDirectory=/home/gs/Projects/Job-Applications
ExecStart=/home/gs/Projects/Job-Applications/venv/bin/python \
          job_applications_mcp_server.py
Environment=MCP_MODE=http
Environment=JOB_APP_BASE_DIR=/home/gs/Projects/Job-Applications/data
EnvironmentFile=/home/gs/Projects/Job-Applications/.env
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
```

**`job-applications-tracker.timer`** — daily digest, no Mac required
```ini
[Unit]
Description=Job Applications Daily Tracker

[Timer]
OnCalendar=*-*-* 07:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

**`job-applications-tracker.service`** — the daily job
```ini
[Unit]
Description=Job Applications Daily Tracker Run
After=network.target

[Service]
WorkingDirectory=/home/gs/Projects/Job-Applications
ExecStart=/home/gs/Projects/Job-Applications/venv/bin/python \
          tracker_daily.py
EnvironmentFile=/home/gs/Projects/Job-Applications/.env
```

### `tracker_daily.py` — standalone daily script

Runs independently of the MCP server. No FastMCP, no external dependencies beyond stdlib:

```
1. Load tracker.json from JOB_APP_BASE_DIR
2. For each application:
   - Mark follow-ups as overdue where due_date < today and status == "pending"
   - Save tracker.json (writes back)
   - rsync tracker.json → NAS share
3. Compile digest:
   - Active applications grouped by stage
   - Overdue follow-ups (sorted by due date)
   - Follow-ups due in next 7 days
4. Send digest email via smtplib (Gmail App Password from .env)
   - To: DIGEST_EMAIL (from .env)
   - Subject: "Job Applications Daily — {date} | {N} active, {M} overdue"
5. Log run to ~/Projects/Job-Applications/tracker_daily.log
```

### NAS Docker Compose (Export Engine only, port 8086 reserved but optional)

The NAS container is **optional** — it handles document export (weasyprint PDF, python-docx DOCX) which cannot run on pi-4 if those deps are too heavy. The MCP server primary instance is on pi-4. The NAS container, if deployed, is a pure export worker callable from the Mac or pi-4.

If weasyprint and python-docx install cleanly on pi-4 (aarch64, Debian 13), the NAS container is not needed. Verify during Task 8.

---

## Components and Interfaces

### Component Overview

| Component | File / Module | Responsibility |
|-----------|--------------|----------------|
| MCP Server (entry point) | `job_applications_mcp_server.py` | FastMCP registration, startup validation, tool dispatch |
| JD Ingestor | `_ingestor_*` functions | Parse JD from file or URL, write JD.md, register in tracker |
| Profile Manager | `_profile_*` functions | Load/save profile.json, merge, conflict detection, summary |
| Tracker | `_tracker_*` functions | Load/save tracker.json, enforce stage machine, follow-up records |
| Path Resolver | `_resolve_*` functions | Route to legacy or role-slug sub-folder |
| Export Engine | `_export_*` functions | Markdown → PDF (weasyprint) and Markdown → DOCX (python-docx) |
| Context Prep Tools | `score_match`, `analyse_gaps`, `generate_learning_program` | Assemble context dicts for Claude to perform LLM reasoning |
| Existing I/O Tools | `company_research`, `save_*`, `generate_pitch`, etc. | Preserved from v0.1.0 with targeted extensions |

### External MCP Interfaces

The server calls out to four external MCP servers when orchestrating company research:

| Server | Tools used | Purpose |
|--------|-----------|---------|
| `gebiz-awards` | `ask_question` | Singapore government procurement records |
| `sgdi` | `sgdi_query` | Singapore government directory contacts |
| `contacts` | `search_contacts`, `get_contacts_by_org` | Personal contact network |
| `ai-assistant` | `search_contacts` | Additional contact lookup |

These are **outbound MCP calls** made by Claude (the AI client) when instructed by tool responses — the MCP server itself does not call them directly. Tool responses include `next_steps` arrays with the exact MCP call syntax.

---

## Component Design

### 4.1 JD Ingestor

**Responsibility:** Accept a file path (PDF/MD/TXT) or URL, extract text, parse
structured fields, write `JD.md`, and register the application in `tracker.json`.

**Internal functions:**

```python
def _ingest_jd_file(source: Path) -> str:
    """Extract raw text from PDF, MD, or TXT."""

def _ingest_jd_url(url: str) -> str:
    """Fetch URL, strip HTML tags, return visible text."""
    # Uses: requests + BeautifulSoup (html.parser)

def _parse_jd_fields(raw_text: str) -> dict:
    """
    Return structured fields. Uses heuristic regex patterns.
    All absent fields stored as null (not omitted).
    Fields: role_title, company_name, location, employment_type,
            required_skills (list), preferred_skills (list),
            years_of_experience (int|null), responsibilities_summary (str|null)
    """

def _resolve_application_path(company: str, role_slug: str | None) -> Path:
    """Return the correct folder for this company+role (§ 4.4)."""
```

**MCP tools exposed:** `ingest_jd`, `create_application` (backward-compat alias)

---

### 4.2 Profile Manager

**Responsibility:** Manage `profile.json` — seed from CV, update from LinkedIn,
merge session data, detect conflicts, produce summaries.

**`profile.json` schema:**

```json
{
  "schema_version": "1.0",
  "headline": "string | null",
  "current_role": { "title": "string", "company": "string" },
  "work_experience": [
    {
      "title": "string",
      "company": "string",
      "start": "YYYY-MM",
      "end": "YYYY-MM | present",
      "description": "string",
      "_source": "linkedin | cv | session"
    }
  ],
  "education": [
    {
      "institution": "string",
      "degree": "string",
      "field": "string",
      "start": "YYYY | null",
      "end": "YYYY | null",
      "_source": "linkedin | cv | session"
    }
  ],
  "certifications": [
    { "name": "string", "issuer": "string", "_source": "linkedin | cv | session" }
  ],
  "skills": ["string"],
  "conflicts": [
    {
      "field_path": "string",
      "linkedin_value": "any",
      "cv_value": "any",
      "flagged_at": "ISO-8601"
    }
  ],
  "last_updated": {
    "work_experience": "ISO-8601 | null",
    "education": "ISO-8601 | null",
    "certifications": "ISO-8601 | null",
    "skills": "ISO-8601 | null"
  }
}
```

**Key rules:**
- LinkedIn source always wins in case of conflict; CV value is stored in `conflicts[]`
- `skills` list is built as a union, deduped, lowercased
- `years_of_experience` is computed on-the-fly from non-overlapping `work_experience` durations

**Internal functions:**

```python
def _load_profile() -> dict:
def _save_profile(data: dict) -> None:
def _merge_profile_section(existing: list, incoming: list, source: str) -> list:
def _compute_years_of_experience(work_exp: list) -> int:
def _top_n_skills(work_exp: list, skills: list, n: int = 5) -> list[str]:
def _seed_profile_from_cv(cv_path: Path) -> dict:
    """Parse Markdown CV and extract structured fields."""
def _parse_linkedin_export(text: str) -> dict:
    """Parse LinkedIn TXT export into profile schema."""
```

**MCP tools exposed:** `update_profile`, `get_profile_summary`, `refresh_profile_from_linkedin`

---

### 4.3 Tracker

**Responsibility:** Manage `tracker.json` — create/update application records, enforce
stage transitions, manage follow-up records.

**`tracker.json` schema:**

```json
{
  "schema_version": "1.0",
  "applications": [
    {
      "id": "uuid4-string",
      "company": "string",
      "role_title": "string",
      "role_slug": "string",
      "date_created": "ISO-8601",
      "stage": "new|applied|screening|interview_r1|interview_r2|interview_r3|offer|accepted|rejected|withdrawn",
      "jd_path": "string",
      "match_score": { "overall": 0-100, "sub_scores": {}, "computed_at": "ISO-8601" } | null,
      "history": [
        { "from_stage": "string", "to_stage": "string", "at": "ISO-8601" }
      ],
      "followups": [
        {
          "id": "uuid4-string",
          "action_type": "send_follow_up_email | send_thank_you_note",
          "due_date": "YYYY-MM-DD",
          "status": "pending | completed | cancelled | overdue",
          "completed_at": "ISO-8601 | null"
        }
      ]
    }
  ]
}
```

**Stage transition map:**

```
new → applied
applied → screening → interview_r1 → interview_r2 → interview_r3 → offer → accepted
                                                                          → rejected
                                                                          → withdrawn
[any non-terminal] → rejected
[any non-terminal] → withdrawn
```

Terminal stages: `accepted`, `rejected`, `withdrawn`

**Internal functions:**

```python
VALID_TRANSITIONS: dict[str, set[str]]  # module-level constant

def _load_tracker() -> dict:
def _save_tracker(data: dict) -> None:
def _find_application(tracker: dict, company: str, role_title: str) -> dict | None:
def _make_role_slug(role_title: str) -> str:
    """URL-safe lowercase: spaces→hyphens, strip non-alphanum."""
def _auto_create_followup(app: dict, new_stage: str) -> None:
    """Create follow-up records on stage transition (Req 11)."""
def _cancel_followup_emails(app: dict) -> None:
    """Cancel pending send_follow_up_email on interview progression."""
```

**MCP tools exposed:** `update_stage`, `list_applications`, `get_application_status`,
`get_due_followups`, `mark_followup_complete`

---

### 4.4 Path Resolver

**Responsibility:** Determine the correct Company_Folder path for any operation,
handling both legacy single-role and new multi-role layouts.

**Layout rules:**

```
# Single role (legacy or new)
BASE_DIR/{Company}/JD.md          → Company_Folder = BASE_DIR/{Company}/

# Multiple roles (new)
BASE_DIR/{Company}/{role-slug}/JD.md  → Company_Folder = BASE_DIR/{Company}/{role-slug}/
```

**Detection logic:**

```python
def _resolve_company_folder(company: str, role_title: str | None = None) -> Path:
    """
    1. If company folder has a JD.md at root and role_title is None or matches
       the title in tracker.json → return company root (legacy mode).
    2. If company folder has no root JD.md and role_title is given
       → return company/role-slug/.
    3. If multiple roles exist in tracker for this company and role_title is None
       → raise AmbiguousRoleError (caller must disambiguate).
    """
```

---

### 4.5 Export Engine

**Responsibility:** Convert `CV_tailored.md` or `Cover_Letter.md` to PDF or DOCX.

**Library choices (with graceful degradation):**

| Format | Primary library | Fallback |
|--------|----------------|---------|
| PDF    | `weasyprint`   | `md2pdf` |
| DOCX   | `python-docx`  | none (error with install instructions) |

**DOCX template spec:**
- Page margins: 2.54 cm all sides
- Body font: Calibri 11pt
- H1: Calibri 16pt Bold
- H2: Calibri 13pt Bold
- H3: Calibri 11pt Bold Italic
- Bullet list: Calibri 11pt, 0.5 cm indent

**PDF rendering:**
- Markdown → HTML (via `markdown` library) → PDF (via `weasyprint`)
- Stylesheet: A4 page, 2.5 cm margins, Georgia 11pt body, bold headings

**Internal functions:**

```python
def _export_to_pdf(source_md: Path, output_path: Path) -> None:
def _export_to_docx(source_md: Path, output_path: Path) -> None:
def _check_export_deps(fmt: str) -> list[str]:
    """Return list of missing dependencies with install commands."""
```

**MCP tool exposed:** `export_document`

---

## Data Models

### JD Structured Record (stored in tracker.json under each application)

```python
@dataclass
class JDRecord:
    role_title: str | None
    company_name: str | None
    location: str | None
    employment_type: str | None
    required_skills: list[str]
    preferred_skills: list[str]
    years_of_experience: int | None
    responsibilities_summary: str | None
    raw_text_path: str          # relative path to JD.md
    ingested_at: str            # ISO-8601
```

### Gap Item (written to gap_analysis.md)

```python
@dataclass
class GapItem:
    gap_id: str                 # uuid4
    category: Literal["missing", "understated", "mismatch"]
    jd_criterion: str
    affected_cv_section: str
    current_text_excerpt: str | None
    recommendation: str
```

### Match Score Result (stored in tracker.json)

```python
@dataclass
class MatchScoreResult:
    overall: int                # 0-100
    sub_scores: dict            # {required_skills_match, preferred_skills_match,
                                #  years_of_experience_match, industry_domain_alignment,
                                #  seniority_alignment}
    reasoning: str              # max 500 words
    strengths: list[str]        # up to 3
    gaps: list[str]             # up to 3
    missing_skills: list[str]
    computed_at: str            # ISO-8601 UTC
```

---

## MCP Tool Inventory

Full list of 15 tools (Req 12.1) mapped to modules:

| Tool name | Module | Req |
|-----------|--------|-----|
| `create_application` | JD Ingestor | 1 |
| `ingest_jd` | JD Ingestor | 1 |
| `update_profile` | Profile Manager | 2, 13 |
| `get_profile_summary` | Profile Manager | 2 |
| `refresh_profile_from_linkedin` | Profile Manager | 13 |
| `score_match` | Tracker + context prep | 3 |
| `analyse_gaps` | Tracker + context prep | 4 |
| `generate_learning_program` | Tracker + context prep | 5 |
| `tailor_cv` | context prep (existing) | 6 |
| `save_tailored_cv` | file I/O (existing) | 6 |
| `generate_cover_letter` | context prep (existing) | 7 |
| `save_cover_letter` | file I/O (existing) | 7 |
| `export_document` | Export Engine | 8 |
| `update_stage` | Tracker | 9, 11 |
| `list_applications` | Tracker | 9, 10 |
| `get_application_status` | Tracker | 9 |
| `get_due_followups` | Tracker | 11 |
| `mark_followup_complete` | Tracker | 11 |
| `company_research` | existing | 14 |
| `save_research` | existing | 14 |
| `map_territory` | existing | 14 |
| `save_territory_map` | existing | 14 |
| `generate_pitch` | existing | — |
| `save_pitch` | existing | — |

> Note: `refresh_profile_from_linkedin` and `update_profile` are additive tools
> (not in the original Req 12.1 list of 15) but are required by Reqs 2 and 13.
> The 15-tool list in Req 12.1 covers the core workflow; the above are the full set.

---

## File Structure

### Source (Mac `~/Projects/Job-Applications/`)
```
job_applications_mcp_server.py   # Main server (extended)
requirements.txt                 # Updated with new deps
Dockerfile                       # NAS container build (amd64)
docker-compose.nas.yml           # NAS UGOS compose project
.mcp.json                        # Mac stdio MCP config (env vars, no hardcoded paths)
.env.example                     # Documents all env vars
.gitignore                       # includes .env, tracker.json, profile.json
```

### NAS Docker Volume `job-app-data` (mounted at `/data` in container)
```
/data/
├── tracker.json                     # All application + follow-up records
├── profile.json                     # User profile store
│
├── Gartner/                         # Legacy single-role folder (kept as-is)
│   ├── JD.md
│   ├── research.md
│   ├── CV_tailored.md
│   ├── cv_diff_summary.md
│   ├── Cover_Letter.md
│   ├── gap_analysis.md
│   ├── learning_program.md
│   ├── pitch.md
│   └── territory_map.md
│
├── Salesforce/                      # Multi-role folder (new format)
│   ├── enterprise-ae-strategic-accounts/
│   │   ├── JD.md
│   │   ├── CV_tailored.md
│   │   └── Cover_Letter.md
│   └── solution-engineer-public-sector/
│       ├── JD.md
│       └── CV_tailored.md
└── ...
```

On Mac, `JOB_APP_BASE_DIR` points to the NAS mount path (e.g.
`/Volumes/NAS-Projects/Job-Applications`) so Mac stdio writes go to the same volume
as the NAS container. The existing `~/Projects/Job-Applications/` directory on Mac
contains **source code only** — artefacts migrate to the NAS volume.

---

## Startup Validation Sequence

On MCP server start (executed before any tool call is accepted):

```python
def _startup_validate():
    # 1. Verify BASE_DIR exists and is a directory
    if not BASE_DIR.is_dir():
        sys.stderr.write(f"[job-applications] BASE_DIR not found: {BASE_DIR}\n")
        sys.exit(1)

    # 2. Initialise tracker.json if absent
    tracker_path = BASE_DIR / "tracker.json"
    if not tracker_path.exists():
        tracker_path.write_text('{"schema_version":"1.0","applications":[]}')

    # 3. Initialise profile.json if absent
    profile_path = BASE_DIR / "profile.json"
    if not profile_path.exists():
        profile_path.write_text('{"schema_version":"1.0"}')
```

---

## Environment Variable Configuration

| Env var | pi-4 value | Mac stdio value | Purpose |
|---------|-----------|-----------------|---------|
| `JOB_APP_BASE_DIR` | `/home/gs/Projects/Job-Applications/data` | NAS mount path | Root for tracker.json, profile.json |
| `JOB_APP_ARTEFACTS_DIR` | NAS mount (e.g. `/mnt/nas/job-app-data`) | same NAS mount | Root for company artefact folders |
| `JOB_APP_TRACKER_PATH` | `{BASE_DIR}/tracker.json` | same | Tracker file |
| `JOB_APP_PROFILE_PATH` | `{BASE_DIR}/profile.json` | same | Profile file |
| `JOB_APP_BASE_CV_PATH` | `{ARTEFACTS_DIR}/DXC/CV LEE...md` | same | Default base CV |
| `MCP_AUTH_TOKEN` | set in `.env` on pi-4 | not required for stdio | Bearer auth for HTTP mode |
| `MCP_MODE` | `http` | `stdio` | FastMCP transport |
| `NAS_SYNC_PATH` | `gs@rv-cloud.local:/share/job-app-data/` | n/a | rsync destination for tracker backup |
| `DIGEST_EMAIL` | `geesin.lee@gmail.com` | n/a | Daily digest recipient |
| `GMAIL_APP_PASSWORD` | set in `.env` on pi-4 | n/a | smtplib auth (same as pi-3 GeBiz pattern) |

---

## Updated `.mcp.json`

Mac connects to pi-4's HTTP server during sessions. External MCP servers use env vars.

```json
{
  "mcpServers": {
    "job-applications": {
      "type": "http",
      "url": "http://gs-pi-4.local:8086/mcp",
      "headers": { "Authorization": "Bearer ${MCP_AUTH_TOKEN}" }
    },
    "ai-assistant": {
      "command": "python3",
      "args": ["${AI_ASSISTANT_SERVER_PATH}"]
    },
    "contacts": {
      "command": "python3",
      "args": ["${CONTACTS_SERVER_PATH}"],
      "env": { "CONTACTS_CACHE_PATH": "${CONTACTS_CACHE_PATH}" }
    },
    "sgdi": {
      "command": "python3",
      "args": ["${SGDI_SERVER_PATH}"],
      "env": { "SGDI_CACHE_PATH": "${SGDI_CACHE_PATH}" }
    },
    "gebiz-awards": {
      "command": "python3",
      "args": ["${GEBIZ_SERVER_PATH}"]
    }
  }
}
```

During active development, swap `job-applications` to a local stdio entry pointing at the source dir.

---

## Updated `requirements.txt`

```
# MCP server — fleet-wide pin (AGENTS.md: fastmcp>=2.0,<3)
fastmcp>=2.0,<3
mcp~=1.0

# PDF parsing
PyPDF2~=3.0

# URL fetching & HTML parsing (JD ingestion from URLs)
requests~=2.31
beautifulsoup4~=4.12

# Markdown processing
markdown~=3.6

# DOCX export
python-docx~=1.1

# PDF export (x86_64 NAS container; not required on pi)
weasyprint~=61.0

# Utilities
python-dotenv~=1.0
```

> `weasyprint` is only needed in the NAS container (x86_64). The Mac stdio mode
> also has it available via the venv. Neither pi-3 nor pi-4 runs this server.

---

## Key Workflows

### Workflow A: New Application from URL

```
1. ingest_jd(company="Databricks", jd_url="https://...", role_title="AE - Public Sector")
   → _ingest_jd_url() fetches and strips HTML
   → _parse_jd_fields() extracts structure
   → Tracker creates new application record (stage=new)
   → JD.md written to Databricks/ae-public-sector/

2. score_match(company="Databricks", role_title="AE - Public Sector")
   → Loads profile.json + JD structured fields
   → Returns context dict for Claude to produce MatchScoreResult
   → Claude calls back with score → stored in tracker.json

3. analyse_gaps(company="Databricks", role_title="AE - Public Sector")
   → Loads Base_CV + JD structured fields + match_score.missing_skills
   → Returns context dict for Claude to produce gap list
   → Claude calls back with gaps → written to gap_analysis.md

4. tailor_cv / save_tailored_cv
5. generate_cover_letter / save_cover_letter
6. export_document(document_type="tailored_cv", format="pdf")
7. update_stage(company="Databricks", role_title="AE - Public Sector", new_stage="applied")
   → Tracker appends history entry
   → Auto-creates send_follow_up_email followup (due +7 days)
```

### Workflow B: Multi-Role at Same Company

```
# First role (creates Salesforce/enterprise-ae-strategic-accounts/)
ingest_jd(company="Salesforce", jd_path="...", role_title="Enterprise AE Strategic Accounts")

# Second role (creates Salesforce/solution-engineer-public-sector/)
ingest_jd(company="Salesforce", jd_path="...", role_title="Solution Engineer Public Sector")

# Ambiguous company call → returns disambiguation prompt
get_application_status(company="Salesforce")
→ {"disambiguation_required": true, "roles": ["Enterprise AE Strategic Accounts", "Solution Engineer Public Sector"]}

# Role-specific call
get_application_status(company="Salesforce", role_title="Enterprise AE Strategic Accounts")
→ normal status response
```

### Workflow C: Profile Bootstrap

```
# Step 1: Seed from existing Base CV (one-time setup)
update_profile(source="cv", cv_path="DXC/CV LEE Gee Sin 2026 - DXC Client Partner Public Sector.md")

# Step 2: Enrich from LinkedIn export
refresh_profile_from_linkedin(source="export_file", file_path="linkedin_export.txt")
→ Merges; LinkedIn fields win conflicts; conflicts[] logged

# Step 3: Verify
get_profile_summary()
→ current_role, years_exp, top_5_skills, education, timestamps
```

---

## Correctness Properties

The following invariants must hold at all times and are verified by unit tests:

### Property 1: Stage Machine Safety
A tracker record's `stage` field can only be a value from the defined `VALID_STAGES` set. A transition to any other value is rejected with `invalid_stage_transition`. Once a record reaches `accepted`, `rejected`, or `withdrawn` (terminal stages), no further stage transitions are accepted.

**Validates: Requirements 9.4, 9.5**

### Property 2: Profile Source Precedence
For any field present in both LinkedIn and CV sources, the value in `profile.json` always reflects the LinkedIn value. The CV value is preserved only in `conflicts[]` with a source marker. This invariant cannot be violated by any merge operation.

**Validates: Requirements 2.6, 2.7**

### Property 3: No Content Fabrication
`analyse_gaps` and `tailor_cv` context prep tools pass through only content present in the Base_CV or Profile_Store. The instruction strings embedded in tool responses explicitly prohibit fabrication. `save_tailored_cv` scans for the protection pattern (`\d+\s*[%$SGD€£]` or keywords `ARR|quota|deal|target`) and rejects saves where any such segment from the Base_CV has been altered.

**Validates: Requirements 4.5, 6.5**

### Property 4: JSON Round-Trip Fidelity
`profile.json` and `tracker.json` are always written via `json.dumps(..., ensure_ascii=False)` and read via `json.loads`. No Python-specific types (`Path`, `datetime`) are stored; all timestamps are ISO-8601 strings. All `@mcp.tool()` functions return dicts containing only `str | int | float | bool | list | dict | None`.

**Validates: Requirements 12.3, 13.4**

### Property 5: Follow-up Deduplication
Before creating a new follow-up record, the tracker checks for an existing pending record of the same `action_type` for the same application. Duplicates are silently suppressed. On interview progression, pending `send_follow_up_email` records are set to `cancelled` — never left as `pending` for a stale action.

**Validates: Requirements 11.1, 11.2, 11.7**

---

## Error Handling

All MCP tools follow a consistent error response pattern:

```python
# Success
return {"ok": True, "company": company, ...}

# Error (never raises exception to FastMCP layer)
return {"ok": False, "error": "short_code", "message": "Human-readable description"}
```

Common error codes:

| Code | Meaning |
|------|---------|
| `jd_not_found` | File path doesn't exist |
| `jd_url_unreachable` | HTTP non-200 or network error |
| `jd_no_text` | PDF extracted zero characters |
| `profile_not_initialised` | profile.json is empty `{}` |
| `jd_not_ingested` | No JD record for this application |
| `no_match_score` | score_match hasn't been run |
| `base_cv_not_found` | BASE_CV_PATH doesn't exist |
| `invalid_stage_transition` | Not in VALID_TRANSITIONS map |
| `ambiguous_role` | Multiple roles, none specified |
| `invalid_tone` | Not bold/conservative/storyteller |
| `missing_export_dep` | weasyprint or python-docx not installed |
| `source_file_missing` | CV_tailored.md or Cover_Letter.md not found for export |

---

## Backward Compatibility

The following existing tools are **preserved unchanged** in signature and behaviour:

- `create_application` — kept as alias for `ingest_jd` with file-path-only interface
- `get_application_status` — extended to read from tracker.json; falls back to
  filesystem scan if application not in tracker (legacy folder support)
- `company_research`, `save_research` — unchanged
- `map_territory`, `save_territory_map` — unchanged
- `generate_pitch`, `save_pitch` — unchanged
- `generate_cover_letter`, `save_cover_letter` — extended with versioning (Req 7.5)
- `tailor_cv`, `save_tailored_cv` — extended to write cv_diff_summary.md (Req 6.8)

---

## Testing Strategy

Unit tests in `test_mcp_server.py` (pytest):

| Test class | Coverage |
|-----------|---------|
| `TestJDIngestor` | PDF extraction, URL fetch (mocked), field parsing, null handling, zero-text PDF |
| `TestTracker` | Stage machine transitions, follow-up auto-creation, cancellation, duplicate guard |
| `TestProfileManager` | Seed from CV, merge, conflict flagging, years computation, top-N skills |
| `TestPathResolver` | Legacy folder, single-role new, multi-role, ambiguous company |
| `TestExportEngine` | PDF output (mocked weasyprint), DOCX structure (python-docx assertions) |
| `TestMCPTools` | Tool response serialisability (no Path/datetime), error code consistency |

---

## Implementation Phases

### Phase 1 — Foundation (tracker + profile + path resolver)
- Implement `_startup_validate`, env var config
- Implement Tracker (tracker.json schema, VALID_TRANSITIONS, stage machine)
- Implement Profile Manager (profile.json schema, seed from CV, summary)
- Implement Path Resolver (legacy + multi-role detection)
- Update `create_application` / `get_application_status` to use tracker
- Tests for all above

### Phase 2 — Intelligence Tools
- `ingest_jd` with URL support (requests + BeautifulSoup)
- `score_match` context prep tool
- `analyse_gaps` context prep tool
- `generate_learning_program` context prep tool
- Follow-up management (`update_stage` auto-creates followups)
- Tests for all above

### Phase 3 — Document Generation & Export
- `save_tailored_cv` extension (cv_diff_summary.md)
- `save_cover_letter` extension (versioned backups)
- `export_document` (PDF + DOCX via Export Engine)
- LinkedIn profile ingestion (`refresh_profile_from_linkedin`)
- Tests for all above

### Phase 4 — Hardening
- `.env.example` and `.mcp.json` update (env var paths)
- `requirements.txt` pinned with `~=` specifiers
- Full integration smoke test against existing company folders
- README update
