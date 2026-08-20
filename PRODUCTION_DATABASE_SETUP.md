# Production Database Setup

## Status: ✅ CONFIGURED FOR NAS POSTGRESQL

The Job Applications MCP Server is now configured to use **PostgreSQL on NAS** (rv-cloud.local:5432) for all persistent storage in production.

---

## Configuration

### pi-4 Environment (.env)

```
DATABASE_URL=postgresql://postgres:password@rv-cloud.local:5432/job_applications
NAS_SYNC_PATH=gs@rv-cloud.local:/share/job-app-data/
```

**Details:**
- **Host:** rv-cloud.local (NAS)
- **Port:** 5432 (standard PostgreSQL)
- **Database:** job_applications
- **Connection:** Verified working ✓

### Mac Environment (.env)

- **DATABASE_URL:** Not set (uses in-memory for stdio mode, which is acceptable for development)
- **MCP_MODE:** stdio

---

## Backend Initialization Logic

The MCP server uses intelligent backend selection:

1. **If DATABASE_URL is set and valid PostgreSQL URL:**
   - Connect to PostgreSQL
   - Use PostgresEvidenceBackend (production)
   - Log: "PostgreSQL backend initialized successfully"

2. **If DATABASE_URL not set or connection fails:**
   - Fall back to InMemoryEvidenceBackend
   - Log: "using in-memory backend"

**Current status on pi-4:** ✅ PostgreSQL (production)
**Current status on Mac:** ✅ In-memory (acceptable for development)

---

## Verification

### Check Active Backend

```bash
# On pi-4, grep the startup logs
systemctl --user status job-applications-mcp.service

# Should show:
# INFO:src.evidence_backend:Connected to Postgres: postgresql://postgres:password@rv-cloud.local:5432/job_applications
# INFO:job_applications_mcp_server:PostgreSQL backend initialized successfully
```

### Test Data Persistence

```bash
# List opportunities (queries PostgreSQL)
ssh gs@gs-pi-4 'cd ~/Projects/Job-Applications && \
  source venv/bin/activate && \
  python3 -c "from job_applications_mcp_server import list_opportunities; \
    print(list_opportunities())"'
```

---

## Data Location

### Production (Persistent)
- **Database:** PostgreSQL on NAS (rv-cloud.local:5432)
- **Database name:** job_applications
- **Tables:** All opportunity, evidence, and workflow data
- **Backup:** NAS Docker containers with volume persistence

### Local Cache (Non-Persistent)
- **Mac:** In-memory backend (cleared on app exit)
- **pi-4:** Only during active connections

### Tracker Files (Hybrid)
- **Source:** /home/gs/Projects/Job-Applications/tracker.json (pi-4)
- **Sync destination:** NAS via rsync (NAS_SYNC_PATH)
- **Frequency:** After every update

---

## Before/After

### Before (Bug)
- DATABASE_URL pointed to localhost:5432
- PostgreSQL not running on pi-4
- Server fell back to in-memory backend
- Data was not persistent across service restarts
- Log: "using in-memory backend"

### After (Fixed)
- DATABASE_URL points to rv-cloud.local:5432
- PostgreSQL running on NAS
- Server connects to production database
- Data persists across service restarts
- Log: "PostgreSQL backend initialized successfully"

---

## Cleanup Completed

Removed unnecessary test artifacts to keep systems clean:

**On Mac:**
- ✓ Removed .pytest_cache/
- ✓ Removed __pycache__/
- ✓ Removed job_digest.log
- ✓ Removed .coverage

**On pi-4:**
- ✓ Removed .pytest_cache/
- ✓ Removed __pycache__/
- ✓ Removed job_digest.log
- ✓ Removed .coverage
- ✓ Freed ~20-50MB disk space

**Test files retained** (part of CI/CD):
- tests/unit/*
- tests/integration/*
- tests/acceptance/*
- test_*.py (root level)

---

## Current Disk Usage

| System | Size | Contents |
|--------|------|----------|
| Mac    | ~130MB | Code + venv + data |
| pi-4   | ~428MB | Code + venv + data + digests |
| NAS    | PostgreSQL DB | All persistent data |

---

## No Data on Mac or pi-4 for:
- ✓ Opportunity records (PostgreSQL on NAS)
- ✓ Evidence items (PostgreSQL on NAS)
- ✓ Interview context (PostgreSQL on NAS)
- ✓ User profile changes (synced to NAS)

---

## Service Restart Status

**2026-08-20 14:34 UTC+8**

Service restarted after configuration change:
- ✓ job-applications-mcp.service restarted
- ✓ Connected to PostgreSQL on NAS
- ✓ Listening on port 8086
- ✓ Ready for requests

---

**Last Updated:** 2026-08-20  
**Configuration:** Production-ready ✅
