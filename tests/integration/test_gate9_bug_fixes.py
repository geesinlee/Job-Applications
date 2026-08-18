"""
Regression tests for Gate 9 bug fixes.

Tests verify:
1. Timeline ordering: evidence sorted reverse-chronologically by role/tenure
2. Deduplication: verbatim repeated evidence is rephrased or deduplicated
3. Evidence extraction completeness: all sections are extracted (no loss)
"""

import pytest
from datetime import datetime
from src.evidence_service import (
    EvidenceExtractor,
    EvidenceExtractionService,
    CVGenerationService,
    JDAnalyzer,
    EvidenceMatcher,
    CVAssembler
)
from src.evidence_backend import PostgresEvidenceBackend
from src.evidence_models import StructuredEvidence, RankedEvidence


@pytest.fixture
def backend():
    """Mock Postgres backend for testing."""
    backend = PostgresEvidenceBackend(db_url="postgresql://postgres:password@localhost/job_applications_test")
    yield backend
    backend.close()


def test_timeline_ordering_by_role_and_tenure(backend):
    """
    Bug fix: evidence should be ordered by role/company, then reverse-chronologically within each.

    Saves evidence out of order and verifies it loads in reverse-chronological order.
    """
    cv_id = "cv_timeline_test"

    # Save evidence out of chronological order
    evidence_items = [
        StructuredEvidence(
            achievement="Refactored ORM layer",
            context="Mid-level work",
            impact="30% query speedup",
            skills_demonstrated=["Python", "SQLAlchemy"],
            job_title="Software Engineer",
            company_name="Corp A",
            time_period_start=datetime(2019, 6, 1),
            time_period_end=datetime(2020, 12, 31),
            source_section="Experience",
            source_cv_id=cv_id
        ),
        StructuredEvidence(
            achievement="Led team to 10M requests/day",
            context="Senior role",
            impact="Architecture redesign",
            skills_demonstrated=["System Design", "Python"],
            job_title="Senior Engineer",
            company_name="Corp B",
            time_period_start=datetime(2021, 1, 1),
            time_period_end=datetime(2023, 12, 31),
            source_section="Experience",
            source_cv_id=cv_id
        ),
        StructuredEvidence(
            achievement="Built caching layer",
            context="Early-career work",
            impact="40% latency reduction",
            skills_demonstrated=["Redis", "Python"],
            job_title="Software Engineer",
            company_name="Corp A",
            time_period_start=datetime(2018, 1, 1),
            time_period_end=datetime(2019, 5, 31),
            source_section="Experience",
            source_cv_id=cv_id
        ),
    ]

    for evidence in evidence_items:
        backend.save_evidence(evidence)

    # Load and verify ordering
    loaded = backend.get_evidence_by_cv_id(cv_id)

    # Should be sorted reverse-chronologically
    for i in range(len(loaded) - 1):
        if loaded[i].time_period_end and loaded[i + 1].time_period_end:
            assert loaded[i].time_period_end >= loaded[i + 1].time_period_end, \
                f"Evidence not reverse-chronologically ordered: {loaded[i]} vs {loaded[i + 1]}"


def test_deduplication_avoids_verbatim_repeats(backend):
    """
    Bug fix: when same achievement used multiple times, should be rephrased or flagged as duplicate.

    Tests that CVAssembler avoids verbatim repeats of the same achievement.
    """
    cv_id = "cv_dedup_test"

    # Create evidence with same achievement from different roles
    achievement = "Implemented distributed caching"
    evidence_items = [
        StructuredEvidence(
            achievement=achievement,
            context="At Corp A",
            impact="40% latency improvement",
            skills_demonstrated=["Redis"],
            job_title="Engineer",
            company_name="Corp A",
            time_period_start=datetime(2020, 1, 1),
            time_period_end=datetime(2021, 12, 31),
            source_section="Experience",
            source_cv_id=cv_id
        ),
        StructuredEvidence(
            achievement=achievement,  # Same!
            context="At Corp B",
            impact="50% latency improvement",
            skills_demonstrated=["Memcached"],
            job_title="Engineer",
            company_name="Corp B",
            time_period_start=datetime(2022, 1, 1),
            time_period_end=datetime(2023, 12, 31),
            source_section="Experience",
            source_cv_id=cv_id
        ),
    ]

    for evidence in evidence_items:
        backend.save_evidence(evidence)

    loaded = backend.get_evidence_by_cv_id(cv_id)
    assert len(loaded) == 2

    # Assemble CV - deduplication logic in CVAssembler should avoid verbatim repeats
    ranked = [RankedEvidence(e, match_score=0.9, matched_skills=[], matched_criteria=[]) for e in loaded]
    assembler = CVAssembler()
    assembled = assembler.assemble(ranked, section_type="Experience", max_per_role=2)

    # Count how many times the achievement appears verbatim
    count = assembled.count(achievement)
    # Should appear at most once verbatim (second should be rephrased or deduplicated)
    assert count <= 1, f"Achievement appeared {count} times verbatim: {assembled}"


def test_evidence_extraction_completeness(backend):
    """
    Bug fix: all evidence from CV should be extracted (no loss).

    Verifies that extraction service persists all extracted evidence without loss.
    """
    cv_id = "cv_completeness_test"

    cv_sections = {
        "Experience": [
            {
                "company": "Corp A",
                "title": "Engineer",
                "text": "Built API. Scaled to 1M QPS. Wrote 10k LOC.",
                "start_date": datetime(2020, 1, 1),
                "end_date": datetime(2022, 12, 31)
            },
            {
                "company": "Corp B",
                "title": "Senior Engineer",
                "text": "Led team. Designed 3 systems. Mentored 5 people.",
                "start_date": datetime(2023, 1, 1),
                "end_date": None
            }
        ],
        "Projects": [
            {
                "company": "Open Source",
                "title": "Project X",
                "text": "Built distributed system. 100 stars on GitHub.",
                "start_date": None,
                "end_date": None
            }
        ]
    }

    extraction_service = EvidenceExtractionService(
        extractor=EvidenceExtractor(),
        backend=backend
    )

    extracted_count = extraction_service.extract_and_persist(cv_id=cv_id, cv_sections=cv_sections)

    # Verify all evidence persisted
    loaded = backend.get_evidence_by_cv_id(cv_id)
    assert len(loaded) == extracted_count, f"Extracted {extracted_count} but loaded {len(loaded)}"
    assert extracted_count >= 3, f"Should extract at least 3 items, got {extracted_count}"

    # Verify data integrity
    for evidence in loaded:
        assert evidence.source_cv_id == cv_id
        assert evidence.achievement and len(evidence.achievement) > 0
        assert evidence.job_title and len(evidence.job_title) > 0
        assert evidence.company_name and len(evidence.company_name) > 0
