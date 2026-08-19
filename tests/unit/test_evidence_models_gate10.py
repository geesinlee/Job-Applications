"""Tests for Gate 10 evidence models."""

from src.evidence_models import ApplicationScopedEvidence


def test_application_scoped_evidence_creation():
    """Test creating an ApplicationScopedEvidence entry."""
    evidence = ApplicationScopedEvidence(
        evidence_id="ev_12345",
        application_id="gartner_sae_2026",
        source="user_input",
        question="Do you have enterprise account experience?",
        response="Yes, I managed 5 enterprise accounts at Acme.",
    )

    assert evidence.evidence_id == "ev_12345"
    assert evidence.application_id == "gartner_sae_2026"
    assert evidence.source == "user_input"
    assert evidence.question == "Do you have enterprise account experience?"
    assert evidence.response == "Yes, I managed 5 enterprise accounts at Acme."
    assert evidence.timestamp is not None
    assert evidence.added_by_agent is False


def test_application_scoped_evidence_to_dict():
    """Test converting to dict for JSON serialization."""
    evidence = ApplicationScopedEvidence(
        evidence_id="ev_12345",
        application_id="gartner_sae_2026",
        source="user_input",
        question="Enterprise experience?",
        response="Yes.",
    )

    d = evidence.to_dict()
    assert isinstance(d, dict)
    assert d["evidence_id"] == "ev_12345"
    assert d["application_id"] == "gartner_sae_2026"
    assert "timestamp" in d
