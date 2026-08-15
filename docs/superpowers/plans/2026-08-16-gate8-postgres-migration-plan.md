# Gate 8: PostgreSQL Migration for CV Versioning

**Date:** 2026-08-16  
**Goal:** Migrate from JSON file-based persistence to NAS PostgreSQL  
**Architecture:** Prisma ORM, same API (CVVersioningService), persistent storage on NAS

---

## Why PostgreSQL?

**Gate 7 (JSON + rsync) solved:**
- ✅ Persistence across service restarts
- ✅ NAS backup via rsync
- ✅ Single-application CV tracking

**Gate 8 (Postgres) enables:**
- ✅ Cross-application evidence reuse queries
- ✅ Complex filtering & analytics
- ✅ Concurrent writes safely
- ✅ No JSON serialization overhead
- ✅ Integration with AI-CRM pattern (existing Prisma setup)

**When to use:**
- Now: Enables evidence reuse features (Gate 9)
- Already built: NAS Postgres infrastructure (AI-CRM, GeBiz use it)
- No new deployment: Just add schema to existing NAS Postgres

---

## Infrastructure

**Connection:**
```
CVVersioningService → Prisma Client → NAS Postgres
                                    (rv-cloud.local:5432)
                                    [ai-assistant-db]
```

**Similar to:** AI-CRM setup (prisma/schema.prisma, DATABASE_URL env var)

**No host-publishing:** Internal NAS bridge only (existing pattern)

---

## Schema Design

```prisma
model CVRecord {
  id              String    @id @default(uuid())
  cvId            String    @unique
  applicationId   String
  version         String
  status          String    // draft | approved | final
  content         String    @db.Text
  createdAt       DateTime  @default(now())
  approvedBy      String?
  approvedAt      DateTime?
  finalizedAt     DateTime?
  
  evidence        CVEvidenceUsage[]
  application     Application @relation(fields: [applicationId], references: [id])
  
  @@index([applicationId])
  @@index([status])
  @@index([createdAt])
}

model CVEvidenceUsage {
  id              String    @id @default(uuid())
  cvRecordId      String
  evidenceId      String
  requirementId   String
  contentExcerpt  String    @db.Text
  placementSection String
  
  record          CVRecord  @relation(fields: [cvRecordId], references: [id], onDelete: Cascade)
  
  @@index([cvRecordId])
  @@index([evidenceId])
}

model Application {
  id              String    @id @default(uuid())
  name            String
  createdAt       DateTime  @default(now())
  
  cvRecords       CVRecord[]
}
```

---

## Tasks

### Task 1: Create Prisma Schema

**Purpose:** Define data model for CV records in Postgres

**What to do:**
1. Create `prisma/schema.prisma` (or update if exists)
2. Define CVRecord, CVEvidenceUsage, Application models
3. Add migrations directory
4. Write failing tests for schema validation

### Task 2: Create Prisma Client & Database Layer

**Purpose:** Implement persistence layer with Prisma

**What to do:**
1. Add Prisma dependency to project
2. Create `db.py` or `prisma_client.py` helper
3. Implement `load_cv_records()` and `save_cv_records()` using Prisma
4. Write tests for DB operations

### Task 3: Refactor CVVersioningService for Postgres

**Purpose:** Replace JSON persistence with Prisma queries

**What to do:**
1. Update `__init__()` to use Prisma instead of file loading
2. Replace `_persist_records()` with Prisma `.create()` / `.update()`
3. Update `get_cv_history()` to use `.findMany()` query
4. Verify all Gate 6+7 tests still pass

### Task 4: Migration Script (JSON → Postgres)

**Purpose:** Migrate existing cv_records.json to Postgres

**What to do:**
1. Create migration script: `scripts/migrate_json_to_postgres.py`
2. Read cv_records.json
3. Transform and insert into Postgres
4. Verify record count matches

### Task 5: Full Verification

**Purpose:** End-to-end testing with Postgres backend

**What to do:**
1. Run all CVVersioningService tests (should all pass)
2. Test cross-database persistence
3. Verify NAS connection works
4. Check coverage >90%
5. Document Postgres setup for deployment

---

## Configuration

**Environment variables:**
- `DATABASE_URL` — Postgres connection string
  - Example: `postgresql://user:pass@rv-cloud.local/ai-assistant-db`
  - Stored in: `.env` (local) or UGOS env (NAS)

**No changes to:**
- CVVersioningService API
- MCP tool signatures
- Test interfaces

---

## Success Criteria

- ✅ 30+ tests PASSING with Postgres backend
- ✅ Coverage >90%
- ✅ Existing cv_records.json successfully migrated
- ✅ NAS Postgres connection verified
- ✅ No API changes to CVVersioningService
- ✅ Prisma migrations tracked in git

---

## Next Phase (Gate 9)

Once Postgres is live:
- Cross-application evidence queries
- Evidence reuse scoring
- Bulk CV generation with shared evidence
