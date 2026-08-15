# Gate 7: CV Versioning Persistence Layer

**Date:** 2026-08-16  
**Goal:** Implement file-based persistence for CVVersioningService with NAS rsync backup  
**Architecture:** JSON-based storage (consistent with tracker.json/profile.json pattern)

---

## Infrastructure Decision

**Approach:** Phase 1 — File-based persistence with NAS rsync  
**Why:** Consistent with Job-Applications architecture, zero deployment overhead, proven pattern  
**Future:** Phase 2 (PostgreSQL migration) only when cross-app evidence queries needed

**Storage Pattern:**
- `cv_records.json` — Array of CVRecord objects (metadata)
- `cv_versions/{cv_id}.json` — Per-CV content files (for large content)
- **Sync:** Non-blocking rsync to NAS (same as tracker.json, profile.json)
- **Config:** `CV_RECORDS_PATH` env var, `NAS_SYNC_PATH` existing

---

## Tasks

### Task 1: Add File Persistence Helpers

**Purpose:** Create `_load_cv_records()` and `_save_cv_records()` functions

**What to do:**
1. Write failing tests for load/save operations
2. Implement file I/O helpers
3. Add NAS rsync for cv_records.json
4. Verify tests pass

**Files:**
- `cv_versioning_service.py` — Add load/save helpers
- `tests/unit/test_cv_versioning_service.py` — Add persistence tests

---

### Task 2: Refactor CVVersioningService to Use Persistence

**Purpose:** Replace in-memory dict with persistent file store

**What to do:**
1. Write failing tests for service initialization with persistence
2. Modify `__init__()` to load from disk
3. Wrap all `self.cv_records` mutations with `_save_cv_records()`
4. Verify all existing tests still pass

**Files:**
- `cv_versioning_service.py` — Modify initialization and all write operations
- `tests/unit/test_cv_versioning_service.py` — Add integration tests

---

### Task 3: Configuration and Environment

**Purpose:** Set up `CV_RECORDS_PATH` and NAS sync configuration

**What to do:**
1. Add `CV_RECORDS_PATH` env var to `job_applications_mcp_server.py`
2. Add initialization logic to create cv_records.json if absent
3. Wire up NAS rsync for CV records

**Files:**
- `job_applications_mcp_server.py` — Add config and helpers

---

### Task 4: Cross-Service Persistence Tests

**Purpose:** Verify persistence across service instantiations

**What to do:**
1. Write test: Create CV record, destroy service, recreate service, verify record exists
2. Write test: Multiple drafts, verify version numbering persists
3. Write test: Evidence traceability persists across restarts

**Files:**
- `tests/unit/test_cv_versioning_service.py` — Add persistence integration tests

---

### Task 5: Full Verification

**Purpose:** End-to-end verification with NAS sync

**What to do:**
1. Run all tests (30+ expected)
2. Check coverage (>90%)
3. Verify server imports
4. Git status clean
5. Document NAS sync configuration

---

## Success Criteria

- ✅ 30+ tests PASSING
- ✅ Coverage >90%
- ✅ `cv_records.json` persists across service restarts
- ✅ NAS rsync working (non-blocking)
- ✅ No breaking changes to CVVersioningService API
- ✅ All Gate 6 tests still passing

---

## Notes

- Reuse `_nas_sync()` pattern from job_applications_mcp_server.py
- No database deployment changes needed
- JSON structure mirrors CVRecord dataclass
- Version numbering (draft_1, draft_2) persists via file reload
