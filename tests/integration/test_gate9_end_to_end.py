"""
End-to-end integration tests for Gate 9.

Tests the full workflow:
1. Bootstrap: extract evidence from ground-truth CV
2. Generate: tailor CV for specific JD
3. Verify: output meets expectations
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


@pytest.fixture
def backend():
    """Mock Postgres backend for testing."""
    backend = PostgresEvidenceBackend(db_url="postgresql://postgres:password@localhost/job_applications_test")
    yield backend
    backend.close()


def test_full_gate9_workflow_comprehensive(backend):
    """
    Comprehensive end-to-end test of the full Gate 9 workflow:
    1. Bootstrap: extract evidence from ground-truth CV
    2. Generate: tailor CV for specific JD
    3. Verify: output meets expectations
    """
    cv_id = "cv_comprehensive_e2e"

    # Step 1: Bootstrap - extract evidence from realistic multi-section CV
    cv_sections = {
        "Experience": [
            {
                "company": "StartupA",
                "title": "Backend Engineer",
                "text": """
                Architected Python microservices platform.
                Designed async task queue with Celery and Redis.
                Optimized PostgreSQL queries, 10x throughput improvement.
                Mentored 2 junior engineers on system design.
                Tech: Python 3.10, FastAPI, PostgreSQL, Redis, Docker, Kubernetes.
                """,
                "start_date": datetime(2020, 3, 1),
                "end_date": datetime(2022, 8, 31)
            },
            {
                "company": "TechCorp",
                "title": "Senior Backend Engineer",
                "text": """
                Led 5-person backend team building payment processing system.
                Designed gRPC APIs for inter-service communication.
                Implemented distributed tracing with Jaeger.
                Reduced payment latency from 500ms to 50ms.
                Mentored team on best practices, code reviews.
                Tech: Go, gRPC, Kubernetes, Prometheus, Jaeger.
                """,
                "start_date": datetime(2022, 9, 1),
                "end_date": datetime(2023, 12, 31)
            }
        ],
        "Projects": [
            {
                "company": "Open Source",
                "title": "FastCache",
                "text": "Open-source distributed caching library. 500 GitHub stars. Used by 20+ companies.",
                "start_date": datetime(2021, 6, 1),
                "end_date": None
            }
        ],
        "Skills": [
            {
                "company": None,
                "title": None,
                "text": "Python, Go, Kubernetes, Docker, PostgreSQL, Redis, gRPC, System Design, Leadership",
                "start_date": None,
                "end_date": None
            }
        ]
    }

    # Extract and persist
    extraction_service = EvidenceExtractionService(
        extractor=EvidenceExtractor(),
        backend=backend
    )
    extracted_count = extraction_service.extract_and_persist(cv_id=cv_id, cv_sections=cv_sections)
    assert extracted_count >= 5, f"Expected at least 5 evidence items, got {extracted_count}"

    # Step 2: Generate tailored CV
    jd_text = """
    Senior Software Engineer - Infrastructure Team

    About the role:
    We're building the next generation of infrastructure tooling for cloud-native companies.

    Requirements:
    - 5+ years backend development (Go or Python)
    - Strong experience with Kubernetes and containerization
    - System design and architectural skills
    - Distributed systems knowledge
    - Experience leading small teams

    Nice to have:
    - gRPC experience
    - Open source contributions
    - Experience with microservices patterns
    - Jaeger or similar distributed tracing tools
    """

    cv_gen_service = CVGenerationService(
        analyzer=JDAnalyzer(),
        matcher=EvidenceMatcher(),
        assembler=CVAssembler(),
        backend=backend
    )

    result = cv_gen_service.generate_cv(
        ground_truth_cv_id=cv_id,
        jd_text=jd_text,
        company_name="CloudInc",
        role_title="Senior Software Engineer"
    )

    # Step 3: Verify output
    assert result["tailored_cv"] is not None
    assert len(result["tailored_cv"]) > 200, "CV should be substantive"
    assert result["matched_evidence_count"] >= 3, f"Should match at least 3 items, got {result['matched_evidence_count']}"

    # Verify sections are present
    cv_text = result["tailored_cv"]
    assert "Experience" in cv_text or "TechCorp" in cv_text, "Should include experience"
    # Look for key terms from the JD or CV
    assert any(keyword in cv_text for keyword in ["gRPC", "Kubernetes", "Python", "Go", "Backend"]), \
        "Should mention key skills or frameworks"

    # Verify JD analysis
    jd_analysis = result["jd_analysis"]
    assert len(jd_analysis.explicit_skills) > 0
    assert len(jd_analysis.importance_ranking) > 0

    # Verify evidence ranking
    evidence_items = result["evidence_items"]
    assert len(evidence_items) > 0
    # Should be sorted by match_score descending
    for i in range(len(evidence_items) - 1):
        assert evidence_items[i].match_score >= evidence_items[i + 1].match_score

    print("✓ Full Gate 9 workflow passed!")
