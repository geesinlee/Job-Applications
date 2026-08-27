"""End-to-end integration tests for Gate 9: evidence extraction and CV generation."""

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

        def get_evidence_by_cv_id(self, cv_id):
            return [e for e in self.store.values() if e.source_cv_id == cv_id]

        def close(self):
            pass

    return MockBackend()


def test_mcp_tool_generate_cv_from_jd(mock_backend):
    """Integration test: bootstrap CV, then generate tailored CV via orchestration."""

    # Setup: extract and persist evidence from a test CV
    cv_id = "cv_mcp_test_001"

    cv_sections = {
        "Experience": [
            {
                "company": "TechCorp",
                "title": "Senior Backend Engineer",
                "text": """
                Led microservices migration from monolith to containerized architecture.
                Reduced API latency by 40% through caching and optimization.
                Mentored team of 3 junior engineers.
                Tech: Python, Kubernetes, Docker, PostgreSQL, Redis.
                """,
                "start_date": datetime(2020, 1, 1),
                "end_date": datetime(2023, 12, 31)
            }
        ],
        "Projects": [
            {
                "company": "Open Source",
                "title": "Python Data Processing Library",
                "text": "Built distributed data processing library using Ray. 500+ GitHub stars.",
                "start_date": datetime(2022, 6, 1),
                "end_date": None
            }
        ]
    }

    extraction_service = EvidenceExtractionService(
        extractor=EvidenceExtractor(),
        backend=mock_backend
    )

    extraction_service.extract_and_persist(cv_id=cv_id, cv_sections=cv_sections)

    # Now, generate a tailored CV for a job description
    cv_gen_service = CVGenerationService(
        analyzer=JDAnalyzer(),
        matcher=EvidenceMatcher(),
        assembler=CVAssembler(),
        backend=mock_backend
    )

    jd_text = """
    Senior Software Engineer - Backend

    We're looking for someone with:
    - 5+ years backend development (Python preferred)
    - Kubernetes and containerization experience
    - System design and architectural skills
    - Experience scaling high-traffic systems

    Nice to have:
    - Open source contributions
    - Mentoring experience
    """

    result = cv_gen_service.generate_cv(
        ground_truth_cv_id=cv_id,
        jd_text=jd_text,
        company_name="TargetCorp",
        role_title="Senior Software Engineer"
    )

    assert result["tailored_cv"] is not None
    assert len(result["tailored_cv"]) > 0
    assert result["matched_evidence_count"] > 0
    assert "Experience" in result["tailored_cv"] or "Projects" in result["tailored_cv"]
    assert result["jd_analysis"] is not None
