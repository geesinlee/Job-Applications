"""Unit tests for CVVersioningService."""
import pytest
from unittest.mock import Mock
from cv_versioning_service import (
    CVVersioningService,
    CVRecord,
    CVDraft,
    CVEvidenceUsage,
    CVStatus,
)


@pytest.fixture
def mock_requirement_service():
    """Mock RequirementService."""
    service = Mock()
    service.extract_requirements = Mock(return_value={"required_skills": ["Python", "AWS"]})
    service.match_evidence = Mock(return_value={"matches": []})
    return service


@pytest.fixture
def mock_evidence_service():
    """Mock EvidenceService."""
    service = Mock()
    service.get_evidence = Mock(return_value={"id": "e1", "text": "Experienced with Python"})
    service.find_matching_evidence = Mock(return_value=[])
    return service


@pytest.fixture
def cv_service(mock_requirement_service, mock_evidence_service):
    """Create a CVVersioningService with mocked dependencies."""
    return CVVersioningService(mock_requirement_service, mock_evidence_service)


@pytest.fixture
def sample_cv_record():
    """Create a sample CV record for testing."""
    return CVRecord(
        cv_id="cv-001",
        application_id="app-001",
        version="draft_1",
        status=CVStatus.DRAFT,
        content="# CV\n## Experience\nPython developer",
        evidence_used=[],
    )


@pytest.fixture
def sample_cv_draft():
    """Create a sample CV draft for testing."""
    return CVDraft(
        content="# CV\n## Experience\nPython developer",
        evidence_used=[],
        requirements_covered=2,
        requirements_partial=1,
        requirements_missing=0,
        coverage_percentage=75.0,
    )


class TestCVVersioningServiceInit:
    """Tests for CVVersioningService initialization."""

    def test_init_with_valid_services(self, mock_requirement_service, mock_evidence_service):
        """Test initialization with valid services."""
        service = CVVersioningService(mock_requirement_service, mock_evidence_service)
        assert service.requirement_service == mock_requirement_service
        assert service.evidence_service == mock_evidence_service
        assert service.cv_records == {}

    def test_init_with_none_requirement_service(self, mock_evidence_service):
        """Test initialization fails when requirement_service is None."""
        with pytest.raises(ValueError, match="requirement_service is required"):
            CVVersioningService(None, mock_evidence_service)

    def test_init_with_none_evidence_service(self, mock_requirement_service):
        """Test initialization fails when evidence_service is None."""
        with pytest.raises(ValueError, match="evidence_service is required"):
            CVVersioningService(mock_requirement_service, None)


class TestCVVersioningServiceMethods:
    """Tests for CVVersioningService method signatures."""

    def test_generate_draft_cv_raises_not_implemented(self, cv_service):
        """Test generate_draft_cv raises NotImplementedError."""
        with pytest.raises(NotImplementedError):
            cv_service.generate_draft_cv(
                application_id="app-001",
                jd_fields={"required_skills": ["Python"]},
                profile={"work_experience": []},
            )

    def test_create_draft_record_raises_not_implemented(self, cv_service):
        """Test create_draft_record raises NotImplementedError."""
        with pytest.raises(NotImplementedError):
            cv_service.create_draft_record(
                application_id="app-001",
                content="# CV",
                evidence_used=[],
            )

    def test_approve_draft_raises_not_implemented(self, cv_service):
        """Test approve_draft raises NotImplementedError."""
        with pytest.raises(NotImplementedError):
            cv_service.approve_draft(cv_id="cv-001", approved_by="user-001")

    def test_finalize_cv_raises_not_implemented(self, cv_service):
        """Test finalize_cv raises NotImplementedError."""
        with pytest.raises(NotImplementedError):
            cv_service.finalize_cv(cv_id="cv-001")

    def test_get_cv_record_raises_not_implemented(self, cv_service):
        """Test get_cv_record raises NotImplementedError."""
        with pytest.raises(NotImplementedError):
            cv_service.get_cv_record(cv_id="cv-001")

    def test_get_cv_history_raises_not_implemented(self, cv_service):
        """Test get_cv_history raises NotImplementedError."""
        with pytest.raises(NotImplementedError):
            cv_service.get_cv_history(application_id="app-001")
