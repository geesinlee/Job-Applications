# Job Applications Handoff

**Date:** 2026-08-21
**Status:** Postgres-canonical cutover complete; legacy normalized-table reconciliation remains

## Runtime Source Of Truth

- Structured application/profile/CV state: NAS PostgreSQL `CanonicalState`
- Application artefacts and interview notes: Job Applications data volume
- Evidence/workflow persistence: PostgreSQL on `192.168.10.109`, user `job-app`
- MCP service: pi-4 `job-applications-mcp.service`, local port `8086`
- Claude Desktop public endpoint: `https://gs-pi-4.tail210e4f.ts.net/mcp`

PostgreSQL is canonical. The pi-4 MCP service does not read or write tracker/profile JSON. Do not run the archived migration scripts.

## Tracker Recovery

- The live tracker had been replaced by an incomplete 11-record migration snapshot.
- Restored tracker state: 15 applications, 50 history entries, 19 follow-ups.
- Imported IBM record: `a0648e08-5ec1-449b-a7fa-5e4075ee9af4`, `Account Executive, Confluent (Kafka) - Banking & Financial Services`, `interview_r1`.
- Removed synthetic migration record: `ibm-confluent-001`.
- IBM interview notes remain at `IBM/account-executive-confluent-kafka-banking-financial-services/interview_notes.md`.
- The pre-recovery live tracker and old backup are in `temp-trash/2026-08-21/` on the development copy and retained on pi-4 for confirmation.

## MCP Transport

- Job Applications accepts streamable HTTP with direct bearer authentication.
- FastMCP OAuth advertisement was removed because this service has no OAuth client-registration endpoint.
- Tailscale routes `/mcp` to Job Applications on `8086` and `/` to Work-RAG on `8087`.
- The Tailscale route is shared infrastructure; do not modify it while working only on Job Applications without explicit approval.
- The active Claude Desktop token was aligned with the pi-4 service token on 2026-08-21.

## Postgres Cutover

- Added additive `CanonicalState` table and seeded `tracker` from the verified 15-record NAS recovery state, plus `profile` and empty `cv_records` state.
- Runtime uses `JOB_APP_STORAGE_BACKEND=postgres`; JSON is not a fallback when Postgres is unavailable.
- The legacy daily tracker timer is disabled on pi-4 so only the MCP service writes structured state.
- Existing normalized `Application` rows are an incomplete historical migration snapshot and are not the canonical source; reconcile separately before deleting.

## Cleanup Status

- Obsolete migration scripts, SQL, planning documents, and the credential-bearing migration handover were moved to `temp-trash/2026-08-21/`.
- Production code, tests, application folders, interview notes, Prisma evidence schema, and runtime deployment files were retained.
- Nine historical output references in the restored tracker point to missing artefacts; this is a separate artefact-reconciliation task and must not be “fixed” by deleting tracker history.

## Safe Next Steps

1. Use Claude Desktop to verify IBM status, list applications, and append interview notes.
2. Reconcile missing output paths against the application folders before permanent temp-trash deletion.
3. After confirmation, permanently remove the archived migration/recovery material from `temp-trash/`.

## Required Handoff Files

- [AGENTS.md](/Users/gslee/Projects/Job-Applications/AGENTS.md)
- [docs/CURRENT_STATE.md](/Users/gslee/Projects/Job-Applications/docs/CURRENT_STATE.md)
- [docs/DECISIONS.md](/Users/gslee/Projects/Job-Applications/docs/DECISIONS.md)
- [docs/ARCHITECTURE.md](/Users/gslee/Projects/Job-Applications/docs/ARCHITECTURE.md)
