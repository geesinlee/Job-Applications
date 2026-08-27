# AGENTS.md — Job Applications MCP Server

> Onboarding reference for AI coding agents. Read this at the start of every session.

## Purpose

MCP server for managing the full job-application lifecycle: JD ingestion, profile management, match scoring, gap analysis, document generation (CV, cover letter, pitch), application tracking with follow-up reminders, and PDF/DOCX export. Claude orchestrates calls; the server provides state management and context preparation.

## Repository Structure

```
Job-Applications/
├── job_applications_mcp_server.py   # Main server — 24 MCP tools, all in one file
├── tracker_daily.py                 # Standalone daily digest (stdlib only, no FastMCP)
├── requirements.txt                 # Pinned deps (fastmcp>=2.0,<3 fleet-wide)
├── conftest.py                      # Autouse fixture isolating paths to tmp_path
├── test_mcp_server.py               # Integration/unit tests (22 classes)
├── test_tracker_daily.py             # Daily digest tests
├── .env.example                     # All env vars documented
├── .mcp.json                        # Environment-driven MCP client config
├── deploy/pi-4/                     # Generic systemd user-unit examples
│   ├── job-applications-mcp.service
│   ├── job-applications-tracker.service
│   └── job-applications-tracker.timer
├── data/                            # Ignored tenant-owned runtime data
├── tracker.json                     # Ignored legacy migration/recovery copy
└── profile.json                     # Ignored legacy migration/recovery copy
```

## Technology Stack

- **Language:** Python 3.11+
- **MCP framework:** FastMCP >=2.0,<3 (fleet-wide pin)
- **Key deps:** PyPDF2, requests, beautifulsoup4, markdown, python-docx, weasyprint (PDF export), python-dotenv
- **Transport:** stdio (local development) or HTTP :8086 with bearer auth
- **Data store:** PostgreSQL CanonicalState records; filesystem volume for artefacts
- **Deployment:** generic systemd user-unit examples

## Development Commands

```bash
# Setup
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env   # fill in real values

# Run locally (stdio mode)
python3 job_applications_mcp_server.py

# Tests
python3 -m pytest -v

# Deploy to a target host
rsync -av --exclude .venv --exclude .env --exclude data ./ \
  <deploy-user>@<job-app-host>:~/Projects/Job-Applications/
```

## Key Conventions

1. **Single-file server.** All MCP tools live in `job_applications_mcp_server.py`. Do not split into modules without a compelling reason.
2. **All tools return dicts.** `{ok: True/False, ...}` — never raise exceptions to the FastMCP layer. Error responses use short `error` codes (e.g., `jd_not_found`, `ambiguous_role`).
3. **JSON-serializable only.** Convert `Path` to `str()`, `datetime` to ISO-8601 strings. No Python-specific types in tool responses.
4. **Stateless tools, stateful deployment.** Every tool reads/writes owner state on each call.
5. **Context-prep pattern.** Tools like `score_match`, `analyse_gaps`, `tailor_cv` assemble inputs and return structured prompts. Claude performs the LLM reasoning and calls back with `save_*` tools.
6. **Fabrication protection.** `save_tailored_cv` rejects edits that alter quantified achievements (regex: digits + currency/percentage/keywords). Never fabricate experience or credentials.
7. **LinkedIn wins conflicts.** When merging profile data, LinkedIn source always takes precedence. CV values are preserved in `conflicts[]`.
8. **Cover letter versioning.** Saving a new `Cover_Letter.md` renames the existing one to `Cover_Letter_v{N}.md`.
9. **Stage machine is strict.** `VALID_TRANSITIONS` dict governs all stage changes. Terminal stages (`accepted`, `rejected`, `withdrawn`) block further transitions.
10. **Postgres is canonical in production.** With `JOB_APP_STORAGE_BACKEND=postgres`, tracker/profile/CV metadata are read and written through PostgreSQL. Do not add JSON fallbacks to the production path.
11. **fastmcp version pin.** Use `fastmcp>=2.0,<3` — fleet-wide rule, do not change.

## Environment Variables

| Var | Purpose | Production example | Local default |
|-----|---------|-----------|-------------|
| `JOB_APP_BASE_DIR` | Persistent data root | `/srv/job-applications/data` | `./data` |
| `JOB_APP_ARTEFACTS_DIR` | Artefact folders root | `/srv/job-applications/data` | Same as BASE_DIR |
| `JOB_APP_TRACKER_PATH` | tracker.json location | Migration only | BASE_DIR/tracker.json |
| `JOB_APP_PROFILE_PATH` | profile.json location | Migration only | BASE_DIR/profile.json |
| `JOB_APP_BASE_CV_PATH` | Tenant-owned reference CV | `/srv/job-applications/data/base_cv/Reference_CV.md` | `data/base_cv/Reference_CV.md` |
| `MCP_MODE` | Transport | `http` | `stdio` |
| `MCP_AUTH_TOKEN` | Bearer token (HTTP mode) | Set in .env | Not needed |
| `NAS_SYNC_PATH` | optional rsync backup destination (legacy) | Empty | Empty |
| `JOB_APP_STORAGE_BACKEND` | Structured state backend | `postgres` | `file` for isolated tests |

## Ingest JD Sources

`ingest_jd` accepts three mutually exclusive content sources:

| Parameter | Content source | Use case |
|-----------|---------------|----------|
| `jd_path` | Local file (PDF, Markdown, TXT) | JD saved to disk |
| `jd_url` | URL fetched and parsed | Job posting URL |
| `jd_text` | Pasted text directly | URL blocked or not available |

`jd_url` can be provided alongside `jd_text` as a reference/provenance URL — it's stored in the tracker record as `jd_source_url` but not fetched. This is useful when a JD was found at a URL but couldn't be scraped (login walls, blocked domains).

## Output Tracking

Every `save_*` function records its output in the tracker record's `outputs` dict. This provides an audit trail of what was generated, when, and where:

```json
"outputs": {
  "research": [{"path": "...", "saved_at": "..."}],
  "cover_letter": [{"path": "...", "saved_at": "...", "version": 1}],
  "tailored_cv": [{"path": "...", "saved_at": "..."}],
  "match_score": [{"overall": 78, "saved_at": "..."}],
  "interview_notes": [{"path": "...", "saved_at": "...", "section": "Round 2"}]
}
```

`get_application_status` returns `outputs`, `submitted`, and `submitted_files` in its response.

## Submitted Documents

`mark_submitted` snapshots the current tailored CV and/or cover letter into a `submitted/` subfolder inside the company directory, and records the submission in the tracker's `submitted` dict:

```json
"submitted": {
  "cv": {"path": "Example Company/submitted/CV_tailored.md", "submitted_at": "..."},
  "cover_letter": {"path": "Example Company/submitted/Cover_Letter.md", "submitted_at": "..."}
}
```

This creates a permanent record of exactly which documents were sent to the employer. Re-submitting overwrites the snapshot with a new timestamp.

## Interview Notes

`save_interview_notes` creates or appends to `interview_notes.md` in the company folder. Notes are appended under timestamped headings, preserving the full history. An optional `section` parameter adds a sub-heading (e.g., "Recruiter call", "Round 2 feedback").

## Context Maintenance

At the end of substantial development work:

- Update `docs/CURRENT_STATE.md` if project status, active work, known issues, or next steps changed.
- Update `docs/ARCHITECTURE.md` when system architecture or major component relationships change.
- Update `docs/DECISIONS.md` when a significant architectural or implementation decision is made.
- Keep these documents consistent with the actual codebase.
- Never record assumptions as established facts.

## MCP Client Preference

**Standard practice is to use Claude Desktop to interface with MCP servers**, not the CLI. Claude Desktop provides a richer interaction surface and is the primary client for all MCP tool calls. The CLI (`claude`) is for development and debugging only.

## Things Agents Should NOT Do

- **Do not** commit `.env`, `tracker.json`, `profile.json`, or `tracker_daily.log` — they are gitignored runtime data.
- **Do not** modify `VALID_TRANSITIONS` or `VALID_STAGES` without updating the corresponding tests.
- **Do not** reintroduce JSON as a production source of truth. Postgres is canonical; JSON is only a migration/recovery format or local test backend.
- **Do not** split `job_applications_mcp_server.py` into a package without rewriting `conftest.py` imports.
- **Do not** hardcode absolute paths — use env vars with `__file__`-relative defaults.
- **Do not** fabricate, invent, or embellish experience, skills, or credentials in any document generation tool.
- **Do not** alter numeric segments (ARR, quota, deal sizes, percentages) when tailoring CVs.
- **Do not** bypass the stage machine — all stage transitions must go through `update_stage`.
- **Do not** commit tenant data, client tokens, or deployment-specific configuration.
- **Do not** change `fastmcp` version pin from `>=2.0,<3`.
