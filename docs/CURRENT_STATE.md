# Current State — Job Applications MCP Server

> Last updated: 2026-08-27.

## Release

Version `0.4.0` provides a tenant-neutral MCP server with Postgres-canonical
structured state and filesystem-managed application artefacts.

The Git repository intentionally contains no candidate CVs, application
folders, tracker/profile/CV runtime records, OAuth credentials, or client
configuration containing tokens. Local data defaults to the ignored `data/`
directory; production data paths are supplied through environment variables.

## Implemented

- Application/JD ingestion and strict stage transitions, including unbounded
  positive interview rounds (`interview_rN`).
- Postgres-backed canonical tracker, profile, and CV metadata state.
- Candidate context, match scoring, gap analysis, research, document, and
  interview-note owner tools.
- Context-preparation workflow: the frontend MCP client performs LLM reasoning.
- Supervised Kafka consumer for AI-Assistant interview-follow-up proposals.
- Dry-run by default, explicit execute opt-in, and separate stage-update opt-in.
- Correlated `orchestration.action_completed` result events for deterministic
  dry-run, rejected, and executed outcomes.
- Isolated tests that force temporary file-backed state and a mock LLM provider.

## Production invariants

- Set `JOB_APP_STORAGE_BACKEND=postgres`; do not use JSON as a production
  fallback.
- Keep application artefacts on a tenant-owned persistent volume outside Git.
- Route all application mutations through the existing owner functions.
- Route every stage transition through `update_stage`.
- Do not write directly to another system's database.
- Keep orchestration execution and stage changes disabled unless explicitly
  reviewed and enabled by the deployer.

## Deployment

Generic systemd user-unit examples are provided under `deploy/pi-4/`; despite
the historical folder name, they use `%h` and contain no user-specific paths.
They assume the checkout is at `%h/Projects/Job-Applications` and configuration
is stored at `%h/.config/job-applications/env`.

Postgres, Kafka, SMTP, MCP URLs, persistent-volume paths, and authentication
values are entirely deployment-specific and must be supplied outside Git.

## Verification

```bash
.venv/bin/python -m pytest -q
```

The optional digest tests additionally require the separately distributed
`fleet-notify` package.
