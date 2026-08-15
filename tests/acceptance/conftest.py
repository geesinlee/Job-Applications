# tests/acceptance/conftest.py
"""
Shared fixtures for acceptance tests.
These fixtures provide test data factories and pre-populated repos.
"""

import pytest
import uuid
from datetime import datetime
from pathlib import Path


# ============================================================================
# EVIDENCE FACTORY
# ============================================================================

@pytest.fixture
def evidence_factory():
    """Factory for creating CareerEvidence test objects."""
    def _create(
        statement="Test achievement",
        evidence_type="achievement",
        source_type="baseline_cv",
        source_reference="Test CV line 1",
        confidence="LEVEL_A",
        verification_status="user_confirmed",
        user_confirmed=True,
        metrics=None,
        competencies=None,
        technologies=None,
        industries=None,
        geographies=None,
        application_origin=None,
        supersedes=None,
        superseded_by=None,
        related_to=None,
        **kwargs
    ):
        return {
            "evidence_id": str(uuid.uuid4()),
            "statement": statement,
            "evidence_type": evidence_type,
            "source_type": source_type,
            "source_reference": source_reference,
            "source_document_id": None,
            "source_date": "2026-05-15T00:00:00Z",
            "first_captured_at": datetime.utcnow().isoformat() + "Z",
            "last_confirmed_at": datetime.utcnow().isoformat() + "Z",
            "application_origin": application_origin,
            "verification_status": verification_status,
            "confidence": confidence,
            "user_confirmed": user_confirmed,
            "supersedes": supersedes or [],
            "superseded_by": superseded_by or [],
            "related_to": related_to or [],
            "competencies": competencies or [],
            "technologies": technologies or [],
            "industries": industries or [],
            "geographies": geographies or [],
            "metrics": metrics or {},
            "notes": "",
            "created_by": "test",
            "created_at": datetime.utcnow().isoformat() + "Z",
            "last_modified_by": "test",
            "last_modified_at": datetime.utcnow().isoformat() + "Z",
            **kwargs
        }
    return _create


# ============================================================================
# REQUIREMENT FACTORY
# ============================================================================

@pytest.fixture
def requirement_factory():
    """Factory for creating JobRequirement test objects."""
    def _create(
        requirement_id=None,
        statement="Test requirement",
        category="mandatory",
        req_type="domain_experience",
        application_id=None,
        matched_evidence=None,
        gap_status="covered",
        gap_interview_question=None,
        user_response=None,
        evidence_created_from_response=None,
        coverage_score=None,
        **kwargs
    ):
        if coverage_score is None:
            coverage_score = 1.0 if gap_status == "covered" else 0.0

        return {
            "requirement_id": requirement_id or str(uuid.uuid4()),
            "application_id": application_id or str(uuid.uuid4()),
            "category": category,
            "type": req_type,
            "statement": statement,
            "extracted_from": {
                "jd_path": "Test/JD.md",
                "section": "Requirements",
                "line_number": 1,
                "text_excerpt": statement
            },
            "matched_evidence": matched_evidence or [],
            "gap_status": gap_status,
            "gap_interview_question": gap_interview_question,
            "user_response": user_response,
            "evidence_created_from_response": evidence_created_from_response,
            "coverage_score": coverage_score,
            "required_for_cv": True,
            "created_at": datetime.utcnow().isoformat() + "Z",
            **kwargs
        }
    return _create


# ============================================================================
# APPLICATION FACTORY
# ============================================================================

@pytest.fixture
def application_factory(tmp_path):
    """Factory for creating Application test objects."""
    def _create(
        application_id=None,
        company="TestCorp",
        role_title="Test Role",
        stage="new",
        jd_path=None,
        **kwargs
    ):
        if jd_path is None:
            jd_path = tmp_path / company / "JD.md"
            jd_path.parent.mkdir(parents=True, exist_ok=True)
            jd_path.write_text("Test JD content")

        return {
            "id": application_id or str(uuid.uuid4()),
            "company": company,
            "role_title": role_title,
            "jd_path": str(jd_path),
            "stage": stage,
            "date_created": datetime.utcnow().isoformat() + "Z",
            "history": [{"stage": stage, "at": datetime.utcnow().isoformat() + "Z"}],
            "followups": [],
            "jd_source_url": None,
            "requirements_extracted_at": None,
            "requirements": [],
            "requirement_analysis_quality": None,
            "gap_interview_phase": "not_started",
            "gap_interview_questions": [],
            "gap_interview_answers": [],
            "evidence_selected": [],
            "evidence_omitted": [],
            "cv_records": [],
            "cv_draft_count": 0,
            "cv_approved_at": None,
            "cv_final_id": None,
            "discovered_at": datetime.utcnow().isoformat() + "Z",
            "applied_at": None,
            "significant_decisions": [],
            **kwargs
        }
    return _create


# ============================================================================
# CV RECORD FACTORY
# ============================================================================

@pytest.fixture
def cv_record_factory():
    """Factory for creating CVRecord test objects."""
    def _create(
        cv_record_id=None,
        application_id=None,
        version="draft_1",
        status="draft",
        content="Test CV content",
        evidence_used=None,
        major_changes=None,
        changed_sections=None,
        significant_omissions=None,
        approved_at=None,
        finalized_at=None,
        predecessor_id=None,
        successor_id=None,
        **kwargs
    ):
        version_number = int(version.split("_")[-1]) if "draft_" in version else (
            0 if version == "baseline" else 99
        )

        return {
            "cv_record_id": cv_record_id or str(uuid.uuid4()),
            "application_id": application_id or str(uuid.uuid4()),
            "version": version,
            "version_number": version_number,
            "status": status,
            "content": content,
            "evidence_used": evidence_used or [],
            "major_changes": major_changes or [],
            "changed_sections": changed_sections or [],
            "significant_omissions": significant_omissions or [],
            "created_at": datetime.utcnow().isoformat() + "Z",
            "approved_at": approved_at,
            "finalized_at": finalized_at,
            "predecessor_id": predecessor_id,
            "successor_id": successor_id,
            "created_by": "app:claude",
            "last_modified_by": "app:claude",
            "last_modified_at": datetime.utcnow().isoformat() + "Z",
            **kwargs
        }
    return _create


# ============================================================================
# BASELINE DATA FIXTURES
# ============================================================================

@pytest.fixture
def baseline_dxc_cv(tmp_path):
    """DXC baseline CV for seeding."""
    cv_path = tmp_path / "Base CV" / "CV LEE Gee Sin 2026.md"
    cv_path.parent.mkdir(parents=True, exist_ok=True)
    cv_path.write_text("""# LEE Gee Sin
## Professional Summary
Enterprise account executive with 8+ years in SaaS sales. Grew revenue 40% annually. Led teams in Singapore and APAC.

## Experience
### Workato, 2021–Present
- Regional VP Sales, APAC
- Grew revenue from $10M to $15M (50% growth)
- Managed 12+ enterprise accounts
- Led public-sector initiative with GIC

### Previous Company, 2018–2021
- Enterprise Account Manager
- Quota: 120%, 2 years running

## Skills
- Enterprise sales, Account management, SaaS, Salesforce, Python
""")
    return str(cv_path)


@pytest.fixture
def evidence_repo_baseline(baseline_dxc_cv, evidence_factory):
    """Pre-populated evidence repo with baseline CV imports."""
    return {
        "schema_version": "1.0",
        "evidence_repository": {
            "evidence_list": [
                evidence_factory(
                    statement="Grew revenue from $10M to $15M (50% growth) at Workato, managing 12+ enterprise accounts in APAC",
                    evidence_type="achievement",
                    source_type="baseline_cv",
                    source_reference="DXC CV: Professional Summary and Experience",
                    confidence="LEVEL_A",
                    competencies=["Enterprise Sales", "Revenue Growth", "Account Management"],
                    industries=["SaaS"],
                    geographies=["Singapore", "APAC"],
                    metrics={
                        "revenue": {
                            "amount": 5000000,
                            "currency": "SGD",
                            "period": "2021-Present",
                            "verified_source": "baseline_cv"
                        },
                        "customer_count": {
                            "count": 12,
                            "period": "2023"
                        }
                    }
                ),
                evidence_factory(
                    statement="Enterprise Account Manager at previous company, consistently achieved 120% quota",
                    evidence_type="work_experience",
                    source_type="baseline_cv",
                    source_reference="DXC CV: Experience section",
                    confidence="LEVEL_B",
                    competencies=["Account Management", "Sales", "Quota Achievement"],
                    industries=["SaaS"],
                    metrics={
                        "quota_attainment": {
                            "percentage": 120,
                            "period": "2 consecutive years",
                            "verified_source": "baseline_cv"
                        }
                    }
                ),
                evidence_factory(
                    statement="Technical proficiency: Salesforce, Python, cloud platforms",
                    evidence_type="technical_knowledge",
                    source_type="baseline_cv",
                    source_reference="DXC CV: Skills section",
                    confidence="LEVEL_B",
                    technologies=["Salesforce", "Python", "Cloud Platforms"],
                ),
                evidence_factory(
                    statement="8+ years enterprise account management experience in SaaS",
                    evidence_type="work_experience",
                    source_type="baseline_cv",
                    source_reference="DXC CV: Professional Summary",
                    confidence="LEVEL_A",
                    competencies=["Enterprise Sales", "Account Management"],
                    industries=["SaaS"],
                    metrics={
                        "years_of_experience": {
                            "value": 8,
                            "verified_source": "baseline_cv"
                        }
                    }
                ),
            ]
        }
    }


@pytest.fixture
def gartner_jd(tmp_path):
    """Gartner SAE job description."""
    jd_path = tmp_path / "Gartner" / "JD.md"
    jd_path.parent.mkdir(parents=True, exist_ok=True)
    jd_path.write_text("""# Gartner: Strategic Account Executive - APAC
## Requirements
- 5+ years enterprise account management
- Proven revenue growth track record ($5M+)
- Public-sector experience preferred
- Salesforce platform experience required
- Leadership of cross-functional teams

## Responsibilities
- Manage tier-1 enterprise accounts in APAC
- Drive renewal and expansion revenue
- Develop customer success plans
- Lead sales initiatives across Singapore and Malaysia
""")
    return str(jd_path)


@pytest.fixture
def tracker_with_apps(application_factory, gartner_jd):
    """Tracker with sample applications."""
    gartner_app = application_factory(
        company="Gartner",
        role_title="Strategic Account Executive",
        jd_path=gartner_jd
    )
    return {
        "schema_version": "2.0",
        "applications": [gartner_app]
    }


# ============================================================================
# PYTEST MARKERS
# ============================================================================

def pytest_configure(config):
    """Register pytest markers."""
    config.addinivalue_line("markers", "evidence: Tests for CareerEvidence entity")
    config.addinivalue_line("markers", "requirement: Tests for requirement analysis")
    config.addinivalue_line("markers", "gap: Tests for gap interview")
    config.addinivalue_line("markers", "cv: Tests for CV workflow")
    config.addinivalue_line("markers", "reuse: Tests for cross-application reuse")
    config.addinivalue_line("markers", "contradiction: Tests for conflict detection")
    config.addinivalue_line("markers", "e2e: End-to-end scenario tests")
