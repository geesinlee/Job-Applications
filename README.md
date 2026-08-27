# Job Applications MCP Server

An MCP server for managing the job-application lifecycle: job-description
ingestion, application tracking, follow-up reminders, profile context, match
and gap analysis, document preparation, and interview notes.

Structured state is Postgres-backed in production. CVs, job descriptions,
notes, and other tenant-owned artefacts remain outside Git in a configurable
data directory.

## Safety and ownership

- The release tree contains no candidate CVs, company applications, live
  credentials, tracker state, or deployment-specific client configuration.
  Review `SECURITY.md` before publishing an existing clone with prior history.
- Local runtime data defaults to `./data`, which is ignored except for an empty
  `.gitkeep` placeholder.
- Production should set `JOB_APP_STORAGE_BACKEND=postgres`; JSON files are for
  local development and migration/recovery only.
- Application stage changes always pass through the owner stage machine.
- The optional Kafka orchestration worker is disabled and dry-run by default.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
mkdir -p data/base_cv
```

Put the candidate-owned reference CV at the path configured by
`JOB_APP_BASE_CV_PATH`. Do not commit it.

The digest utilities use the fleet-local `fleet-notify` package. Install it
separately if those commands are required:

```bash
.venv/bin/pip install -e /path/to/fleet-notify
```

## Run

Local stdio mode:

```bash
JOB_APP_STORAGE_BACKEND=file .venv/bin/python job_applications_mcp_server.py
```

HTTP mode requires `MCP_AUTH_TOKEN` and a Postgres `DATABASE_URL`:

```bash
MCP_MODE=http .venv/bin/python job_applications_mcp_server.py
```

The server listens on port `8086` by default. Copy `.mcp.json` and configure
`JOB_APP_MCP_URL` plus `MCP_AUTH_TOKEN` for an MCP client, or adapt
`claude_config.json.example`.

## Data layout

```text
data/                              # ignored tenant-owned root
├── base_cv/Reference_CV.md
├── Example Company/
│   ├── JD.md
│   ├── interview_notes.md
│   ├── Cover_Letter.md
│   └── CV_tailored.md
├── tracker.json                   # file-backend development only
├── profile.json                   # file-backend development only
└── cv_records.json                # file-backend development only
```

Set `JOB_APP_BASE_DIR` and `JOB_APP_ARTEFACTS_DIR` to a persistent volume in
production. The volume may be local, NFS, SMB, or another filesystem mounted by
the deployer.

## Core tools

- Application tracking: `ingest_jd`, `get_application_status`,
  `list_applications`, `update_stage`
- Follow-ups: `get_due_followups`, `mark_followup_complete`
- Candidate context: `update_profile`, `refresh_profile_from_linkedin`,
  `get_profile_summary`
- Analysis: `score_match`, `save_match_score`, `analyse_gaps`,
  `save_gap_analysis`
- Documents: `generate_cover_letter`, `save_cover_letter`, `tailor_cv`,
  `save_tailored_cv`, `export_document`
- Interview records: `save_interview_notes`

All tools return JSON-serializable dictionaries with an `ok` field.

## AI-Assistant orchestration

`orchestration_consumer.py` consumes `orchestration.action_proposed` and only
handles job-application interview follow-up actions. Execution requires
`JOB_APP_ORCHESTRATION_EXECUTE=true`; stage updates require the separate
`JOB_APP_ORCHESTRATION_UPDATE_STAGE=true` opt-in and still use `update_stage`.

Deterministic `dry_run`, `rejected`, and `executed` results can be emitted to
`orchestration.action_completed`. See
[`docs/ORCHESTRATION_PILOT.md`](docs/ORCHESTRATION_PILOT.md).

## Deployment

Generic systemd user-unit examples are under `deploy/pi-4/`. They assume the
checkout is located at `%h/Projects/Job-Applications` and environment values
are stored in `%h/.config/job-applications/env`. Adapt these paths for the
target host.

Application artefacts and credentials must be provisioned separately from the
Git deployment.

## Tests

With the optional shared notification package installed:

```bash
.venv/bin/python -m pytest -q
```

The test suite forces file-backed state, temporary data paths, and a mock LLM
provider so it cannot mutate production state or make provider calls.
