# tests/unit/test_evidence_service.py
"""
Unit tests for EvidenceService.

Tests CRUD, duplicate detection, contradiction detection, querying, and validation.
"""

import pytest
from datetime import datetime
from evidence_service import (
    EvidenceService,
    EvidenceValidator,
    create_evidence_service,
    DuplicateCandidate,
    Contradiction,
)
from evidence_persistence import EvidenceRepository


@pytest.fixture
def evidence_repo(tmp_path):
    """EvidenceRepository for testing."""
    return EvidenceRepository(str(tmp_path))


@pytest.fixture
def evidence_service(evidence_repo):
    """EvidenceService for testing."""
    return EvidenceService(evidence_repo)


# ============================================================================
# CRUD TESTS
# ============================================================================

@pytest.mark.evidence
def test_create_evidence(evidence_service):
    """Can create evidence with all fields."""
    evidence = evidence_service.create_evidence(
        statement="Grew revenue 50% in Singapore",
        evidence_type="achievement",
        source_type="baseline_cv",
        source_reference="DXC CV line 5",
        confidence="LEVEL_A",
        verification_status="user_confirmed",
        user_confirmed=True,
        competencies=["Enterprise Sales"],
        industries=["SaaS"],
        geographies=["Singapore"],
        metrics={
            "revenue": {
                "amount": 5000000,
                "currency": "SGD",
                "verified_source": "baseline_cv"
            }
        }
    )

    assert evidence is not None
    assert evidence["statement"] == "Grew revenue 50% in Singapore"
    assert evidence["confidence"] == "LEVEL_A"
    assert evidence["user_confirmed"] == True
    assert len(evidence["competencies"]) == 1
    assert evidence["metrics"]["revenue"]["verified_source"] == "baseline_cv"


@pytest.mark.evidence
def test_create_evidence_rejects_metric_without_source(evidence_service):
    """Metric without verified_source is rejected."""
    with pytest.raises(ValueError, match="verified_source"):
        evidence_service.create_evidence(
            statement="Test metric",
            evidence_type="achievement",
            source_type="user_supplied",
            source_reference="Test",
            metrics={
                "revenue": {
                    "amount": 5000000
                    # Missing: verified_source
                }
            }
        )


@pytest.mark.evidence
def test_get_evidence(evidence_service):
    """Can retrieve evidence by ID."""
    created = evidence_service.create_evidence(
        statement="Test",
        evidence_type="achievement",
        source_type="baseline_cv",
        source_reference="Test"
    )

    retrieved = evidence_service.get_evidence(created["evidence_id"])
    assert retrieved is not None
    assert retrieved["evidence_id"] == created["evidence_id"]
    assert retrieved["statement"] == "Test"


@pytest.mark.evidence
def test_list_evidence(evidence_service):
    """Can list all evidence."""
    for i in range(3):
        evidence_service.create_evidence(
            statement=f"Test {i}",
            evidence_type="achievement",
            source_type="baseline_cv",
            source_reference="Test"
        )

    all_evidence = evidence_service.list_evidence()
    assert len(all_evidence) == 3


@pytest.mark.evidence
def test_update_evidence_verification(evidence_service):
    """Can update verification status."""
    evidence = evidence_service.create_evidence(
        statement="Test",
        evidence_type="achievement",
        source_type="user_supplied",
        source_reference="Test",
        verification_status="unverified",
        user_confirmed=False
    )

    updated = evidence_service.update_evidence_verification(
        evidence["evidence_id"],
        verification_status="user_confirmed",
        user_confirmed=True,
        notes="User confirmed this fact"
    )

    assert updated is not None
    assert updated["verification_status"] == "user_confirmed"
    assert updated["user_confirmed"] == True
    assert "User confirmed" in updated["notes"]


# ============================================================================
# DUPLICATE DETECTION TESTS
# ============================================================================

@pytest.mark.evidence
def test_find_duplicates_deterministic(evidence_service):
    """Detects exact duplicates (normalized)."""
    stmt1 = "Enterprise sales experience in APAC"
    stmt2 = "enterprise   SALES  EXPERIENCE  in  APAC"  # Different spacing/case

    evidence1 = evidence_service.create_evidence(
        statement=stmt1,
        evidence_type="skill",
        source_type="baseline_cv",
        source_reference="Test"
    )

    evidence2 = evidence_service.create_evidence(
        statement=stmt2,
        evidence_type="skill",
        source_type="user_supplied",
        source_reference="Test"
    )

    all_evidence = evidence_service.list_evidence()
    candidates = evidence_service.find_duplicates(stmt2, all_evidence=all_evidence)

    assert len(candidates) > 0
    assert any(c.match_type == "deterministic" for c in candidates)


@pytest.mark.evidence
def test_find_duplicates_semantic(evidence_service):
    """Detects semantic duplicates (word overlap)."""
    stmt1 = "Enterprise sales experience in APAC"
    stmt2 = "Spent 3 years doing enterprise account management across Singapore, Malaysia, Thailand"

    evidence1 = evidence_service.create_evidence(
        statement=stmt1,
        evidence_type="skill",
        source_type="baseline_cv",
        source_reference="Test"
    )

    all_evidence = evidence_service.list_evidence()
    candidates = evidence_service.find_duplicates(stmt2, confidence_threshold=0.5, all_evidence=all_evidence)

    # Should detect semantic similarity (both mention enterprise/sales/geography)
    assert len(candidates) > 0
    if candidates:
        assert candidates[0].match_type in ["deterministic", "semantic"]


# ============================================================================
# CONTRADICTION DETECTION TESTS
# ============================================================================

@pytest.mark.contradiction
def test_detect_geographic_contradiction(evidence_service):
    """Detects geographic scope contradiction."""
    stmt_old = "Regional responsibility: Singapore market"
    stmt_new = "I covered Singapore and Malaysia markets"

    evidence_old = evidence_service.create_evidence(
        statement=stmt_old,
        evidence_type="work_experience",
        source_type="baseline_cv",
        source_reference="CV",
        geographies=["Singapore"]
    )

    contradictions = evidence_service.detect_contradictions(stmt_new, [evidence_old])

    assert len(contradictions) > 0
    assert any(c.field == "geographic_scope" for c in contradictions)


@pytest.mark.contradiction
def test_resolve_contradiction_supersede(evidence_service):
    """Can resolve contradiction by superseding."""
    old = evidence_service.create_evidence(
        statement="Singapore only",
        evidence_type="work_experience",
        source_type="baseline_cv",
        source_reference="CV"
    )

    new = evidence_service.create_evidence(
        statement="Singapore and Malaysia",
        evidence_type="work_experience",
        source_type="user_supplied",
        source_reference="Interview"
    )

    # Resolve by using new
    success = evidence_service.resolve_contradiction(old["evidence_id"], new["evidence_id"], "use_new")

    assert success == True

    # Verify old is marked as superseded
    updated_old = evidence_service.get_evidence(old["evidence_id"])
    assert updated_old["verification_status"] == "superseded"
    assert new["evidence_id"] in updated_old["superseded_by"]


# ============================================================================
# QUERYING TESTS
# ============================================================================

@pytest.mark.evidence
def test_query_evidence_by_competencies(evidence_service):
    """Can query evidence by competencies."""
    evidence_service.create_evidence(
        statement="Enterprise sales",
        evidence_type="skill",
        source_type="baseline_cv",
        source_reference="Test",
        competencies=["Enterprise Sales", "Revenue Growth"]
    )

    evidence_service.create_evidence(
        statement="Python programming",
        evidence_type="skill",
        source_type="baseline_cv",
        source_reference="Test",
        competencies=["Technical Skills", "Python"]
    )

    # Query for Enterprise Sales
    results = evidence_service.query_evidence(competencies=["Enterprise Sales"])
    assert len(results) == 1
    assert "Enterprise sales" in results[0]["statement"]


@pytest.mark.evidence
def test_query_evidence_by_multiple_filters(evidence_service):
    """Can query with multiple filters (AND logic between fields)."""
    evidence_service.create_evidence(
        statement="Enterprise sales in Singapore",
        evidence_type="work_experience",
        source_type="baseline_cv",
        source_reference="Test",
        competencies=["Enterprise Sales"],
        industries=["SaaS"],
        geographies=["Singapore"]
    )

    evidence_service.create_evidence(
        statement="Technical work in US",
        evidence_type="work_experience",
        source_type="baseline_cv",
        source_reference="Test",
        competencies=["Technical"],
        industries=["Tech"],
        geographies=["United States"]
    )

    # Query: (Enterprise Sales) AND SaaS AND Singapore
    results = evidence_service.query_evidence(
        competencies=["Enterprise Sales"],
        industries=["SaaS"],
        geographies=["Singapore"]
    )

    assert len(results) == 1
    assert "Enterprise sales in Singapore" in results[0]["statement"]


@pytest.mark.evidence
def test_query_evidence_by_confidence(evidence_service):
    """Can query by minimum confidence level."""
    evidence_service.create_evidence(
        statement="Strong achievement",
        evidence_type="achievement",
        source_type="baseline_cv",
        source_reference="Test",
        confidence="LEVEL_A"
    )

    evidence_service.create_evidence(
        statement="General skill",
        evidence_type="skill",
        source_type="baseline_cv",
        source_reference="Test",
        confidence="LEVEL_C"
    )

    # Query for LEVEL_A or better
    results = evidence_service.query_evidence(min_confidence="LEVEL_A")
    assert len(results) == 1
    assert results[0]["confidence"] == "LEVEL_A"


@pytest.mark.evidence
def test_query_evidence_verification_required(evidence_service):
    """Can filter by verification status."""
    evidence_service.create_evidence(
        statement="Confirmed fact",
        evidence_type="achievement",
        source_type="baseline_cv",
        source_reference="Test",
        user_confirmed=True
    )

    evidence_service.create_evidence(
        statement="Unconfirmed fact",
        evidence_type="achievement",
        source_type="user_supplied",
        source_reference="Test",
        user_confirmed=False
    )

    # Query for confirmed only
    results = evidence_service.query_evidence(verification_required=True)
    assert len(results) == 1
    assert results[0]["user_confirmed"] == True


# ============================================================================
# PROVENANCE TESTS
# ============================================================================

@pytest.mark.evidence
def test_get_evidence_provenance(evidence_service):
    """Can retrieve full provenance chain."""
    evidence = evidence_service.create_evidence(
        statement="Growth achievement",
        evidence_type="achievement",
        source_type="baseline_cv",
        source_reference="DXC CV p1",
        confidence="LEVEL_A",
        verification_status="user_confirmed",
        user_confirmed=True,
        metrics={
            "revenue": {
                "amount": 5000000,
                "currency": "SGD",
                "verified_source": "baseline_cv"
            }
        }
    )

    provenance = evidence_service.get_evidence_provenance(evidence["evidence_id"])

    assert provenance is not None
    assert provenance["fact"]["statement"] == "Growth achievement"
    assert provenance["fact"]["source_type"] == "baseline_cv"
    assert provenance["verification"]["user_confirmed"] == True
    assert provenance["metrics"]["revenue"]["verified_source"] == "baseline_cv"


# ============================================================================
# VALIDATION TESTS
# ============================================================================

@pytest.mark.evidence
def test_validate_cv_fidelity_level_a(evidence_service):
    """LEVEL_A evidence can use strong language in CV."""
    cv_text = "Led enterprise transformation initiative"

    assert EvidenceValidator.validate_cv_evidence_fidelity(cv_text, "LEVEL_A") == True


@pytest.mark.evidence
def test_validate_cv_fidelity_level_c_must_qualify(evidence_service):
    """LEVEL_C evidence must qualify language in CV."""
    strong_cv = "Led enterprise initiative"
    qualified_cv = "Exposure to enterprise initiatives"

    assert EvidenceValidator.validate_cv_evidence_fidelity(strong_cv, "LEVEL_C") == False
    assert EvidenceValidator.validate_cv_evidence_fidelity(qualified_cv, "LEVEL_C") == True


@pytest.mark.evidence
def test_validate_cv_fidelity_level_d_never_valid(evidence_service):
    """LEVEL_D evidence can never be used in CV."""
    cv_text = "Any text here"

    assert EvidenceValidator.validate_cv_evidence_fidelity(cv_text, "LEVEL_D") == False


# ============================================================================
# INTEGRATION TESTS
# ============================================================================

@pytest.mark.e2e
def test_full_evidence_lifecycle(evidence_service):
    """Full evidence lifecycle: create → verify → query → supersede."""

    # 1. Create baseline evidence
    baseline = evidence_service.create_evidence(
        statement="Singapore market only",
        evidence_type="work_experience",
        source_type="baseline_cv",
        source_reference="DXC CV",
        confidence="LEVEL_A",
        user_confirmed=True,
        geographies=["Singapore"]
    )

    # 2. User supplies new information
    enriched = evidence_service.create_evidence(
        statement="Singapore and Malaysia markets",
        evidence_type="work_experience",
        source_type="user_supplied",
        source_reference="Gap interview",
        confidence="LEVEL_B",
        user_confirmed=True,
        geographies=["Singapore", "Malaysia"]
    )

    # 3. Contradiction detected
    contradictions = evidence_service.detect_contradictions(
        enriched["statement"],
        [baseline]
    )
    assert len(contradictions) > 0

    # 4. User resolves: use new
    evidence_service.resolve_contradiction(
        baseline["evidence_id"],
        enriched["evidence_id"],
        "use_new"
    )

    # 5. Query shows enriched version
    results = evidence_service.query_evidence(
        geographies=["Malaysia"]
    )
    assert len(results) == 1  # Enriched
    assert "Malaysia" in results[0]["statement"]

    # 6. Provenance shows history
    provenance = evidence_service.get_evidence_provenance(enriched["evidence_id"])
    assert provenance is not None
    assert provenance["fact"]["statement"] == "Singapore and Malaysia markets"


@pytest.mark.e2e
def test_cross_application_reuse(evidence_service):
    """Evidence from one app reused in another (via querying)."""

    # App 1: Gartner
    gartner_evidence = evidence_service.create_evidence(
        statement="Led public-sector AI automation pilot at GIC",
        evidence_type="achievement",
        source_type="user_supplied",
        source_reference="Gartner gap interview",
        confidence="LEVEL_B",
        user_confirmed=True,
        application_origin={
            "application_id": "app-gartner",
            "company": "Gartner"
        },
        competencies=["Public Sector", "AI"],
        geographies=["Singapore"]
    )

    # App 2: Salesforce
    # Query for public-sector evidence
    results = evidence_service.query_evidence(
        competencies=["Public Sector"]
    )

    # Should find Gartner's evidence
    assert len(results) == 1
    assert "GIC" in results[0]["statement"]
    assert results[0]["application_origin"]["company"] == "Gartner"


@pytest.mark.e2e
def test_factory_function(tmp_path):
    """Factory function creates working service."""
    service = create_evidence_service(str(tmp_path))

    evidence = service.create_evidence(
        statement="Test via factory",
        evidence_type="achievement",
        source_type="test",
        source_reference="Factory"
    )

    assert evidence is not None
    retrieved = service.get_evidence(evidence["evidence_id"])
    assert retrieved["statement"] == "Test via factory"
