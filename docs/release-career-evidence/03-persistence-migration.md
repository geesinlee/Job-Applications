# Gate 3: Persistence & Migration Implementation
## Career Evidence Repository + Governed CV Workflow Release

**Date:** 2026-08-14  
**Status:** Implementation complete  
**Scope:** Schema migration, persistence layer, baseline evidence import

---

## Overview

Gate 3 implements the persistence layer for the Career Evidence Repository. This is a **non-destructive, reversible migration** that:

1. ✅ Extends `tracker.json` from v1.0 → v2.0 (adds new fields, preserves all existing)
2. ✅ Creates `evidence.json` (new evidence repository)
3. ✅ Creates `cv_versions.json` (new CV version history)
4. ✅ Imports baseline evidence from existing `profile.json`
5. ✅ Maintains backward compatibility (old code continues to work)
6. ✅ Enables rollback (revert to v1.0 if needed)

---

## Implementation Files

### New Production Code

**`evidence_persistence.py`** (450+ lines)
- `EvidenceRepository` class — Evidence CRUD, filtering, persistence
- `CVVersionsRepository` class — CV version CRUD, persistence
- `TrackerRepository` class (extended) — Schema migration, backward compat
- `BaselineEvidenceImporter` class — One-time baseline evidence import
- `perform_initial_migration()` — Orchestration function

### New Test Code

**`tests/unit/test_evidence_persistence.py`** (500+ lines)
- 20+ unit tests for all persistence operations
- Tests for schema migration (v1.0 → v2.0 → v1.0)
- Tests for idempotency and reversibility
- Integration tests for full migration flow

---

## Schema Changes

### tracker.json Migration (v1.0 → v2.0)

**Before (v1.0):**
```json
{
  "schema_version": "1.0",
  "applications": [
    {
      "id": "...",
      "company": "Gartner",
      "role_title": "SAE",
      "jd_path": "...",
      "stage": "new",
      "date_created": "2026-08-10T...",
      "history": [...],
      "followups": [],
      "jd_source_url": null
    }
  ]
}
```

**After (v2.0) — New Fields Added with Defaults:**
```json
{
  "schema_version": "2.0",
  "applications": [
    {
      // All v1.0 fields preserved
      "id": "...",
      "company": "Gartner",
      // ... (existing fields unchanged)
      
      // NEW v2.0 FIELDS (all initialized to safe defaults)
      "requirements_extracted_at": null,
      "requirements": [],
      "requirement_analysis_quality": null,
      "gap_interview_phase": "not_started",
      "gap_interview_questions": [],
      "gap_interview_answers": [],
      "evidence_selected": [],
      "evidence_omitted": [],
      "cv_records": [],
      "cv_draft_count": 0,
      "cv_approved_at": null,
      "cv_final_id": null,
      "discovered_at": "2026-08-10T...",  // Backfilled from date_created
      "applied_at": null,
      "significant_decisions": []
    }
  ]
}
```

**Key Properties:**
- ✅ **Non-destructive:** All v1.0 fields preserved
- ✅ **Safe defaults:** New fields start empty/null (no data loss)
- ✅ **Backward compatible:** Old tools ignore new fields; new tools handle null gracefully
- ✅ **Reversible:** Can revert to v1.0 by removing new fields

---

### evidence.json (NEW)

```json
{
  "schema_version": "1.0",
  "evidence_repository": {
    "evidence_list": [
      {
        "evidence_id": "550e8400-e29b-41d4-a716-446655440000",
        "statement": "Grew revenue 50% in Singapore region, managing 12+ enterprise accounts",
        "evidence_type": "achievement",
        "source_type": "baseline_cv",
        "source_reference": "DXC CV p1 line 5",
        "source_document_id": null,
        "source_date": "2026-05-15T00:00:00Z",
        "first_captured_at": "2026-08-14T10:30:00Z",
        "last_confirmed_at": "2026-08-14T10:30:00Z",
        "application_origin": null,
        "verification_status": "user_confirmed",
        "confidence": "LEVEL_A",
        "user_confirmed": true,
        "supersedes": [],
        "superseded_by": [],
        "related_to": [],
        "competencies": ["Enterprise Sales", "Revenue Growth"],
        "technologies": [],
        "industries": ["SaaS"],
        "geographies": ["Singapore"],
        "metrics": {
          "revenue": {
            "amount": 5000000,
            "currency": "SGD",
            "period": "2021-Present",
            "verified_source": "baseline_cv"
          }
        },
        "notes": "Imported from baseline profile",
        "created_by": "baseline_import",
        "created_at": "2026-08-14T10:30:00Z",
        "last_modified_by": "baseline_import",
        "last_modified_at": "2026-08-14T10:30:00Z"
      }
    ]
  }
}
```

**Structure:**
- Central repository of all CareerEvidence items
- Flat list (not hierarchical) for easy querying
- Full provenance and verification metadata on each item
- No application references within the evidence (evidence is application-agnostic)

---

### cv_versions.json (NEW)

```json
{
  "schema_version": "1.0",
  "cv_records": [
    {
      "cv_record_id": "550e8400-e29b-41d4-a716-446655440001",
      "application_id": "app-gartner-sae",
      "version": "draft_1",
      "version_number": 1,
      "status": "draft",
      "content": "[Full CV markdown here]",
      "evidence_used": [
        {
          "evidence_id": "550e8400-e29b-41d4-a716-446655440000",
          "evidence_statement": "Grew revenue 50% in Singapore...",
          "cv_section": "Professional Summary",
          "adapted_text": "Demonstrated consistent revenue growth, expanding customer base by 50%",
          "confidence_level": "LEVEL_A",
          "justification": "Directly addresses JD requirement"
        }
      ],
      "major_changes": ["Reordered roles by recency"],
      "changed_sections": ["Professional Summary"],
      "significant_omissions": [],
      "created_at": "2026-08-14T15:00:00Z",
      "approved_at": null,
      "finalized_at": null,
      "predecessor_id": null,
      "successor_id": null,
      "created_by": "app:claude",
      "last_modified_by": "app:claude",
      "last_modified_at": "2026-08-14T15:00:00Z"
    }
  ]
}
```

**Structure:**
- Central repository of all CV versions across all applications
- Tracks version chain (predecessor → successor for draft iterations)
- Evidence traceability: each CV section references the evidence used
- No duplication: one source of truth for CV history

---

## Migration Process

### Step 1: Schema Migration (Automatic)

```python
from evidence_persistence import TrackerRepository

tracker_repo = TrackerRepository("tracker.json")
tracker_repo.migrate_to_v2()
```

**What happens:**
1. Loads existing tracker.json (v1.0)
2. Iterates over all applications
3. Adds v2.0 fields to each application (with defaults)
4. Backfills `discovered_at` from `date_created`
5. Updates schema_version to "2.0"
6. Saves updated tracker.json

**Safety:**
- ✅ No data deleted
- ✅ All v1.0 fields preserved
- ✅ New fields start safe (empty/null)
- ✅ Idempotent (safe to run twice)

### Step 2: Evidence Repository Creation (Automatic)

```python
from evidence_persistence import EvidenceRepository

evidence_repo = EvidenceRepository(".")
evidence_repo.load()  # Creates evidence.json if not exists
```

**What happens:**
1. Checks if evidence.json exists
2. If not, creates default empty repository
3. Returns repository object

### Step 3: CV Versions Repository Creation (Automatic)

```python
from evidence_persistence import CVVersionsRepository

cv_repo = CVVersionsRepository(".")
cv_repo.load()  # Creates cv_versions.json if not exists
```

### Step 4: Baseline Evidence Import (Automatic)

```python
from evidence_persistence import BaselineEvidenceImporter

importer = BaselineEvidenceImporter("profile.json", evidence_repo)
count = importer.import_baseline_evidence()
print(f"Imported {count} evidence items")
```

**What happens:**
1. Reads existing profile.json
2. Iterates over work_experience, education, skills
3. Creates CareerEvidence items for each:
   - `_source` field determines source_type (baseline_cv or linkedin)
   - confidence set based on type (LEVEL_A for education, LEVEL_B for experience, LEVEL_C for skills)
   - Proper provenance tracking (source_reference, source_date)
4. Stores all evidence in evidence.json
5. Returns count

**Results:**
- Work experiences → LEVEL_B evidence
- Education → LEVEL_A evidence
- Skills → LEVEL_C evidence

### Step 5: One-Call Orchestration (Recommended)

```python
from evidence_persistence import perform_initial_migration

result = perform_initial_migration(
    tracker_path="tracker.json",
    profile_path="profile.json",
    data_dir="."
)

print(result)
# Output:
# {
#   "status": "success",
#   "tracker_migrated_to": "v2.0",
#   "evidence_items_created": 17,
#   "cv_versions_repo_initialized": True,
#   "timestamp": "2026-08-14T14:30:00Z"
# }
```

---

## Rollback / Revert

### Manual Revert to v1.0

```python
from evidence_persistence import TrackerRepository

tracker_repo = TrackerRepository("tracker.json")
tracker_repo.revert_to_v1()
```

**What happens:**
1. Loads tracker.json (v2.0)
2. Removes all v2.0 fields from each application
3. Preserves all v1.0 fields
4. Sets schema_version to "1.0"
5. Saves reverted tracker.json

**Safety:**
- ✅ All original data preserved
- ✅ Can be done at any time
- ✅ evidence.json and cv_versions.json remain untouched

### Data Loss Prevention

- `evidence.json` and `cv_versions.json` are **separate files** — removing them is a deliberate delete
- `tracker.json` v1.0 fields are **never overwritten** — only additions can be removed
- Migration is **idempotent** — running twice has no adverse effect

---

## Backward Compatibility

### Old Code Still Works

Existing `job_applications_mcp_server.py` (31 MCP tools) **requires NO changes** for Gate 3:

```python
# Old tool still works
tracker = load_tracker()  # Loads v2.0 tracker
app = tracker["applications"][0]

# Old fields accessible
company = app["company"]  # ✅ Works
stage = app["stage"]      # ✅ Works
history = app["history"]  # ✅ Works

# New fields ignored (present but unused)
requirements = app.get("requirements", [])  # ✅ Safe (v1.0 code uses .get())
```

### New Code Handles Null

New code (Gates 4–7) handles v2.0 fields gracefully:

```python
# New code: safe to access v2.0 fields
app = tracker["applications"][0]

gap_phase = app.get("gap_interview_phase", "not_started")  # Safe default
cv_records = app.get("cv_records", [])  # Safe empty list
```

### Mixed Deployments

If some instances are v1.0-only and others are v2.0-capable:

```
Instance A (v1.0)
  - Reads tracker.json
  - Ignores unknown fields (gap_interview_phase, requirements, etc.)
  - Works normally
  
Instance B (v2.0)
  - Reads tracker.json
  - Uses all fields (v1.0 + v2.0)
  - Works normally
```

Both instances share the same tracker.json without conflict.

---

## Testing

### Run All Migration Tests

```bash
# Run all persistence tests
pytest tests/unit/test_evidence_persistence.py -v

# Run specific test
pytest tests/unit/test_evidence_persistence.py::test_tracker_migrate_to_v2 -v

# Run by marker
pytest -m "tracker" -v       # TrackerRepository tests
pytest -m "evidence" -v      # EvidenceRepository tests
pytest -m "e2e" -v          # Full migration flow
```

### Test Coverage

| Test | Purpose | Status |
|------|---------|--------|
| `test_evidence_repo_creates_new_repo` | Evidence.json creation | ✅ Pass |
| `test_evidence_repo_add_and_retrieve` | Evidence CRUD | ✅ Pass |
| `test_evidence_repo_list_all` | Evidence listing | ✅ Pass |
| `test_evidence_repo_filter` | Evidence filtering | ✅ Pass |
| `test_evidence_repo_update` | Evidence update | ✅ Pass |
| `test_cv_versions_repo_creates_new_repo` | CV versions creation | ✅ Pass |
| `test_cv_versions_repo_add_and_list` | CV version CRUD | ✅ Pass |
| `test_tracker_schema_v1_detection` | Schema version detection | ✅ Pass |
| `test_tracker_migrate_to_v2` | Migration logic | ✅ Pass |
| `test_tracker_idempotent_migration` | Idempotency | ✅ Pass |
| `test_tracker_revert_to_v1` | Revert logic | ✅ Pass |
| `test_baseline_evidence_import` | Evidence import | ✅ Pass |
| `test_baseline_evidence_has_correct_source` | Source tracking | ✅ Pass |
| `test_baseline_evidence_idempotent` | Import safety | ✅ Pass |
| `test_full_migration_flow` | End-to-end | ✅ Pass |

---

## Integration with Gates 4–7

### Gate 4: Evidence Services
Will use `EvidenceRepository` directly:
```python
from evidence_persistence import EvidenceRepository

class EvidenceService:
    def __init__(self):
        self.repo = EvidenceRepository(".")
    
    def create_evidence(self, **kwargs):
        evidence = {...}
        self.repo.add_evidence(evidence)
        return evidence
```

### Gate 5: Requirement Services
Will query evidence:
```python
def match_evidence(requirement, evidence_repo):
    all_evidence = evidence_repo.list_evidence()
    # Find matches
    return matched_evidence
```

### Gate 6: CV Versioning
Will use `CVVersionsRepository`:
```python
from evidence_persistence import CVVersionsRepository

class CVVersioningService:
    def __init__(self):
        self.cv_repo = CVVersionsRepository(".")
    
    def create_draft(self, app_id, content):
        cv_record = {...}
        self.cv_repo.add_cv_record(cv_record)
```

---

## Error Handling

### JSON Corruption Handling

```python
try:
    repo = EvidenceRepository(".")
    repo.load()
except ValueError as e:
    print(f"ERROR: Corrupted evidence.json: {e}")
    # Offer user: restore from backup, re-import baseline
```

### Migration Failure

```python
try:
    tracker_repo.migrate_to_v2()
except Exception as e:
    print(f"ERROR: Migration failed: {e}")
    # Offer user: retry, revert to v1.0, restore from backup
```

### Missing Profile During Import

```python
importer = BaselineEvidenceImporter("profile.json", evidence_repo)
count = importer.import_baseline_evidence()
# Returns 0 if profile.json not found (logged as warning, not error)
# Migration continues without baseline evidence
```

---

## Verification

### Post-Migration Checklist

```bash
# 1. Verify tracker.json is v2.0
grep '"schema_version": "2.0"' tracker.json

# 2. Verify evidence.json exists and has items
jq '.evidence_repository.evidence_list | length' evidence.json

# 3. Verify cv_versions.json exists
ls -la cv_versions.json

# 4. Run existing tests (regression)
pytest tests/unit/test_mcp_server.py -v

# 5. Run migration tests
pytest tests/unit/test_evidence_persistence.py -v
```

### Backward Compat Verification

```bash
# Run existing tools (should still work with v2.0 tracker)
python3 job_applications_mcp_server.py  # Starts MCP server
# Existing tools like ingest_jd, save_tailored_cv should work normally
```

---

## Summary

✅ **Gate 3 Complete**

| Component | Status | Notes |
|-----------|--------|-------|
| Schema migration (v1.0 → v2.0) | ✅ Implemented | Reversible, idempotent, tested |
| evidence.json creation | ✅ Implemented | Auto-created on load |
| cv_versions.json creation | ✅ Implemented | Auto-created on load |
| Baseline evidence import | ✅ Implemented | From profile.json, tested |
| Backward compatibility | ✅ Verified | Old code works unchanged |
| Rollback capability | ✅ Verified | Can revert to v1.0 |
| Test coverage | ✅ Complete | 15+ tests, all passing |

**Next:** Gate 4 (Career Evidence Services) — CRUD and query services.
