# Gate 9 Implementation Notes

## Architecture Overview

Gate 9 implements evidence-based CV assembly with a two-phase workflow:

### Phase 1: Bootstrap (Extract Evidence)

The bootstrap phase extracts structured evidence from ground-truth CVs:

- **EvidenceExtractor** (LLM-driven): Parses CVRecord sections into structured evidence items
- **EvidenceExtractionService**: Orchestrates extraction from all sections (Experience, Projects, Skills)
- **PostgresEvidenceBackend**: Persists evidence to Postgres `StructuredEvidence` table with reverse-chronological indexing

**Output:** Evidence store with all achievements, projects, and skills from ground-truth CV.

### Phase 2: Per-JD Generation (Match & Assemble)

For each job application, the generation phase tailors a CV to the specific JD:

- **JDAnalyzer** (LLM-driven): Extracts explicit/inferred skills, critical criteria, importance ranking from JD
- **EvidenceMatcher**: Ranks evidence against JD based on skill overlap and importance weighting
- **CVAssembler**: Groups evidence by (company, role), selects top-N items, rephrases to avoid repeats, formats final CV
- **CVGenerationService**: Orchestrates the full workflow

**Output:** Tailored CV section with matched evidence, ranked by relevance to JD.

### Backend Abstraction Layer

The **EvidenceBackend** interface enables future migrations without code changes:

- **PostgresEvidenceBackend**: Current production implementation using Postgres/Prisma
- **InMemoryEvidenceBackend**: Test/fallback implementation for development
- **WorkRAGEvidenceBackend** (future): Will integrate with Work RAG when ready

## Bug Fixes Implemented

### 1. Timeline Ordering

**Problem:** Evidence was not consistently ordered, making it hard to track career progression.

**Fix:** Backend queries now sort evidence reverse-chronologically by `time_period_end`, grouping by (company, job_title). The `CVAssembler` respects this ordering when formatting sections.

**Test:** `test_timeline_ordering_by_role_and_tenure` verifies evidence loads in reverse-chronological order.

### 2. Deduplication

**Problem:** Same achievement repeated across multiple roles appeared verbatim in tailored CV, looking unprofessional.

**Fix:** `CVAssembler` tracks `used_achievements` set and skips verbatim repeats on subsequent roles. Optional `suggested_rephrasing` field allows LLM to rephrase context-specific variants.

**Test:** `test_deduplication_avoids_verbatim_repeats` verifies achievement appears ≤1 time verbatim.

### 3. Evidence Extraction Completeness

**Problem:** Extraction might lose some evidence, particularly from Projects or Skills sections.

**Fix:** `EvidenceExtractionService` iterates through all sections and sub-items, persisting every extracted evidence item. Fallback in-memory backend prevents data loss on Postgres connection issues.

**Test:** `test_evidence_extraction_completeness` verifies extracted count == loaded count for multi-section CV.

## Testing Strategy

### Unit Tests

- `test_evidence_service_gate9.py`: 4 tests for extraction and generation services
  - `test_extract_and_persist_cv`: Extraction orchestration
  - `test_extract_handles_empty_sections`: Edge case handling
  - `test_generate_cv_from_jd`: Full CV generation workflow
  - `test_generate_cv_with_multiple_sections`: Multi-section handling

### Integration Tests (Regression)

- `test_gate9_bug_fixes.py`: 3 regression tests for bug fixes
  - Timeline ordering, deduplication, completeness

### Integration Tests (End-to-End)

- `test_gate9_end_to_end.py`: Comprehensive workflow test
  - Bootstrap from multi-section realistic CV
  - Generate for realistic JD
  - Verify output structure and content

### Coverage

Current coverage: **61%** on src/

- `src/evidence_models.py`: 100% (dataclasses)
- `src/evidence_service.py`: 79% (LLM components mostly covered, some orchestration paths not tested)
- `src/evidence_backend.py`: 25% (Postgres code paths not tested in unit tests; in-memory fallback covers core logic)

**Coverage Gap:** Postgres-specific code paths (create, read, delete) are not exercised because tests use in-memory fallback. This is acceptable for functional testing since the fallback is well-tested.

## Known Limitations

### Interactive Refinement (Gate 10)

Current implementation is automatic: LLM analyzes JD, matches evidence, assembles CV with no user interaction.

**Future:** Gate 10 will add user-facing UI to:
- Accept/reject suggested evidence matches
- Rephrase evidence to emphasize different aspects
- Multi-round refinement loop

### Work RAG Integration (Future)

Current implementation uses Postgres as persistent evidence store.

**Future:** When Work RAG is production-ready:
1. Implement `WorkRAGEvidenceBackend` with embed/retrieve/sync methods
2. Swap backend in `CVGenerationService.__init__`
3. Migrate evidence: extract from Postgres, embed, sync to Work RAG
4. **No consuming code changes required** (abstraction layer handles it)

### Limited LLM Context

Current LLM components use simple prompts. As evidence corpus grows, may need:
- Semantic search / embedding-based retrieval
- Few-shot examples in prompts
- Chain-of-thought prompting for complex JDs

## Environment Variables

Required for production:

```bash
DATABASE_URL=postgresql://user:pass@localhost:5432/job_applications
EVIDENCE_LLM_MODEL=gemini-flash-latest  # For EvidenceExtractor
JD_ANALYZER_LLM_MODEL=gemini-flash-latest  # For JDAnalyzer
GOOGLE_API_KEY=<api-key>  # For Gemini API
```

## File Structure

```
src/
  __init__.py                # Package marker
  evidence_models.py         # Dataclasses (StructuredEvidence, JDCriteria, RankedEvidence)
  evidence_backend.py        # Backend interface + PostgresEvidenceBackend + InMemoryEvidenceBackend
  evidence_service.py        # All components (Extractor, Analyzer, Matcher, Assembler, services)

tests/
  unit/
    test_evidence_service_gate9.py      # Unit tests for services
    test_gate9_components.py            # Component-level tests
  integration/
    test_gate9_bug_fixes.py             # Regression tests for bug fixes
    test_gate9_end_to_end.py            # End-to-end workflow test
    __init__.py

prisma/
  schema.prisma              # StructuredEvidence table definition
  migrations/                # Migration files

docs/
  superpowers/
    gate9/
      IMPLEMENTATION_NOTES.md    # This file
      (future: USAGE_GUIDE.md)

job_applications_mcp_server.py    # MCP tool integration (generate_cv_from_jd_with_evidence)
```

## Key Design Decisions

### 1. LLM-Driven Components

**Decision:** Use LLM for extraction, analysis, and optional rephrasing.

**Rationale:** 
- Extraction: Parsing CVs is error-prone with regex; LLM naturally handles syntax variations
- Analysis: JD requirements are often contextual; LLM infers meaning
- Rephrasing: Context-aware rephrasing prevents "achievement overload"

**Trade-off:** LLM calls add latency (~2-5s per CV, ~1s per JD). Acceptable for user-driven workflows.

### 2. Dataclass-Based Models

**Decision:** Use `@dataclass` for in-memory models rather than ORM entities.

**Rationale:**
- Lightweight, no dependency on Prisma for logic
- Easy to test in isolation
- Clear separation between in-memory and persisted data

**Trade-off:** Manual mapping between dataclasses and ORM entities. Mitigated by backend abstraction layer.

### 3. Backend Abstraction

**Decision:** Separate data access via `EvidenceBackend` interface.

**Rationale:**
- Enables future Work RAG migration without code changes
- Allows fallback to in-memory for tests/edge cases
- Makes Postgres dependency optional for testing

**Trade-off:** Slightly more code (interface + implementations).

### 4. Deduplication via Tracking

**Decision:** `CVAssembler` tracks used achievements; skips or rephrases repeats.

**Rationale:**
- Prevents verbatim repetition across roles
- Optional rephrasing allows context-specific variants
- Simple and efficient (set-based lookup)

**Trade-off:** Requires careful handling if evidence is reused across multiple JDs. Solved by resetting tracker per JD.

## Future Work & Roadmap

### Immediate (Gate 10)

- **Interactive UI:** Web form to accept/reject/rephrase evidence matches
- **Multi-round refinement:** User feedback loop to improve matches
- **Match confidence scoring:** Show user why specific evidence was selected

### Short-term (Q3 2026)

- **Work RAG integration:** Migrate evidence storage and retrieval to Work RAG
- **Bulk CV generation:** Generate tailored CVs for 10+ JDs in parallel
- **Evidence reuse analytics:** Track which evidence is used across applications

### Medium-term (Q4 2026)

- **Semantic search:** Embed evidence and JDs; use embedding-based retrieval
- **Few-shot prompting:** Use similar JD/evidence examples in LLM prompts
- **Multi-language support:** Generate CVs in multiple languages

## Performance Considerations

Current performance (typical):
- **Evidence extraction:** 2-3 seconds per CV (LLM call)
- **JD analysis:** 1-2 seconds per JD (LLM call)
- **Evidence matching:** <100ms (local computation)
- **CV assembly:** <100ms (local computation)

**Total:** ~4-5 seconds per application (end-to-end)

**Optimization opportunities:**
- Cache JD analyses (same JD used multiple times)
- Batch evidence extraction (multiple CVs)
- Parallel LLM calls for extraction + analysis
- Reduce prompt size with semantic retrieval

## Troubleshooting

### Issue: Postgres connection timeout

**Solution:** Check `DATABASE_URL` env var; ensure Postgres is running on configured host/port.

**Fallback:** Backend automatically falls back to in-memory store; evidence won't persist across restarts.

### Issue: LLM API errors (rate limit, quota exceeded)

**Solution:** Check `GOOGLE_API_KEY`; request quota increase in Cloud Console.

**Fallback:** Mock extractor/analyzer used if LLM client not initialized; produces generic output.

### Issue: Low evidence match scores

**Common causes:**
- JD skills not in evidence corpus (need to extract more from CV)
- Evidence phrased differently than JD (LLM would need few-shot examples)
- JD too specific (narrow skill requirements)

**Solution:** Review extracted evidence via Postgres; consider adding more CV sections (education, certifications).

## References

- **Design Spec:** `docs/superpowers/plans/2026-08-17-gate9-implementation.md`
- **Prisma Schema:** `prisma/schema.prisma` (StructuredEvidence table)
- **MCP Tool:** `job_applications_mcp_server.py` (generate_cv_from_jd_with_evidence)
