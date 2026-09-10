# Architecture — Job Applications MCP Server

## System Overview

A single-file Python/FastMCP server that orchestrates the job-application lifecycle. MCP clients call owner tools through stdio or HTTP. Structured state is canonical in PostgreSQL; application artefacts and interview notes remain on a deployer-configured filesystem volume.

## Canonical Storage (2026-08-21)

Production uses `JOB_APP_STORAGE_BACKEND=postgres`. The `CanonicalState` table stores the existing `tracker`, `profile`, and `cv_records` payload shapes so application stages, history, follow-ups, outputs, profile data, and CV metadata are read and written through Postgres. JSON files are migration/recovery formats only. The legacy daily JSON tracker timer should remain disabled in Postgres deployments.

```mermaid
graph TB
    subgraph "MCP clients"
        CC[Desktop, CLI, or agent client]
    end

    subgraph "Application host"
        MCP[job_applications_mcp_server.py<br/>FastMCP HTTP :8086]
        ORCH[orchestration_consumer.py<br/>supervised Kafka worker]
        DIGEST[job_digest.py<br/>scheduled LinkedIn discovery]
        HEALTH[app_health.py<br/>scheduled health probe]
    end

    subgraph "Persistent storage"
        PG[(PostgreSQL<br/>CanonicalState)]
        ARTEFACTS[Company folders<br/>JD.md, CV, research, ...]
        DIGEST_STATE[Digest files<br/>last-success marker, failure state]
        HEALTH_STATE[Health snapshot<br/>alert signature]
    end

    AI[AI-Assistant] -->|orchestration.action_proposed| KAFKA[(Kafka)]
    KAFKA -->|matching follow-up proposals| ORCH
    ORCH -->|orchestration.action_completed| KAFKA
    KAFKA -->|correlated owner outcome| AI
    DIGEST -.->|future digest health/status events| KAFKA
    HEALTH -.->|health status events| KAFKA
    CC -->|MCP HTTP / stdio| MCP
    MCP -->|tracker, profile, CV metadata| PG
    ORCH -->|execute mode via owner functions| PG
    MCP -->|read/write| ARTEFACTS
    ORCH -->|save_interview_notes| ARTEFACTS
    DIGEST -->|read tracker/profile context| PG
    DIGEST -->|write digest and retry state| DIGEST_STATE
    HEALTH -->|probe runtime dependencies| MCP
    HEALTH -->|write health state| HEALTH_STATE
```

## Major Components

| Component | File | Responsibility |
|-----------|------|----------------|
| MCP Server | `job_applications_mcp_server.py` | 24 tools, startup validation, state I/O |
| Orchestration Consumer | `orchestration_consumer.py` | Dry-run-by-default Kafka consumer for interview follow-up proposals and producer of correlated owner outcomes |
| Job Discovery Digest | `job_digest.py` | Scheduled LinkedIn job-alert ingestion, deterministic AI/enterprise-sales filtering, retry-safe digest delivery |
| Health Probe | `app_health.py` | Standalone operational checks, durable health snapshot, state-change notifications, optional Kafka/webhook alerts |
| Daily Tracker | `tracker_daily.py` | Overdue follow-ups, email digest, optional remote backup |
| Tests | `test_mcp_server.py`, `test_tracker_daily.py`, `test_orchestration_consumer.py` | Owner behavior, isolated state, and fake Kafka input |
| Systemd Units | `deploy/pi-4/*.service`, `*.timer` | Always-on MCP and orchestration services; legacy timers retained for recovery/local use |

## MCP Tool Groups

### Application Lifecycle
`ingest_jd`, `create_application`, `get_application_status`, `update_stage`, `list_applications`

### Follow-up Management
`get_due_followups`, `mark_followup_complete`

### Candidate Profile
`update_profile`, `refresh_profile_from_linkedin`, `get_profile_summary`

### Intelligence (context-prep pattern)
`score_match` → `save_match_score` → `analyse_gaps` → `save_gap_analysis` → `generate_learning_program` → `save_learning_program`

### Document Generation (context-prep pattern)
`tailor_cv` → `save_tailored_cv`, `generate_cover_letter` → `save_cover_letter`, `generate_pitch` → `save_pitch`

### Research
`company_research` → `save_research`, `map_territory` → `save_territory_map`

### Interview Notes
`save_interview_notes` (append-style, timestamped headings)

### Submission Tracking
`mark_submitted` (copies CV/cover letter to `submitted/` folder, records in tracker)

### Export
`export_document` (PDF via weasyprint, DOCX via python-docx)

## Data Model

### tracker.json

```json
{
  "schema_version": "1.1",
  "applications": [{
    "id": "uuid4",
    "company": "Example Company",
    "role_title": "Example Role",
    "role_slug": "example-role",
    "date_created": "2026-05-28T23:17:00Z",
    "stage": "applied",
    "interview_round": null,
    "jd_path": "/srv/job-applications/Example Company/JD.md",
    "jd_source_url": "https://jobs.example.com/...",
    "match_score": { "overall": 75, "sub_scores": {}, "computed_at": "..." },
    "history": [{ "stage": "new", "at": "..." }],
    "followups": [{ "id": "uuid4", "action_type": "send_follow_up_email", "due_date": "2026-06-04", "status": "cancelled" }],
    "outputs": {
      "research": [{"path": "...", "saved_at": "..."}],
      "tailored_cv": [{"path": "...", "saved_at": "..."}],
      "cover_letter": [{"path": "...", "saved_at": "...", "version": 1}],
      "match_score": [{"overall": 75, "saved_at": "..."}],
      "interview_notes": [{"path": "...", "saved_at": "...", "section": "Recruiter call"}]
    },
    "submitted": {
      "cv": {"path": "Example Company/submitted/CV_tailored.md", "submitted_at": "..."},
      "cover_letter": {"path": "Example Company/submitted/Cover_Letter.md", "submitted_at": "..."}
    }
  }]
}
```

### profile.json

```json
{
  "schema_version": "1.0",
  "headline": "...",
  "current_role": { "title": "...", "company": "..." },
  "work_experience": [{ "title": "...", "company": "...", "start": "YYYY-MM", "end": "present", "description": "...", "_source": "cv|linkedin|session" }],
  "education": [...],
  "certifications": [...],
  "skills": ["..."],
  "conflicts": [{ "field_path": "...", "linkedin_value": "...", "cv_value": "...", "flagged_at": "..." }],
  "last_updated": { "work_experience": "...", "education": "...", "skills": "..." }
}
```

### Stage Machine

```
new → applied → screening → interview_r1 → interview_r2 → ... → interview_rN → offer → accepted
                                                                                          → rejected
                                                                                          → withdrawn
[any non-terminal] → rejected | withdrawn
```

`interview_rN` accepts any positive integer (`interview_r1` through `interview_r10` and beyond). The stored `interview_round` integer is derived from the stage and backfilled for legacy records; history entries carry the same field for reporting.

Terminal stages: `accepted`, `rejected`, `withdrawn`. No transitions out of terminal stages.

## Data Flow

```mermaid
sequenceDiagram
    participant C as Claude
    participant M as MCP Server
    participant T as tracker.json
    participant P as profile.json
    participant N as Persistent Artefacts

    C->>M: ingest_jd(company, jd_path)
    M->>T: Create application record (stage=new)
    M->>N: Write JD.md
    M-->>C: {ok: True, fields: {...}}

    C->>M: update_stage(company, "applied")
    M->>T: Validate transition, append history
    M->>T: Auto-create follow-up (due +7 days)
    M-->>C: {ok: True, ...}

    C->>M: score_match(company)
    M->>T: Load JD fields
    M->>P: Load profile
    M-->>C: Context dict for Claude to score

    C->>M: save_match_score(company, overall=75, ...)
    M->>T: Persist match_score
    M-->>C: {ok: True}
```

## External Services

| Service | Host | Port | Auth | Purpose |
|---------|------|------|------|---------|
| This MCP server | Deployment-specific | 8086 | Bearer token | Job application lifecycle |
| AI-Assistant | Deployment-specific | — | Deployment-specific | Communication ingestion and orchestration proposals |
| Kafka | Deployment-specific | 9092 | Deployment-specific | Orchestration event transport |

External MCP calls are made by Claude (the AI client), not by the server directly. Tool responses include `next_steps` arrays with the exact MCP call syntax.

## Deployment Architecture

### Application host

- **Services:**
  - `job-applications-mcp.service` — FastMCP HTTP :8086, bearer auth, `Restart=on-failure`
  - `job-applications-orchestration.service` — supervised Kafka consumer, disabled/dry-run by default
  - `job-applications-health.timer` — scheduled operational health probe
  - `job-applications-tracker.timer` — legacy file-backend timer, disabled in Postgres production
- **Data paths:** `JOB_APP_*` variables point to a deployer-owned persistent volume.

### Persistent storage

- **PostgreSQL:** Canonical structured state.
- **Filesystem volume:** Company artefacts, interview notes, submitted-document
  snapshots, daily discovery digests, the last successful digest marker, and
  unresolved digest failure state.

### Job discovery resilience

`job_digest.py` treats Gmail OAuth, model-based triage, and SMTP delivery as
independently fallible runtime dependencies. A non-dry-run digest holds an
advisory lock before doing work, paginates Gmail job-alert searches across the
whole available result set, deduplicates LinkedIn jobs by stable job ID, and
only advances `.job_digest_last_run` after the digest email is delivered. If
authentication, triage, or delivery fails, it writes `.job_digest_failure.json`
and leaves LinkedIn source emails plus the last-success marker untouched so the
next successful run catches up from the previous successful date.

Discovery triage can run in deterministic `rules` mode or LLM-backed `llm`
mode. LLM triage sends deduplicated LinkedIn cards plus a bounded reference-CV
excerpt to the configured provider and requires structured JSON decisions with
scores and evidence-based rejection reasons. Ambiguous cards are rejected.

The next delivered digest includes a recovery note summarizing the unresolved
failure and clears the failure state. SMTP failure alerts remain best-effort:
when SMTP itself is the broken dependency, the durable state file is the source
of truth until an independent alert channel is added.

Kafka is already part of the application architecture for orchestration events.
It is a good fit for future digest health/status events because it can decouple
failure detection from email delivery, but the digest pipeline should remain
recoverable without Kafka so discovery does not depend on the event bus being
healthy.

### App health and alerting

`app_health.py` runs outside the MCP process and checks the deployment
environment, artefact paths, Postgres reachability, MCP HTTP availability, SMTP
configuration/login, Gmail OAuth refresh, LLM triage configuration, job-digest
freshness/failure state, and optional Kafka broker reachability. It writes the current snapshot to
`.job_app_health.json` and records the last notified failure signature in
`.job_app_health_alert_state.json`.

Health notifications are state-change based. This avoids repeated noise during
an unchanged outage while still surfacing new failures or recovery. SMTP remains
supported, but an independent alert route such as `JOB_APP_HEALTH_WEBHOOK_URL`
or Kafka health events should be configured because SMTP can be the failed
dependency.

### Development host

- **MCP access:** Any compatible MCP HTTP client or local stdio transport.
- **Local stdio:** Run in `MCP_MODE=stdio` with the ignored `data/` directory.

## Important Dependencies

| Package | Version | Purpose | Notes |
|---------|---------|---------|-------|
| fastmcp | >=2.0,<3 | MCP server framework | Fleet-wide pin |
| PyPDF2 | ~=3.0 | PDF text extraction | Optional; graceful degradation |
| requests | ~=2.32 | JD URL fetching | Required for URL ingestion |
| beautifulsoup4 | ~=4.12 | HTML parsing | Required for URL ingestion |
| confluent-kafka | ~=2.15.0 | Kafka consumer | AI-Assistant orchestration pilot; imported lazily |
| markdown | ~=3.6 | MD→HTML conversion | Required for PDF export |
| python-docx | ~=1.1 | DOCX export | Required for DOCX export |
| weasyprint | ~=61.0 | PDF export | Requires host Cairo/Pango libraries |
| python-dotenv | ~=1.0 | .env loading | Optional; server works without .env |

## Authentication & Security

- **MCP HTTP mode:** Bearer token via `MCP_AUTH_TOKEN`. Generate with `python3 -c "import secrets;print(secrets.token_urlsafe(32))"`.
- **Gmail SMTP:** App password in `.env` as `GMAIL_APP_PASSWORD`. File mode 600.
- **Storage/network controls:** Deployment-specific; tenant data volumes should not be publicly exposed.
- **No live secrets in the release tree.** `.env` is gitignored and example
  files contain placeholders only. Historical exposure still requires rotation
  and history cleanup before public release.
