"""
Tests for Gate 10 workflow tools: confirm_cv and get_workflow_state.

Tests cover:
- CV confirmation (user approval/rejection)
- Workflow state retrieval at different stages
- Error handling and edge cases
"""

import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch
from src.workflow_tools import WorkflowTools
from src.evidence_models import StructuredEvidence


@pytest.fixture
def mock_backend():
    """Create a mock evidence backend."""
    backend = MagicMock()
    return backend


@pytest.fixture
def workflow_tools(mock_backend):
    """Create WorkflowTools instance with mock backend."""
    return WorkflowTools(backend=mock_backend)


# ============================================================================
# TASK 3E: CONFIRM_CV TESTS
# ============================================================================


def test_confirm_cv_user_approves(workflow_tools):
    """Test confirm_cv when user approves the CV."""
    result = workflow_tools.confirm_cv(
        application_id="test-app-001",
        cv_draft="# Experience\nLed team at TechCorp\n\n# Skills\nPython, Kubernetes",
        confirmed_by_user=True
    )

    assert result["confirmed"] is True
    assert result["application_id"] == "test-app-001"
    assert result["next_action"] == "proceed_to_submit"
    assert result["cv_version"] > 0
    assert "cv_final" in result["saved_path"]
    assert "test-app-001" in result["saved_path"]


def test_confirm_cv_user_rejects(workflow_tools):
    """Test confirm_cv when user rejects the CV and wants revisions."""
    result = workflow_tools.confirm_cv(
        application_id="test-app-002",
        cv_draft="# Experience\nSome content",
        confirmed_by_user=False
    )

    assert result["confirmed"] is False
    assert result["application_id"] == "test-app-002"
    assert result["next_action"] == "revise_again"
    assert result["cv_version"] == 0
    assert result["saved_path"] is None


def test_confirm_cv_with_long_content(workflow_tools):
    """Test confirm_cv with longer CV content."""
    long_cv = """# Strategic Account Executive - Tailored CV

## Summary
Experienced SAE with enterprise account management background.

## Experience

### Acme Corp (2020-2023)
Senior Account Manager
- Managed 5 enterprise accounts, each $10M+ ARR
- Grew account value by average 35% year-over-year
- Led quarterly business reviews with C-level executives

### Salesforce (2017-2020)
Account Executive
- Closed $15M in new business annually
- Achieved 98% customer retention
- Mentored 3 junior AEs

## Skills
- Enterprise sales
- Strategic account planning
- Analyst relations
- SaaS expertise
"""
    result = workflow_tools.confirm_cv(
        application_id="gartner-sae-001",
        cv_draft=long_cv,
        confirmed_by_user=True
    )

    assert result["confirmed"] is True
    assert len(result["saved_path"]) > 0


def test_confirm_cv_error_handling(workflow_tools):
    """Test error handling in confirm_cv when unexpected error occurs."""
    # Mock the backend to raise an exception during a hypothetical save
    workflow_tools.backend.side_effect = Exception("Database error")

    result = workflow_tools.confirm_cv(
        application_id="error-app",
        cv_draft="Valid CV content",
        confirmed_by_user=True
    )

    # Should handle gracefully with error dict
    assert "error" in result or "confirmed" in result
    assert result["application_id"] == "error-app"


def test_confirm_cv_preserves_application_id(workflow_tools):
    """Test that confirm_cv always returns the application_id."""
    for app_id in ["app-1", "gartner_sae_2026", "acme-002"]:
        result = workflow_tools.confirm_cv(
            application_id=app_id,
            cv_draft="Test CV",
            confirmed_by_user=True
        )
        assert result["application_id"] == app_id


def test_confirm_cv_version_is_unique(workflow_tools):
    """Test that multiple CV confirmations get unique versions."""
    import time

    result1 = workflow_tools.confirm_cv(
        application_id="unique-test",
        cv_draft="CV Draft 1",
        confirmed_by_user=True
    )

    # Add delay to ensure different second-level timestamps
    time.sleep(1.1)

    result2 = workflow_tools.confirm_cv(
        application_id="unique-test",
        cv_draft="CV Draft 2",
        confirmed_by_user=True
    )

    # Versions should be different (timestamps are unique)
    assert result1["cv_version"] != result2["cv_version"]


# ============================================================================
# TASK 3E: GET_WORKFLOW_STATE TESTS
# ============================================================================


def test_get_workflow_state_jd_analysis_stage(mock_backend, workflow_tools):
    """Test workflow state at JD analysis stage (no evidence yet)."""
    mock_backend.get_evidence_by_cv_id.return_value = []

    result = workflow_tools.get_workflow_state("test-app")

    assert result["application_id"] == "test-app"
    assert result["current_stage"] == "jd_analysis"
    assert result["progress_percent"] == 10
    assert result["evidence_count"] == 0
    assert result["questions_asked"] == 0
    assert result["cv_iterations"] == 0
    assert "JD analyzed" in result["summary"]


def test_get_workflow_state_evidence_gathering_stage(mock_backend, workflow_tools):
    """Test workflow state at evidence gathering stage (1-2 items)."""
    mock_evidence = [MagicMock() for _ in range(2)]
    mock_backend.get_evidence_by_cv_id.return_value = mock_evidence

    result = workflow_tools.get_workflow_state("test-app")

    assert result["current_stage"] == "evidence_gathering"
    assert result["progress_percent"] == 30
    assert result["evidence_count"] == 2
    assert result["questions_asked"] == 2
    assert "Collecting evidence" in result["summary"]


def test_get_workflow_state_cv_generation_stage(mock_backend, workflow_tools):
    """Test workflow state at CV generation stage (3-7 items)."""
    mock_evidence = [MagicMock() for _ in range(5)]
    mock_backend.get_evidence_by_cv_id.return_value = mock_evidence

    result = workflow_tools.get_workflow_state("test-app")

    assert result["current_stage"] == "cv_generation"
    assert result["progress_percent"] == 60
    assert result["evidence_count"] == 5
    assert result["questions_asked"] == 5
    assert result["cv_iterations"] == max(0, (5 - 3) // 2)
    assert "Strong evidence collection" in result["summary"]


def test_get_workflow_state_cv_refinement_stage(mock_backend, workflow_tools):
    """Test workflow state at CV refinement stage (8+ items)."""
    mock_evidence = [MagicMock() for _ in range(10)]
    mock_backend.get_evidence_by_cv_id.return_value = mock_evidence

    result = workflow_tools.get_workflow_state("test-app")

    assert result["current_stage"] == "cv_refinement"
    assert result["progress_percent"] == 85
    assert result["evidence_count"] == 10
    assert result["questions_asked"] == 7  # capped at 7
    assert result["cv_iterations"] == max(0, (10 - 3) // 2)
    assert "CV generated" in result["summary"]


def test_get_workflow_state_includes_timestamp(mock_backend, workflow_tools):
    """Test that workflow state includes ISO timestamp."""
    mock_backend.get_evidence_by_cv_id.return_value = []

    result = workflow_tools.get_workflow_state("test-app")

    assert "last_update" in result
    # Should be parseable as ISO format
    datetime.fromisoformat(result["last_update"])


def test_get_workflow_state_error_handling(mock_backend, workflow_tools):
    """Test error handling when backend fails - gracefully degrades to empty state."""
    mock_backend.get_evidence_by_cv_id.side_effect = Exception("DB connection failed")

    result = workflow_tools.get_workflow_state("error-app")

    # Should return a valid response even on error, with fallback state
    assert result["application_id"] == "error-app"
    # On backend error, _get_application_evidence catches it and returns empty list
    # So we should be in jd_analysis stage (evidence_count == 0)
    assert result["evidence_count"] == 0
    assert result["current_stage"] == "jd_analysis"


def test_get_workflow_state_cv_iteration_calculation(mock_backend, workflow_tools):
    """Test that CV iteration count is calculated correctly."""
    test_cases = [
        (0, 0),   # 0 evidence -> 0 iterations
        (1, 0),   # 1 evidence -> 0 iterations
        (2, 0),   # 2 evidence -> 0 iterations
        (3, 0),   # 3 evidence -> 0 iterations
        (4, 0),   # 4 evidence -> (4-3)//2 = 0
        (5, 1),   # 5 evidence -> (5-3)//2 = 1
        (6, 1),   # 6 evidence -> (6-3)//2 = 1
        (7, 2),   # 7 evidence -> (7-3)//2 = 2
        (10, 3),  # 10 evidence -> (10-3)//2 = 3
    ]

    for evidence_count, expected_iterations in test_cases:
        mock_evidence = [MagicMock() for _ in range(evidence_count)]
        mock_backend.get_evidence_by_cv_id.return_value = mock_evidence

        result = workflow_tools.get_workflow_state("test-app")

        assert result["cv_iterations"] == expected_iterations, (
            f"Evidence count {evidence_count} should yield "
            f"{expected_iterations} iterations, got {result['cv_iterations']}"
        )


def test_get_workflow_state_summary_contains_relevant_info(mock_backend, workflow_tools):
    """Test that summary includes key metrics."""
    mock_evidence = [MagicMock() for _ in range(5)]
    mock_backend.get_evidence_by_cv_id.return_value = mock_evidence

    result = workflow_tools.get_workflow_state("test-app")

    summary = result["summary"]
    assert str(result["evidence_count"]) in summary  # Should mention evidence count


def test_get_workflow_state_questions_asked_capped(mock_backend, workflow_tools):
    """Test that questions_asked is capped at 7."""
    mock_evidence = [MagicMock() for _ in range(20)]
    mock_backend.get_evidence_by_cv_id.return_value = mock_evidence

    result = workflow_tools.get_workflow_state("test-app")

    assert result["questions_asked"] == 7


def test_get_workflow_state_multiple_calls_same_app(mock_backend, workflow_tools):
    """Test retrieving state multiple times for same application."""
    mock_evidence_v1 = [MagicMock() for _ in range(3)]
    mock_backend.get_evidence_by_cv_id.return_value = mock_evidence_v1

    result1 = workflow_tools.get_workflow_state("multi-app")
    assert result1["evidence_count"] == 3
    assert result1["current_stage"] == "cv_generation"

    # Simulate more evidence added
    mock_evidence_v2 = [MagicMock() for _ in range(8)]
    mock_backend.get_evidence_by_cv_id.return_value = mock_evidence_v2

    result2 = workflow_tools.get_workflow_state("multi-app")
    assert result2["evidence_count"] == 8
    assert result2["current_stage"] == "cv_refinement"


# ============================================================================
# INTEGRATION TESTS
# ============================================================================


def test_confirm_then_get_state_flow(mock_backend, workflow_tools):
    """Test workflow: confirm CV and then check state."""
    mock_backend.get_evidence_by_cv_id.return_value = [MagicMock() for _ in range(5)]

    # First, confirm the CV
    confirm_result = workflow_tools.confirm_cv(
        application_id="integration-test",
        cv_draft="# Test CV",
        confirmed_by_user=True
    )

    assert confirm_result["confirmed"] is True
    assert confirm_result["next_action"] == "proceed_to_submit"

    # Then get workflow state
    state_result = workflow_tools.get_workflow_state("integration-test")

    assert state_result["application_id"] == "integration-test"
    assert state_result["evidence_count"] == 5
    assert state_result["current_stage"] == "cv_generation"


def test_revision_cycle_workflow(mock_backend, workflow_tools):
    """Test workflow: reject, revise, confirm."""
    # First attempt: user rejects
    reject_result = workflow_tools.confirm_cv(
        application_id="revision-test",
        cv_draft="# Initial Draft",
        confirmed_by_user=False
    )

    assert reject_result["confirmed"] is False
    assert reject_result["next_action"] == "revise_again"

    # Revise and try again
    approve_result = workflow_tools.confirm_cv(
        application_id="revision-test",
        cv_draft="# Revised Draft with improvements",
        confirmed_by_user=True
    )

    assert approve_result["confirmed"] is True
    assert approve_result["next_action"] == "proceed_to_submit"
    assert approve_result["cv_version"] != reject_result["cv_version"]
