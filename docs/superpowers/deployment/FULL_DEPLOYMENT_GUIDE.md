# Full Deployment Guide: Job-Applications to Postgres

**Date:** 2026-08-19  
**Target:** pi-4 (Debian 13, Python 3.13)  
**Architecture:** Evidence-based CV generation with Postgres persistence

## Overview

This guide walks through deploying Gate 10 (interactive evidence discovery & CV workflow) to production with full Postgres initialization.

**Key Changes:**
- Code/services on pi-4 (no Mac execution)
- Data on NAS-shared Postgres (job_applications DB)
- 7 MCP workflow tools + 3 CV file access tools
- Full migration pipeline: base CV → applications → evidence → cleanup

## Prerequisites

- [ ] pi-4 accessible via SSH as user `gs`
- [ ] Tailscale Serve configured on pi-4
- [ ] Postgres server running on NAS (192.168.10.109:5432)
- [ ] Job-Applications code deployed to pi-4 (~/Projects/Job-Applications)
- [ ] Python venv configured on pi-4 with dependencies
- [ ] Claude Desktop configured with MCP endpoint

## Deployment Checklist

### 1. Pre-Deployment Validation

```bash
# On pi-4:
cd ~/Projects/Job-Applications
source venv/bin/activate

# Check dependencies
pip list | grep -E 'prisma|fastmcp|langchain'

# Verify Postgres connectivity
python3 -c "
import psycopg2
conn = psycopg2.connect('postgresql://postgres:password@192.168.10.109/job_applications')
print('✓ Postgres connection successful')
conn.close()
"

# Check base CV exists
test -f "/home/gs/Projects/Job-Applications/DXC/CV LEE Gee Sin 2026 - DXC Client Partner Public Sector.md" && echo "✓ Base CV found"
```

### 2. Initialize Postgres Schema

```bash
# On pi-4:
cd ~/Projects/Job-Applications

# Run Prisma migrations
npx prisma migrate deploy

# Verify schema
npx prisma studio  # Open browser to http://localhost:5555
```

### 3. Phase A: Base CV Ingestion

```bash
# On pi-4:
cd ~/Projects/Job-Applications
python3 scripts/migrate_to_postgres_full.py --phase a

# Expected output:
# [INFO] Parsing base CV: /home/gs/Projects/Job-Applications/DXC/...
# [INFO] Created application record: <uuid>
# [INFO] Created CVRecord: <uuid>
# [INFO] Ingested 150+/150+ evidence items into Postgres

# Verify in Postgres:
psql postgresql://postgres:password@192.168.10.109/job_applications << EOF
SELECT COUNT(*) as evidence_count FROM "StructuredEvidence";
SELECT COUNT(*) as app_count FROM "Application";
EOF
```

### 4. Phase B: Application Migration

```bash
# On pi-4:
python3 scripts/migrate_to_postgres_full.py --phase b

# Expected output:
# [INFO] Found X applications in tracker.json
# [INFO] Migrated X/X applications

# Verify:
psql postgresql://postgres:password@192.168.10.109/job_applications << EOF
SELECT name, COUNT(*) FROM "Application" GROUP BY name;
EOF
```

### 5. Phase C: Evidence Discovery

```bash
# On pi-4:
python3 scripts/migrate_to_postgres_full.py --phase c

# Expected output:
# [INFO] Found X company folders
# [INFO] Discovered Y additional evidence items
```

### 6. Phase D: Cleanup

```bash
# On pi-4:
python3 scripts/migrate_to_postgres_full.py --phase d

# Expected output:
# [INFO] Backed up tracker.json to tracker.json.backup
# [INFO] Removed: Gartner/gap_analysis.md
# [INFO] Cleanup complete
```

### 7. Run Full Migration (All Phases)

```bash
# On pi-4:
python3 scripts/migrate_to_postgres_full.py --phase all

# Tail logs in another session:
tail -f migration.log
```

### 8. Verify MCP Server

```bash
# On pi-4:
systemctl --user status job-applications-mcp.service

# Expected output:
# Active: active (running) since ...
# [INFO] Uvicorn running on http://0.0.0.0:8086

# Test endpoint:
curl -s -H 'Authorization: Bearer <TOKEN>' \
  -X POST -H 'Content-Type: application/json' \
  http://localhost:8086/mcp \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | jq .
```

### 9. Update Claude Desktop Config

**File:** `~/Library/Application Support/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "job-applications": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote",
        "https://gs-pi-4.tail210e4f.ts.net/mcp",
        "--header",
        "Authorization:Bearer qp0rSc-xe8yl2HoHB7P5FkQm6zTiXeCnzEGWqDtwUs8"
      ]
    }
  }
}
```

Then restart Claude Desktop.

### 10. Verify Tools in Claude Desktop

In Claude Desktop, check the tools panel:
- [ ] start_job_application_workflow
- [ ] generate_clarifying_questions
- [ ] answer_clarifying_questions
- [ ] generate_cv_draft
- [ ] revise_cv
- [ ] confirm_cv
- [ ] get_workflow_state
- [ ] get_base_cv
- [ ] get_reference_cv
- [ ] save_tailored_cv

All 10 tools should be discoverable.

### 11. Run Production Test

1. **Start workflow:**
   ```
   Call start_job_application_workflow with a job description
   ```

2. **Expected flow:**
   - Analyzes JD, extracts skills and criteria
   - Matches against base CV evidence in Postgres
   - Returns matched evidence + gaps
   - Generates clarifying questions

3. **Generate CV:**
   - Call get_base_cv() to retrieve CV content
   - Call generate_cv_draft() with matched evidence
   - Call save_tailored_cv() to store result

4. **Verify database:**
   ```bash
   # Check workflow state persistence
   psql postgresql://postgres:password@192.168.10.109/job_applications << EOF
   SELECT * FROM "Application" WHERE name LIKE 'test-app%';
   SELECT COUNT(*) FROM "StructuredEvidence" WHERE application_id IS NOT NULL;
   EOF
   ```

## Rollback Plan

If migration fails:

```bash
# On pi-4:
# 1. Restore tracker.json from backup
cp ~/Projects/Job-Applications/tracker.json.backup ~/Projects/Job-Applications/tracker.json

# 2. Restart MCP service
systemctl --user restart job-applications-mcp.service

# 3. Check logs
journalctl --user-unit=job-applications-mcp.service -n 50
```

## Troubleshooting

### "Postgres connection refused"
```bash
# Check NAS Postgres
ssh gs@rv-cloud.local "docker ps | grep job_applications"

# Verify DATABASE_URL on pi-4
cat ~/Projects/Job-Applications/.env | grep DATABASE_URL
```

### "Prisma client not found"
```bash
# On pi-4:
source venv/bin/activate
pip install -U prisma
npx prisma generate
```

### "MCP tools not discoverable"
```bash
# Restart Claude Desktop
killall "Claude Desktop"
open /Applications/"Claude Desktop".app

# Check authorization header
curl -s -H 'Authorization: Bearer WRONG_TOKEN' http://localhost:8086/mcp
# Should return 401 Unauthorized
```

### "Base CV not found"
```bash
# Check path
ls -la "~/Projects/Job-Applications/DXC/CV LEE Gee Sin 2026 - DXC Client Partner Public Sector.md"

# Set correct path
export JOB_APP_BASE_CV_PATH="/path/to/correct/cv.md"
python3 scripts/migrate_to_postgres_full.py --phase a
```

## Post-Deployment

1. **Monitor logs:**
   ```bash
   tail -f migration.log
   journalctl --user-unit=job-applications-mcp.service -f
   ```

2. **Validate data integrity:**
   ```bash
   # Check for orphaned records
   psql postgresql://postgres:password@192.168.10.109/job_applications << EOF
   SELECT COUNT(*) FROM "CVRecord" WHERE "applicationId" NOT IN (SELECT id FROM "Application");
   SELECT COUNT(*) FROM "StructuredEvidence" WHERE "source_cv_id" NOT IN (SELECT id FROM "CVRecord");
   EOF
   ```

3. **Backup Postgres:**
   ```bash
   pg_dump postgresql://postgres:password@192.168.10.109/job_applications > backup_post_migration.sql
   ```

## Architecture After Deployment

```
┌─────────────────────┐
│  Claude Desktop     │
│  (MacBook)          │
└──────────┬──────────┘
           │ Tailscale HTTPS
           │ Bearer Token Auth
           ↓
┌─────────────────────────────────────────┐
│  Job-Applications MCP (pi-4 :8086)      │
│  - start_job_application_workflow       │
│  - generate_clarifying_questions        │
│  - generate_cv_draft                    │
│  - get_base_cv / get_reference_cv       │
│  - save_tailored_cv                     │
└──────────┬──────────────────────────────┘
           │ LangChain ReAct + Postgres
           ↓
┌──────────────────────────────────────────────┐
│  Postgres (NAS: 192.168.10.109:5432)         │
│  - Application (tracker)                     │
│  - CVRecord (base CV + generated)            │
│  - StructuredEvidence (extracted evidence)   │
│  - CVEvidenceUsage (CV section mapping)      │
└──────────────────────────────────────────────┘
```

## Next Steps

1. Run production test with comprehensive job description
2. Validate evidence matching accuracy (>80% confidence threshold)
3. Test CV revision cycles (feedback → revise → confirm)
4. Monitor Postgres query performance with large evidence sets
5. Plan for periodic evidence updates (new projects, roles)
6. Set up automated backup of Postgres to NAS
