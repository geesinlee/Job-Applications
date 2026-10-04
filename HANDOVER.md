# Handover — Job Applications

> Last updated: 2026-09-22T12:00:00+08:00

## Recent Changes & Consolidations

### 1. MCP Tool Consolidation — Phase 1 (2026-09-22)
- **Goal**: Reduce tool surface bloat, modularize toward `src/tools/`, eliminate redundancy.
- **Changes**:
  - `update_stage` → `update_application` (MCP tool name). Accepts `new_stage`, `linkedin_url`, `interview_round` in one call. Python alias `update_stage()` preserved for tests.
  - `get_opportunity` → delegates to `get_application_status(application_id=...)`. Reduces code duplication.
  - `update_opportunity_url` → delegates to `src/tools/lifecycle.update_application(application_id=..., linkedin_url=...)`.
  - `list_applications` → delegates to `src/tools/lifecycle.list_applications`.
  - Fixed `src/tools/lifecycle.py`: added `_can_advance_to_stage` interview-round-skip logic (matches monolith's `_allowed_next_stages` + `_can_advance_to_stage`).
  - Fixed `src/tools/lifecycle.py`: added `previous_stage` and `new_stage` fields to response (backwards-compat with old `update_stage`).
  - Added `from typing import Any` to monolith (needed for `save_application_artefact` MCP registration).
- **Registered MCP tools**: 32 (unchanged count — tool renaming, not removal, in this phase).
- **Legacy Python functions preserved**: `update_stage()`, `list_applied_opportunities()`, `review_daily_discoveries()`, `get_base_cv()`, `get_reference_cv()`, `get_opportunity()`, `update_opportunity_url()` — all callable for tests and `orchestration_consumer.py`.
- **Next phases** (per review plan):
  - Phase 2: Extract `_load_tracker`, `_save_tracker`, `_find_application`, etc. into `src/tools/_state.py` to break circular import.
  - Phase 3: Move `save_*` implementations from monolith into `artefacts.py`, create `src/tools/workflow.py` for Gate 10 suite.
  - Phase 4: Unregister `generate_cv_from_jd_with_evidence` and `confirm_cv`, decide on generate+save merge strategy.

### 2. Unified Application Tracking & Gate 10 Pipeline
- **Problem**: Applications like PwC (`8c416e34-d85b-460b-a9c6-8248d93071f4`) existed in `tracker.json`, but Gate 10 tools (`generate_clarifying_questions`, `start_job_application_workflow`) required raw JD text in the tool payload and couldn't find legacy roles.
- **Resolution**:
  - Enhanced `_resolve_jd_content` in `job_applications_mcp_server.py` to auto-resolve JDs from `ARTEFACTS_DIR`, `BASE_DIR`, `~/Personal/Jobs`, and NAS mount points. Supports both Markdown and PDF formats.
  - Made `jd_content` optional in `generate_clarifying_questions` and `job_jd` optional in `start_job_application_workflow`. Calling with `application_id` alone now loads the JD and prepares Gate 10 prompts automatically.
  - Added `jd_available` and `workflow_ready` flags to `get_opportunity` tool response.
  - Synchronized company folders from `~/Personal/Jobs` to local `data/` (PwC, Gartner, Thoughtworks, etc.), git-ignored under ADR-3.
  - Added synchronization & validation script: `scripts/sync_legacy_tracker_to_gate10.py`.

### 3. Resolved Fleet Incident & Delegation
- **Delegation Ticket**: `DELEGATE-1789994579-FE5C7F` marked `RESOLVED`.
- **ITSM Incident**: `INC-1789994575-2` marked `RESOLVED`.
- **Fleet Handover**: Cleared `BLOCKED_ON_DELEGATION` in `fleet-rationalization/HANDOVER.md`.

## Verification
- `pytest`: 323 passed, 8 skipped (all test files).
- Security governance: 14 passed.
- MCP tool count: 32 registered.