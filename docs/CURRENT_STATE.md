# Current State — Job Applications MCP Server

> Last updated: 2026-09-04.

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
- Daily job discovery uses a strict two-gate relevance policy: the company must
  be AI-core, AI-product, or AI-adjacent, and the role must be enterprise sales
  or sales/GTM/revenue leadership. Rejected cards retain an audit reason, and a
  non-blocking process lock prevents overlapping schedulers from sending the same
  digest twice. Gmail job-alert queries paginate through all available results,
  and parsed jobs are deduplicated by LinkedIn job ID before triage.
- Job discovery can use LLM-backed triage against a bounded reference-CV excerpt
  when `JOB_DIGEST_TRIAGE_MODE=llm`; deterministic rules remain available as a
  fallback mode.
- Job discovery failures are retry-safe: OAuth/authentication or SMTP delivery
  failures persist unresolved state beneath the artefact volume, leave source
  emails and the last-success marker untouched, and are summarized in the next
  successful digest.
- App-wide operational health is checked by a standalone probe that writes a
  durable JSON snapshot and can alert on state changes through SMTP, webhook,
  or Kafka.
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
values are entirely deployment-specific and must be supplied outside Git. Kafka
is already part of the architecture for orchestration events and is the preferred
future transport for digest health/status events, but job discovery catch-up does
not require Kafka to be available.

## Verification

```bash
.venv/bin/python -m pytest -q
```

The optional digest tests additionally require the separately distributed
`fleet-notify` package.
