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
