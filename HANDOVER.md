# Handover State (2026-10-20)

## Completed Tasks
- **MCP Postgres Backend & NAS Path Alignment (`pi-4` & Repo)**:
  - Fixed unawaited Prisma async client calls in [`PostgresEvidenceBackend`](file:///Users/gslee/Projects/Job-Applications/src/evidence_backend.py#L225-L542) via `_resolve()` helper; verified clean connection to `rv-cloud.local:5432/job_applications` without `RuntimeWarning`.
  - Added explicit `"backend": "PostgreSQL"` reporting to [`ingest_jd`](file:///Users/gslee/Projects/Job-Applications/job_applications_mcp_server.py#L2394-L2408), [`save_interview_notes`](file:///Users/gslee/Projects/Job-Applications/job_applications_mcp_server.py#L3853-L3861), [`save_application_artefact`](file:///Users/gslee/Projects/Job-Applications/src/tools/artefacts.py#L40-L106), and lifecycle tools in [`src/tools/lifecycle.py`](file:///Users/gslee/Projects/Job-Applications/src/tools/lifecycle.py#L104-L362).
  - Updated `/home/gs/Projects/Job-Applications/.env` on `pi-4`: aligned `JOB_APP_BASE_DIR` and `JOB_APP_ARTEFACTS_DIR` to `/mnt/job-app-data` and replaced hardcoded LAN IP with `rv-cloud.local`.
  - Synced the full 4,504-byte Snowflake `JD.md` to `/mnt/job-app-data/Snowflake/enterprise-account-executive-acquisition/JD.md`, updated `jd_path` in PostgreSQL `CanonicalState` (`tracker`), and restarted `job-applications-mcp.service` on `pi-4`.

## Incoming Fleet Tasks (Delegated to Agent)
- **`DELEGATE-1792030874-6635E8`** (from AI-Assistant, HIGH priority): `RESOLVED` (2026-10-15).

## MCP Tool Consolidation & Refactoring (2026-10-26)
- **Consolidated 47 Tools to 31 Tools**:
  - Eliminated token bloat and redundant queries (`list_applied_opportunities` -> `list_applications`, `get_opportunity` -> `get_application_status`, `update_opportunity_url` -> `update_application`, `review_daily_discoveries` -> `list_job_discoveries`).
  - Unified 8 separate `save_*` persistence endpoints into a single typed tool: [`save_application_artefact`](file:///Users/gslee/Projects/Job-Applications/src/tools/artefacts.py).
  - Consolidated master and reference CV getters into [`get_cv(document_type='base'|'reference')`](file:///Users/gslee/Projects/Job-Applications/src/tools/profile_tools.py).
  - Retired Gate 9 direct LLM tool from FastMCP tool list in favor of Gate 10 Context-Prep standard.
  - Decomposed domain handlers into modular subpackages in [`src/tools/`](file:///Users/gslee/Projects/Job-Applications/src/tools/).
- **100% Backwards Compatibility**:
  - Preserved all original Python callable functions in [`job_applications_mcp_server.py`](file:///Users/gslee/Projects/Job-Applications/job_applications_mcp_server.py) so consumer scripts (`orchestration_consumer.py`) and existing test suites pass with zero regressions.
- **Verification**:
  - 462 passing tests in pytest suite (`pytest test_mcp_server.py test_orchestration_consumer.py test_mcp_discovery_tools.py test_fabrication_guard_options.py test_job_digest.py test_tracker_daily.py tests/`).
  - Added dedicated catalog test suite in [`tests/unit/test_consolidated_mcp_tools.py`](file:///Users/gslee/Projects/Job-Applications/tests/unit/test_consolidated_mcp_tools.py) (7/7 passed).

## Plane Backlog Sync (`JOBS`)
- **`JOBS-4`** (`Done`): `[Epic] Consolidate and Modularize Job-Applications FastMCP Tools (47 to 31)`
- **`JOBS-5`** (`Todo`): `[Deployment] Deploy Consolidated FastMCP Tools to Production Pi-4`
- **`JOBS-6`** (`Backlog`): `[Tooling] Phase 2 MCP Tool Catalog Shrink to ~22 Canonical Tools`
- **`JOBS-7`** (`Backlog`): `[Feature] Gmail API OAuth Automated Pipeline for LinkedIn Job Alert Ingestion`
- **`JOBS-8`** (`Backlog`): `[Feature] Wire Interview Context Capture into Gate 10 Workflow (Option C)`
- **`JOBS-9`** (`Backlog`): `[Quality] Modernize Python 3.14 Datetime UTC Deprecations in Acceptance Tests`
- **`JOBS-10`** (`Backlog`): `[Governance] NAS Persistent Artefact Directory Hygiene & Candidate PII Isolation`
- **`JOBS-11`** (`Done`): `[Epic] Work-RAG Evidence Retrieval for CV Gap Enrichment & Customization`
- **`JOBS-12`** (`Done`): `[Story] Automated Work-RAG Query Generation from Unmatched JD Requirements`
- **`JOBS-13`** (`Done`): `[Story] Work-RAG Cross-Domain Evidence Retrieval Client & Adapter`
- **`JOBS-14`** (`Done`): `[Story] Evidence Synthesis, Level A/B Verification & Fabrication Guard Enforcement`
- **`JOBS-15`** (`Done`): `[Story] Gate 10 Context-Prep Integration (analyse_gaps & generate_cv_draft)`
- **`JOBS-16`** (`Todo`): `[Bugfix] Add MCP rename capability for application company/title (Scitech -> Scientech Consulting)`

## Work-RAG CV Customization Delivery (2026-10-26)
- **Work-RAG Adapter (`src/tools/work_rag_adapter.py`)**:
  - `WorkRagQueryPlanner`: Automated query generation from JD gaps & missing skills, stripping boilerplate.
  - `WorkRagClient`: FastMCP client querying Work-RAG `search_hybrid` over Tailscale with 10s timeout and circuit-breaker.
  - `CareerEvidenceEnricher`: Synthesizes retrieved chunks into typed `LEVEL_A`/`LEVEL_B` evidence items with source citations and stint attribution.
- **Gate 10 MCP Tools**:
  - `analyse_gaps`: Enriched with automatic `work_rag_evidence` retrieval for missing skills/requirements.
  - `enrich_gaps_from_work_rag`: New dedicated tool in 32-tool consolidated MCP catalog.
  - `generate_cv_draft`: Augments `system_prompt` payload with `<work_rag_evidence>` directives.
- **Verification**:
  - 12/12 unit and integration tests passing (`tests/unit/test_work_rag_adapter.py`, `tests/integration/test_work_rag_cv_enrichment.py`, `tests/unit/test_consolidated_mcp_tools.py`).
  - 278/278 regression tests passing.





## rename-application-company-title Bugfix — Task 4 (2026-10-27)
- **Added test coverage** (Task 4 of `.kiro/specs/rename-application-company-title`):
  - `tests/unit/test_rename_company_title_unit.py` (11 unit tests): company/title/both rename by lookup + application_id; no-op rename (no spurious field mark / audit); missing target -> `application_not_found` no save; mixed `new_stage`+rename applies both, saves once.
  - `tests/unit/test_rename_company_title_properties.py` (3 PBTs): Property 1 renames persist+reported; Property 2 non-rename leaves identity untouched; Property 3 missing recordRef errors with zero mutation.
  - `tests/integration/test_rename_company_title_integration.py` (6 tests): file backend persists to `tracker.json` + `_nas_sync` invoked (NAS mocked); Postgres backend writes via mocked `_save_postgres_state`/`_load_postgres_state` (no real DB); E2E through MCP wrapper `update_application`.
- **Result**: 39/39 rename tests pass (11 unit + 3 PBT + 6 integration + 19 existing exploration/preservation). No real NAS/DB touched.
- **Open gate**: Task 5 — Plane `JOBS` update MUST precede any PR (Req 2.6). Not yet done.

## rename-application-company-title Bugfix — Task 5 Plane Gate (2026-11-01)
- **Plane JOBS gate (Req 2.6)** satisfied via cross-agent delegation to `fleet-rationalization`.
- **Delegation ticket**: `DELEGATE-1793496815-71F2B3` (status `RESOLVED`) — Infra-Agent created Plane issue **`JOBS-16`** (`[Bugfix] Add MCP rename capability for application company/title (Scitech -> Scientech Consulting)`).
- **Issue URL**: https://gs-pi-4.tail210e4f.ts.net:3040/fleet/projects/JOBS/issues/16
- **State**: `UNBLOCKED` (Plane issue `JOBS-16` confirmed in Plane backlog). Code is complete (39/39 tests pass). Ready for PR creation per Req 2.6.
- **Live data correction** (Scitech -> Scientech Consulting; confirm title) is now possible via the new `update_application` rename params — run operationally against the live tracker/DB when ready (separate from shipping the code).

## rename-application-company-title Bugfix — Plane Gate RESOLVED (2026-11-01)
- Delegation `DELEGATE-1793496815-71F2B3` attended to: Plane issue **`JOBS-16`** created — "[Bugfix] Add MCP rename capability for application company/title (Scitech -> Scientech Consulting)".
- `JOBS-16` moved `Todo` -> `In Progress` (code complete, 39/39 tests pass; shipping).
- Req 2.6 satisfied: Plane JOBS updated before PR. `BLOCKED_ON_DELEGATION` cleared.
- PR may now be opened. Move `JOBS-16` -> `Done` after merge.

## rename-application-company-title Bugfix — Merged + Deployed to Production (2026-11-01)
- **Merged to main**: commit `3e4093f` pushed to `origin/main` (`a53d978..3e4093f`). Scoped to rename fix only (lifecycle.py, MCP wrapper, HANDOVER.md, 5 test files); unrelated working-tree changes left unstaged. Pre-commit compliance gate passed (0 violations).
- **Production deploy (pi-4)**: completed via ticket `DELEGATE-1793499638-D334D2` (RESOLVED). Git repo synced to `3e4093f`, `job-applications-mcp.service` restarted and verified active/reachable on :8086 with 32 tools exposed.
- **Plane**: `JOBS-16` and `JOBS-5` moved to `Done`.
- **Live data correction** (Scitech -> Scientech Consulting + confirmed title): ready for user execution via Claude Desktop against production MCP.

## Work-RAG Token Security Patch (2026-11-01)
- **Committed**: `5eb2b64` on `origin/main` — removed the hardcoded Work-RAG bearer token that was an os.getenv fallback in `src/tools/work_rag_adapter.py`; now fail-closed `os.getenv("WORK_RAG_TOKEN", "")`. Adapter tests 3/3 pass. Compliance gate 0 violations. (File was previously untracked, so the literal is not in committed main history for this file.)
- **DEPLOY HOLD**: Do NOT deploy `5eb2b64` to pi-4 until `WORK_RAG_TOKEN` is provisioned — it is currently MISSING from pi-4 `.env`, so the live service was relying on the removed fallback. Deploying now would 401 Work-RAG calls.
- **Delegated (infra/secret-owned)**: ticket `DELEGATE-1793524321-6F442A` — (1) rotate compromised token, (2) set rotated `WORK_RAG_TOKEN` in pi-4 + local `.env`, (3) then deploy. State: `BLOCKED_ON_DELEGATION: DELEGATE-1793524321-6F442A`.
- **Verified earlier**: WRAG-12 Work-RAG endpoint reachable from pi-4 (`:8087/health` → 200). FCP-21 / FCP-23 have no consumer in this repo (out of domain; not testable here).

## Live Data Correction + Duplicate Cleanup (2026-11-01)
- **Root cause of duplicate**: Claude Desktop's MCP client cached the tool list from before the 10:27 pi-4 restart, so it couldn't see new_company/new_role_title and created a duplicate record instead of renaming. Deployed service DOES expose the params (live signature confirmed). Fix: reconnect/restart Claude Desktop MCP connection.
- **Original record** dcdd5d19-e6fe-4dd6-a081-122b6b42b0cb corrected via deployed rename tool (by application_id): company 'Scitech' -> 'ScienTec Consulting'; role_title -> 'Product Manager, Pre-Sales & Adoption (SCTD Products) - Senior Consultant'. Preserved true date_created 2026-10-24T09:41:53Z, full history, followups, audit trail. Verified from Postgres.
- **Duplicate record** f14ee3c8-... (created 2026-11-01) DELETED via server _load_tracker/_save_tracker path (no raw SQL). Records 29 -> 28. Pre-delete backup: pi-4 /tmp/tracker_backup_20261101T100557Z.json.
- **JOBS-16**: moved to Done.
- **Open (delegated, infra-owned)**: ticket DELEGATE-1793527879-69F710 — rename on-disk artefact folder /mnt/job-app-data/Scitech/... -> ScienTec Consulting/... and update jd_path/outputs paths. Non-urgent; old paths still resolve. Also still open: DELEGATE-1793524321-6F442A (Work-RAG token rotation + WORK_RAG_TOKEN provisioning before deploying security commit 5eb2b64).
