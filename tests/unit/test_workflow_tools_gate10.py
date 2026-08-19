"""Tests for Gate 10 workflow tools."""

import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch

from src.workflow_tools import WorkflowTools
from src.evidence_models import StructuredEvidence, JDCriteria, RankedEvidence


@pytest.fixture
def mock_backend():
    """Create a mock backend."""
    return MagicMock()


@pytest.fixture
def mock_orchestrator():
    """Create a mock orchestrator."""
    return MagicMock()


@pytest.fixture
def workflow_tools(mock_backend, mock_orchestrator):
    """Create WorkflowTools instance with mocks."""
    return WorkflowTools(backend=mock_backend, orchestrator=mock_orchestrator)


def test_start_job_application_workflow_initiates_workflow(workflow_tools, mock_backend):
    """Test that start_job_application_workflow analyzes JD and matches evidence."""

    # Mock evidence
    evidence = StructuredEvidence(
        achievement="Led team of 5 engineers on cloud migration project",
        context="At TechCorp, responsible for infrastructure modernization",
        impact="Reduced deployment time by 60%, improved reliability",
        skills_demonstrated=["Python", "AWS", "Leadership"],
        job_title="Senior Engineer",
        company_name="TechCorp",
        source_section="Experience",
        source_cv_id="cv-001",
        time_period_start=datetime(2023, 1, 1),
        time_period_end=datetime(2024, 6, 30),
        id="ev-001"
    )
    mock_backend.get_evidence_by_application.return_value = [evidence]

    result = workflow_tools.start_job_application_workflow(
        job_jd="Acme Corp is hiring for a Senior Software Engineer role. Required: Python, AWS, Leadership.",
        application_id="acme-001",
        user_name="Alice"
    )

    # Assertions
    assert result["application_id"] == "acme-001"
    assert "jd_analysis" in result
    assert isinstance(result["jd_analysis"]["explicit_skills"], list)
    assert len(result["jd_analysis"]["explicit_skills"]) > 0
    assert "identified_gaps" in result
    assert "clarifying_questions" in result
    assert isinstance(result["clarifying_questions"], list)
    assert len(result["clarifying_questions"]) > 0
    assert "next_steps" in result
    # Note: per spec, timestamp is only in error responses, not success responses
    assert "timestamp" not in result


def test_start_job_application_workflow_with_no_backend(workflow_tools):
    """Test workflow when backend is None."""
    tools = WorkflowTools(backend=None, orchestrator=None)

    jd = "Senior Engineer - Python/AWS at Acme Corp"
    result = tools.start_job_application_workflow(
        job_jd=jd,
        application_id="app-001",
        user_name="Bob"
    )

    assert result["application_id"] == "app-001"
    assert "jd_analysis" in result
    assert "identified_gaps" in result
    assert result["identified_gaps"]["coverage_percentage"] == 0.0  # No evidence


def test_start_job_application_workflow_handles_no_evidence(workflow_tools, mock_backend):
    """Test workflow when no evidence exists for application."""
    mock_backend.get_evidence_by_application.return_value = []

    result = workflow_tools.start_job_application_workflow(
        job_jd="Test JD",
        application_id="new-app-001",
        user_name="Charlie"
    )

    assert result["application_id"] == "new-app-001"
    assert result["identified_gaps"]["coverage_percentage"] == 0.0
    assert len(result["clarifying_questions"]) > 0


def test_start_job_application_workflow_error_handling(workflow_tools, mock_backend):
    """Test error handling when backend fails."""
    mock_backend.get_evidence_by_application.side_effect = Exception("DB error")

    result = workflow_tools.start_job_application_workflow(
        job_jd="Test JD",
        application_id="app-001",
        user_name="Diana"
    )

    assert "application_id" in result
    assert result["application_id"] == "app-001"
    # Should still return a valid result even with backend error
    assert "jd_analysis" in result
    assert "identified_gaps" in result


def test_extract_company_name():
    """Test company name extraction."""
    tools = WorkflowTools()

    # Test explicit pattern
    jd1 = "Company: Acme Corp\nJob Description..."
    assert "Acme" in tools._extract_company_name(jd1)

    # Test about pattern
    jd2 = "About Google\n\nGoogle is hiring..."
    assert "Google" in tools._extract_company_name(jd2)

    # Test fallback
    jd3 = "Some JD"
    result = tools._extract_company_name(jd3)
    assert isinstance(result, str) and len(result) > 0


def test_extract_role_title():
    """Test role title extraction."""
    tools = WorkflowTools()

    # Test explicit pattern
    jd1 = "Position: Senior Software Engineer\n\nDescription..."
    assert "Senior" in tools._extract_role_title(jd1)

    # Test role pattern
    jd2 = "Role: Backend Developer"
    assert "Backend" in tools._extract_role_title(jd2)

    # Test fallback
    jd3 = "Some JD"
    result = tools._extract_role_title(jd3)
    assert isinstance(result, str) and len(result) > 0


def test_skill_match():
    """Test skill matching logic."""
    tools = WorkflowTools()

    # Exact match
    assert tools._skill_match("Python", "Python")

    # Case insensitive
    assert tools._skill_match("python", "Python")

    # Partial match
    assert tools._skill_match("Python", "python programming")
    assert tools._skill_match("AWS", "amazon AWS")

    # No match
    assert not tools._skill_match("Python", "Java")


def test_generate_clarifying_questions(workflow_tools):
    """Test clarifying question generation."""
    jd_analysis = JDCriteria(
        explicit_skills=["Python", "AWS", "Docker"],
        inferred_skills=["Cloud Architecture"],
        critical_criteria=["5+ years experience", "Kubernetes"],
        importance_ranking={"Python": 0.9, "AWS": 0.85, "Docker": 0.7},
        company_name="Acme",
        role_title="Senior Engineer"
    )

    missing_skills = ["Docker", "Kubernetes"]
    matched = []

    questions = workflow_tools._generate_clarifying_questions(
        jd_analysis, missing_skills, matched, "Alice"
    )

    assert isinstance(questions, list)
    assert len(questions) > 0
    assert len(questions) <= 5
    # Should mention missing skills
    assert any("Docker" in q or "Kubernetes" in q for q in questions)


def test_determine_next_steps(workflow_tools):
    """Test next steps determination."""
    # High coverage
    result = workflow_tools._determine_next_steps(85.0, 5)
    assert "Ready to generate CV draft" in result

    # Medium coverage
    result = workflow_tools._determine_next_steps(60.0, 3)
    assert "Answer clarifying questions" in result

    # Low coverage
    result = workflow_tools._determine_next_steps(20.0, 1)
    assert "Low coverage" in result


def test_start_job_application_workflow_high_coverage(workflow_tools, mock_backend):
    """Test workflow with high evidence coverage."""
    # Create multiple matching evidence
    evidence_list = [
        StructuredEvidence(
            achievement="Built microservices in Python",
            context="At Company A",
            impact="Improved performance 10x",
            skills_demonstrated=["Python", "microservices"],
            job_title="Engineer",
            company_name="Company A",
            source_section="Experience",
            source_cv_id="cv-001",
            id="ev-001"
        ),
        StructuredEvidence(
            achievement="Deployed to AWS",
            context="At Company B",
            impact="Reduced costs 30%",
            skills_demonstrated=["AWS", "DevOps"],
            job_title="DevOps Engineer",
            company_name="Company B",
            source_section="Experience",
            source_cv_id="cv-001",
            id="ev-002"
        ),
    ]
    mock_backend.get_evidence_by_application.return_value = evidence_list

    result = workflow_tools.start_job_application_workflow(
        job_jd="Senior Engineer - Python/AWS required",
        application_id="high-coverage-app",
        user_name="Eve"
    )

    assert result["application_id"] == "high-coverage-app"
    assert len(result["initial_matches"]) > 0
    assert result["identified_gaps"]["coverage_percentage"] > 0


def test_start_job_application_workflow_full_flow(workflow_tools, mock_backend):
    """Test complete workflow flow with realistic data."""
    evidence = StructuredEvidence(
        achievement="Led architecture redesign",
        context="Modernized legacy system",
        impact="Reduced technical debt by 40%",
        skills_demonstrated=["System Design", "Python"],
        job_title="Senior Architect",
        company_name="OldTech",
        source_section="Experience",
        source_cv_id="cv-001",
        time_period_start=datetime(2022, 1, 1),
        time_period_end=datetime(2024, 8, 1),
        id="ev-arch-001"
    )
    mock_backend.get_evidence_by_application.return_value = [evidence]

    jd_text = """
    Position: Senior Software Engineer
    Company: NewTech Inc

    About NewTech:
    We're a cloud-first company building next-generation infrastructure.

    Requirements:
    - 5+ years in system design and architecture
    - Expert in Python and cloud technologies
    - Experience with microservices and Kubernetes
    - Strong leadership skills
    """

    result = workflow_tools.start_job_application_workflow(
        job_jd=jd_text,
        application_id="newtech-senior-eng",
        user_name="Frank"
    )

    # Verify structure
    assert result["application_id"] == "newtech-senior-eng"
    assert "jd_analysis" in result
    assert "initial_matches" in result
    assert "identified_gaps" in result
    assert "clarifying_questions" in result
    assert "next_steps" in result
    # Note: per spec, timestamp is only in error responses, not success responses
    assert "timestamp" not in result

    # Verify content
    jd = result["jd_analysis"]
    assert isinstance(jd["explicit_skills"], list)
    assert isinstance(jd["inferred_skills"], list)
    assert isinstance(jd["critical_criteria"], list)
    assert isinstance(jd["importance_ranking"], dict)

    gaps = result["identified_gaps"]
    assert isinstance(gaps["missing_skills"], list)
    assert isinstance(gaps["missing_criteria"], list)
    assert 0 <= gaps["coverage_percentage"] <= 100

    questions = result["clarifying_questions"]
    assert isinstance(questions, list)
    assert all(isinstance(q, str) for q in questions)
