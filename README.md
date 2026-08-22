# Job Applications MCP Server

Lifecycle MCP server for managing job applications end to end: JD ingestion, a
stage-tracked pipeline with follow-up reminders, candidate profile management,
JD/profile match scoring and gap analysis, document generation (CV, cover
letter, pitch), PDF/DOCX export, and a daily tracker digest. Claude Code
orchestrates calls to this server alongside other MCP servers (AI-Assistant,
AI-CRM, Contact-Cleanup, GeBiz-Awards).

## Tools

### Application tracking

| Tool | Description |
|------|-------------|
| `create_application` | Create company folder, parse JD (PDF/Markdown), set up tracking (legacy alias, no tracker record) |
| `ingest_jd` | Ingest a JD from file or URL; creates/updates the canonical Postgres application state and extracts structured fields |
| `get_application_status` | Check which workflow steps are completed for a company/role |
| `update_stage` | Advance a tracked application to a new pipeline stage (validates transitions, auto-creates/cancels follow-ups) |
| `list_applications` | List tracked applications, optionally filtered by company and/or stage |
| `get_due_followups` | List pending follow-up actions due today or earlier (UTC) |
| `mark_followup_complete` | Mark a follow-up action as completed |

### Candidate profile

| Tool | Description |
|------|-------------|
| `update_profile` | Seed or update the canonical Postgres profile from a CV file or freeform session notes |
| `refresh_profile_from_linkedin` | Merge a LinkedIn export into the canonical Postgres profile; LinkedIn wins conflicts |
| `get_profile_summary` | Condensed profile view: current role, years of experience, top skills, education |

### Match scoring, gaps, learning

| Tool | Description |
|------|-------------|
| `score_match` | Prepare context for scoring how well the profile matches a JD |
| `save_match_score` | Persist a computed match score to the tracker record |
| `analyse_gaps` | Prepare context for comparing the Base CV against a JD's requirements |
| `save_gap_analysis` | Save a gap analysis to `gap_analysis.md` |
| `generate_learning_program` | Prepare context for a skill-gap learning program (based on missing skills from the latest score) |
| `save_learning_program` | Save a learning program to `learning_program.md` |

### Research and territory mapping

| Tool | Description |
|------|-------------|
| `company_research` | Get a structured research template for a target company, or view existing research |
| `save_research` | Save research content to `research.md` |
| `map_territory` | Get a territory mapping template for specific accounts |
| `save_territory_map` | Save contact/territory mapping to `territory_map.md` |

### Documents

| Tool | Description |
|------|-------------|
| `generate_cover_letter` | Prepare context for a tailored cover letter |
| `save_cover_letter` | Save a cover letter (auto-versions the previous one as `Cover_Letter_v{N}.md`) |
| `generate_pitch` | Prepare context for an interview pitch and questions |
| `save_pitch` | Save an interview pitch |
| `tailor_cv` | Prepare context for tailoring a CV to a JD (includes match score + gap analysis when present) |
| `save_tailored_cv` | Save a tailored CV (rejects edits that alter Base CV's quantified achievements; writes `cv_diff_summary.md`) |
| `export_document` | Export a tailored CV or cover letter to PDF or DOCX |

## Workflow

1. `ingest_jd` → Ingest the JD (file or URL); creates the tracker record and extracts structured fields. (`create_application` remains as a backward-compatible file-only alias that does **not** create a tracker record.)
2. `update_profile` / `refresh_profile_from_linkedin` → Seed or refresh the candidate profile (once, reused across applications)
3. `score_match` → `save_match_score` → JD/profile match scoring
4. `analyse_gaps` → `save_gap_analysis`, then `generate_learning_program` → `save_learning_program` (if gaps found)
5. `company_research` → `save_research`
6. `map_territory` → `save_territory_map`
7. `generate_pitch` → `save_pitch`
8. `generate_cover_letter` → `save_cover_letter`
9. `tailor_cv` → `save_tailored_cv`
10. `export_document` → PDF/DOCX export of the tailored CV or cover letter
11. `update_stage` as the application progresses; `get_due_followups` / `mark_followup_complete` to manage reminders

Use `get_application_status` or `list_applications` at any point to check progress.

## Company Folder Structure

```
Job-Applications/
├── Gartner/                           # Per-company folder (or per-role subfolder if multiple roles)
│   ├── JD.md                          # Job description (extracted from PDF/Markdown/URL)
│   ├── research.md                    # Deep research output
│   ├── territory_map.md               # Contacts & accounts mapping
│   ├── pitch.md                       # Interview pitch & questions
│   ├── Cover_Letter.md                # Current cover letter (versioned backups: Cover_Letter_v1.md, ...)
│   ├── CV_tailored.md                 # JD-tailored CV
│   ├── cv_diff_summary.md             # Summary of changes from Base CV
│   ├── gap_analysis.md                # Skill/experience gaps vs. JD
│   ├── learning_program.md            # Learning plan for missing skills
│   └── Gartner Strategic Account Executive - Large Accounts.pdf  # Original JD
├── Salesforce/                        # Future company folders
└── ...
tracker.json                           # Application records, stages, follow-ups (gitignored)
profile.json                           # Candidate profile (gitignored)
```

## Deployment Model

- **pi-4 is the always-on host.** `job-applications-mcp.service` runs the
  server in `MCP_MODE=http` on `0.0.0.0:8086`, bearer-token authenticated
  (`MCP_AUTH_TOKEN`).
- **Structured state lives in NAS Postgres** (`rv-cloud.local`, database user
  `job-app`) through the `CanonicalState` table. Artefact folders, JDs, CVs,
  and interview notes remain on the NAS filesystem at `/mnt/job-app-data`.
- **`tracker.json`, `profile.json`, and `cv_records.json`** are legacy
  migration/recovery formats only; production pi-4 does not read or write them.
- **`job-applications-tracker.timer`** is retired; pi-4 provides only the MCP
  service for Claude Desktop.
  via `smtplib`/`GMAIL_APP_PASSWORD` (skips sending if unset).
- **The Mac is transient — it runs no always-on services.** The Mac's Claude
  Code session talks to pi-4 over HTTP; see `.mcp.json`'s `job-applications`
  entry (`http://gs-pi-4.local:8086/mcp`, bearer auth via `${MCP_AUTH_TOKEN}`).
  Claude Desktop also connects to pi-4 via `mcp-remote`.
- pi-3 does not run this workload (armv7l 32-bit, 921 MB is insufficient for
  FastMCP + weasyprint + python-docx).

### NAS-Shared Storage Setup

All data paths point to an NFS-mounted NAS share to ensure consistency
between Mac and pi-4:

```
rv-cloud.local:/share/job-app-data  →  /mnt/job-app-data  (NFS mount)
```

**pi-4 fstab entry:**
```
192.168.10.109:/share/job-app-data  /mnt/job-app-data  nfs  rw,_netdev,auto  0 0
```

**Mac automount (optional, for local stdio access):**
Follow the existing `auto_obsidian` pattern in `/etc/auto_master`, or mount
manually: `mount -t nfs 192.168.10.109:/share/job-app-data /mnt/job-app-data`

If NFS is unavailable from macOS, SMB works as a fallback:
`mount_smbfs //gs@rv-cloud.local/job-app-data /mnt/job-app-data`

**pi-4 `.env` (NAS paths):**
```env
JOB_APP_BASE_DIR=/mnt/job-app-data
JOB_APP_ARTEFACTS_DIR=/mnt/job-app-data
JOB_APP_TRACKER_PATH=/mnt/job-app-data/tracker.json
JOB_APP_PROFILE_PATH=/mnt/job-app-data/profile.json
JOB_APP_BASE_CV_PATH=/mnt/job-app-data/DXC/CV LEE Gee Sin 2026 - DXC Client Partner Public Sector.md
NAS_SYNC_PATH=
```

**Data migration (one-time, pi-4 → NAS):**
```bash
rsync -av /home/gs/Projects/Job-Applications/tracker.json /mnt/job-app-data/
rsync -av /home/gs/Projects/Job-Applications/profile.json /mnt/job-app-data/
for dir in /home/gs/Projects/Job-Applications/*/; do
  dirname=$(basename "$dir")
  case "$dirname" in deploy|.git|.venv|__pycache__|test*) continue ;; esac
  rsync -av "$dir" /mnt/job-app-data/"$dirname"/
done
```

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in real values; .env is gitignored, mode 600
```

Key env vars (see `.env.example` for the full list and defaults):

| Var | Purpose |
|-----|---------|
| `JOB_APP_BASE_DIR` | Base directory for `tracker.json`/`profile.json` and company folders. NFS mount on pi-4: `/mnt/job-app-data` |
| `JOB_APP_ARTEFACTS_DIR` | Directory for per-company artefact folders (defaults to `JOB_APP_BASE_DIR`) |
| `JOB_APP_TRACKER_PATH` | Explicit path to `tracker.json` (defaults to `JOB_APP_BASE_DIR/tracker.json`) |
| `JOB_APP_PROFILE_PATH` | Explicit path to `profile.json` (defaults to `JOB_APP_BASE_DIR/profile.json`) |
| `JOB_APP_BASE_CV_PATH` | Path to the base/master CV for tailoring |
| `MCP_MODE` | `stdio` (local Claude session, default) or `http` (always-on service) |
| `MCP_AUTH_TOKEN` | Bearer token required for HTTP mode; generate with `python3 -c "import secrets;print(secrets.token_urlsafe(32))"` |
| `NAS_SYNC_PATH` | ~~rsync destination~~ **No longer needed** when using NAS-shared storage. Leave empty. |
| `DIGEST_EMAIL` / `GMAIL_APP_PASSWORD` | Daily digest email recipient/credential for `tracker_daily.py` (optional; digest just skips sending if unset) |

## Running

**Local (stdio, Mac/Claude Code session):**

```bash
python3 job_applications_mcp_server.py
```

**Always-on (HTTP, pi-4):** installed as a systemd user unit; see
`deploy/pi-4/job-applications-mcp.service` and
`deploy/pi-4/job-applications-tracker.{service,timer}`.

```bash
systemctl --user enable --now job-applications-mcp.service
systemctl --user enable --now job-applications-tracker.timer
systemctl --user status job-applications-mcp.service
curl -H "Authorization: Bearer $MCP_AUTH_TOKEN" http://localhost:8086/mcp
```

## Deploy Steps (pi-4)

### Prerequisites: NFS mount

Ensure `/mnt/job-app-data` is mounted before starting the service:

```bash
# On pi-4 — add to /etc/fstab (if not already present)
echo '192.168.10.109:/share/job-app-data  /mnt/job-app-data  nfs  rw,_netdev,auto  0 0' | sudo tee -a /etc/fstab
sudo mkdir -p /mnt/job-app-data
sudo mount /mnt/job-app-data
```

### Initial data migration (one-time)

If data exists on pi-4's local disk, migrate it to the NAS share:

```bash
rsync -av /home/gs/Projects/Job-Applications/tracker.json /mnt/job-app-data/
rsync -av /home/gs/Projects/Job-Applications/profile.json /mnt/job-app-data/
for dir in /home/gs/Projects/Job-Applications/*/; do
  dirname=$(basename "$dir")
  case "$dirname" in deploy|.git|.venv|__pycache__|test*) continue ;; esac
  rsync -av "$dir" /mnt/job-app-data/"$dirname"/
done
```

### Service deployment

```bash
# From Mac — rsync the code
rsync -av --exclude venv --exclude .env ./ gs@gs-pi-4.local:~/Projects/Job-Applications/

# On pi-4 — deploy
ssh gs@gs-pi-4.local
cd ~/Projects/Job-Applications
python3 -m venv venv && venv/bin/pip install -r requirements.txt
# copy/edit .env with NAS paths and real tokens
mkdir -p ~/.config/systemd/user
cp deploy/pi-4/job-applications-mcp.service deploy/pi-4/job-applications-tracker.service \
   deploy/pi-4/job-applications-tracker.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now job-applications-mcp.service
systemctl --user enable --now job-applications-tracker.timer

# Verify
systemctl --user status job-applications-mcp.service
curl -H "Authorization: Bearer $MCP_AUTH_TOKEN" http://localhost:8086/mcp
```

## Testing

```bash
python3 -m pytest -v          # full suite: test_mcp_server.py + test_tracker_daily.py
```
