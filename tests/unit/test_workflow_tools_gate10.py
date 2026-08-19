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


def test_generate_clarifying_questions_creates_varied_questions():
    """Test that generate_clarifying_questions creates diverse question types."""

    backend = MagicMock()
    tools = WorkflowTools(backend=backend)

    jd_analysis = {
        "explicit_skills": ["Python", "AWS"],
        "inferred_skills": ["Cloud Architecture"],
        "critical_criteria": ["5+ years"],
        "nice_to_have_criteria": ["Team leadership"],
        "importance_ranking": {"Python": 0.9, "AWS": 0.85}
    }

    identified_gaps = {
        "missing_skills": ["Kubernetes", "Docker"],
        "missing_criteria": ["Team leadership"],
        "coverage_percentage": 60.0
    }

    initial_matches = [
        {
            "evidence_id": "ev-001",
            "matched_skills": ["Python", "AWS"],
            "confidence_score": 0.85
        }
    ]

    result = tools.generate_clarifying_questions(
        application_id="test-app",
        jd_analysis=jd_analysis,
        identified_gaps=identified_gaps,
        initial_matches=initial_matches
    )

    assert result["application_id"] == "test-app"
    assert len(result["clarifying_questions"]) > 0
    assert len(result["clarifying_questions"]) <= 7

    # Check question structure
    for q in result["clarifying_questions"]:
        assert "question" in q
        assert "gap_type" in q
        assert "importance" in q
        assert q["gap_type"] in ["missing_skill", "missing_criteria", "adjacent_skill", "context"]
        assert "suggested_prompt" in q
        assert "expected_response_type" in q


def test_generate_clarifying_questions_high_coverage_strategy():
    """Test that high coverage adjusts questioning strategy."""

    backend = MagicMock()
    tools = WorkflowTools(backend=backend)

    jd_analysis = {
        "explicit_skills": ["Python", "AWS"],
        "inferred_skills": [],
        "critical_criteria": [],
        "nice_to_have_criteria": [],
        "importance_ranking": {}
    }

    identified_gaps = {
        "missing_skills": [],
        "missing_criteria": [],
        "coverage_percentage": 85.0  # High coverage
    }

    initial_matches = [
        {"evidence_id": f"ev-{i}", "matched_skills": ["Python"], "confidence_score": 0.8}
        for i in range(6)
    ]

    result = tools.generate_clarifying_questions(
        application_id="test-app-2",
        jd_analysis=jd_analysis,
        identified_gaps=identified_gaps,
        initial_matches=initial_matches
    )

    assert "Strong coverage" in result["strategy"]
    assert "deepen" in result["strategy"].lower()


def test_generate_clarifying_questions_moderate_coverage_strategy():
    """Test that moderate coverage adjusts questioning strategy."""

    backend = MagicMock()
    tools = WorkflowTools(backend=backend)

    jd_analysis = {
        "explicit_skills": ["Python", "AWS"],
        "inferred_skills": ["Kubernetes"],
        "critical_criteria": ["5+ years"],
        "nice_to_have_criteria": [],
        "importance_ranking": {"Python": 0.9}
    }

    identified_gaps = {
        "missing_skills": ["Kubernetes"],
        "missing_criteria": ["5+ years"],
        "coverage_percentage": 60.0  # Moderate coverage
    }

    initial_matches = [
        {"evidence_id": "ev-001", "matched_skills": ["Python"], "confidence_score": 0.8}
    ]

    result = tools.generate_clarifying_questions(
        application_id="test-app-3",
        jd_analysis=jd_analysis,
        identified_gaps=identified_gaps,
        initial_matches=initial_matches
    )

    assert "Moderate coverage" in result["strategy"]
    assert "fill critical gaps" in result["strategy"].lower()


def test_generate_clarifying_questions_low_coverage_strategy():
    """Test that low coverage adjusts questioning strategy."""

    backend = MagicMock()
    tools = WorkflowTools(backend=backend)

    jd_analysis = {
        "explicit_skills": ["Python", "AWS", "Kubernetes"],
        "inferred_skills": ["Cloud Architecture", "DevOps"],
        "critical_criteria": ["5+ years", "Team leadership"],
        "nice_to_have_criteria": [],
        "importance_ranking": {}
    }

    identified_gaps = {
        "missing_skills": ["AWS", "Kubernetes"],
        "missing_criteria": ["Team leadership"],
        "coverage_percentage": 20.0  # Low coverage
    }

    initial_matches = []  # No matches

    result = tools.generate_clarifying_questions(
        application_id="test-app-4",
        jd_analysis=jd_analysis,
        identified_gaps=identified_gaps,
        initial_matches=initial_matches
    )

    assert "Low coverage" in result["strategy"]
    assert "skill discovery" in result["strategy"].lower()


def test_generate_clarifying_questions_error_handling():
    """Test error handling in generate_clarifying_questions."""

    backend = MagicMock()
    tools = WorkflowTools(backend=backend)

    result = tools.generate_clarifying_questions(
        application_id="error-app",
        jd_analysis=None,  # Invalid: None instead of dict
        identified_gaps={},
        initial_matches=[]
    )

    assert "error" in result
    assert result["application_id"] == "error-app"


def test_generate_clarifying_questions_prioritizes_high_importance():
    """Test that high importance skills get asked first."""

    backend = MagicMock()
    tools = WorkflowTools(backend=backend)

    jd_analysis = {
        "explicit_skills": ["Python", "AWS"],
        "inferred_skills": [],
        "critical_criteria": [],
        "nice_to_have_criteria": [],
        "importance_ranking": {
            "Python": 0.95,  # Very high importance
            "Docker": 0.4    # Low importance
        }
    }

    identified_gaps = {
        "missing_skills": ["Python", "Docker"],
        "missing_criteria": [],
        "coverage_percentage": 50.0
    }

    initial_matches = []

    result = tools.generate_clarifying_questions(
        application_id="test-app-priority",
        jd_analysis=jd_analysis,
        identified_gaps=identified_gaps,
        initial_matches=initial_matches
    )

    questions = result["clarifying_questions"]

    # Find questions about Python and Docker
    python_questions = [q for q in questions if "Python" in q["question"]]
    docker_questions = [q for q in questions if "Docker" in q["question"]]

    # Python should have higher importance than Docker
    if python_questions and docker_questions:
        assert python_questions[0]["importance"] > docker_questions[0]["importance"]


def test_generate_clarifying_questions_empty_gaps():
    """Test generate_clarifying_questions with no gaps."""

    backend = MagicMock()
    tools = WorkflowTools(backend=backend)

    jd_analysis = {
        "explicit_skills": ["Python"],
        "inferred_skills": [],
        "critical_criteria": [],
        "nice_to_have_criteria": [],
        "importance_ranking": {}
    }

    identified_gaps = {
        "missing_skills": [],
        "missing_criteria": [],
        "coverage_percentage": 100.0
    }

    initial_matches = [
        {"evidence_id": "ev-001", "matched_skills": ["Python"], "confidence_score": 0.95}
    ]

    result = tools.generate_clarifying_questions(
        application_id="complete-match-app",
        jd_analysis=jd_analysis,
        identified_gaps=identified_gaps,
        initial_matches=initial_matches
    )

    # Should still generate depth questions even with no gaps
    assert len(result["clarifying_questions"]) > 0
    assert result["application_id"] == "complete-match-app"


# Tests for answer_clarifying_questions (Task 3c)

def test_answer_clarifying_questions_stores_evidence(mock_backend):
    """Test that answer_clarifying_questions stores evidence correctly."""

    mock_backend.save_application_evidence.return_value = "ev-new-001"

    tools = WorkflowTools(backend=mock_backend)

    result = tools.answer_clarifying_questions(
        application_id="test-app",
        question_index=0,
        answer="Led a team of 5 engineers building cloud infrastructure",
        confidence=0.85
    )

    assert result["application_id"] == "test-app"
    assert result["evidence_stored"] is True
    assert result["evidence_id"] == "ev-new-001"
    assert result["questions_answered"] == 1
    assert result["questions_remaining"] == 6

    # Verify backend was called
    mock_backend.save_application_evidence.assert_called_once()


def test_answer_clarifying_questions_skip(mock_backend):
    """Test that skip action doesn't store evidence."""

    tools = WorkflowTools(backend=mock_backend)

    result = tools.answer_clarifying_questions(
        application_id="test-app",
        question_index=1,
        answer="",
        skip=True
    )

    assert result["evidence_stored"] is False
    assert result["evidence_id"] is None
    assert "Skipped" in result["summary"]
    assert result["next_action"] == "ask_next_question"

    # Backend should NOT be called for skipped questions
    mock_backend.save_application_evidence.assert_not_called()


def test_answer_clarifying_questions_empty_answer(mock_backend):
    """Test that empty answer is rejected without storing."""

    tools = WorkflowTools(backend=mock_backend)

    result = tools.answer_clarifying_questions(
        application_id="test-app",
        question_index=0,
        answer="",
        confidence=0.5
    )

    assert result["evidence_stored"] is False
    assert result["evidence_id"] is None
    assert result["next_action"] == "ask_more_clarifications"
    assert "Please provide an answer" in result["summary"]
    mock_backend.save_application_evidence.assert_not_called()


def test_answer_clarifying_questions_whitespace_answer(mock_backend):
    """Test that whitespace-only answer is rejected."""

    tools = WorkflowTools(backend=mock_backend)

    result = tools.answer_clarifying_questions(
        application_id="test-app",
        question_index=0,
        answer="   \t\n  ",
        confidence=0.5
    )

    assert result["evidence_stored"] is False
    mock_backend.save_application_evidence.assert_not_called()


def test_answer_clarifying_questions_determines_next_action_substantial_answer(mock_backend):
    """Test next_action for substantial answer with high confidence."""

    mock_backend.save_application_evidence.return_value = "ev-new-002"

    tools = WorkflowTools(backend=mock_backend)

    result = tools.answer_clarifying_questions(
        application_id="test-app",
        question_index=2,
        answer="I spent 3 years building microservices with Python and Docker, leading a team of engineers",
        confidence=0.9
    )

    assert result["next_action"] == "ask_next_question"
    assert "Good answer" in result["summary"]


def test_answer_clarifying_questions_determines_next_action_low_confidence(mock_backend):
    """Test next_action for low confidence answer."""

    mock_backend.save_application_evidence.return_value = "ev-new-003"

    tools = WorkflowTools(backend=mock_backend)

    result = tools.answer_clarifying_questions(
        application_id="test-app",
        question_index=2,
        answer="maybe something with Python",
        confidence=0.3
    )

    assert result["next_action"] == "ask_more_clarifications"
    assert "Can you provide more" in result["summary"]


def test_answer_clarifying_questions_determines_next_action_brief_answer(mock_backend):
    """Test next_action for brief answer (<=20 chars)."""

    mock_backend.save_application_evidence.return_value = "ev-new-004"

    tools = WorkflowTools(backend=mock_backend)

    result = tools.answer_clarifying_questions(
        application_id="test-app",
        question_index=3,
        answer="Yes, I did that",  # 16 characters
        confidence=0.7
    )

    assert result["next_action"] == "ask_more_clarifications"


def test_answer_clarifying_questions_suggest_cv_generation_after_5_questions(mock_backend):
    """Test that after 5+ questions, suggest proceeding to CV generation."""

    mock_backend.save_application_evidence.return_value = "ev-new-005"

    tools = WorkflowTools(backend=mock_backend)

    result = tools.answer_clarifying_questions(
        application_id="test-app",
        question_index=5,  # 6th question (0-based)
        answer="Lots of relevant experience here with multiple projects",
        confidence=0.8
    )

    assert result["next_action"] == "proceed_to_cv_generation"
    assert "Ready to generate CV" in result["summary"]
    assert result["questions_answered"] == 6
    assert result["questions_remaining"] == 1


def test_answer_clarifying_questions_suggest_cv_generation_after_6_questions(mock_backend):
    """Test that after 6 questions, suggest proceeding to CV generation."""

    mock_backend.save_application_evidence.return_value = "ev-new-006"

    tools = WorkflowTools(backend=mock_backend)

    result = tools.answer_clarifying_questions(
        application_id="test-app",
        question_index=6,  # 7th question (0-based)
        answer="Another detailed response about experience",
        confidence=0.75
    )

    assert result["next_action"] == "proceed_to_cv_generation"
    assert result["questions_answered"] == 7
    assert result["questions_remaining"] == 0


def test_answer_clarifying_questions_error_handling(mock_backend):
    """Test error handling in answer_clarifying_questions."""

    mock_backend.save_application_evidence.side_effect = Exception("DB error")

    tools = WorkflowTools(backend=mock_backend)

    result = tools.answer_clarifying_questions(
        application_id="error-app",
        question_index=0,
        answer="test answer"
    )

    assert "error" in result
    assert result["application_id"] == "error-app"
    assert result["evidence_stored"] is False


def test_answer_clarifying_questions_default_confidence_is_none(mock_backend):
    """Test that when confidence is None (not provided), it's handled correctly."""

    mock_backend.save_application_evidence.return_value = "ev-new-007"

    tools = WorkflowTools(backend=mock_backend)

    result = tools.answer_clarifying_questions(
        application_id="test-app",
        question_index=1,
        answer="This is a substantial answer with good details about experience",
        confidence=None  # Not provided
    )

    assert result["evidence_stored"] is True
    assert result["next_action"] == "ask_next_question"
    assert "not specified" in result["summary"]


def test_answer_clarifying_questions_sequence(mock_backend):
    """Test a sequence of answers progressing toward CV generation."""

    mock_backend.save_application_evidence.side_effect = [
        "ev-q0-001", "ev-q1-002", "ev-q2-003", "ev-q3-004", "ev-q4-005", "ev-q5-006"
    ]

    tools = WorkflowTools(backend=mock_backend)

    # Question 0
    result0 = tools.answer_clarifying_questions(
        application_id="test-app",
        question_index=0,
        answer="Strong experience with cloud architecture and distributed systems",
        confidence=0.85
    )
    assert result0["next_action"] == "ask_next_question"
    assert result0["questions_answered"] == 1

    # Question 1
    result1 = tools.answer_clarifying_questions(
        application_id="test-app",
        question_index=1,
        answer="Led teams of 3-8 engineers on mission-critical projects",
        confidence=0.9
    )
    assert result1["next_action"] == "ask_next_question"
    assert result1["questions_answered"] == 2

    # Question 2
    result2 = tools.answer_clarifying_questions(
        application_id="test-app",
        question_index=2,
        answer="Implemented CI/CD pipelines reducing deployment time by 70%",
        confidence=0.88
    )
    assert result2["next_action"] == "ask_next_question"
    assert result2["questions_answered"] == 3

    # Question 3
    result3 = tools.answer_clarifying_questions(
        application_id="test-app",
        question_index=3,
        answer="Expertise in Python, Go, Kubernetes, and AWS services",
        confidence=0.92
    )
    assert result3["next_action"] == "ask_next_question"
    assert result3["questions_answered"] == 4

    # Question 4
    result4 = tools.answer_clarifying_questions(
        application_id="test-app",
        question_index=4,
        answer="Mentored junior engineers and conducted technical interviews for hiring",
        confidence=0.87
    )
    assert result4["next_action"] == "ask_next_question"
    assert result4["questions_answered"] == 5

    # Question 5 - should now suggest CV generation
    result5 = tools.answer_clarifying_questions(
        application_id="test-app",
        question_index=5,
        answer="Passionate about clean code, system design, and technical excellence",
        confidence=0.85
    )
    assert result5["next_action"] == "proceed_to_cv_generation"
    assert result5["questions_answered"] == 6


def test_answer_clarifying_questions_no_next_question_generated(mock_backend):
    """Test that next_question is None (stub implementation)."""

    mock_backend.save_application_evidence.return_value = "ev-new-008"

    tools = WorkflowTools(backend=mock_backend)

    result = tools.answer_clarifying_questions(
        application_id="test-app",
        question_index=0,
        answer="Detailed answer about experience with multiple technologies",
        confidence=0.85
    )

    # next_question should be None since _generate_next_question is a stub
    assert result["next_question"] is None


def test_answer_clarifying_questions_confidences_comparison(mock_backend):
    """Test that different confidence levels produce different summaries."""

    mock_backend.save_application_evidence.side_effect = ["ev1", "ev2", "ev3"]

    tools = WorkflowTools(backend=mock_backend)

    answer = "I have experience with Python and cloud technologies"

    # High confidence
    result_high = tools.answer_clarifying_questions(
        application_id="test-app",
        question_index=0,
        answer=answer,
        confidence=0.95
    )
    assert "high" in result_high["summary"]

    # Moderate confidence
    result_moderate = tools.answer_clarifying_questions(
        application_id="test-app",
        question_index=1,
        answer=answer,
        confidence=0.65
    )
    assert "moderate" in result_moderate["summary"]

    # Low confidence
    result_low = tools.answer_clarifying_questions(
        application_id="test-app",
        question_index=2,
        answer=answer,
        confidence=0.35
    )
    assert "low" in result_low["summary"]
