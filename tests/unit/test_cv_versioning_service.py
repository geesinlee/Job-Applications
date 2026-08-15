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

# Import Mock for use in test decorators
from unittest.mock import Mock as MockObject


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


class TestGenerateDraftCV:
    """Tests for generate_draft_cv method."""

    def test_draft_generation_basic(self, cv_service, mock_requirement_service, mock_evidence_service):
        """Test basic draft generation returns CVDraft with properties."""
        # Setup mocks
        mock_requirement_service.extract_requirements.return_value = [
            Mock(id="req-1", text="Python expertise", confidence_threshold=0.7),
            Mock(id="req-2", text="AWS experience", confidence_threshold=0.7),
        ]
        mock_evidence_service.find_matching_evidence.side_effect = [
            [Mock(id="e-1", text="Python dev", similarity_score=0.9)],
            [Mock(id="e-2", text="AWS cert", similarity_score=0.85)],
        ]

        profile = {
            "work_experience": ["Senior Python Developer at TechCorp"],
            "skills": ["Python", "AWS", "Docker"],
            "education": ["BS Computer Science"],
        }
        jd_fields = {"required_skills": ["Python", "AWS"]}

        # Act
        draft = cv_service.generate_draft_cv("app-001", jd_fields, profile)

        # Assert
        assert isinstance(draft, CVDraft)
        assert draft.content is not None
        assert len(draft.content) > 0
        assert draft.requirements_covered == 2
        assert draft.requirements_partial == 0
        assert draft.requirements_missing == 0
        assert draft.coverage_percentage == 100.0
        assert len(draft.evidence_used) == 2

    def test_draft_includes_evidence_traceability(self, cv_service, mock_requirement_service, mock_evidence_service):
        """Test draft includes evidence traceability linking evidence to requirements."""
        # Setup mocks
        mock_requirement_service.extract_requirements.return_value = [
            Mock(id="req-1", text="Python expertise", confidence_threshold=0.7),
            Mock(id="req-2", text="Leadership", confidence_threshold=0.7),
        ]
        mock_evidence_service.find_matching_evidence.side_effect = [
            [Mock(id="e-1", text="Led Python team", similarity_score=0.95)],
            [],  # No match for leadership
        ]

        profile = {
            "work_experience": ["Tech Lead at StartupXYZ"],
            "skills": ["Python", "Leadership"],
            "education": [],
        }

        # Act
        draft = cv_service.generate_draft_cv("app-002", {}, profile)

        # Assert
        assert draft.requirements_covered == 1
        assert draft.requirements_partial == 0
        assert draft.requirements_missing == 1
        assert draft.coverage_percentage == 50.0
        assert len(draft.evidence_used) == 1
        assert draft.evidence_used[0].evidence_id == "e-1"
        assert draft.evidence_used[0].requirement_id == "req-1"


class TestDraftWorkflow:
    """Tests for draft creation, approval, and finalization workflow."""

    def test_create_draft_record(self, cv_service):
        """Test creating a draft CV record."""
        content = "# CV\n## Experience\nPython Developer"
        evidence = [CVEvidenceUsage(
            evidence_id="e-1",
            requirement_id="req-1",
            content_excerpt="Python",
            placement_section="experience"
        )]

        record = cv_service.create_draft_record("app-001", content, evidence)

        assert record.application_id == "app-001"
        assert record.content == content
        assert record.status == CVStatus.DRAFT
        assert record.version == "draft_1"
        assert len(record.evidence_used) == 1
        assert record.cv_id is not None
        assert record.created_at is not None
        assert record.approved_by is None
        assert record.approved_at is None

    def test_approve_draft(self, cv_service):
        """Test approving a draft CV."""
        record = cv_service.create_draft_record("app-001", "# CV", [])
        cv_id = record.cv_id

        approved = cv_service.approve_draft(cv_id, "user-001")

        assert approved.status == CVStatus.APPROVED
        assert approved.approved_by == "user-001"
        assert approved.approved_at is not None
        assert approved.cv_id == cv_id

    def test_finalize_cv(self, cv_service):
        """Test finalizing an approved CV."""
        record = cv_service.create_draft_record("app-001", "# CV", [])
        cv_service.approve_draft(record.cv_id, "user-001")

        finalized = cv_service.finalize_cv(record.cv_id)

        assert finalized.status == CVStatus.FINAL
        assert finalized.finalized_at is not None
        assert finalized.cv_id == record.cv_id

    def test_cannot_finalize_unapproved_draft(self, cv_service):
        """Test that finalizing unapproved draft raises error."""
        record = cv_service.create_draft_record("app-001", "# CV", [])

        with pytest.raises(ValueError, match="not approved"):
            cv_service.finalize_cv(record.cv_id)

    def test_get_cv_record(self, cv_service):
        """Test retrieving a CV record by ID."""
        record = cv_service.create_draft_record("app-001", "# CV", [])
        cv_id = record.cv_id

        retrieved = cv_service.get_cv_record(cv_id)

        assert retrieved is not None
        assert retrieved.cv_id == cv_id
        assert retrieved.application_id == "app-001"

    def test_get_cv_history(self, cv_service):
        """Test retrieving all CV versions for an application."""
        record1 = cv_service.create_draft_record("app-001", "# CV v1", [])
        record2 = cv_service.create_draft_record("app-001", "# CV v2", [])

        history = cv_service.get_cv_history("app-001")

        assert len(history) == 2
        assert history[0].cv_id == record1.cv_id
        assert history[1].cv_id == record2.cv_id
        assert history[0].version == "draft_1"
        assert history[1].version == "draft_2"


class TestIntegrationAndEdgeCases:
    """Integration and edge case tests for CVVersioningService."""

    def test_full_cv_lifecycle(self, cv_service, mock_requirement_service, mock_evidence_service):
        """Test complete CV lifecycle: generate → create → approve → finalize."""
        mock_requirement_service.extract_requirements.return_value = [
            Mock(id="req-1", text="Python", confidence_threshold=0.7),
        ]
        mock_evidence_service.find_matching_evidence.return_value = [
            Mock(id="e-1", text="Python dev", similarity_score=0.9),
        ]

        # Generate draft
        draft = cv_service.generate_draft_cv("app-001", {}, {
            "work_experience": ["Python Dev"],
            "skills": ["Python"],
            "education": []
        })
        assert draft.coverage_percentage == 100.0

        # Create record
        record = cv_service.create_draft_record("app-001", draft.content, draft.evidence_used)
        cv_id = record.cv_id
        assert record.status == CVStatus.DRAFT

        # Approve
        record = cv_service.approve_draft(cv_id, "user-001")
        assert record.status == CVStatus.APPROVED
        assert record.approved_by == "user-001"

        # Finalize
        record = cv_service.finalize_cv(cv_id)
        assert record.status == CVStatus.FINAL
        assert record.finalized_at is not None

        # Check history
        history = cv_service.get_cv_history("app-001")
        assert len(history) == 1
        assert history[0].cv_id == cv_id

    def test_multiple_draft_versions(self, cv_service):
        """Test creating multiple drafts with proper versioning."""
        record1 = cv_service.create_draft_record("app-001", "# CV v1", [])
        record2 = cv_service.create_draft_record("app-001", "# CV v2", [])
        record3 = cv_service.create_draft_record("app-001", "# CV v3", [])

        assert record1.version == "draft_1"
        assert record2.version == "draft_2"
        assert record3.version == "draft_3"

        history = cv_service.get_cv_history("app-001")
        assert len(history) == 3

    def test_evidence_traceability_preserved(self, cv_service):
        """Test evidence usage preserved through creation workflow."""
        evidence = [
            CVEvidenceUsage(
                evidence_id="e-1",
                requirement_id="req-1",
                content_excerpt="Python expert",
                placement_section="experience"
            ),
            CVEvidenceUsage(
                evidence_id="e-2",
                requirement_id="req-2",
                content_excerpt="AWS certified",
                placement_section="skills"
            ),
        ]

        record = cv_service.create_draft_record("app-001", "# CV", evidence)
        assert len(record.evidence_used) == 2
        assert record.evidence_used[0].evidence_id == "e-1"
        assert record.evidence_used[1].evidence_id == "e-2"

        retrieved = cv_service.get_cv_record(record.cv_id)
        assert len(retrieved.evidence_used) == 2

    def test_approve_nonexistent_cv(self, cv_service):
        """Test approving non-existent CV raises error."""
        with pytest.raises(ValueError, match="not found"):
            cv_service.approve_draft("nonexistent-cv", "user-001")

    def test_finalize_nonexistent_cv(self, cv_service):
        """Test finalizing non-existent CV raises error."""
        with pytest.raises(ValueError, match="not found"):
            cv_service.finalize_cv("nonexistent-cv")

    def test_approve_already_approved(self, cv_service):
        """Test approving already-approved CV raises error."""
        record = cv_service.create_draft_record("app-001", "# CV", [])
        cv_service.approve_draft(record.cv_id, "user-001")

        with pytest.raises(ValueError, match="draft status"):
            cv_service.approve_draft(record.cv_id, "user-002")

    def test_empty_evidence_list(self, cv_service):
        """Test creating record with empty evidence list."""
        record = cv_service.create_draft_record("app-001", "# CV", [])
        assert len(record.evidence_used) == 0
        assert record.status == CVStatus.DRAFT

        # Should be retrievable and updatable
        retrieved = cv_service.get_cv_record(record.cv_id)
        assert retrieved is not None


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
