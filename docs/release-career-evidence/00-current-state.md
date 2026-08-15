# Gate 0: Current State Assessment
## Career Evidence Repository + Governed CV Workflow Release

**Date:** 2026-08-14  
**Status:** Pre-implementation assessment complete  
**Scope:** Job-Applications MCP Server v0.3.0

---

## Executive Summary

The Job-Applications MCP Server is a **workflow-and-output-tracking system**, not a **career evidence repository system**. It successfully manages job application lifecycle, document generation, conflict detection, and fabrication protection, but **does not persist evidence across applications** or implement a draft/final CV approval workflow.

Implementing the Career Evidence Repository specification requires **architectural changes** to the core persistence and workflow models. The existing codebase can be extended, but will not support the requirements without adding new data structures, state transitions, and MCP tools.

---

## 1. Architecture Discovered

### Server Model
- **Type:** Single-file FastMCP server (`job_applications_mcp_server.py`, 3100+ lines)
- **Transport:** HTTP :8086 (pi-4 production) or stdio (Mac dev)
- **Auth:** Bearer token (MCP_AUTH_TOKEN env var)
- **Persistence:** JSON files on NFS-mounted NAS (`/mnt/job-app-data`)

### Core Components
1. **MCP Server** — 31 @mcp.tool() functions across 5 functional groups
2. **Tracker** — `tracker.json` application records with stage machine
3. **Profile** — `profile.json` with source-tagged work history and conflict detection
4. **File System** — Per-company directories containing JD.md, CV variants, gap_analysis.md, etc.
5. **Daily Pipelines** — `job_digest.py` (LinkedIn alerts) and `tracker_daily.py` (follow-up scheduler)

### External Dependencies
- **fleet_notify** — shared SMTP library for email dispatch (not in requirements.txt)
- **Gmail API** — OAuth2 for LinkedIn alert ingestion (google-auth-oauthlib, google-api-python-client, not in requirements.txt)
- **FastMCP >=2.0,<3** — MCP server framework (fleet-wide pin)

---

## 2. Current Workflow

### Application Lifecycle (Start to Finish)

```
ingest_jd
  ↓
[Application created in "new" stage if not exists]
  ↓
score_match (context-prep)
  ↓
save_match_score (stores in app["match_score"])
  ↓
analyse_gaps (context-prep)
  ↓
save_gap_analysis (writes {Company}/gap_analysis.md)
  ↓
[Optional: iterative refinement via gap questions]
  ↓
tailor_cv (context-prep)
  ↓
save_tailored_cv (writes {Company}/CV_tailored.md, can be called multiple times)
  ↓
[Optional: save_interview_notes, save_cover_letter, save_pitch, etc.]
  ↓
mark_submitted (copies CV/cover_letter to submitted/, updates app["submitted"])
  ↓
update_stage (manual transition through tracker stages)
```

### Stage Machine

```
new → applied → screening → interview_r1 → interview_r2 → interview_r3 → offer → accepted
  ↓                                                                        ↓
  └──────────────────────────────────────────────────────────────────────┘
                        ↓                      ↓
                      rejected              withdrawn
```

**Terminal stages:** accepted, rejected, withdrawn (no outbound transitions)

**Key observation:** Application is created at ingest_jd (start of workflow), NOT when create_application is called. create_application is a filesystem-only helper.

---

## 3. Current Storage Model

### tracker.json Application Record

```json
{
  "id": "uuid4",
  "company": "string",
  "role_title": "string",
  "jd_path": "string or null",
  "stage": "string (one of VALID_STAGES)",
  "date_created": "ISO8601",
  "history": [{"stage": "string", "at": "ISO8601"}],
  "followups": [{"id": "uuid4", "action_type": "string", "due_date": "YYYY-MM-DD", "status": "string"}],
  "jd_source_url": "string (optional, provenance reference only)"
}
```

**Observation:** NO `outputs`, `submitted`, `match_score`, `gaps` fields in current tracker.json, though code creates them in memory. **Not yet persisted to disk.**

### profile.json Candidate Record

```json
{
  "schema_version": "1.0",
  "headline": "string",
  "current_role": {"title": "string", "company": "string"},
  "work_experience": [{
    "title": "string",
    "company": "string",
    "start": "YYYY-MM",
    "end": "YYYY-MM or 'present'",
    "description": "string",
    "_source": "cv | linkedin"
  }],
  "education": [{...}],
  "certifications": [],
  "skills": ["string"],
  "conflicts": [{
    "field_path": "string",
    "linkedin_value": "string",
    "cv_value": "string",
    "flagged_at": "ISO8601"
  }],
  "last_updated": {
    "work_experience": "ISO8601",
    "education": "ISO8601",
    "skills": "ISO8601"
  }
}
```

**Observation:** Profile entries have `_source` (origin marker: cv, linkedin, session) and conflicts[] (logged contradictions), but NO `verified`, `confidence`, `evidence_id`, or `source_reference` fields.

### Per-Company File Structure

```
{Company}/
├── JD.md                           # Ingested job description
├── CV_tailored.md                  # Single tailored CV (overwrites each call)
├── Cover_Letter.md                 # Current cover letter
├── Cover_Letter_v1.md              # Versioned backups (cover letter only)
├── gap_analysis.md                 # Structured gap recommendations (NOT in tracker)
├── match_score.md                  # Match scoring (optional, user-generated)
├── research.md                     # Company research
├── territory_map.md                # Customer/territory mapping
├── interview_notes.md              # Timestamped interview prep
├── submitted/
│   ├── CV_tailored.md              # Snapshot of submitted CV
│   └── Cover_Letter.md             # Snapshot of submitted cover letter
└── ... (other JD PDFs, revision history, etc.)
```

**Observation:** Gap analysis is saved to markdown file only. No structured `gaps[]` in tracker. Evidence enrichment (user-supplied experience) is NOT stored anywhere except in the gap_analysis.md narrative.

---

## 4. Existing Job Application Tracker Behaviour

### State Transitions
- **Valid transitions:** Encoded in VALID_TRANSITIONS dict (lines 169–180)
- **Enforcement:** update_stage tool validates before transition; raises error if invalid
- **History recording:** Each transition appended to app["history"] with stage and timestamp
- **Terminal stages:** Block all further transitions

### Application Records
- **Created:** On ingest_jd call (NOT at application start, but when JD is first supplied)
- **Updated:** By update_stage, save_match_score, save_gap_analysis, mark_submitted, etc.
- **Deletion:** NOT supported (applications are terminal, not removable)

### Output Tracking (In-Memory Only)
- Code creates app["outputs"] dict with structure:
  ```json
  {
    "research": [{"path": "...", "saved_at": "..."}],
    "cover_letter": [{"path": "...", "saved_at": "...", "version": 1}],
    "match_score": [{"overall": 75, "saved_at": "..."}],
    ...
  }
  ```
- **NOT currently persisted** to tracker.json (code writes it, but JSON file does not reflect it)

### Follow-Up Management
- Auto-created on update_stage (e.g., due +7 days when moved to "applied")
- Stored in app["followups"] array
- Marked complete via mark_followup_complete tool
- Used by daily tracker_daily.py scheduler

---

## 5. Current CV Draft/Final Workflow

### Workflow Model
- **No draft vs. final distinction**
- **No approval gate**
- save_tailored_cv can be called multiple times
- Each call overwrites CV_tailored.md (no versioned backups)
- No tool to mark CV as "final", "approved", or "submitted for review"

### CV Versioning (Current State)
- **Cover letter:** YES, versioned (Cover_Letter.md → Cover_Letter_v1.md → Cover_Letter_v2.md)
  - Tracker records: `{"version": 1}` in outputs
  - Driven by need to preserve iteration history (requirements doc Req 7.5)
  
- **CV_tailored.md:** NO, not versioned
  - Single file, overwrites on each save_tailored_cv call
  - Tracker records only: `{"path": "...", "saved_at": "..."}`
  - No version field

- **Baseline CV:** Preserved at DXC/CV_LEE...md (protected from edit)

### Fabrication Protection (Current Implementation)
- **_protected_lines()** identifies base CV lines matching:
  - Quantified figures: regex `\d+\s*(?:%|\$|SGD|€|£)` (e.g., "40%", "$2M")
  - Keywords: regex `\b(?:ARR|quota|deal|target)\b` (case-insensitive)
  
- **save_tailored_cv validation** checks if protected lines are present in new content
  - If ANY protected line is altered/missing → returns error, blocks file write
  - Test confirms: can detect removal or modification of "Grew ARR by 40% to $2M SGD region."

- **Does NOT protect against:**
  - Fabrication of completely new achievements not in base CV
  - Claims that contain no quantified figures or keywords
  - Misrepresentation of roles/responsibilities (if not explicitly quantified)

---

## 6. Evidence from Applications (Persistence)

### What Is Captured
- **Gap analysis:** Recommendations for missing/understated/mismatched skills
  - Saved to {Company}/gap_analysis.md
  - Each gap has: category, current_text_excerpt (if applicable), recommendation

- **Match score:** Reasoning and missing_skills list
  - Saved to tracker app["match_score"] (in memory, not yet persisted to disk)
  - missing_skills is a string list, NOT structured evidence

### What IS NOT Captured or Reused
- User-supplied answers to gap questions are NOT stored as structured facts
- Generated CV content (reworded bullets) is NOT stored as reusable evidence
- Recommendations from one application do NOT carry forward to the next application
- No query mechanism exists to retrieve "all facts used to generate Application X"

### Evidence Enrichment Flow (Current)
```
User responds to gap questions
  ↓
Claude incorporates response into gap_analysis.md
  ↓
User approves gap_analysis.md content
  ↓
save_gap_analysis validates and saves
  ↓
[End of enrichment — no further persistence]
  ↓
Future applications start fresh with base profile only
```

**Observation:** Evidence enrichment is **conversational and ephemeral**, not architectural. No mechanism to extract and store reusable facts.

---

## 7. Major Gaps Against Specification

### Critical Gaps (Required for Specification Compliance)

| Gap | Specification Requirement | Current State | Impact |
|-----|---------------------------|---------------|--------|
| **Evidence Repository** | Atomic, reusable career facts with provenance | No distinct evidence entity; facts embedded in markdown | Cannot query "all public-sector experience" across applications |
| **Evidence Persistence** | Facts persisted and queryable across applications | Facts embedded in per-company gap_analysis.md files; no retrieval mechanism | Each application starts from baseline only |
| **Draft/Final CV Workflow** | Explicit draft creation, review gate, final approval | Single CV_tailored.md, can be overwritten; no approval stage | No protection against inadvertent CV generation during refinement |
| **Requirement Matching** | Link JD requirements to evidence in repository | analyse_gaps identifies gaps; no linking to profile facts | Cannot prove "this JD requirement is covered by this evidence" |
| **Audit Trail** | Provenance of every fact and decision | tracker history[] only records stage changes | Cannot retrieve "why was this fact used in this CV?" |
| **Evidence Quality Scoring** | Level A/B/C/D confidence hierarchy | No confidence or verification field on profile | Cannot distinguish "confirmed strong experience" from "mentioned once" |
| **Contradiction Resolution** | Explicit conflict handling, not overwrite | Conflicts logged to profile.conflicts[]; no resolution workflow | Conflicting data accumulates; no merge mechanism |
| **Evidence Deduplication** | Detect and merge duplicate facts | No duplicate detection; profile entries only matched by company+title | Same fact recorded multiple times if mentioned in different applications |

### Design Contradictions

| Area | Specification | Current Implementation | Consequence |
|------|---------------|------------------------|-------------|
| Application timing | Create record at START | Created at ingest_jd (mid-workflow) | No record if user abandons before JD ingest |
| Evidence sourcing | Separate baseline / user-supplied / inferred | All mixed in profile; only `_source` field (cv/linkedin/session) | Cannot distinguish "CV said X" from "user later said Y" |
| CV versioning | Baseline → draft v1 → draft v2 → final | Only CV_tailored.md, no versions or final flag | Cannot recover which CV variant was sent to employer |
| Gap interview | Focused questions seeking actual evidence | No gap interview tool; analyse_gaps returns context only | Gap questions are entirely LLM-driven; no structured capture |

### Partial Implementations

| Feature | What Exists | What's Missing |
|---------|------------|-----------------|
| Conflict detection | Logged to profile.conflicts[] | No resolution workflow; no merge mechanism |
| Fabrication protection | Numeric/keyword regex on CV bulletpoints | No protection for completely fabricated claims |
| Source tracking | `_source` field on profile entries (cv, linkedin, session) | No reference to original document, no timestamp, no version |
| Output recording | Paths and timestamps recorded in app["outputs"] | Not yet persisted to tracker.json; no evidence linking |

---

## 8. Proposed Gate 1 Architecture

### Career Evidence Model

```
CareerEvidence {
  evidence_id: UUID
  evidence_type: string (work_experience, achievement, skill, domain_knowledge, customer_example, leadership, technical_knowledge, other)
  
  # Factual Content
  statement: string (atomic claim, e.g., "Launched enterprise AI adoption programme at Fortune 500 bank")
  
  # Provenance
  source_type: enum (baseline_cv, linkedin, user_supplied, imported_document, inferred, generated)
  source_reference: string (e.g., "DXC CV line 23", "LinkedIn profile section", "Application: Gartner SAE")
  source_document_id: string (reference to CVRecord, LinkedInSnapshotRecord, etc.)
  source_date: ISO8601 (when source was acquired)
  
  # Lifecycle
  first_captured_at: ISO8601
  last_confirmed_at: ISO8601 (updated when user re-confirms)
  application_origin: struct {
    company: string
    role: string
    date: ISO8601
  }
  
  # Verification
  verification_status: enum (unverified, user_confirmed, inferred, conflicted, superseded)
  confidence: enum (LEVEL_A, LEVEL_B, LEVEL_C, LEVEL_D) (see below)
  user_confirmed: boolean
  
  # Relationships
  supersedes: [evidence_id] (if this replaces older facts)
  superseded_by: [evidence_id] (if this has been replaced)
  linked_to: [evidence_id] (related facts)
  
  # Tagging
  competencies: [string] (e.g., "Enterprise Sales", "AI Leadership")
  technologies: [string] (e.g., "Salesforce", "Databricks", "Kafka")
  industries: [string] (e.g., "Financial Services", "Public Sector")
  geographies: [string] (e.g., "Singapore", "APAC")
  
  # Metrics (if applicable)
  metrics: struct {
    revenue: { amount, currency, verified_source }
    quota_attainment: { percentage, period }
    customer_count: { count, verified_source }
    team_size: { count, period }
    growth_percentage: { value, period }
    ... (flexible)
  }
  
  # Notes
  notes: string (context, caveats, related details)
}
```

### Evidence Confidence Levels

```
LEVEL_A: Strong Evidence
  - Specific example + role + action + quantified outcome
  - Directly from baseline CV or LinkedIn
  - Example: "Grew revenue from $10M to $15M (50% growth) in Singapore region, 2021–2023"

LEVEL_B: Substantive Evidence
  - Specific responsibility/experience; limited measurable outcome
  - Example: "Led enterprise customer onboarding for Salesforce in Singapore; managed 15+ implementations"

LEVEL_C: General Evidence
  - User confirms familiarity/experience but limited detail
  - Example: "Familiar with data platform architecture and enterprise integration patterns"

LEVEL_D: Inference Only
  - Potentially relevant but not verified
  - CANNOT be used in CV as established fact
  - Example: "Likely has experience with cloud deployment (inferred from company's tech stack)"
```

### Application Workflow States (Extended)

```
DISCOVERED
  ↓
EVALUATING
  ↓
REQUIREMENT_ANALYSIS
  ↓
EVIDENCE_MATCHING
  ↓
GAP_ANALYSIS
  ↓
ENRICHING_PROFILE (optional, if gaps identified)
  ↓
DRAFTING
  ↓
AWAITING_CV_REVIEW (new approval gate)
  ↓
REVISING (optional, if user requests changes)
  ↓
READY_TO_APPLY
  ↓
APPLIED
  ↓
RECRUITER_SCREEN | INTERVIEW | REJECTED | WITHDRAWN
  ↓
OFFER | CLOSED
```

### Requirement Model

```
JobRequirement {
  requirement_id: UUID
  category: enum (mandatory, preferred)
  type: enum (technical_skill, domain_experience, years_of_experience, seniority, responsibility, behaviour, other)
  statement: string (e.g., "5+ years leading enterprise sales")
  extracted_from: { jd_path, line_number }
  
  # Matching to Evidence
  evidence_matches: [
    {
      evidence_id: UUID,
      match_strength: enum (STRONG, ADEQUATE, PARTIAL, NO_EVIDENCE, CONTRADICTORY, NEEDS_CLARIFICATION),
      evidence_statement: string,
      confidence: LEVEL_A|B|C|D,
      gap_description: string (if not STRONG)
    }
  ]
  
  # For gaps
  gap_interview_question: string (if match is PARTIAL/NO_EVIDENCE/NEEDS_CLARIFICATION)
  user_response: string (captured from gap interview)
  evidence_created_from_response: evidence_id (link to newly created evidence)
}
```

### CV Version Control

```
CVRecord {
  cv_record_id: UUID
  application_id: UUID
  
  version: string (baseline, draft_1, draft_2, draft_N, approved, final)
  status: enum (draft, pending_review, approved, final)
  
  content: string (markdown or HTML)
  major_changes: [string] (bullet list of key differences from baseline)
  
  evidence_used: [
    {
      evidence_id: UUID,
      statement: string,
      section: string (Professional Summary, Experience, etc.),
      confidence_used: LEVEL_A|B|C|D
    }
  ]
  
  significant_omissions: [
    {
      evidence_id: UUID,
      reason: string (e.g., "not relevant to role", "already covered by other section", "weak evidence")
    }
  ]
  
  created_at: ISO8601
  approved_at: ISO8601 (null if draft)
  finalized_at: ISO8601 (null if not finalized)
  
  # Versioning
  previous_version_id: UUID (draft_1 → draft_2 → approved → final)
}
```

### Files to Create / Modify

**New files:**
- `Job-Applications/evidence_repository.py` — CareerEvidence service (CRUD, query, provenance tracking)
- `Job-Applications/job_requirements.py` — Requirement analysis and matching
- `Job-Applications/cv_versioning.py` — Draft/final CV management
- `Job-Applications/application_workflow.py` — Extended state machine and lifecycle
- Schema migration: `Job-Applications/migrations/001_add_career_evidence.py`

**Modified files:**
- `job_applications_mcp_server.py` — Add new tools, integrate evidence services
- `tracker.json` / `profile.json` schemas — Add evidence references, extend fields
- `conftest.py` — Update test fixtures for new schemas
- All existing tests — Adapt to new state machine and evidence model

---

## 9. Implementation Sequence Recommendation

### Phase 1: Foundation (Gate 1–2)
1. **Domain Design** (Gate 1) — Finalize schemas, prove no contradictions
2. **Acceptance Tests** (Gate 2) — Write 17+ executable test scenarios before code

### Phase 2: Persistence & Queries (Gate 3–4)
3. **Migration** (Gate 3) — Add evidence tables, preserve existing applications
4. **Evidence Services** (Gate 4) — CRUD, provenance, dedup, contradiction handling

### Phase 3: Workflow (Gate 5–6)
5. **Application Workflow** (Gate 5) — Extended state machine, gap lifecycle
6. **Governed CV** (Gate 6) — Draft/final, approval gate, traceability

### Phase 4: Integration & Testing (Gate 7–8)
7. **MCP Interface** (Gate 7) — Expose new tools, teach workflow
8. **End-to-End Test** (Gate 8) — Complete scenario, fixture-based

---

## 10. Tests Currently Available

### Test Coverage Summary

| Component | Test File | Test Count | Coverage |
|-----------|-----------|-----------|----------|
| MCP Server | test_mcp_server.py | 151 functions / 34 classes | Comprehensive (stage transitions, CV protection, conflict merge) |
| Job Digest | test_job_digest.py | Multiple | LinkedIn email parsing and digest generation |
| Gmail OAuth | test_gmail_auth.py | Multiple | Token management and refresh |
| Email Parser | test_email_parser.py | Multiple | LinkedIn alert extraction |
| Backfill | test_backfill_digests.py | Multiple | Historical email import |
| Daily Tracker | test_tracker_daily.py | Multiple | Follow-up scheduling |
| Discovery Tools | test_mcp_discovery_tools.py | Multiple | review_daily_discoveries, ingest_from_discovery |

### Test Functions by Area (test_mcp_server.py)

| Area | Functions | Examples |
|------|-----------|----------|
| CV Protection | 5+ | test_rejects_altered_protected_figures, test_accepts_content_preserving_protected_figures |
| Gap Analysis | 3+ | test_rejects_empty_gaps, test_saves_valid_gaps |
| Conflict Merge | 2+ | test_linkedin_merge_wins_conflict_and_logs, test_session_merge_fills_gap |
| Stage Transitions | 6+ | test_valid_transition, test_terminal_stage_blocks_all_transitions |
| Duplicate Ingest | 1+ | test_duplicate_ingest_preserves_stage |
| Profile & Evidence | Not explicitly named for evidence persistence | Missing: evidence querying, cross-application reuse |

### Test Gaps (Required for New Release)

**NOT FOUND:**
- Tests for evidence persistence across applications
- Tests for evidence retrieval/querying
- Tests for draft vs. final CV distinction
- Tests for requirement-to-evidence linking
- Tests for evidence deduplication
- Tests for contradiction resolution workflow
- Tests for evidence confidence scoring
- Fixtures for multi-application evidence reuse scenarios

---

## 11. Risks & Decisions Required

### Schema Evolution Risk
- **Risk:** Existing applications in tracker.json have no evidence_id references; migrations must backfill or null-check
- **Mitigation:** Design reversible migration (Phase 2); preserve existing applications without evidence links until explicitly enriched

### Backward Compatibility
- **Risk:** New approval gate (AWAITING_CV_REVIEW) breaks existing workflow where save_tailored_cv is final
- **Decision Required:** Should existing applications skip approval gate? Or should workflow be retrofitted?
- **Recommendation:** Add optional `skip_review=false` parameter to save_tailored_cv; default enforces new gate

### Evidence Granularity
- **Risk:** Storing "I worked at Workato on enterprise AI adoption in APAC" as single CareerEvidence vs. atomizing into 5+ facts
- **Decision Required:** How fine-grained should evidence decomposition be?
- **Recommendation:** Store as single evidence; provide secondary "evidence relationships" to link related facts

### Confidence Scoring Subjectivity
- **Risk:** LEVEL_A/B/C/D is somewhat subjective; two people might rate the same fact differently
- **Decision Required:** Should confidence be auto-assigned based on source_type + metadata, or user-supplied, or both?
- **Recommendation:** Auto-assign based on source_type (baseline_cv → A/B, user_supplied → C/B, inferred → D); allow user override with notes

### MCP Tool Explosion
- **Risk:** 31 tools already; new evidence/requirement/workflow tools could push to 50+
- **Decision Required:** Should new tools replace existing ones (breaking change) or extend alongside?
- **Recommendation:** Extend alongside for Gate 0–2 (acceptance tests phase); after Gate 2, propose deprecation of old tools if they duplicate

---

## 12. Definition of Done (Gate 0)

✅ **Complete:** This assessment document  
✅ **Complete:** Code-level inspection of 3100+ lines  
✅ **Complete:** Schema analysis (tracker.json, profile.json)  
✅ **Complete:** MCP tool signature inventory (31 tools)  
✅ **Complete:** Test coverage analysis (151 test functions)  
✅ **Complete:** Gap identification against specification  

**Next Step:** Gate 1 (Domain Design) — user to review this document and confirm:
1. Proposed CareerEvidence model is acceptable
2. Application workflow state machine aligns with intent
3. Implementation sequence and phase breakdown is feasible
4. Backward compatibility strategy (skip_review parameter approach) is acceptable

---

## Appendix: Key File References

### Core Implementation Files
- `/Users/gslee/Projects/Job-Applications/job_applications_mcp_server.py` — Main server (lines 1–3100+)
  - VALID_STAGES (lines 161–165)
  - VALID_TRANSITIONS (lines 169–180)
  - _protected_lines() (lines 969–976)
  - save_tailored_cv() (lines 2611–2695)
  - analyse_gaps() (lines 1844–1914)

### Data Files
- `/Users/gslee/Projects/Job-Applications/tracker.json` — Live application records
- `/Users/gslee/Projects/Job-Applications/profile.json` — Candidate profile with conflicts[]

### Test Files
- `/Users/gslee/Projects/Job-Applications/test_mcp_server.py` — 1951 lines, 34 test classes, 151 functions
- Other tests — job_digest, gmail_auth, email_parser, tracker_daily, backfill_digests, discovery_tools

### Documentation
- `/Users/gslee/Projects/Job-Applications/docs/ARCHITECTURE.md` — System overview (updated 2026-08-14)
- `/Users/gslee/Projects/Job-Applications/docs/DECISIONS.md` — ADRs (updated 2026-08-14)
- `/Users/gslee/Projects/Job-Applications/docs/CURRENT_STATE.md` — Status (updated 2026-08-14)

### Specification Reference
- Original requirements: See messages in this session (Gate 0 brief, items 1–19)

---

## Summary Statement

The Job-Applications repository is **ready for Gate 1 domain design**. No blocking issues exist. The codebase provides a solid foundation for evidence persistence and governance; the new features require **architectural additions, not rewrites**. Existing tests will provide regression coverage; new tests will drive acceptance criteria for the evidence repository layer.

**Estimated Gates 1–2 effort:** 3–4 days (design + acceptance tests, no implementation yet)
