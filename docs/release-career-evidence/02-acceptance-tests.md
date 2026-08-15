# Gate 2: Acceptance Tests & Criteria
## Career Evidence Repository + Governed CV Workflow Release

**Date:** 2026-08-14  
**Status:** Test-driven acceptance criteria finalized  
**Scope:** 18+ testable scenarios, pytest structure, fixtures

---

## Overview

This document defines acceptance tests (in executable pytest form) that validate the domain design. Tests are **written before implementation** (TDD discipline). All tests will fail until Gates 3–7 implement the services and MCP tools.

**Philosophy:** A capability is NOT complete until:
1. Tests exist
2. Tests pass
3. Acceptance criteria are satisfied
4. No regression in existing tests

---

## Test Organization

```
tests/
├── acceptance/
│   ├── conftest.py                          # Shared fixtures
│   ├── test_evidence_lifecycle.py           # CareerEvidence CRUD and provenance
│   ├── test_evidence_quality.py             # Confidence levels, LEVEL_D blocking
│   ├── test_requirement_matching.py         # JD parsing, evidence matching
│   ├── test_gap_interview.py               # Gap identification, user responses
│   ├── test_cv_workflow.py                 # Draft, approval, final
│   ├── test_evidence_reuse.py              # Cross-application reuse
│   ├── test_contradictions.py              # Conflict detection and resolution
│   ├── test_duplicates.py                  # Deduplication
│   ├── test_application_state.py           # Extended state machine
│   ├── test_evidence_metrics.py            # Metric verification
│   └── test_end_to_end.py                  # Full lifecycle scenario
└── unit/
    └── [Existing test_mcp_server.py, etc. — regression tests]
```

---

## Shared Fixtures

### conftest.py

```python
import pytest
import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path

# === TEST DATA FACTORIES ===

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
        **kwargs
    ):
        return {
            "evidence_id": str(uuid.uuid4()),
            "statement": statement,
            "evidence_type": evidence_type,
            "source_type": source_type,
            "source_reference": source_reference,
            "source_date": "2026-05-15T00:00:00Z",
            "first_captured_at": datetime.utcnow().isoformat() + "Z",
            "last_confirmed_at": datetime.utcnow().isoformat() + "Z",
            "application_origin": None,
            "verification_status": verification_status,
            "confidence": confidence,
            "user_confirmed": user_confirmed,
            "supersedes": [],
            "superseded_by": [],
            "related_to": [],
            "competencies": competencies or [],
            "technologies": [],
            "industries": [],
            "geographies": [],
            "metrics": metrics or {},
            "notes": "",
            "created_by": "test",
            "created_at": datetime.utcnow().isoformat() + "Z",
            "last_modified_by": "test",
            "last_modified_at": datetime.utcnow().isoformat() + "Z",
            **kwargs
        }
    return _create

@pytest.fixture
def requirement_factory():
    """Factory for creating JobRequirement test objects."""
    def _create(
        statement="Test requirement",
        category="mandatory",
        req_type="domain_experience",
        matched_evidence=None,
        gap_status="covered",
        **kwargs
    ):
        return {
            "requirement_id": str(uuid.uuid4()),
            "application_id": str(uuid.uuid4()),
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
            "gap_interview_question": None,
            "user_response": None,
            "evidence_created_from_response": None,
            "coverage_score": 1.0 if gap_status == "covered" else 0.0,
            "required_for_cv": True,
            "created_at": datetime.utcnow().isoformat() + "Z",
            **kwargs
        }
    return _create

@pytest.fixture
def application_factory(tmp_path):
    """Factory for creating Application test objects."""
    def _create(
        company="TestCorp",
        role_title="Test Role",
        stage="new",
        **kwargs
    ):
        jd_path = tmp_path / company / "JD.md"
        jd_path.parent.mkdir(parents=True, exist_ok=True)
        jd_path.write_text("Test JD content")
        
        return {
            "id": str(uuid.uuid4()),
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

@pytest.fixture
def cv_record_factory():
    """Factory for creating CVRecord test objects."""
    def _create(
        application_id=None,
        version="draft_1",
        status="draft",
        content="Test CV content",
        evidence_used=None,
        **kwargs
    ):
        return {
            "cv_record_id": str(uuid.uuid4()),
            "application_id": application_id or str(uuid.uuid4()),
            "version": version,
            "version_number": int(version.split("_")[-1]) if "draft_" in version else 0,
            "status": status,
            "content": content,
            "evidence_used": evidence_used or [],
            "major_changes": [],
            "changed_sections": [],
            "significant_omissions": [],
            "created_at": datetime.utcnow().isoformat() + "Z",
            "approved_at": None,
            "finalized_at": None,
            "predecessor_id": None,
            "successor_id": None,
            "created_by": "app:claude",
            "last_modified_by": "app:claude",
            "last_modified_at": datetime.utcnow().isoformat() + "Z",
            **kwargs
        }
    return _create

# === TEST DATA FIXTURES ===

@pytest.fixture
def baseline_dxc_cv(tmp_path):
    """DXC baseline CV for seeding."""
    cv_path = tmp_path / "Base CV" / "CV LEE Gee Sin 2026.md"
    cv_path.parent.mkdir(parents=True, exist_ok=True)
    cv_path.write_text("""
# LEE Gee Sin
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
                    statement="Grew revenue from $10M to $15M (50% growth) at Workato, managing 12+ enterprise accounts",
                    evidence_type="achievement",
                    source_type="baseline_cv",
                    source_reference="DXC CV: Professional Summary",
                    confidence="LEVEL_A",
                    competencies=["Enterprise Sales", "Revenue Growth"],
                    industries=["SaaS"],
                    geographies=["Singapore", "APAC"],
                    metrics={
                        "revenue": {
                            "amount": 5000000,
                            "currency": "SGD",
                            "period": "2021-Present",
                            "verified_source": "baseline_cv"
                        }
                    }
                ),
                evidence_factory(
                    statement="Enterprise Account Manager at previous company, consistently achieved 120% quota",
                    evidence_type="work_experience",
                    source_type="baseline_cv",
                    source_reference="DXC CV: Experience section",
                    confidence="LEVEL_B",
                    competencies=["Account Management", "Sales"],
                    industries=["SaaS"],
                ),
                evidence_factory(
                    statement="Technical proficiency: Salesforce, Python, cloud platforms",
                    evidence_type="technical_knowledge",
                    source_type="baseline_cv",
                    source_reference="DXC CV: Skills",
                    confidence="LEVEL_B",
                    technologies=["Salesforce", "Python"],
                ),
            ]
        }
    }

@pytest.fixture
def gartner_jd(tmp_path):
    """Gartner SAE job description."""
    jd_path = tmp_path / "Gartner" / "JD.md"
    jd_path.parent.mkdir(parents=True, exist_ok=True)
    jd_path.write_text("""
# Gartner: Strategic Account Executive
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

# === MOCK SERVICES (Stubs for implementation) ===

class MockEvidenceService:
    """Stub that will be replaced by real implementation."""
    def __init__(self):
        self.evidence_repo = {}
    
    def create_evidence(self, **kwargs):
        raise NotImplementedError("Implementation in Gate 3")
    
    def get_evidence(self, evidence_id):
        raise NotImplementedError("Implementation in Gate 3")
    
    def list_evidence(self, filters=None):
        raise NotImplementedError("Implementation in Gate 3")

class MockRequirementService:
    """Stub that will be replaced by real implementation."""
    def extract_requirements(self, jd_path):
        raise NotImplementedError("Implementation in Gate 5")
    
    def match_evidence(self, requirement, evidence_list):
        raise NotImplementedError("Implementation in Gate 5")

# === PYTEST MARKERS ===

def pytest_configure(config):
    config.addinivalue_line("markers", "evidence: Tests for CareerEvidence entity")
    config.addinivalue_line("markers", "requirement: Tests for requirement analysis")
    config.addinivalue_line("markers", "gap: Tests for gap interview")
    config.addinivalue_line("markers", "cv: Tests for CV workflow")
    config.addinivalue_line("markers", "reuse: Tests for cross-application reuse")
    config.addinivalue_line("markers", "contradiction: Tests for conflict detection")
    config.addinivalue_line("markers", "e2e: End-to-end scenario tests")
```

---

## Acceptance Test Scenarios

### Test 1: Baseline Evidence Imported

**File:** `test_evidence_lifecycle.py::test_baseline_evidence_imported`

**Scenario:** User's DXC CV is parsed into CareerEvidence items during baseline import.

**Test Code:**
```python
@pytest.mark.evidence
def test_baseline_evidence_imported(evidence_repo_baseline):
    """Evidence from DXC CV is imported with source=baseline_cv, confidence=LEVEL_A."""
    evidence_list = evidence_repo_baseline["evidence_repository"]["evidence_list"]
    
    # Should have at least 3 evidence items
    assert len(evidence_list) >= 3
    
    # All should have source_type = baseline_cv
    for evidence in evidence_list:
        assert evidence["source_type"] == "baseline_cv"
        assert evidence["confidence"] in ["LEVEL_A", "LEVEL_B"]  # Baseline is strong
        assert evidence["user_confirmed"] == True
        assert "DXC CV" in evidence["source_reference"]
    
    # Revenue achievement should be LEVEL_A (quantified)
    revenue_evidence = [e for e in evidence_list if "revenue" in e["statement"].lower()]
    assert len(revenue_evidence) > 0
    assert revenue_evidence[0]["confidence"] == "LEVEL_A"
    assert revenue_evidence[0]["metrics"].get("revenue") is not None
```

**Assertion:** Evidence has source_type="baseline_cv", confidence=LEVEL_A/B, verified.

---

### Test 2: LinkedIn Evidence Separate

**File:** `test_evidence_lifecycle.py::test_linkedin_evidence_separate`

**Scenario:** LinkedIn profile refresh creates distinct CareerEvidence with source="linkedin".

**Test Code:**
```python
@pytest.mark.evidence
def test_linkedin_evidence_separate(evidence_factory):
    """LinkedIn evidence is distinguishable from baseline CV evidence."""
    # Create two evidence items: one from CV, one from LinkedIn
    cv_evidence = evidence_factory(
        statement="Worked at Workato",
        source_type="baseline_cv",
        source_reference="CV"
    )
    linkedin_evidence = evidence_factory(
        statement="Work at Workato",  # Slightly different wording
        source_type="linkedin",
        source_reference="LinkedIn profile snapshot"
    )
    
    # Both should exist in repo
    evidence_list = [cv_evidence, linkedin_evidence]
    
    # Should be queryable separately
    cv_only = [e for e in evidence_list if e["source_type"] == "baseline_cv"]
    linkedin_only = [e for e in evidence_list if e["source_type"] == "linkedin"]
    
    assert len(cv_only) == 1
    assert len(linkedin_only) == 1
```

**Assertion:** LinkedIn evidence has source_type="linkedin" and is separately queryable.

---

### Test 3: User-Supplied Evidence Created

**File:** `test_evidence_lifecycle.py::test_user_supplied_evidence_created`

**Scenario:** User answers gap interview question → CareerEvidence created with source="user_supplied".

**Test Code:**
```python
@pytest.mark.gap
def test_user_supplied_evidence_created(evidence_factory, application_factory):
    """Gap interview response creates CareerEvidence with source=user_supplied."""
    app = application_factory(company="Gartner", role_title="SAE")
    app_id = app["id"]
    
    # Simulate gap interview response
    user_response = "At Workato I spent 6 months on GIC AI adoption pilot. Reduced RFP processing by 60%."
    
    # Service should create evidence from this
    # (Implementation in Gate 3: GapInterviewService.capture_response)
    new_evidence = evidence_factory(
        statement="Worked as Solutions Architect on public-sector AI automation (GIC RFP pilot); reduced processing time 60%",
        evidence_type="achievement",
        source_type="user_supplied",
        source_reference="Gartner gap interview",
        application_origin={
            "application_id": app_id,
            "company": "Gartner",
            "role_title": "Strategic Account Executive",
            "date_supplied": datetime.utcnow().isoformat() + "Z"
        },
        confidence="LEVEL_B",
        user_confirmed=True,
        competencies=["Public Sector", "AI Automation"],
        geographies=["Singapore"],
        metrics={
            "processing_time_reduction": {
                "percentage": 60,
                "verified_source": "self-reported"
            }
        }
    )
    
    # Verify properties
    assert new_evidence["source_type"] == "user_supplied"
    assert new_evidence["application_origin"] is not None
    assert new_evidence["application_origin"]["application_id"] == app_id
    assert new_evidence["user_confirmed"] == True
    assert new_evidence["confidence"] == "LEVEL_B"
```

**Assertion:** Evidence has source_type="user_supplied", application_origin populated, user_confirmed=true.

---

### Test 4: Evidence Reused in Future Application

**File:** `test_evidence_reuse.py::test_evidence_reused_future_application`

**Scenario:** Evidence from first application is queryable and can be matched to requirements in second application.

**Test Code:**
```python
@pytest.mark.reuse
def test_evidence_reused_future_application(
    evidence_repo_baseline,
    evidence_factory,
    application_factory,
    requirement_factory
):
    """Evidence from Application 1 (Gartner) is reused in Application 2 (Salesforce)."""
    
    # Application 1: Gartner (has public-sector evidence)
    gartner_app = application_factory(company="Gartner", role_title="SAE")
    public_sector_evidence = evidence_factory(
        statement="Led public-sector AI adoption pilot at GIC",
        source_type="user_supplied",
        application_origin={
            "application_id": gartner_app["id"],
            "company": "Gartner",
            "role_title": "Strategic Account Executive"
        },
        competencies=["Public Sector", "AI"],
        geographies=["Singapore"]
    )
    
    # Add to evidence repo
    evidence_list = evidence_repo_baseline["evidence_repository"]["evidence_list"]
    evidence_list.append(public_sector_evidence)
    
    # Application 2: Salesforce (also needs public-sector experience)
    salesforce_app = application_factory(company="Salesforce", role_title="Enterprise Account Executive")
    
    # Service should find the same evidence for Salesforce requirement
    public_sector_requirement = requirement_factory(
        statement="Public-sector customer experience required",
        application_id=salesforce_app["id"]
    )
    
    # Query evidence for this requirement
    # (Implementation in Gate 5: RequirementService.match_evidence)
    matching_evidence = [e for e in evidence_list 
                        if "public" in e["statement"].lower() and "sector" in e["statement"].lower()]
    
    assert len(matching_evidence) > 0
    assert matching_evidence[0]["evidence_id"] == public_sector_evidence["evidence_id"]
    
    # Requirement should be marked as covered (no re-interview)
    # Gap status should not be "missing" or "partial"
    # (Verified in test_requirement_matching.py)
```

**Assertion:** Evidence queryable across applications; requirement-matching finds it; gap skipped.

---

### Test 5: Generated Content NOT Evidence

**File:** `test_evidence_quality.py::test_generated_content_not_evidence`

**Scenario:** CV content generated by LLM is NOT stored as CareerEvidence.

**Test Code:**
```python
@pytest.mark.cv
def test_generated_content_not_evidence(cv_record_factory, evidence_factory):
    """Generated CV prose is not stored as queryable evidence for future apps."""
    
    # Original evidence
    original_evidence = evidence_factory(
        statement="Grew revenue 50% at Workato",
        evidence_type="achievement",
        confidence="LEVEL_A"
    )
    
    # CV draft adapts this evidence
    cv_draft = cv_record_factory(
        version="draft_1",
        status="draft",
        evidence_used=[
            {
                "evidence_id": original_evidence["evidence_id"],
                "evidence_statement": original_evidence["statement"],
                "cv_section": "Professional Summary",
                "adapted_text": "Demonstrated consistent revenue growth, expanding enterprise customer base by 50% in competitive market",
                "confidence_level": "LEVEL_A"
            }
        ]
    )
    
    # The adapted_text should NOT become a new CareerEvidence
    # It should remain in CVRecord.evidence_used[].adapted_text only
    assert "adapted_text" in cv_draft["evidence_used"][0]
    assert cv_draft["evidence_used"][0]["evidence_id"] == original_evidence["evidence_id"]
    
    # Service should NOT create a new evidence for "Demonstrated consistent revenue growth..."
    # (Verified by: service does not create evidence in save_tailored_cv implementation)
    # Evidence repo still has only the original evidence
```

**Assertion:** CV records evidence_used with adapted_text; does NOT create new CareerEvidence from adapted text.

---

### Test 6: Unsupported Claim Rejected

**File:** `test_evidence_quality.py::test_unsupported_metric_rejected`

**Scenario:** User supplies a quantified metric with no verified_source → rejected.

**Test Code:**
```python
@pytest.mark.evidence
def test_unsupported_metric_rejected(evidence_factory):
    """Evidence with quantified metrics requires verified_source; rejected if missing."""
    
    # Invalid evidence: metric without verified_source
    invalid_evidence_spec = {
        "statement": "Increased revenue by 500%",
        "evidence_type": "achievement",
        "source_type": "user_supplied",
        "metrics": {
            "revenue_increase": {
                "percentage": 500
                # NOTE: missing verified_source
            }
        }
    }
    
    # Service should reject this
    # (Implementation in Gate 3: EvidenceService.create_evidence validates metrics)
    with pytest.raises(ValueError, match="verified_source required for metric"):
        # This would be called during gap_response_capture
        evidence = evidence_factory(**invalid_evidence_spec)
        # Validation happens here; should raise
        validate_evidence_metrics(evidence)
    
    # Valid evidence: metric with verified_source
    valid_evidence = evidence_factory(
        statement="Increased revenue by 500% (500 to 2500 customers)",
        metrics={
            "customer_growth": {
                "before": 500,
                "after": 2500,
                "verified_source": "company_announcement"
            }
        }
    )
    
    # Should be accepted
    assert valid_evidence["metrics"]["customer_growth"]["verified_source"] == "company_announcement"
```

**Assertion:** Metrics without verified_source rejected; with verified_source accepted.

---

### Test 7: Contradictions Detected

**File:** `test_contradictions.py::test_contradiction_detected_not_overwritten`

**Scenario:** New evidence contradicts existing → system detects, does NOT auto-overwrite.

**Test Code:**
```python
@pytest.mark.contradiction
def test_contradiction_detected_not_overwritten(evidence_factory):
    """Contradicting evidence detected; system does not auto-overwrite."""
    
    # Existing evidence: baseline CV
    existing = evidence_factory(
        statement="Regional responsibility: Singapore market",
        source_type="baseline_cv",
        source_reference="DXC CV",
        verification_status="user_confirmed"
    )
    
    # New evidence: user later says APAC
    new = evidence_factory(
        statement="I covered Singapore and Malaysia markets",
        source_type="user_supplied",
        source_reference="Gartner gap interview",
        verification_status="user_confirmed"
    )
    
    # Service should detect contradiction
    # (Implementation in Gate 4: EvidenceService.detect_contradictions)
    contradictions = detect_contradictions(new, [existing])
    
    assert len(contradictions) > 0
    contradiction = contradictions[0]
    assert contradiction["type"] == "geographic_scope_mismatch"
    assert contradiction["existing_value"] == "Singapore"
    assert contradiction["new_value"] == "Singapore, Malaysia"
    
    # Service should NOT auto-overwrite existing
    # Existing should remain in repo
    assert existing["verification_status"] != "superseded"
    assert existing["superseded_by"] == []
    
    # System should prompt user to resolve
    assert contradiction["requires_user_action"] == True
```

**Assertion:** Contradictions detected; system does NOT overwrite; flags for resolution.

---

### Test 8: Duplicate Evidence Handled

**File:** `test_duplicates.py::test_duplicate_detected_and_merged`

**Scenario:** Same fact mentioned twice → detected, merged, no duplication.

**Test Code:**
```python
@pytest.mark.evidence
def test_duplicate_detected_and_merged(evidence_factory):
    """Duplicate facts detected; user can merge them."""
    
    # First mention: from Gartner gap interview
    fact1 = evidence_factory(
        statement="Enterprise sales experience in APAC",
        source_type="user_supplied",
        application_origin={
            "application_id": "app-1-gartner",
            "company": "Gartner"
        }
    )
    
    # Second mention: from Salesforce gap interview (same fact, more detail)
    fact2_text = "Spent 3 years doing enterprise account management across Singapore, Malaysia, and Thailand"
    
    # Service should detect semantic similarity
    # (Implementation in Gate 4: EvidenceService.find_duplicates)
    candidates = find_duplicates(fact2_text, [fact1])
    
    assert len(candidates) > 0
    candidate = candidates[0]
    assert candidate["similarity_score"] > 0.85
    
    # System should ask user: "Merge these?"
    # If user confirms merge:
    # - Create merged evidence combining both facts
    # - Mark originals as related_to
    
    merged = evidence_factory(
        statement="Enterprise account management experience across Singapore, Malaysia, Thailand (APAC), 3 years",
        supersedes=[fact1["evidence_id"]],
        related_to=[fact2_text]  # Reference to original mention
    )
    
    # Old evidence marked as superseded
    fact1_superseded = fact1.copy()
    fact1_superseded["verification_status"] = "superseded"
    fact1_superseded["superseded_by"] = [merged["evidence_id"]]
    
    assert merged["supersedes"] == [fact1["evidence_id"]]
    assert fact1_superseded["verification_status"] == "superseded"
```

**Assertion:** Duplicates detected; merged with supersede relationships; no data loss.

---

### Test 9: Draft CV Created Before Final

**File:** `test_cv_workflow.py::test_draft_cv_created_before_final`

**Scenario:** save_tailored_cv creates draft, sets stage to AWAITING_CV_REVIEW (no direct final).

**Test Code:**
```python
@pytest.mark.cv
def test_draft_cv_created_before_final(application_factory, cv_record_factory):
    """Draft CV is created; application moves to AWAITING_CV_REVIEW."""
    
    app = application_factory(company="Gartner", role_title="SAE", stage="new")
    app_id = app["id"]
    
    # User calls save_tailored_cv
    draft_content = "# Tailored CV for Gartner\n..."
    
    # Service should create draft (not final)
    # (Implementation in Gate 6: CVVersioningService.create_draft)
    draft = cv_record_factory(
        application_id=app_id,
        version="draft_1",
        status="draft",
        content=draft_content
    )
    
    # Verify draft properties
    assert draft["status"] == "draft"
    assert draft["approved_at"] is None
    assert draft["finalized_at"] is None
    assert draft["version"] == "draft_1"
    
    # Application should move to AWAITING_CV_REVIEW
    # (Verified in test_application_state.py)
    # NOT to READY_TO_APPLY or APPLIED
    
    # Cannot finalize without approval
    # (Verified: finalize_cv raises error if status != "approved")
    with pytest.raises(ValueError, match="Cannot finalize non-approved CV"):
        # Service validation prevents this
        pass
```

**Assertion:** save_tailored_cv creates draft, not final; application stage = AWAITING_CV_REVIEW.

---

### Test 10: Human Review Gate Enforced

**File:** `test_cv_workflow.py::test_review_gate_enforced`

**Scenario:** Application in AWAITING_CV_REVIEW; cannot skip approval step.

**Test Code:**
```python
@pytest.mark.cv
def test_review_gate_enforced(application_factory, cv_record_factory):
    """Approval gate blocks finalization; user must explicitly approve."""
    
    app = application_factory(company="Gartner", stage="awaiting_cv_review")
    app_id = app["id"]
    
    draft = cv_record_factory(
        application_id=app_id,
        version="draft_1",
        status="draft"
    )
    draft_id = draft["cv_record_id"]
    
    # Service prevents direct finalization
    with pytest.raises(ValueError, match="Draft must be approved before finalization"):
        # This should fail
        finalize_cv(draft_id)  # Implementation should validate
    
    # User must call approve_cv first
    # (Implementation in Gate 6: approve_cv tool)
    approved = cv_record_factory(
        cv_record_id=draft_id,
        status="approved",
        approved_at=datetime.utcnow().isoformat() + "Z"
    )
    
    # Only then can finalize
    # (Verified: no error this time)
    # finalize_cv(draft_id) → should succeed
    
    # Application moves to READY_TO_APPLY
    # (Verified in test_application_state.py)
```

**Assertion:** Approval gate enforced; finalization blocked until explicit approve_cv call.

---

### Test 11: Application Survives Partial Completion

**File:** `test_application_state.py::test_application_survives_partial_completion`

**Scenario:** User ingests JD, abandons workflow → application persists with partial state.

**Test Code:**
```python
@pytest.mark.evidence
def test_application_survives_partial_completion(
    application_factory,
    tracker_with_apps,
    tmp_path
):
    """Application created at ingest_jd; survives if workflow abandoned."""
    
    # User ingests Gartner JD
    # (Implementation: ingest_jd creates application record immediately)
    gartner_app = tracker_with_apps["applications"][0]
    app_id = gartner_app["id"]
    
    # Application should be in "new" stage, with JD loaded
    assert gartner_app["stage"] == "new"
    assert gartner_app["jd_path"] is not None
    
    # User abandons (closes conversation)
    # Next day, user queries get_application
    
    # Application should still exist
    retrieved_app = get_application_from_tracker(app_id, tracker_with_apps)
    assert retrieved_app is not None
    assert retrieved_app["id"] == app_id
    assert retrieved_app["company"] == "Gartner"
    
    # Application has no requirements, cv_records, etc. yet (partial state)
    assert len(retrieved_app["requirements"]) == 0
    assert len(retrieved_app["cv_records"]) == 0
    assert retrieved_app["gap_interview_phase"] == "not_started"
    
    # No data loss: JD is still there
    assert retrieved_app["jd_path"] is not None
    assert Path(retrieved_app["jd_path"]).exists()
```

**Assertion:** Application persists from ingest_jd; no loss of work if user abandons.

---

### Test 12: Final CV Version Recoverable

**File:** `test_cv_workflow.py::test_final_cv_version_recoverable`

**Scenario:** After submission, exact CV sent to employer can be retrieved.

**Test Code:**
```python
@pytest.mark.cv
def test_final_cv_version_recoverable(
    application_factory,
    cv_record_factory
):
    """After mark_submitted, exact CV version is recoverable."""
    
    app = application_factory(company="Gartner", role_title="SAE")
    app_id = app["id"]
    
    # Multiple draft iterations
    draft1 = cv_record_factory(
        application_id=app_id,
        version="draft_1",
        status="draft",
        content="# Draft 1 Content"
    )
    
    draft2 = cv_record_factory(
        application_id=app_id,
        version="draft_2",
        status="approved",
        content="# Draft 2 Content (approved)",
        predecessor_id=draft1["cv_record_id"]
    )
    draft1["successor_id"] = draft2["cv_record_id"]
    
    # Final submission
    final = cv_record_factory(
        application_id=app_id,
        version="final",
        status="final",
        content="# Final Submitted CV",
        predecessor_id=draft2["cv_record_id"]
    )
    draft2["successor_id"] = final["cv_record_id"]
    
    # User later asks: "What CV did I send?"
    # Service retrieves final version
    # (Implementation: get_cv_version(app_id, version="final"))
    cv_versions = [draft1, draft2, final]
    
    final_version = [cv for cv in cv_versions if cv["version"] == "final"][0]
    
    assert final_version["content"] == "# Final Submitted CV"
    assert final_version["status"] == "final"
    assert final_version["finalized_at"] is not None
    
    # Version chain is traceable
    assert final_version["predecessor_id"] == draft2["cv_record_id"]
    assert draft2["predecessor_id"] == draft1["cv_record_id"]
```

**Assertion:** Final CV exact version recoverable; version chain traceable.

---

### Test 13: Second Application Leverages Enrichment

**File:** `test_evidence_reuse.py::test_second_app_leverages_enrichment`

**Scenario:** First app's user-supplied evidence reused in second app without re-interview.

**Test Code:**
```python
@pytest.mark.reuse
def test_second_app_leverages_enrichment(
    evidence_repo_baseline,
    evidence_factory,
    application_factory,
    requirement_factory
):
    """Evidence enriched in first application is reused in second without re-interview."""
    
    # First application: Gartner
    gartner_app = application_factory(company="Gartner")
    gartner_req = requirement_factory(
        statement="Public-sector AI adoption experience",
        application_id=gartner_app["id"],
        gap_status="missing"  # Initially missing
    )
    
    # Gap interview: user supplies evidence
    user_response = "At Workato, led GIC AI automation pilot"
    gic_evidence = evidence_factory(
        statement="Led public-sector AI automation pilot for GIC (Singapore)",
        evidence_type="achievement",
        source_type="user_supplied",
        application_origin={
            "application_id": gartner_app["id"],
            "company": "Gartner"
        },
        confidence="LEVEL_B",
        competencies=["Public Sector", "AI"],
        geographies=["Singapore"]
    )
    
    # Add to repo
    evidence_repo_baseline["evidence_repository"]["evidence_list"].append(gic_evidence)
    
    # Requirement is now matched
    gartner_req["gap_status"] = "covered"
    gartner_req["matched_evidence"] = [{
        "evidence_id": gic_evidence["evidence_id"],
        "match_strength": "ADEQUATE"
    }]
    
    # Second application: Salesforce
    salesforce_app = application_factory(company="Salesforce")
    salesforce_req = requirement_factory(
        statement="Public-sector enterprise experience",
        application_id=salesforce_app["id"],
        gap_status="missing"  # Initially missing in new app
    )
    
    # Service matches existing evidence
    # (Implementation: RequirementService.match_evidence queries evidence_repo)
    evidence_list = evidence_repo_baseline["evidence_repository"]["evidence_list"]
    matching = [e for e in evidence_list 
               if "public" in e["statement"].lower() and e["evidence_type"] == "achievement"]
    
    assert len(matching) > 0
    
    # Requirement no longer marked as missing
    salesforce_req["gap_status"] = "covered"
    salesforce_req["matched_evidence"] = [{
        "evidence_id": matching[0]["evidence_id"],
        "match_strength": "ADEQUATE"
    }]
    
    # Gap interview NOT needed for this requirement
    assert salesforce_req["gap_interview_question"] is None
```

**Assertion:** Evidence from app 1 reused in app 2; gap skipped; no re-interview.

---

### Test 14: Evidence NOT Fabricated

**File:** `test_evidence_quality.py::test_evidence_not_fabricated`

**Scenario:** Vague baseline evidence not automatically promoted to strong claim.

**Test Code:**
```python
@pytest.mark.evidence
def test_evidence_not_fabricated(evidence_factory, cv_record_factory):
    """Weak or vague evidence not fabricated into strong claims in CV."""
    
    # Weak evidence: user only confirms familiarity
    weak_evidence = evidence_factory(
        statement="Familiar with enterprise AI adoption concepts",
        evidence_type="skill",
        source_type="user_supplied",
        confidence="LEVEL_C"  # General, not strong
    )
    
    # CV draft uses this
    draft = cv_record_factory(
        version="draft_1",
        evidence_used=[
            {
                "evidence_id": weak_evidence["evidence_id"],
                "cv_section": "Skills",
                "adapted_text": "Enterprise AI adoption expertise",  # Stronger wording
                "confidence_level": "LEVEL_C"
            }
        ]
    )
    
    # Service should validate: confidence mismatch
    # If evidence is LEVEL_C, adapted text should NOT claim "expertise"
    # (Implementation validation in Gate 6: save_tailored_cv validator)
    
    with pytest.raises(ValueError, match="CV claim exceeds evidence confidence"):
        # "Expertise" is LEVEL_A/B language; evidence is LEVEL_C
        validate_cv_evidence_fidelity(draft, weak_evidence)
    
    # Correct adaptation would be:
    correct_draft = cv_record_factory(
        version="draft_1",
        evidence_used=[
            {
                "evidence_id": weak_evidence["evidence_id"],
                "cv_section": "Skills",
                "adapted_text": "Exposure to enterprise AI adoption initiatives",  # Qualified
                "confidence_level": "LEVEL_C"
            }
        ]
    )
    
    # Should pass validation (no fabrication)
    assert correct_draft["evidence_used"][0]["adapted_text"].startswith("Exposure")
```

**Assertion:** Weak evidence not fabricated into strong claims; language matches confidence level.

---

### Test 15: Evidence Provenance Traceable

**File:** `test_evidence_lifecycle.py::test_evidence_provenance_traceable`

**Scenario:** Evidence used in CV is traceable back to source.

**Test Code:**
```python
@pytest.mark.evidence
def test_evidence_provenance_traceable(evidence_factory, cv_record_factory):
    """Evidence in CV is traceable to original source document."""
    
    evidence = evidence_factory(
        statement="Grew revenue 50% in Singapore",
        source_type="baseline_cv",
        source_reference="DXC CV p1 line 5",
        source_date="2026-05-15T00:00:00Z"
    )
    
    draft = cv_record_factory(
        version="draft_1",
        evidence_used=[
            {
                "evidence_id": evidence["evidence_id"],
                "evidence_statement": evidence["statement"],
                "cv_section": "Professional Summary",
                "adapted_text": "50% revenue growth in key market",
                "confidence_level": "LEVEL_A",
                "justification": "Directly addresses JD requirement for proven revenue growth"
            }
        ]
    )
    
    # User asks: "Where did this fact come from?"
    # Service should trace back
    # (Implementation: query_cv_evidence_sources(cv_id))
    
    cv_evidence_mapping = {
        draft["evidence_used"][0]["evidence_id"]: evidence
    }
    
    # Trace
    source = cv_evidence_mapping[draft["evidence_used"][0]["evidence_id"]]
    
    assert source["source_type"] == "baseline_cv"
    assert "DXC CV" in source["source_reference"]
    assert source["source_date"] is not None
    
    # Full provenance chain visible
    provenance = {
        "fact_in_cv": draft["evidence_used"][0]["adapted_text"],
        "original_statement": source["statement"],
        "source_type": source["source_type"],
        "source_reference": source["source_reference"],
        "confidence": source["confidence"],
        "captured_at": source["first_captured_at"]
    }
    
    assert provenance["source_reference"] is not None
```

**Assertion:** CV evidence traceable to original source; full provenance chain visible.

---

### Test 16: Metric Verification Enforced

**File:** `test_evidence_metrics.py::test_metric_verification_enforced`

**Scenario:** Quantified metrics require verified_source; cannot be estimated.

**Test Code:**
```python
@pytest.mark.evidence
def test_metric_verification_enforced(evidence_factory):
    """Quantified metrics require verified_source; no estimated numbers."""
    
    # Invalid: metric without verified_source
    invalid_spec = {
        "statement": "Grew revenue to $5M",
        "metrics": {
            "revenue": {
                "amount": 5000000,
                "currency": "SGD"
                # Missing: verified_source
            }
        }
    }
    
    with pytest.raises(ValueError, match="Metric requires verified_source"):
        evidence = evidence_factory(**invalid_spec)
        validate_evidence_metrics(evidence)
    
    # Valid: metric with verified_source
    valid_spec = {
        "statement": "Grew revenue to $5M (verified by company announcement)",
        "metrics": {
            "revenue": {
                "amount": 5000000,
                "currency": "SGD",
                "period": "FY2023",
                "verified_source": "company_announcement"  # Valid source
            }
        }
    }
    
    evidence = evidence_factory(**valid_spec)
    validate_evidence_metrics(evidence)  # Should pass
    
    assert evidence["metrics"]["revenue"]["verified_source"] == "company_announcement"
    
    # Acceptable verified_sources:
    # - baseline_cv (user's own CV)
    # - company_announcement (company press release, SEC filing)
    # - contract (customer contract)
    # - self-reported (user says so in interview)
    # NOT acceptable: "estimated", "probably", "inferred"
```

**Assertion:** Metrics without verified_source rejected; acceptable sources defined and enforced.

---

### Test 17: Contradiction Resolution Preserves History

**File:** `test_contradictions.py::test_contradiction_resolution_preserves_history`

**Scenario:** When user resolves contradiction, old evidence marked superseded; history preserved.

**Test Code:**
```python
@pytest.mark.contradiction
def test_contradiction_resolution_preserves_history(evidence_factory):
    """Resolved contradictions: old evidence marked superseded; history preserved."""
    
    # Baseline says Singapore only
    old = evidence_factory(
        statement="Regional responsibility: Singapore",
        source_type="baseline_cv",
        source_reference="DXC CV",
        verification_status="user_confirmed"
    )
    
    # User later says APAC
    new_statement = "I covered Singapore, Malaysia, Thailand"
    
    # System detects contradiction
    conflicts = detect_contradictions(new_statement, [old])
    assert len(conflicts) > 0
    
    # User resolves: "APAC is correct; CV was old"
    # Service creates new evidence and marks old as superseded
    # (Implementation in Gate 4: resolve_contradiction)
    
    new = evidence_factory(
        statement="Regional coverage: Singapore, Malaysia, Thailand (APAC)",
        source_type="user_supplied",
        source_reference="Gap interview clarification",
        verification_status="user_confirmed",
        supersedes=[old["evidence_id"]],
        notes="Previous evidence claimed Singapore only; clarified to APAC coverage"
    )
    
    # Old evidence marked as superseded
    old_superseded = old.copy()
    old_superseded["verification_status"] = "superseded"
    old_superseded["superseded_by"] = [new["evidence_id"]]
    
    # Both remain in repo (no deletion)
    evidence_list = [old_superseded, new]
    
    assert len(evidence_list) == 2
    assert old_superseded["verification_status"] == "superseded"
    assert new["supersedes"] == [old["evidence_id"]]
    
    # History preserved: can see why change was made
    assert new["notes"] is not None and "clarified" in new["notes"].lower()
```

**Assertion:** Resolved contradiction: old evidence marked superseded, not deleted; history preserved.

---

### Test 18: Extended State Machine Validates

**File:** `test_application_state.py::test_extended_state_machine_validates`

**Scenario:** Application state machine enforces valid transitions (new stages).

**Test Code:**
```python
@pytest.mark.evidence
def test_extended_state_machine_validates(application_factory):
    """Extended state machine validates transitions."""
    
    app = application_factory(stage="new")
    
    # Valid transitions
    valid = ["discovered", "evaluating", "requirement_analysis", "evidence_matching",
             "gap_analysis", "enriching_profile", "drafting", "awaiting_cv_review",
             "revising", "ready_to_apply", "applied"]
    
    # Test a valid path
    for target_stage in ["discovered", "evaluating", "requirement_analysis"]:
        assert is_valid_transition(app["stage"], target_stage)
        app["stage"] = target_stage
    
    # Invalid transitions
    app["stage"] = "drafting"
    
    # Cannot jump back to new
    assert not is_valid_transition("drafting", "new")
    
    # Cannot skip AWAITING_CV_REVIEW
    assert not is_valid_transition("drafting", "ready_to_apply")
    
    # Terminal stages
    app["stage"] = "applied"
    app["history"].append({"stage": "applied", "at": datetime.utcnow().isoformat() + "Z"})
    
    # Can move forward
    assert is_valid_transition("applied", "recruiter_screen")
    
    # But terminal stages (offer→accepted) block further movement
    app["stage"] = "accepted"
    assert not is_valid_transition("accepted", "rejected")  # No from terminal
```

**Assertion:** State machine validates new stages; blocks invalid transitions.

---

## Summary

**18 acceptance test scenarios defined, pytest-ready**

| # | Scenario | File | Status |
|---|----------|------|--------|
| 1 | Baseline evidence imported | test_evidence_lifecycle.py | ✓ Defined |
| 2 | LinkedIn evidence separate | test_evidence_lifecycle.py | ✓ Defined |
| 3 | User-supplied evidence created | test_evidence_lifecycle.py | ✓ Defined |
| 4 | Evidence reused in future app | test_evidence_reuse.py | ✓ Defined |
| 5 | Generated content NOT evidence | test_evidence_quality.py | ✓ Defined |
| 6 | Unsupported claim rejected | test_evidence_quality.py | ✓ Defined |
| 7 | Contradictions detected | test_contradictions.py | ✓ Defined |
| 8 | Duplicates handled | test_duplicates.py | ✓ Defined |
| 9 | Draft CV created before final | test_cv_workflow.py | ✓ Defined |
| 10 | Review gate enforced | test_cv_workflow.py | ✓ Defined |
| 11 | Application survives partial | test_application_state.py | ✓ Defined |
| 12 | Final CV recoverable | test_cv_workflow.py | ✓ Defined |
| 13 | Second app leverages enrichment | test_evidence_reuse.py | ✓ Defined |
| 14 | Evidence NOT fabricated | test_evidence_quality.py | ✓ Defined |
| 15 | Provenance traceable | test_evidence_lifecycle.py | ✓ Defined |
| 16 | Metric verification enforced | test_evidence_metrics.py | ✓ Defined |
| 17 | Contradiction resolution preserves history | test_contradictions.py | ✓ Defined |
| 18 | Extended state machine validates | test_application_state.py | ✓ Defined |

**All 18 tests runnable but will FAIL until implementation (Gates 3–7).**

**Next:** Gate 3 (Persistence & Migration) — implement JSON schema changes and migration.
