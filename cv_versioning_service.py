from dataclasses import dataclass, field
from typing import List, Optional, Dict
from datetime import datetime, timezone
from enum import Enum
import uuid


def _utc_now() -> str:
    """Return current UTC time in ISO 8601 format with Z suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class CVStatus(str, Enum):
    """Status of a CV record."""
    DRAFT = "draft"
    APPROVED = "approved"
    FINAL = "final"


@dataclass
class CVEvidenceUsage:
    """Link between CV content and evidence used."""
    evidence_id: str                   # ID of evidence used
    requirement_id: str                # Requirement this evidence satisfies
    content_excerpt: str               # CV text that uses this evidence
    placement_section: str             # CV section (experience, skills, etc.)


@dataclass
class CVRecord:
    """Represents a single version of a CV."""
    cv_id: str                         # Unique ID (UUID)
    application_id: str                # Application this CV is for
    version: str                       # "draft_1", "draft_2", "final"
    status: CVStatus                   # draft | approved | final
    content: str                       # CV markdown/text content
    evidence_used: List[CVEvidenceUsage] = field(default_factory=list)  # Traceability
    created_at: str = field(default_factory=_utc_now)
    approved_by: Optional[str] = None  # Claude / user who approved
    approved_at: Optional[str] = None  # Timestamp of approval
    finalized_at: Optional[str] = None  # Timestamp when marked final


@dataclass
class CVDraft:
    """Draft CV with coverage information."""
    content: str                       # Generated CV content
    evidence_used: List[CVEvidenceUsage]  # Evidence references
    requirements_covered: int          # Count of fully covered requirements
    requirements_partial: int          # Count of partially covered requirements
    requirements_missing: int          # Count of missing requirements
    coverage_percentage: float         # (covered / total) * 100


# Import service dependencies (assuming they exist in the same directory)
try:
    from requirement_service import RequirementService
except ImportError:
    RequirementService = None  # Will be provided at runtime

try:
    from evidence_service import EvidenceService
except ImportError:
    EvidenceService = None  # Will be provided at runtime


class CVVersioningService:
    """Service for generating and versioning CVs backed by evidence."""

    def __init__(self, requirement_service: "RequirementService", evidence_service: "EvidenceService"):
        """Initialize with dependencies.

        Args:
            requirement_service: RequirementService for requirement extraction and matching.
            evidence_service: EvidenceService for evidence queries.

        Raises:
            ValueError: If either service is None.
        """
        if requirement_service is None:
            raise ValueError("requirement_service is required")
        if evidence_service is None:
            raise ValueError("evidence_service is required")
        self.requirement_service = requirement_service
        self.evidence_service = evidence_service
        self.cv_records: Dict[str, CVRecord] = {}  # In-memory store (will use persistence in Gate 7)

    def generate_draft_cv(self, application_id: str, jd_fields: Dict, profile: Dict) -> CVDraft:
        """Generate a draft CV by matching evidence to JD requirements.

        Args:
            application_id: ID of the application.
            jd_fields: Extracted JD fields (required_skills, industry, etc.).
            profile: Candidate profile with work_experience, skills, education.

        Returns:
            CVDraft with generated content and traceability.
        """
        raise NotImplementedError()

    def create_draft_record(self, application_id: str, content: str, evidence_used: List[CVEvidenceUsage]) -> CVRecord:
        """Create a draft CV record.

        Args:
            application_id: ID of the application.
            content: CV content (markdown).
            evidence_used: List of evidence usage references.

        Returns:
            CVRecord with status=draft.
        """
        raise NotImplementedError()

    def approve_draft(self, cv_id: str, approved_by: str) -> CVRecord:
        """Mark a draft as approved, enabling finalization.

        Args:
            cv_id: ID of the CV record.
            approved_by: User/Claude identifier approving the CV.

        Returns:
            CVRecord with status=approved.

        Raises:
            ValueError: If CV is not in draft status.
        """
        raise NotImplementedError()

    def finalize_cv(self, cv_id: str) -> CVRecord:
        """Mark an approved CV as final.

        Args:
            cv_id: ID of the CV record.

        Returns:
            CVRecord with status=final.

        Raises:
            ValueError: If CV is not approved.
        """
        raise NotImplementedError()

    def get_cv_record(self, cv_id: str) -> Optional[CVRecord]:
        """Retrieve a CV record by ID.

        Args:
            cv_id: ID of the CV record.

        Returns:
            CVRecord if found, None otherwise.
        """
        raise NotImplementedError()

    def get_cv_history(self, application_id: str) -> List[CVRecord]:
        """Get all CV versions for an application.

        Args:
            application_id: ID of the application.

        Returns:
            List of CVRecords (draft, approved, final) ordered by created_at.
        """
        raise NotImplementedError()
