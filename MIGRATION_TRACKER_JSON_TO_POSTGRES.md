# Migration Task: tracker.json → PostgreSQL

## Status: PENDING

tracker.json should be **retired** since PostgreSQL on NAS maintains the canonical source of truth for applications.

---

## Current State

### tracker.json (Legacy - Should be Retired)
- **Location:** `/home/gs/Projects/Job-Applications/tracker.json` (pi-4 local)
- **Content:** Application records with full history, followups, stage transitions
- **Current Role:** Source of truth for applications (WRONG - should be DB)
- **Size:** ~25KB
- **Last Updated:** 2026-08-20

### PostgreSQL (Correct - Should Be Canonical)
- **Location:** NAS (rv-cloud.local:5432), database: `job_applications`
- **Schema:** `prisma/schema.prisma` defines `Application` model
- **Status:** Ready to receive application data
- **Models:** Application, InterviewContext, WorkflowState, CVRecord, StructuredEvidence

---

## Migration Steps

### 1. Migrate Data from tracker.json → PostgreSQL
```bash
# Create migration script that:
# - Reads all applications from tracker.json
# - Creates Application records in PostgreSQL
# - Preserves all metadata (stage, dates, followups as JSON or separate records)
# - Validates data integrity
```

### 2. Update Code to Query PostgreSQL
- `list_applied_opportunities()` should query `Application` model instead of reading tracker.json
- `get_opportunity()` should query PostgreSQL
- `update_opportunity_stage()` should write to PostgreSQL
- All application mutations should go to DB, not JSON

### 3. Keep tracker.json as Backup (Temporary)
- Don't delete tracker.json immediately
- Keep as fallback for emergency recovery
- Remove from git after verification

### 4. Remove tracker.json from Code
- Remove TRACKER_PATH references
- Remove tracker.json fallback logic
- Remove JSON reading/writing code

---

## Data Structure Mapping

### tracker.json application record:
```json
{
  "id": "uuid-here",
  "company": "Gartner",
  "role_title": "Strategic Account Executive",
  "jd_path": "path/to/jd.md",
  "stage": "interview_r3",
  "date_created": "2026-06-22T02:00:00Z",
  "history": [...],
  "followups": [...]
}
```

### PostgreSQL Application model:
```
Application {
  id: String (UUID)
  name: String (from tracker.id)
  company: String
  roleTitle: String
  jdPath: String
  stage: String
  createdAt: DateTime
  updatedAt: DateTime
  cvRecords: CVRecord[]
  interviewContexts: InterviewContext[]
  workflowState: WorkflowState
}
```

### Additional Tables Needed:
- **ApplicationHistory** - for tracking stage transitions (history array)
- **ApplicationFollowup** - for followups array
- Or: Store as JSON fields in PostgreSQL (simpler, JSON native support)

---

## Timeline

| Phase | Task | Effort | Status |
|-------|------|--------|--------|
| Phase 1 | Create migration script | 2-4h | TODO |
| Phase 2 | Test migration in dev | 2h | TODO |
| Phase 3 | Update MCP tools to use DB | 3-4h | TODO |
| Phase 4 | Verify data integrity | 2h | TODO |
| Phase 5 | Retire tracker.json | 30min | TODO |

---

## Current Tools State

### ✅ list_applied_opportunities (needs update)
- Currently reads tracker.json
- Should query PostgreSQL Application model
- Add TODO comment to docstring

### ✅ list_job_discoveries (new)
- Reads from digest files (correct - these are temporary feeds)
- Not affected by this migration

### ✅ get_opportunity (needs update)
- Currently reads tracker.json
- Should query PostgreSQL

### ✅ get_application_status (needs update)
- Currently reads tracker.json
- Should query PostgreSQL

---

## Git Tracking

- **Status note added:** 2026-08-20 (this file)
- **Backward compatibility:** list_opportunities() alias maintained
- **Code comments:** TODO markers added to affected functions

---

## Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| Data loss during migration | Keep tracker.json backup for 2 weeks |
| Query performance regression | Add indexes to PostgreSQL (already in schema) |
| Incomplete migration | Validate record counts and spot-check data |
| Code still reading tracker.json | Search codebase after removal for "TRACKER_PATH" |

---

## Success Criteria

- ✅ All application records migrated to PostgreSQL
- ✅ All MCP tools query PostgreSQL (not tracker.json)
- ✅ tracker.json removed from git
- ✅ No references to TRACKER_PATH in production code
- ✅ All tests pass with PostgreSQL backend

---

**Owner:** @user  
**Created:** 2026-08-20  
**Target Completion:** 2026-08-27
