"""Tests for Gate 9 services: EvidenceExtractionService, CVGenerationService."""

import pytest
from datetime import datetime
from src.evidence_service import (
    EvidenceExtractor,
    JDAnalyzer,
    EvidenceMatcher,
    CVAssembler,
    EvidenceExtractionService,
    CVGenerationService,
)
from src.evidence_models import StructuredEvidence


@pytest.fixture
def mock_backend():
    """Simple mock backend for testing."""
    class MockBackend:
        def __init__(self):
            self.store = {}

        def save_evidence(self, evidence):
            eid = f"ev_{len(self.store)}"
            evidence.id = eid
            self.store[eid] = evidence
            return eid

        def get_evidence_by_id(self, evidence_id):
            return self.store.get(evidence_id)

        def get_evidence_by_cv_id(self, cv_id):
            return [e for e in self.store.values() if e.source_cv_id == cv_id]

        def query_by_skills(self, skills):
            return [
                e for e in self.store.values()
                if any(s in e.skills_demonstrated for s in skills)
            ]

        def query_by_company(self, company_name):
            return [e for e in self.store.values() if e.company_name == company_name]

        def query_by_timeframe(self, start, end):
            return [
                e for e in self.store.values()
                if (not e.time_period_end or e.time_period_end <= end)
                and (not e.time_period_start or e.time_period_start >= start)
            ]

        def close(self):
            pass

    return MockBackend()


# Task 8: EVIDENCE EXTRACTION SERVICE TESTS

def test_extract_and_persist_cv(mock_backend):
    """Test EvidenceExtractionService: extract and persist CV sections."""
    extractor = EvidenceExtractor()
    service = EvidenceExtractionService(
        extractor=extractor,
        backend=mock_backend
    )

    cv_sections = {
        "Experience": [
            {
                "company": "TechCorp",
                "title": "Senior Engineer",
                "text": "Led microservices migration. Reduced latency by 40%. Team of 3.",
                "start_date": datetime(2021, 1, 1),
                "end_date": datetime(2023, 12, 31)
            }
        ],
        "Projects": [
            {
                "company": "Self",
                "title": None,
                "text": "Built ML pipeline using PyTorch. Trained on 1M images.",
                "start_date": datetime(2023, 1, 1),
                "end_date": None
            }
        ]
    }

    cv_id = "cv_bootstrap_test_001"
    count = service.extract_and_persist(
        cv_id=cv_id,
        cv_sections=cv_sections
    )

    assert count > 0
    evidence_list = mock_backend.get_evidence_by_cv_id(cv_id)
    assert len(evidence_list) == count
    assert all(e.source_cv_id == cv_id for e in evidence_list)


def test_extract_handles_empty_sections(mock_backend):
    """Test that extraction handles empty sections gracefully."""
    extractor = EvidenceExtractor()
    service = EvidenceExtractionService(
        extractor=extractor,
        backend=mock_backend
    )

    cv_sections = {
        "Experience": [],
        "Projects": [
            {
                "company": "Corp",
                "title": "Role",
                "text": "Did something",
                "start_date": None,
                "end_date": None
            }
        ]
    }

    count = service.extract_and_persist(
        cv_id="cv_test",
        cv_sections=cv_sections
    )

    assert count >= 0


# Task 9: CV GENERATION SERVICE TESTS

def test_generate_cv_from_jd(mock_backend):
    """Test CVGenerationService: generate tailored CV from JD."""
    cv_id = "cv_gen_test_001"
    evidence = StructuredEvidence(
        achievement="Architected microservices platform",
        context="E-commerce backend",
        impact="Reduced deployment time from 2h to 5min",
        skills_demonstrated=["Kubernetes", "Docker", "Python", "Microservices"],
        job_title="Senior Backend Engineer",
        company_name="ScaleCorp",
        time_period_start=datetime(2020, 1, 1),
        time_period_end=datetime(2022, 12, 31),
        source_section="Experience",
        source_cv_id=cv_id
    )
    mock_backend.save_evidence(evidence)

    analyzer = JDAnalyzer()
    matcher = EvidenceMatcher()
    assembler = CVAssembler()
    service = CVGenerationService(
        analyzer=analyzer,
        matcher=matcher,
        assembler=assembler,
        backend=mock_backend
    )

    jd_text = """
    Senior Backend Engineer

    Requirements:
    - 5+ years building scalable systems
    - Kubernetes and containerization expertise
    - Python or Go
    - Microservices architecture experience
    """

    result = service.generate_cv(
        ground_truth_cv_id=cv_id,
        jd_text=jd_text,
        company_name="HireCorp",
        role_title="Senior Backend Engineer"
    )

    assert result["tailored_cv"] is not None
    assert len(result["tailored_cv"]) > 0
    assert result["matched_evidence_count"] > 0
    assert result["jd_analysis"] is not None
    assert result["jd_analysis"].company_name == "HireCorp"
    assert result["jd_analysis"].role_title == "Senior Backend Engineer"


def test_generate_cv_with_multiple_sections(mock_backend):
    """Test CV generation with multiple section types."""
    cv_id = "cv_multi_test"

    experience = StructuredEvidence(
        achievement="Led Python project",
        context="Scaling backend",
        impact="3x throughput",
        skills_demonstrated=["Python", "System Design"],
        job_title="Engineer",
        company_name="Corp A",
        time_period_start=datetime(2021, 1, 1),
        time_period_end=datetime(2023, 12, 31),
        source_section="Experience",
        source_cv_id=cv_id
    )

    project = StructuredEvidence(
        achievement="Open source project",
        context="Distributed systems",
        impact="100+ GitHub stars",
        skills_demonstrated=["Go", "System Design"],
        job_title=None,
        company_name="Self",
        time_period_start=None,
        time_period_end=None,
        source_section="Projects",
        source_cv_id=cv_id
    )

    mock_backend.save_evidence(experience)
    mock_backend.save_evidence(project)

    service = CVGenerationService(
        analyzer=JDAnalyzer(),
        matcher=EvidenceMatcher(),
        assembler=CVAssembler(),
        backend=mock_backend
    )

    result = service.generate_cv(
        ground_truth_cv_id=cv_id,
        jd_text="Need Python and System Design skills",
        company_name="TestCorp",
        role_title="Backend Engineer"
    )

    assert "## Experience" in result["tailored_cv"] or "## Projects" in result["tailored_cv"]
    assert result["matched_evidence_count"] > 0
