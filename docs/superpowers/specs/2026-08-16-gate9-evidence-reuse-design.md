# Gate 9: Evidence Extraction & Smart CV Assembly

**Date:** 2026-08-16  
**Status:** Design approved, ready for implementation  
**Scope:** MVP — evidence extraction + smart assembly (refinement loop in Gate 10)  
**Gates completed:** 1-8 (CV versioning, persistence, Postgres migration)

---

## Problem Statement

Gates 1-8 built CV versioning and persistence, but CV generation has two critical issues:

1. **Timeline/ordering bugs** — Evidence is not properly ordered by role/tenure, then by JD relevance
2. **Evidence deduplication** — Same evidence snippet appears verbatim in multiple sections instead of being rephrased per context
3. **Manual evidence curation** — Users manually select/assemble evidence for each new CV (no intelligent matching to JD)

Gate 9 solves all three by extracting structured evidence and using LLM intelligence to match, rephrase, and assemble CVs.

---

## Solution Overview

### High-Level Workflow

```
1. BOOTSTRAP (one-time per user)
   Ground Truth CV (finalized record from Gates 1-8)
   └─ EvidenceExtractor (LLM)
      └─ StructuredEvidence pool in Postgres

2. GENERATE CV FOR JD (per application)
   New Job Description
   └─ JDAnalyzer (LLM)
      └─ Critical criteria + inferred skills + importance ranking
   
   StructuredEvidence pool + JD analysis
   └─ EvidenceMatcher
      └─ Ranked evidence matches (by relevance to JD)
   
   Matched evidence
   └─ CVAssembler (LLM)
      └─ Tailored CV (respecting timeline, relevance, deduplication)
```

### Key Design Decisions

| Decision | Why |
|----------|-----|
| Structured evidence extraction | LLM can reason about components (achievement, context, impact, skills) rather than raw text |
| Inferred skill inference (e.g., Kafka → Big Data, Agentic AI) | JD often implies skills not explicitly stated; LLM catches these |
| Timeline-first, then relevance-ranked within role | Preserves career narrative while surfacing most relevant experiences |
| Evidence rephrasing per section | Avoids repetition while maximizing evidence reuse across CV sections |
| Postgres storage | Structured evidence benefits from relational queries (future: "all evidence demonstrating leadership") |

---

## Data Model

### StructuredEvidence Table

New Postgres table to store canonicalized evidence:

```sql
CREATE TABLE "StructuredEvidence" (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  
  -- Core evidence content
  achievement TEXT NOT NULL,           -- "Led team of 10 engineers"
  context TEXT NOT NULL,               -- "At Acme Corp, 2022-2024"
  impact TEXT,                         -- "Shipped feature 2 weeks early"
  
  -- Metadata
  skills_demonstrated TEXT[] NOT NULL, -- ["leadership", "Python", "team-building"]
  time_period_start DATE NOT NULL,     -- 2022-01-01
  time_period_end DATE NOT NULL,       -- 2024-12-31
  job_title TEXT,                      -- "Senior Engineer"
  company_name TEXT,                   -- "Acme Corp"
  
  -- Lineage
  source_cv_id UUID NOT NULL,          -- Which CV this was extracted from
  source_section TEXT,                 -- "Experience", "Skills", "Projects"
  
  -- Admin
  created_at TIMESTAMP DEFAULT now(),
  updated_at TIMESTAMP DEFAULT now(),
  
  FOREIGN KEY (source_cv_id) REFERENCES "CVRecord"(id) ON DELETE CASCADE
);

CREATE INDEX idx_skills ON "StructuredEvidence" USING GIN(skills_demonstrated);
CREATE INDEX idx_time_period ON "StructuredEvidence"(time_period_start, time_period_end);
CREATE INDEX idx_source_cv ON "StructuredEvidence"(source_cv_id);
```

**Rationale:** Structured columns allow LLM to reason about and match evidence components independently. Skills as an array enables semantic matching ("Python" ≈ "Big Data").

### JDCriteria (in-memory, not persisted)

Extracted from JD during analysis:

```python
@dataclass
class JDCriteria:
    id: str                    # UUID for this JD analysis
    explicit_skills: List[str] # ["Kafka", "Python", "AWS"]
    inferred_skills: List[str] # ["Big Data", "Stream Processing", "Agentic AI"]
    critical_criteria: List[str] # ["5+ years experience", "Team lead", "Product mindset"]
    importance_ranking: Dict[str, float] # {"Kafka": 0.95, "Agentic AI": 0.7, ...}
    company_name: str          # "IBM"
    role_title: str            # "Confluent Engineer"
```

**Rationale:** Importance ranking lets the matcher and assembler prioritize. Inferred skills catch implicit requirements.

### RankedEvidence (in-memory, not persisted)

Result of matching:

```python
@dataclass
class RankedEvidence:
    evidence: StructuredEvidence
    match_score: float                    # 0.0-1.0 (relevance to JD)
    matched_skills: List[str]             # Which skills matched
    matched_criteria: List[str]           # Which JD criteria this fulfills
    suggested_rephrasing: Optional[str]   # Alternative wording per context
```

---

## Components

### 1. EvidenceExtractor (LLM)

**Purpose:** Parse ground truth CV → extract structured evidence records

**Input:** CVRecord (finalized CV from Gates 1-8)

**Output:** List[StructuredEvidence]

**Algorithm (pseudo):**
```
For each section in CV content (Experience, Skills, Projects, Education):
  For each piece of text:
    LLM extracts:
      - achievement (what was done)
      - context (where, when, how)
      - impact (what was the result)
      - skills_demonstrated (list of skills)
      - time_period (inferred from context or explicit dates)
      - job_title, company_name (if in Experience section)
    Store as StructuredEvidence
```

**LLM Prompt Pattern:**
```
Extract structured evidence from this CV section.
For each distinct achievement/skill, extract:
- Achievement: What was accomplished (one sentence, active voice)
- Context: Where/when/team size (one sentence)
- Impact: Results or outcome (one sentence, quantified if possible)
- Skills: List of 3-5 skills this demonstrates
- Time period: Start date, end date (infer if not explicit)

Return JSON: [{"achievement": "...", "context": "...", ...}, ...]
```

**Implementation location:** `src/evidence_service.py` → `EvidenceExtractor` class

---

### 2. JDAnalyzer (LLM)

**Purpose:** Parse JD → extract criteria + inferred skills + importance ranking

**Input:** JD text (job description)

**Output:** JDCriteria

**Algorithm (pseudo):**
```
LLM reads JD and extracts:
1. Explicit skills mentioned (Kafka, Python, AWS)
2. Inferred skills from context (Kafka → Big Data, Stream Processing, Agentic AI)
3. Critical criteria (years of experience, leadership, domain knowledge)
4. Importance ranking (0.0-1.0 per skill/criterion)
```

**LLM Prompt Pattern:**
```
Analyze this job description. Extract:

1. Explicit skills (mentioned by name): ["Kafka", "Python", ...]
2. Inferred skills (implied by context, role expectations): ["Big Data", "Agentic AI", ...]
3. Critical criteria (must-haves): ["5+ years experience", "Team leadership", ...]
4. Importance ranking (0.0 = nice-to-have, 1.0 = critical):
   {"Kafka": 0.95, "Python": 0.8, "Big Data": 0.7, ...}

For inferred skills: explain your reasoning (e.g., "Kafka is a stream processing tool, so they likely want Big Data experience")

Return JSON: {
  "explicit_skills": [...],
  "inferred_skills": [...],
  "critical_criteria": [...],
  "importance_ranking": {...},
  "reasoning": "..."
}
```

**Implementation location:** `src/evidence_service.py` → `JDAnalyzer` class

---

### 3. EvidenceMatcher

**Purpose:** Match evidence to JD criteria (explicit + inferred skills)

**Input:** List[StructuredEvidence], JDCriteria

**Output:** List[RankedEvidence] (sorted by match_score descending)

**Matching logic:**
```
For each evidence:
  match_score = 0.0
  matched_skills = []
  matched_criteria = []
  
  -- Explicit skill matching
  For each skill in evidence.skills_demonstrated:
    If skill in jd.explicit_skills:
      match_score += jd.importance_ranking[skill]
      matched_skills.append(skill)
    Else if semantic_similarity(skill, jd.explicit_skills) > 0.8:
      match_score += jd.importance_ranking[best_match] * 0.9
      matched_skills.append(skill)
  
  -- Inferred skill matching (semantic)
  For each inferred_skill in jd.inferred_skills:
    For each evidence_skill in evidence.skills_demonstrated:
      If semantic_similarity(evidence_skill, inferred_skill) > 0.7:
        match_score += jd.importance_ranking[inferred_skill] * 0.7
        matched_skills.append(inferred_skill)
  
  -- Criteria matching (LLM-based)
  For each criterion in jd.critical_criteria:
    If evidence_context contains_signal_for(criterion):
      match_score += 0.1
      matched_criteria.append(criterion)
  
  Normalize match_score to [0.0, 1.0]
  Sort by match_score descending
```

**Semantic matching:** Use LLM or embedding similarity (e.g., "team management" ≈ "leadership")

**Implementation location:** `src/evidence_service.py` → `EvidenceMatcher` class

---

### 4. CVAssembler (LLM)

**Purpose:** Select relevant evidence, rephrase per section, order by timeline + relevance, generate CV text

**Input:** List[RankedEvidence], JD company/role info

**Output:** CV text (formatted, ready to save)

**Algorithm (pseudo):**
```
-- Step 1: Group evidence by role/tenure (timeline-aware)
grouped_by_role = group_by(ranked_evidence, key=(company, time_period))
for each group:
  sort by time_period DESC (most recent first within role)
  then sort by match_score DESC (relevance within role)

-- Step 2: Select evidence
selected_evidence = []
for each group in grouped_by_role:
  Take top N evidence pieces (e.g., 3-5 per role, configurable)
  selected_evidence.extend(group[:N])

-- Step 3: Rephrase and organize into sections
sections = {
  "Experience": [],
  "Skills": [],
  "Projects": []
}
for each evidence in selected_evidence:
  section = infer_best_section(evidence, jd_context)
  rephrased = rephrase_for_section(evidence, section, jd_context)
  sections[section].append(rephrased)

-- Step 4: Assemble into CV
cv_text = format_cv(sections, jd.company, jd.role)
```

**Rephrase logic (LLM):**
```
Original evidence: "Led team of 10 engineers, shipped feature in 2 weeks"

If going to "Experience" section:
  "Spearheaded team of 10 engineers to deliver feature 2 weeks ahead of schedule"

If going to "Skills" section:
  "Demonstrated team leadership and project velocity management across 10-person engineering team"

If going to "Projects" section:
  "Project lead: Coordinated 10 engineers to accelerate feature delivery by 14 days"
```

**Implementation location:** `src/evidence_service.py` → `CVAssembler` class

---

### 5. Integration: New MCP Tool

**Tool name:** `generate_cv_from_jd_with_evidence`

**Input parameters:**
- `ground_truth_cv_id` (UUID) — Which finalized CV to extract evidence from
- `job_description` (string) — JD text
- `company_name` (string, optional) — For context
- `role_title` (string, optional) — For context

**Output:**
- `tailored_cv` (string) — Formatted CV
- `matched_evidence_count` (int) — How many evidence pieces were used
- `jd_analysis` (dict) — Extracted criteria, inferred skills, importance ranking (for transparency)

**Workflow in MCP tool:**
```
1. extract_evidence_from_cv(ground_truth_cv_id)
   └─ Store in Postgres (or reuse if already extracted)
2. analyze_jd(job_description)
   └─ JDCriteria
3. match_evidence_to_jd(evidence_list, jd_criteria)
   └─ RankedEvidence[]
4. assemble_cv(ranked_evidence, jd_context)
   └─ CV text
5. Return cv_text + metadata
```

---

## Bug Fixes (in existing CV generation)

### Timeline Ordering
**Current bug:** Evidence appears in random order or grouped incorrectly

**Fix:** Group by (company, role, time_period), then sort by relevance within group
```python
grouped = {}
for evidence in selected_evidence:
  key = (evidence.company_name, evidence.job_title, evidence.time_period_start.year)
  if key not in grouped:
    grouped[key] = []
  grouped[key].append(evidence)

for key in sorted(grouped.keys(), key=lambda x: x[2], reverse=True):  # Reverse chronological
  for evidence in sorted(grouped[key], key=lambda e: e.match_score, reverse=True):
    # Add to CV section
```

### Evidence Deduplication
**Current bug:** Same evidence appears verbatim in multiple sections

**Fix:** Rephrase per section + track used evidence to avoid direct repeats
```python
used_achievements = set()
for evidence in selected_evidence:
  if evidence.achievement in used_achievements:
    # Rephrase with different angle
    evidence.rephrased = rephrase_alternative(evidence, context)
  else:
    evidence.rephrased = evidence.achievement
  used_achievements.add(evidence.achievement)
```

---

## Testing Strategy (TDD)

### Unit Tests

**EvidenceExtractor:**
- ✅ Extract achievement/context/impact from CV text
- ✅ Infer skills from achievement description
- ✅ Handle missing data (no date, no impact) gracefully
- ✅ Support multiple sections (Experience, Skills, Projects, Education)

**JDAnalyzer:**
- ✅ Extract explicit skills from JD
- ✅ Infer related skills (e.g., Kafka → Big Data, Stream Processing)
- ✅ Rank importance correctly (0.95 for critical, 0.7 for nice-to-have)
- ✅ Handle vague JDs (missing explicit skills)

**EvidenceMatcher:**
- ✅ Match explicit skills (exact + semantic)
- ✅ Match inferred skills
- ✅ Rank by relevance (higher score = better match)
- ✅ Handle no matches (empty result set)

**CVAssembler:**
- ✅ Group by role/tenure (timeline order)
- ✅ Rephrase evidence per section (no verbatim repeats)
- ✅ Format as valid CV text
- ✅ Respect relevance ranking

### Integration Tests

- ✅ End-to-end: ground truth CV → extract → JD → match → assemble → output CV
- ✅ Compare output against manually-written CV for same JD (verify correctness)
- ✅ Test with multiple ground truth CVs (different career backgrounds)
- ✅ Test with diverse JDs (different industries, seniority levels)

### Regression Tests

- ✅ Existing `save_tailored_cv` tool still works (backwards compatible)
- ✅ Timeline ordering is correct (not mixed up like current bug)
- ✅ Evidence is rephrased (not raw duplicates)
- ✅ No evidence lost in assembly (selected pieces appear in output)

---

## Architecture Decisions

### Where to Extract Evidence

**Option 1: On-demand per JD** — Extract from ground truth CV each time a new JD is provided
- Pros: Always fresh, no storage
- Cons: Slower (extract every time), LLM API calls each time

**Option 2: Bootstrap once, reuse** — Extract once from ground truth CV, store in Postgres, reuse for all future JDs
- Pros: Faster (stored evidence), fewer LLM calls
- Cons: Must re-extract if ground truth CV is updated

**Decision: Option 2 (bootstrap once)**  
Rationale: Users will generate many CVs from one ground truth; reuse is better. If ground truth changes, re-extraction is a one-time operation.

### Evidence Versioning

Evidence extracted from ground truth CV v1.0. If user updates ground truth to v1.1:
- Old evidence (v1.0) stays in DB (historical)
- New extraction runs, creates evidence with `source_cv_id=v1.1`
- Future CVs use v1.1 evidence

This allows A/B testing ("which CV version gives better results?") later.

### LLM Model Choice

All LLM calls use a configurable model (via env var). Start with `gemini-flash-latest` (fast, cheap), can override to `opus` for critical extractions if needed.

**Calls that need high quality:**
- `EvidenceExtractor` — Extract should be accurate; use `opus` or `flash`
- `JDAnalyzer` — Inferred skills are important; use `opus` or `flash`
- `CVAssembler` — Final output quality matters; use `opus`

**Calls that can be cheaper:**
- `EvidenceMatcher` — Semantic similarity; `flash` is usually fine
- `JDAnalyzer` ranking — Importance scoring; `flash` is usually fine

**Decision: Start with `gemini-flash-latest`, add `opus` overrides if quality issues emerge**

---

## Success Criteria

Gate 9 is complete when:

- ✅ EvidenceExtractor correctly parses ground truth CV and extracts structured evidence
- ✅ JDAnalyzer correctly identifies explicit + inferred skills and ranks importance
- ✅ EvidenceMatcher correctly ranks evidence by relevance to JD
- ✅ CVAssembler generates readable CVs respecting timeline and avoiding raw evidence duplication
- ✅ New `generate_cv_from_jd_with_evidence` MCP tool works end-to-end
- ✅ All unit + integration tests passing (TDD discipline)
- ✅ Timeline ordering bug is fixed (evidence grouped by role/tenure, then ranked)
- ✅ Evidence deduplication bug is fixed (rephrased per section, not verbatim repeats)
- ✅ No regressions in existing CV tools
- ✅ Code coverage >90%

---

## Future Work (Gate 10+)

### Interactive Refinement Loop
- LLM asks: "Should we capture skill X to better match future Confluent-like roles?"
- User adds/enhances evidence
- Pool grows over time

### Evidence Reuse Analytics
- "Which evidence is used most often?"
- "Which evidence gets interviews?"
- Scoring and recommendations

### Multi-CV Bulk Generation
- "Generate CVs for these 5 JDs simultaneously"
- Shared evidence pool, customized per JD

---

## Files to Create/Modify

| File | Action | Purpose |
|------|--------|---------|
| `src/evidence_service.py` | Create | EvidenceExtractor, JDAnalyzer, EvidenceMatcher, CVAssembler classes |
| `prisma/schema.prisma` | Modify | Add StructuredEvidence table |
| `job_applications_mcp_server.py` | Modify | Add `generate_cv_from_jd_with_evidence` tool |
| `tests/unit/test_evidence_service.py` | Create | Unit tests for all 4 components |
| `tests/integration/test_gate9_end_to_end.py` | Create | End-to-end tests |

---

## Appendix: Example

### Input: Ground Truth CV (finalized from Gates 1-8)

```
# CV for Acme Corp

## Experience

### Senior Engineer at Acme Corp (2022-2024)
Led team of 10 engineers to ship a real-time data pipeline. 
Built from scratch using Kafka and Python. Delivered 2 weeks ahead of schedule.
Reduced latency by 40% in production.

### Data Engineer at TechCo (2019-2022)
Designed and implemented data warehouse. Mentored 3 junior engineers.
Adopted Airflow for job orchestration. Improved query performance by 60%.
```

### Extraction Output

```json
[
  {
    "achievement": "Led team of 10 engineers to ship real-time data pipeline",
    "context": "At Acme Corp, 2022-2024, Senior Engineer role",
    "impact": "Delivered 2 weeks ahead of schedule, reduced latency 40%",
    "skills_demonstrated": ["leadership", "Kafka", "Python", "real-time systems"],
    "time_period_start": "2022-01-01",
    "time_period_end": "2024-12-31",
    "company_name": "Acme Corp",
    "job_title": "Senior Engineer"
  },
  {
    "achievement": "Designed and implemented data warehouse",
    "context": "At TechCo, 2019-2022, Data Engineer role",
    "impact": "Improved query performance by 60%",
    "skills_demonstrated": ["data modeling", "SQL", "warehouse design", "big data"],
    "time_period_start": "2019-01-01",
    "time_period_end": "2022-12-31",
    "company_name": "TechCo",
    "job_title": "Data Engineer"
  },
  {
    "achievement": "Mentored 3 junior engineers",
    "context": "At TechCo, 2019-2022",
    "impact": "Built team capability and retention",
    "skills_demonstrated": ["mentoring", "leadership", "knowledge transfer"],
    "time_period_start": "2019-01-01",
    "time_period_end": "2022-12-31",
    "company_name": "TechCo",
    "job_title": "Data Engineer"
  },
  {
    "achievement": "Adopted Airflow for job orchestration",
    "context": "At TechCo, 2019-2022",
    "impact": "Improved reliability and monitoring of data jobs",
    "skills_demonstrated": ["Airflow", "orchestration", "data pipelines"],
    "time_period_start": "2019-01-01",
    "time_period_end": "2022-12-31",
    "company_name": "TechCo",
    "job_title": "Data Engineer"
  }
]
```

### Input: JD for IBM Confluent Role

```
Senior Confluent Engineer
We're looking for a senior engineer with 5+ years experience in stream processing.
You'll own our Kafka infrastructure and mentor a team of 5.
Skills: Kafka, Python, AWS, Big Data, familiarity with Agentic AI a plus.
```

### JDAnalyzer Output

```json
{
  "explicit_skills": ["Kafka", "Python", "AWS", "Big Data"],
  "inferred_skills": ["stream processing", "infrastructure", "data systems", "Agentic AI"],
  "critical_criteria": ["5+ years experience", "team leadership", "Kafka infrastructure ownership"],
  "importance_ranking": {
    "Kafka": 0.95,
    "stream processing": 0.9,
    "leadership": 0.8,
    "Python": 0.75,
    "Big Data": 0.7,
    "AWS": 0.65,
    "Agentic AI": 0.5
  },
  "reasoning": "Kafka is the primary focus (infrastructure owner). Stream processing is core to Kafka work. Leadership is explicit (mentor 5). Python is standard for this role. AWS likely used for deployment. Agentic AI is mentioned as a bonus but signals future direction."
}
```

### EvidenceMatcher Output

```json
[
  {
    "evidence": {"achievement": "Led team of 10 engineers...", ...},
    "match_score": 0.92,
    "matched_skills": ["leadership", "real-time systems"],
    "matched_criteria": ["team leadership"]
  },
  {
    "evidence": {"achievement": "Designed data warehouse...", ...},
    "match_score": 0.85,
    "matched_skills": ["big data", "data modeling"],
    "matched_criteria": []
  },
  {
    "evidence": {"achievement": "Adopted Airflow...", ...},
    "match_score": 0.72,
    "matched_skills": ["data pipelines", "orchestration"],
    "matched_criteria": []
  }
]
```

### CVAssembler Output (formatted CV)

```
Senior Confluent Engineer

Experience

Acme Corp | Senior Engineer (2022-2024)
Led a team of 10 engineers to architect and deploy a real-time data pipeline using Kafka and Python, delivering 2 weeks ahead of schedule and achieving 40% latency reduction in production.

TechCo | Data Engineer (2019-2022)
Spearheaded the design and implementation of a data warehouse serving 60% faster query performance.
Demonstrated strong team leadership by mentoring 3 junior engineers and establishing data engineering practices.
Orchestrated data pipelines using Airflow, improving job reliability and operational visibility.

Skills
- Kafka & Stream Processing
- Python & Data Engineering
- Team Leadership & Mentoring
- Big Data Systems
- AWS Infrastructure
```

---

## Appendix: Implementation Notes

**Environment variables:**
- `EVIDENCE_LLM_MODEL` — Model for evidence extraction (default: `gemini-flash-latest`)
- `JD_ANALYZER_LLM_MODEL` — Model for JD analysis (default: `gemini-flash-latest`)
- `CV_ASSEMBLER_LLM_MODEL` — Model for CV assembly (default: `gemini-flash-latest`)

**Database migrations:**
- New `StructuredEvidence` table via Prisma
- Indexes on `skills_demonstrated` (GIN for array), `time_period`, `source_cv_id`

**Testing infrastructure:**
- Fixture: ground truth CV (sample from test data)
- Fixture: sample JDs (various industries, seniorities)
- Assertion helpers: verify timeline order, check for raw evidence duplicates, validate CV format
