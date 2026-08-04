# AGENTS.md — Job Applications MCP Server

> Onboarding reference for AI coding agents. Read this at the start of every session.

## Purpose

MCP server for managing the full job-application lifecycle: JD ingestion, profile management, match scoring, gap analysis, document generation (CV, cover letter, pitch), application tracking with follow-up reminders, and PDF/DOCX export. Claude orchestrates calls; the server provides state management and context preparation.

## Repository Structure

```
Job-Applications/
├── job_applications_mcp_server.py   # Main server — 22 MCP tools, all in one file
├── tracker_daily.py                 # Standalone daily digest (stdlib only, no FastMCP)
├── requirements.txt                 # Pinned deps (fastmcp>=2.0,<3 fleet-wide)
├── conftest.py                      # Autouse fixture isolating paths to tmp_path
├── test_mcp_server.py               # Integration/unit tests (19 classes)
├── test_tracker_daily.py             # Daily digest tests
├── .env.example                     # All env vars documented
├── .mcp.json                        # MCP server config (HTTP to pi-4)
├── .kiro/specs/job-application-agent/  # Requirements, design, tasks (formal specs)
├── deploy/pi-4/                     # Systemd units for pi-4
│   ├── job-applications-mcp.service
│   ├── job-applications-tracker.service
│   └── job-applications-tracker.timer
├── DXC/ Glean/ Gartner/ ...         # Per-company artefact folders (gitignored)
├── tracker.json                     # Application state (gitignored)
└── profile.json                     # Candidate profile (gitignored)
```

## Technology Stack

- **Language:** Python 3.11+
- **MCP framework:** FastMCP >=2.0,<3 (fleet-wide pin)
- **Key deps:** PyPDF2, requests, beautifulsoup4, markdown, python-docx, weasyprint (PDF export), python-dotenv
- **Transport:** stdio (Mac dev) or HTTP :8086 with bearer auth (pi-4 production)
- **Data store:** JSON files (tracker.json, profile.json) — no database
- **Deployment:** systemd user units on pi-4 (Debian aarch64)
- **NAS:** NFS mount at `/mnt/job-app-data` for artefact storage

## Development Commands

```bash
# Setup
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env   # fill in real values

# Run locally (stdio mode)
python3 job_applications_mcp_server.py

# Tests
python3 -m pytest -v

# Deploy to pi-4
rsync -av --exclude venv --exclude .env ./ gs@gs-pi-4.local:~/Projects/Job-Applications/
ssh gs@gs-pi-4.local  # then: systemctl --user restart job-applications-mcp.service
```

## Key Conventions

1. **Single-file server.** All MCP tools live in `job_applications_mcp_server.py`. Do not split into modules without a compelling reason.
2. **All tools return dicts.** `{ok: True/False, ...}` — never raise exceptions to the FastMCP layer. Error responses use short `error` codes (e.g., `jd_not_found`, `ambiguous_role`).
3. **JSON-serializable only.** Convert `Path` to `str()`, `datetime` to ISO-8601 strings. No Python-specific types in tool responses.
4. **Stateless tools, stateful pi-4.** Every tool reads/writes state on each call. The pi-4 service owns tracker.json and profile.json.
5. **Context-prep pattern.** Tools like `score_match`, `analyse_gaps`, `tailor_cv` assemble inputs and return structured prompts. Claude performs the LLM reasoning and calls back with `save_*` tools.
6. **Fabrication protection.** `save_tailored_cv` rejects edits that alter quantified achievements (regex: digits + currency/percentage/keywords). Never fabricate experience or credentials.
7. **LinkedIn wins conflicts.** When merging profile data, LinkedIn source always takes precedence. CV values are preserved in `conflicts[]`.
8. **Cover letter versioning.** Saving a new `Cover_Letter.md` renames the existing one to `Cover_Letter_v{N}.md`.
9. **Stage machine is strict.** `VALID_TRANSITIONS` dict governs all stage changes. Terminal stages (`accepted`, `rejected`, `withdrawn`) block further transitions.
10. **fastmcp version pin.** Use `fastmcp>=2.0,<3` — fleet-wide rule, do not change.

## Environment Variables

| Var | Purpose | pi-4 value | Mac default |
|-----|---------|-----------|-------------|
| `JOB_APP_BASE_DIR` | Data root | `/mnt/job-app-data` | Script directory |
| `JOB_APP_ARTEFACTS_DIR` | Artefact folders root | `/mnt/job-app-data` | Same as BASE_DIR |
| `JOB_APP_TRACKER_PATH` | tracker.json location | `/mnt/job-app-data/tracker.json` | BASE_DIR/tracker.json |
| `JOB_APP_PROFILE_PATH` | profile.json location | `/mnt/job-app-data/profile.json` | BASE_DIR/profile.json |
| `JOB_APP_BASE_CV_PATH` | Default base CV | `/mnt/job-app-data/DXC/CV LEE Gee Sin 2026 - DXC Client Partner Public Sector.md` | ARTEFACTS_DIR/DXC/... |
| `MCP_MODE` | Transport | `http` | `stdio` |
| `MCP_AUTH_TOKEN` | Bearer token (HTTP mode) | Set in .env | Not needed |
| `NAS_SYNC_PATH` | rsync destination (legacy) | Empty (data on NAS directly) | Empty |

## Ingest JD Sources

`ingest_jd` accepts three mutually exclusive content sources:

| Parameter | Content source | Use case |
|-----------|---------------|----------|
| `jd_path` | Local file (PDF, Markdown, TXT) | JD saved to disk |
| `jd_url` | URL fetched and parsed | Job posting URL |
| `jd_text` | Pasted text directly | URL blocked or not available |

`jd_url` can be provided alongside `jd_text` as a reference/provenance URL — it's stored in the tracker record as `jd_source_url` but not fetched. This is useful when a JD was found at a URL but couldn't be scraped (login walls, blocked domains).

## Context Maintenance

At the end of substantial development work:

- Update `docs/CURRENT_STATE.md` if project status, active work, known issues, or next steps changed.
- Update `docs/ARCHITECTURE.md` when system architecture or major component relationships change.
- Update `docs/DECISIONS.md` when a significant architectural or implementation decision is made.
- Keep these documents consistent with the actual codebase.
- Never record assumptions as established facts.

## Things Agents Should NOT Do

- **Do not** commit `.env`, `tracker.json`, `profile.json`, or `tracker_daily.log` — they are gitignored runtime data.
- **Do not** modify `VALID_TRANSITIONS` or `VALID_STAGES` without updating the corresponding tests.
- **Do not** add database dependencies — the project uses JSON files by design.
- **Do not** split `job_applications_mcp_server.py` into a package without rewriting `conftest.py` imports.
- **Do not** hardcode absolute paths — use env vars with `__file__`-relative defaults.
- **Do not** fabricate, invent, or embellish experience, skills, or credentials in any document generation tool.
- **Do not** alter numeric segments (ARR, quota, deal sizes, percentages) when tailoring CVs.
- **Do not** bypass the stage machine — all stage transitions must go through `update_stage`.
- **Do not** run the server on pi-3 (armv7l 32-bit, 921 MB — insufficient for weasyprint/python-docx).
- **Do not** change `fastmcp` version pin from `>=2.0,<3`.