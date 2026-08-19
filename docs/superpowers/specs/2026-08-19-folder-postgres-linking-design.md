# Design: Folder-Postgres Linking for Job Applications

**Date:** August 19, 2026  
**Status:** Design Phase  
**Purpose:** Establish bidirectional linking between NAS file system and Postgres database for complete context capture

---

## Overview

The Job Applications workflow spans two storage systems:
- **Postgres (NAS):** Application records, evidence, CV versions
- **File System (NAS):** Company folders, JDs, submitted CVs, interview transcripts, research

This design establishes **bidirectional linking** so that:
- Each Application record links to its company folder
- Each folder has a metadata file linking back to the Application record
- Interview context (transcripts, notes) are versioned and linked to stages

---

## Architecture

### NAS Folder Structure

```
/mnt/job-app-data/
├── applications/
│   ├── {application-id}/          # UUID-based application folder
│   │   ├── metadata.json          # links to company, stage, Postgres ID
│   │   ├── jd.md                  # Job description (parsed/cleaned)
│   │   ├── cv-base.md             # Master CV (copied from base-cv/)
│   │   ├── cv-tailored.md         # Final CV (version 1)
│   │   ├── cv-tailored-v2.md      # Previous revisions (kept for history)
│   │   ├── cover-letter.md        # Cover letter (if written)
│   │   ├── research/
│   │   │   ├── company.md         # Research on company
│   │   │   └── role-analysis.md   # Role-specific gaps
│   │   ├── interview-r1/
│   │   │   ├── transcript.md      # Claude Desktop conversation capture
│   │   │   ├── notes.md           # Interviewer notes/key points
│   │   │   └── follow-ups.md      # Action items from interview
│   │   ├── interview-r2/
│   │   ├── interview-r3/
│   │   └── artifacts/
│   │       └── ... (other supporting files)
│   ├── {application-id-2}/
│   └── ...
│
├── evidence/                      # Reusable evidence library (by project/skill)
│   ├── leadership.md
│   └── technical.md
│
└── base-cv/
    └── current.md
```

### Postgres Schema Additions

**Application Model** (enhanced):
```sql
Application {
  id             UUID        -- Primary key
  name           String      -- From tracker.json: application.id (unique)
  company        String      -- "Gartner", "PwC", etc.
  roleTitle      String?     -- "SAE", "Director", etc.
  jdPath         String?     -- Path to JD (relative to app folder)
  stage          String      -- "new" | "applied" | "screening" | "interview_r1" | ... | "rejected" | "offer"
  folderPath     String?     -- Absolute path: /mnt/job-app-data/applications/{id}/
  cvFinalized    Boolean     -- Has CV been finalized?
  matchScore     Float?      -- Current match %
  createdAt      DateTime
  updatedAt      DateTime
}
```

**InterviewContext Model** (new):
```sql
InterviewContext {
  id              CUID        -- Primary key
  applicationId   UUID        -- FK to Application
  interviewRound  String      -- "r1" | "r2" | "r3"
  transcriptPath  String?     -- interview-{round}/transcript.md
  notesPath       String?     -- interview-{round}/notes.md
  followUpsPath   String?     -- interview-{round}/follow-ups.md
  questions       String[]    -- Extracted questions from transcript
  keyThemes       String[]    -- Topics discussed
  nextSteps       String?     -- What happens next
  createdAt       DateTime
  updatedAt       DateTime
}
```

**WorkflowState Model** (new):
```sql
WorkflowState {
  id              CUID        -- Primary key
  applicationId   UUID        -- FK to Application (1:1)
  currentStage    String      -- Gate 10 workflow stage
  gatheredEvidence String[]   -- Evidence IDs collected during workflow
  pendingFeedback String?     -- User feedback awaiting revision
  createdAt       DateTime
  updatedAt       DateTime
}
```

### metadata.json (in each application folder)

```json
{
  "applicationId": "550b7c93-05eb-4ca7-97e7-2f1bdb630838",
  "company": "Gartner",
  "roleTitle": "Strategic Account Executive - Large Accounts",
  "stage": "interview_r3",
  "jdPath": "jd.md",
  "cvBase": "cv-base.md",
  "cvTailored": "cv-tailored.md",
  "createdAt": "2026-06-22T02:00:00Z",
  "updatedAt": "2026-08-19T22:00:00Z",
  "linkedAt": "2026-08-19T22:00:00Z"
}
```

---

## Bidirectional Linking Mechanism

### Direction 1: Postgres → File System
**Query:** Get all files for an application
```python
app = await db.application.find_unique(where={"id": "550b7c93-..."})
# folderPath = "/mnt/job-app-data/applications/550b7c93-..."
# Read: {folderPath}/metadata.json, {folderPath}/jd.md, etc.
```

### Direction 2: File System → Postgres
**Query:** Get app record from folder
```python
# Read: /mnt/job-app-data/applications/{folder-name}/metadata.json
# metadata.applicationId = "550b7c93-..."
app = await db.application.find_unique(where={"id": metadata.applicationId})
```

### Consistency Checks
- On every file write, update Application.updatedAt
- On every Application update, verify folderPath still exists
- metadata.json must match Application record (sanity check)

---

## Interview Context Capture (Gate 10 Integration)

### Transcript Capture Flow
```
Claude Desktop Interview Session
  ↓ (user copies conversation)
User pastes in Gate 10 tool call: log_interview_context()
  ↓
MCP Tool receives transcript + applicationId + round
  ↓
Tool writes to: /mnt/job-app-data/applications/{id}/interview-{round}/transcript.md
  ↓
Tool creates InterviewContext record in Postgres
  ↓
Tool extracts: questions, themes, next steps (via Claude API)
```

### Keys to Context Preservation
1. **Raw Transcript** saved in markdown (human-readable, searchable)
2. **Extracted Metadata** in Postgres (questions, themes, for re-scoring JD match)
3. **Version History** in file system (keep all CV/transcript versions)
4. **Workflow State** in Postgres (current stage in Gate 10, pending feedback)

---

## File Structure Sync Tasks

### Phase 1: Create Application Folders (from existing tracker.json)
For each application in tracker.json:
1. Create `/mnt/job-app-data/applications/{application-id}/`
2. Create `metadata.json` with company, role, stage
3. Copy/symlink JD.md from Mac ~/Projects/Job-Applications/{company}/ (if exists)
4. Copy base CV to cv-base.md
5. Create Application record with folderPath set

### Phase 2: Migrate Existing Files
For each company folder on NAS:
1. If multiple roles exist, create role-specific subdirectories
2. Move interview notes into interview-{round}/ subdirectories
3. Create InterviewContext records for existing interviews

### Phase 3: Setup Metadata Sync
- On save_tailored_cv(), update metadata.json and Application.cvFinalized
- On log_interview_context(), update metadata.json and create InterviewContext
- On update application stage, sync to metadata.json

---

## MCP Tools Needed

### New Tools (Phase 1)

| Tool | Purpose |
|------|---------|
| `sync_app_folders_from_tracker()` | Create folder structure from tracker.json |
| `migrate_interview_files()` | Move existing interview notes into versioned structure |
| `get_application_files()` | Return list of files for an application (linked from Postgres) |
| `get_application_from_folder()` | Find Application record by folder path |

### Enhanced Tools (Phase 2 & 3)

| Tool | Changes |
|------|---------|
| `save_tailored_cv()` | Also update metadata.json + Application.cvFinalized |
| `log_interview_context()` | Create InterviewContext record, extract metadata |
| Existing save_* tools | Update metadata.json on every write |

---

## Validation & Consistency

### On-Read Checks
- If folderPath doesn't exist, warn and suggest recovery
- If metadata.json doesn't match Application record, flag for repair

### On-Write Checks
- After writing file, verify Application.updatedAt is current
- After creating Application, verify folderPath exists (create if needed)
- metadata.json must be valid JSON and match schema

### Recovery Tools
- `repair_metadata()` - Rebuild metadata.json from Application record
- `repair_folder_structure()` - Create missing subdirectories

---

## Timeline

1. **Immediate:** Implement schema + Phase 1 sync (populate folders from tracker.json)
2. **Next:** Build interview context capture (Phase 2 & 3 tools)
3. **Final:** Integrate into Gate 10 workflow (feedback loop, CV versioning)

