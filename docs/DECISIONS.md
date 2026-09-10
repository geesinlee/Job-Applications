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

## ADR-10: Discovery relevance requires two independent gates

Daily discoveries are surfaced only when both the company/product and role
criteria pass. Company relevance comes from a configurable AI/AI-adjacent
target-account list or explicit AI/data-platform product evidence in the job
card. Role relevance requires enterprise/strategic sales or sales/GTM/revenue
leadership; seniority, location, and generic profile-keyword matches cannot
qualify a card on their own.

Deterministic filtering remains available as the no-provider fallback. When
`JOB_DIGEST_TRIAGE_MODE=llm`, deduplicated LinkedIn cards are classified against
a bounded reference-CV excerpt by the configured model provider. The model must
return structured JSON decisions with scores and short evidence-based reasons;
ambiguous cards are rejected.

Rejected cards remain in the digest with a specific reason, and MCP discovery
listings hide them by default while preserving an explicit audit option.

Scheduled non-dry-run discovery also takes a non-blocking advisory lock beneath
`JOB_APP_ARTEFACTS_DIR` before doing any work. The daily completion marker alone
is insufficient because two concurrent processes can both read the old marker
before either process completes.

## ADR-11: Job discovery failures are durable and replayable

The scheduled discovery digest must not treat a written Markdown file as a
completed run. The completion boundary is successful digest delivery. If Gmail
OAuth, Gmail API access, or SMTP delivery fails, the run records unresolved
failure state in the artefact volume and leaves both LinkedIn source emails and
the `.job_digest_last_run` marker unchanged.

Subsequent successful runs therefore query from the previous successful marker
and catch up across the whole result set. The delivered recovery digest includes
the unresolved failure summary and clears the failure state.

Kafka is already used for AI-Assistant orchestration and is an appropriate
future channel for digest health/status events. It is not required for discovery
catch-up because the digest must remain retryable even when the event bus is
unavailable.

## ADR-12: Operational health is checked outside the MCP process

Failure visibility must not depend on the component being checked. The app uses
a standalone `app_health.py` probe that systemd can run independently of the MCP
server, orchestration worker, and digest job.

The probe writes durable health state beneath the artefact volume, exits
non-zero when unhealthy, and sends notifications only when the failure signature
changes. SMTP alerts remain supported for convenience, but webhook and Kafka
outputs exist so an SMTP outage cannot be the only route for reporting an SMTP
outage.
