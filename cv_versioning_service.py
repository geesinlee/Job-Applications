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
        requirements = self.requirement_service.extract_requirements(jd_fields)

        covered_count = 0
        partial_count = 0
        missing_count = 0
        evidence_used = []

        for requirement in requirements:
            matches = self.evidence_service.find_matching_evidence(requirement)

            if matches and matches[0].similarity_score >= requirement.confidence_threshold:
                covered_count += 1
                match = matches[0]
                evidence_used.append(CVEvidenceUsage(
                    evidence_id=match.id,
                    requirement_id=requirement.id,
                    content_excerpt=match.text,
                    placement_section="experience"
                ))
            elif matches:
                partial_count += 1
            else:
                missing_count += 1

        total_requirements = len(requirements) if requirements else 1
        coverage_percentage = (covered_count / total_requirements * 100) if total_requirements > 0 else 0

        content = self._build_cv_content(profile)

        return CVDraft(
            content=content,
            evidence_used=evidence_used,
            requirements_covered=covered_count,
            requirements_partial=partial_count,
            requirements_missing=missing_count,
            coverage_percentage=coverage_percentage
        )

    def _build_cv_content(self, profile: Dict) -> str:
        """Build CV content from profile sections."""
        lines = ["# CV\n"]

        if profile.get("work_experience"):
            lines.append("## Experience\n")
            for exp in profile["work_experience"]:
                lines.append(f"- {exp}\n")
            lines.append("")

        if profile.get("skills"):
            lines.append("## Skills\n")
            for skill in profile["skills"]:
                lines.append(f"- {skill}\n")
            lines.append("")

        if profile.get("education"):
            lines.append("## Education\n")
            for edu in profile["education"]:
                lines.append(f"- {edu}\n")

        return "".join(lines)

    def create_draft_record(self, application_id: str, content: str, evidence_used: List[CVEvidenceUsage]) -> CVRecord:
        """Create a draft CV record.

        Args:
            application_id: ID of the application.
            content: CV content (markdown).
            evidence_used: List of evidence usage references.

        Returns:
            CVRecord with status=draft.
        """
        draft_count = sum(
            1 for record in self.cv_records.values()
            if record.application_id == application_id and record.version.startswith("draft_")
        )
        version = f"draft_{draft_count + 1}"
        cv_id = str(uuid.uuid4())

        record = CVRecord(
            cv_id=cv_id,
            application_id=application_id,
            version=version,
            status=CVStatus.DRAFT,
            content=content,
            evidence_used=evidence_used,
        )
        self.cv_records[cv_id] = record
        return record

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
        record = self.cv_records.get(cv_id)
        if not record:
            raise ValueError(f"CV record {cv_id} not found")
        if record.status != CVStatus.DRAFT:
            raise ValueError(f"CV must be in draft status to approve, current status: {record.status.value}")

        record.status = CVStatus.APPROVED
        record.approved_by = approved_by
        record.approved_at = _utc_now()
        return record

    def finalize_cv(self, cv_id: str) -> CVRecord:
        """Mark an approved CV as final.

        Args:
            cv_id: ID of the CV record.

        Returns:
            CVRecord with status=final.

        Raises:
            ValueError: If CV is not approved.
        """
        record = self.cv_records.get(cv_id)
        if not record:
            raise ValueError(f"CV record {cv_id} not found")
        if record.status != CVStatus.APPROVED:
            raise ValueError(f"CV must be approved before finalizing; currently {record.status.value}, not approved")

        record.status = CVStatus.FINAL
        record.finalized_at = _utc_now()
        return record

    def get_cv_record(self, cv_id: str) -> Optional[CVRecord]:
        """Retrieve a CV record by ID.

        Args:
            cv_id: ID of the CV record.

        Returns:
            CVRecord if found, None otherwise.
        """
        return self.cv_records.get(cv_id)

    def get_cv_history(self, application_id: str) -> List[CVRecord]:
        """Get all CV versions for an application.

        Args:
            application_id: ID of the application.

        Returns:
            List of CVRecords (draft, approved, final) ordered by created_at.
        """
        records = [
            record for record in self.cv_records.values()
            if record.application_id == application_id
        ]
        records.sort(key=lambda r: r.created_at)
        return records
