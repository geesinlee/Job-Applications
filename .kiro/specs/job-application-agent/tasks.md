# Implementation Plan: Job Application Agent

## Overview

Extend `job_applications_mcp_server.py` from its current v0.1.0 state into a full
lifecycle agent. Work is split into 10 sequential tasks across 4 phases. All changes
stay in a single Python file plus supporting JSON/config files — no new processes or
databases.

## Tasks

- [x] 1. Foundation — config, startup validation, and persistence helpers
  - Add env var config block (`JOB_APP_BASE_DIR`, `JOB_APP_TRACKER_PATH`, `JOB_APP_PROFILE_PATH`, `JOB_APP_BASE_CV_PATH`) with `__file__`-relative fallbacks
  - Implement `_startup_validate()`: verify BASE_DIR is a directory (exit non-zero + stderr if not), create `tracker.json` and `profile.json` with empty schemas if absent
  - Implement `_load_tracker()` / `_save_tracker(data)` and `_load_profile()` / `_save_profile(data)` using `json.dumps(ensure_ascii=False, indent=2)`
  - Implement `_utc_now() -> str` returning ISO-8601 UTC (e.g. `2026-08-02T14:30:00Z`)
  - Call `_startup_validate()` at module level; add `python-dotenv` load of `.env` if present
  - Update `requirements.txt` with `~=` pinned specifiers for all new deps; use `fastmcp>=2.0,<3` (fleet-wide pin per AGENTS.md) not `fastmcp~=0.1`
  - Create `.env.example` documenting all env vars
  - Add `.env` to `.gitignore`
  - Unit tests: startup creates files when absent, exits on missing BASE_DIR, env var override works

- [x] 2. Path resolver and multi-role folder support
  - Implement `_make_role_slug(role_title) -> str`: lowercase, spaces/special chars → hyphens
  - Implement `_resolve_company_folder(company, role_title, tracker) -> Path`: legacy root for single-role, role-slug sub-folder for multi-role; raise `AmbiguousRoleError` when multiple roles exist and no `role_title` given
  - Define `AmbiguousRoleError(ValueError)`; all callers catch it and return `{"ok": False, "error": "ambiguous_role", "roles": [...]}` 
  - Update `create_application` and `get_application_status` to use path resolver
  - Unit tests: legacy folder, single new role, two roles, ambiguous raises error

- [x] 3. Tracker — stage machine, application records, follow-up management
  - Define `VALID_STAGES` set and `VALID_TRANSITIONS` dict (per design § 4.3)
  - Implement `_find_application(tracker, company, role_title) -> dict | None` (case-insensitive)
  - Implement `_create_application_record(company, role_title, jd_path) -> dict` (uuid4 id, stage=new, empty history/followups)
  - Implement MCP tool `update_stage(company, role_title, new_stage)`: validate transition, append ISO-8601 history entry, auto-create followups, cancel stale followup emails on interview stages
  - Implement `_auto_create_followup(app, new_stage)`: `send_follow_up_email` +7 days on `applied`; `send_thank_you_note` +1 day on interview stages; deduplication check
  - Implement `_cancel_followup_emails(app)`: set pending `send_follow_up_email` to `cancelled` when stage reaches `interview_r1` or higher
  - Implement MCP tool `list_applications(company=None, stage=None)`: sorted by date_created desc; disambiguation prompt when company given with multiple roles
  - Update `get_application_status` to read from tracker (filesystem fallback for legacy)
  - Implement MCP tool `get_due_followups()`: return pending followups where due_date ≤ today UTC, sorted asc; flag overdue in response without mutating stored status
  - Implement MCP tool `mark_followup_complete(application_id, followup_id)`: set status=completed, completed_at=_utc_now()
  - Unit tests: all valid transitions, all invalid transitions, terminal stage blocking, followup creation, deduplication, cancellation, due query, overdue flag

- [x] 4. JD Ingestor — file and URL ingestion with structured field extraction
  - Implement `_ingest_jd_url(url) -> str`: requests.get (15s timeout), raise on non-200, BeautifulSoup html.parser get_text
  - Implement `_parse_jd_fields(raw_text) -> dict`: regex heuristics for role_title, company_name, location, employment_type, required_skills (list), preferred_skills (list), years_of_experience (int|null), responsibilities_summary; absent fields = null
  - Implement MCP tool `ingest_jd(company, role_title, jd_path=None, jd_url=None)`: validate file or URL (not both), file extension, reachability, zero-text PDF; create tracker record; resolve folder; write JD.md; return structured fields
  - Keep `create_application` as backward-compatible alias (file-path-only)
  - Unit tests: PDF, MD, URL (mocked), null fields, file-not-found, URL error, zero-text PDF, duplicate update preserves stage

- [x] 5. Profile manager — seed, merge, LinkedIn ingestion, summary
  - Implement `_seed_profile_from_cv(cv_path) -> dict`: parse DXC Markdown CV — extract work experience, education, skills sections; tag `_source: "cv"`
  - Implement `_parse_linkedin_export(text) -> dict`: parse LinkedIn TXT export into profile schema; tag `_source: "linkedin"`
  - Implement `_merge_profile(existing, incoming, source) -> dict`: LinkedIn wins conflicts; log to `conflicts[]` with both values and sources; update `last_updated` per section
  - Implement `_compute_years_of_experience(work_exp) -> int`: non-overlapping duration intervals, rounded down
  - Implement `_top_n_skills(profile, n=5) -> list[str]`: frequency across work descriptions + skills list
  - Implement MCP tool `update_profile(source, cv_path=None, text=None)`: seed from CV or merge session text; return count of fields updated
  - Implement MCP tool `refresh_profile_from_linkedin(url=None, file_path=None, text=None)`: handle file (TXT/PDF) or pasted text; validate LinkedIn format; merge; report extraction counts; handle blocked/private URL with clear error
  - Implement MCP tool `get_profile_summary()`: current role, years_of_experience, top_5_skills, education, last_updated; return `setup_required: true` if profile is empty
  - Unit tests: CV seeding, LinkedIn merge wins conflicts, conflict logged, years calculation with overlap, top-5 ordering, empty profile setup_required

- [x] 6. Intelligence context-prep tools — match scoring, gap analysis, learning program
  - Implement MCP tool `score_match(company, role_title)`: load JD fields + profile; validate both exist (error codes jd_not_ingested, profile_not_initialised); return context dict with JD, profile summary, weights (40/25/15/10/10), scoring instructions, and expected output schema
  - Implement MCP tool `save_match_score(company, role_title, overall, sub_scores, reasoning, strengths, gaps, missing_skills)`: validate overall 0-100; persist to tracker under `match_score` with `computed_at`
  - Implement MCP tool `analyse_gaps(company, role_title)`: load JD fields + Base_CV + missing_skills from latest score; validate Base_CV exists and profile not empty; return context dict + gap schema + no-fabrication instruction
  - Implement MCP tool `save_gap_analysis(company, role_title, gaps)`: validate gap item fields; write gap_analysis.md as Markdown
  - Implement MCP tool `generate_learning_program(company, role_title)`: load missing_skills (error if no score); empty list → no-gaps response, no file; return context dict with priority rules (required=high/30d, preferred=medium/60d, other=low/90d) and vendor cert instruction
  - Implement MCP tool `save_learning_program(company, role_title, program)`: validate each entry (hours 1-200, completion_days in {30,60,90}); write learning_program.md sorted by priority
  - Unit tests: score_match errors on empty profile/JD, save_match_score rejects out-of-range, analyse_gaps errors on missing Base_CV, empty missing_skills returns no-gaps

- [x] 7. Document generation extensions
  - Extend `save_tailored_cv`: scan for altered quantified achievements (regex `\d+\s*[%$SGD€£]` and keywords `ARR|quota|deal|target`); reject with error if any Base_CV numeric segment altered; write CV_tailored.md; write cv_diff_summary.md with `[section] [change_type]: [description]` lines (valid types: reorder, condense, add, remove, replace)
  - Extend `save_cover_letter`: validate tone is `bold|conservative|storyteller` (error if not); versioned backup — count existing `Cover_Letter_v*.md`, rename current to `Cover_Letter_v{N+1}.md`, write new Cover_Letter.md
  - Update `tailor_cv` context prep: include match_score strengths for professional summary; include gap_analysis.md if present; note absence in output if not
  - Update `generate_cover_letter` context prep: validate tone; append research-absent warning to response (not to file) if research.md missing
  - Unit tests: numeric protection rejects altered figures, cover letter versioning names backup correctly, context prep includes gap analysis when present

- [x] 8. Export engine — PDF and DOCX generation
  - Implement `_check_export_deps(fmt) -> list[str]`: test importability of weasyprint (PDF) and python-docx (DOCX); return missing deps with pip install commands
  - Implement `_export_to_pdf(source_md, output_path)`: markdown → HTML with css (A4, 2.5cm margins, Georgia 11pt) → weasyprint PDF
  - Implement `_export_to_docx(source_md, output_path)`: parse Markdown with python-docx; Calibri 11pt body, 2.54cm margins, H1/H2/H3 heading styles
  - Implement MCP tool `export_document(company, role_title, document_type, format)`: validate document_type (tailored_cv|cover_letter); check source file exists; check deps; export; save as `{type}_{company}_{YYYY-MM-DD}.{fmt}`; return output path
  - Unit tests: missing source file error, missing dep error with install command, output filename format

- [x] 9. pi-4 deployment — systemd units, daily tracker, NAS sync
  - Write `tracker_daily.py` (standalone, stdlib-only, no FastMCP): load `tracker.json`; mark follow-ups as `overdue` where `due_date < today` and `status == "pending"`; save and rsync to NAS (`rsync tracker.json profile.json ${NAS_SYNC_PATH}`); compile digest (active applications by stage, overdue follow-ups, due in 7 days); send email via `smtplib` using `GMAIL_APP_PASSWORD` from `.env` (same pattern as pi-3 GeBiz alerts); log to `tracker_daily.log`
  - Write `job-applications-mcp.service` (systemd user unit): runs `venv/bin/python job_applications_mcp_server.py`, `MCP_MODE=http`, `JOB_APP_BASE_DIR=/home/gs/Projects/Job-Applications/data`, `EnvironmentFile=.env`, `Restart=on-failure`
  - Write `job-applications-tracker.service` + `job-applications-tracker.timer`: timer fires daily `OnCalendar=*-*-* 07:00:00`, `Persistent=true`; service runs `venv/bin/python tracker_daily.py`
  - Update `.mcp.json`: job-applications entry switches to HTTP client pointing at `http://gs-pi-4.local:8086/mcp` with `Authorization: Bearer ${MCP_AUTH_TOKEN}`; all other external server paths use env vars
  - Update `.env.example` with all pi-4 vars: `MCP_AUTH_TOKEN`, `NAS_SYNC_PATH`, `DIGEST_EMAIL`, `GMAIL_APP_PASSWORD`, `JOB_APP_BASE_DIR`, `JOB_APP_ARTEFACTS_DIR`
  - Add `.env`, `tracker.json`, `profile.json`, `tracker_daily.log` to `.gitignore`
  - **pi-4 deploy steps (requires user approval before execution):** rsync source to pi-4 (`rsync -av --exclude venv --exclude .env ./ gs@gs-pi-4.local:~/Projects/Job-Applications/`); create venv + install requirements; copy `.env`; `systemctl --user enable --now job-applications-mcp.service`; `systemctl --user enable --now job-applications-tracker.timer`; verify with `systemctl --user status` and `curl -H "Authorization: Bearer ..." http://localhost:8086/mcp`

- [x] 10. Integration smoke tests and README update
  - Run full `pytest test_mcp_server.py -v` — fix any regressions (all existing tools must pass)
  - Unit test `tracker_daily.py`: overdue flagging logic, email formatting, rsync command construction (mock subprocess)
  - Manual smoke: ingest existing Gartner PDF → verify tracker.json record + JD.md written to `JOB_APP_ARTEFACTS_DIR`
  - Manual smoke: seed profile from DXC CV → verify profile.json populated
  - Manual smoke: run `tracker_daily.py` locally → verify email delivered to `geesin.lee@gmail.com` (SMTP sender account; Gmail API reads from geesin@gmail.com)
  - Update `README.md`: new tool inventory, deployment model (pi-4 MCP service + daily timer, NAS artefacts, Mac transient), env var setup, deploy steps
  - Update `README.md`: new tool inventory, workflow with new tools, env var setup, fleet deployment notes

## Backlog (next release, not in current wave graph)

- [ ] 11. LinkedIn job-alert discovery + company-portal verification
  - Requested 2026-08-03: user wants a daily feed of candidate roles surfaced automatically, rather than manually pasting each JD URL into `ingest_jd`
  - Ingestion mechanism decided: **Gmail API (OAuth)**, not manual paste or IMAP — reuse the Google OAuth pattern already implemented in Contact-Mgmt's `google-contacts-mcp` server (same fleet project, same credential flow) rather than building a new one
  - Requires a new Gmail OAuth scope (`gmail.readonly`) and credential setup; deploy target still TBD (pi-4 alongside the rest of this server, per Task 9's deployment plan) but not yet decided
  - Implement `_poll_linkedin_job_alerts() -> list[dict]`: query Gmail API for LinkedIn job-alert digest emails, parse out per-role links + role/company names
  - Implement MCP tool `discover_jd_candidates()`: return roles found in recent digest emails that aren't yet in the tracker, for the user to triage (ingest vs skip) — read-only, does not auto-create applications
  - Implement `_verify_jd_on_portal(company, role_title, jd_fields) -> dict`: attempt to locate the same role on the company's own careers portal and compare listing status
  - Implement MCP tool `verify_jd_active(company, role_title)`: re-check a previously ingested JD is still live (source URL + company portal); flag if pulled/changed
  - Design not yet finalised — needs its own requirements/design pass before implementation starts (portal search strategy per company is unclear: no universal careers-page search API)
  - Unit tests: TBD once design finalised

## Task Dependency Graph

```json
{
  "waves": [
    { "wave": 1, "tasks": [1] },
    { "wave": 2, "tasks": [2] },
    { "wave": 3, "tasks": [3] },
    { "wave": 4, "tasks": [4, 5] },
    { "wave": 5, "tasks": [6] },
    { "wave": 6, "tasks": [7] },
    { "wave": 7, "tasks": [8] },
    { "wave": 8, "tasks": [9] },
    { "wave": 9, "tasks": [10] }
  ]
}
```

## Notes

- All tool responses must contain only JSON-serialisable types — convert `Path` to `str()`, `datetime` to `.isoformat() + "Z"` before returning
- The `create_application` tool signature must not change — it is a backward-compat alias
- Existing company folders (Gartner, Salesforce, DXC, etc.) must continue to work without migration
- **Deployment: pi-4 is the always-on MCP server and tracker host.** `tracker.json` + `profile.json` live on pi-4 local disk. Artefact folders live on NAS share.
- **Daily tracker runs independently on pi-4** — no Mac, no Claude session needed. Same pattern as pi-3's GeBiz timers. Uses `smtplib` + Gmail App Password (same credential already on pi-3, set a new one for pi-4).
- **Mac never runs always-on services.** The Mac MCP client points at pi-4's HTTP endpoint (`http://gs-pi-4.local:8086/mcp`).
- **pi-3 does not run this workload** — armv7l 32-bit, 921 MB is insufficient for FastMCP + weasyprint + python-docx.
- **fastmcp version:** use `fastmcp>=2.0,<3` — fleet-wide pin per AGENTS.md.
- **Secret handling:** `MCP_AUTH_TOKEN` and `GMAIL_APP_PASSWORD` must never appear in any committed file. Set in mode-600 `.env` on pi-4. Generate token with `python3 -c "import secrets;print(secrets.token_urlsafe(32))"`.
- **NAS sync:** after every tracker write, `tracker_daily.py` and mutating MCP tools call `subprocess.run(["rsync", "-a", str(TRACKER_PATH), str(PROFILE_PATH), NAS_SYNC_PATH])` — fire-and-forget, non-blocking backup.
