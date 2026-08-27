# Decisions — Job Applications MCP Server

## ADR-1: Owner tools remain in a single server module

All public MCP tools remain in `job_applications_mcp_server.py`. This preserves
the existing tool contract and test-isolation strategy. Splitting the server
requires an explicit package migration rather than an incidental refactor.

## ADR-2: Postgres is canonical in production

With `JOB_APP_STORAGE_BACKEND=postgres`, tracker, profile, and CV metadata are
stored through the `CanonicalState` records. Production must fail closed rather
than falling back to JSON. JSON is supported only for isolated development and
migration/recovery workflows.

Tenant-owned CVs, JDs, interview notes, and generated documents remain on the
filesystem volume configured through `JOB_APP_ARTEFACTS_DIR`.

## ADR-3: Tenant data does not belong in Git

The repository contains source, tests, templates, and generic deployment
examples only. Runtime state, credentials, client configuration, candidate
profiles, CVs, and per-company application folders are ignored. Local defaults
write beneath `data/` to make this boundary explicit.

## ADR-4: Context preparation, not backend LLM orchestration

Intelligence tools return structured prompts and context. The MCP client
performs model reasoning and calls deterministic `save_*` owner tools. This
keeps provider credentials out of the server and makes tool behavior testable.

## ADR-5: Strict stage ownership

Every stage transition passes through `update_stage`. Interview stages accept
`interview_rN` for any positive integer, while terminal stages remain terminal.
No integration may bypass this state machine.

## ADR-6: Fabrication protection

`save_tailored_cv` rejects changes to protected quantified achievements. Model
or user-authored document content must not invent or alter credentials,
experience, metrics, or achievements.

## ADR-7: Supervised orchestration is opt-in

The AI-Assistant Kafka consumer is separate from the HTTP MCP process. It is
disabled and dry-run by default. Owner mutations require
`JOB_APP_ORCHESTRATION_EXECUTE=true`; stage changes require a second explicit
flag and still call `update_stage`.

Only the exact job-application follow-up recommendation/action contract is
processed. Other event types are acknowledged and ignored.

## ADR-8: Completion events precede proposal acknowledgement

For deterministic `dry_run`, `rejected`, and `executed` outcomes, the worker
publishes `orchestration.action_completed` before committing the proposal
offset. Owner-write failures emit no false completion. Completion-delivery
failures leave the proposal uncommitted for replay.

The original correlation ID is used in completion metadata and as the Kafka
message key.

## ADR-9: Deployment configuration is external

Postgres, Kafka, SMTP, MCP URLs, data-volume paths, and credentials are supplied
through an ignored environment file or the deployment platform's secret store.
Committed systemd units use `%h` and placeholder-neutral paths; deployments may
override them without editing source.
