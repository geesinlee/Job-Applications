"""
Data models for evidence extraction and CV assembly.

Dataclasses for:
- StructuredEvidence: extracted evidence from CV sections
- JDCriteria: job description analysis output
- RankedEvidence: evidence ranked against a JD
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class StructuredEvidence:
    """Represents a single extracted piece of evidence from a CV."""
    achievement: str
    context: str
    impact: str
    skills_demonstrated: list[str]
    job_title: str
    company_name: str
    source_section: str  # e.g., "Experience", "Projects", "Skills"
    source_cv_id: str
    time_period_start: Optional[datetime] = None
    time_period_end: Optional[datetime] = None
    id: Optional[str] = None  # Postgres ID when loaded from DB
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class JDCriteria:
    """Job description analysis output."""
    explicit_skills: list[str]
    inferred_skills: list[str]
    critical_criteria: list[str]
    nice_to_have_criteria: list[str] = field(default_factory=list)
    importance_ranking: dict[str, float] = field(default_factory=dict)  # skill/criterion -> importance (0-1)
    company_name: str = ""
    role_title: str = ""


@dataclass
class RankedEvidence:
    """Evidence ranked against a JD."""
    evidence: StructuredEvidence
    match_score: float  # 0-1 overall relevance to JD
    matched_skills: list[str] = field(default_factory=list)  # skills from JD found in this evidence
    matched_criteria: list[str] = field(default_factory=list)  # critical criteria matched
    suggested_rephrasing: Optional[str] = None


@dataclass(frozen=True)
class ApplicationScopedEvidence:
    """Evidence gathered during a specific job application workflow."""

    evidence_id: str  # Links to permanent StructuredEvidence.id in Postgres
    application_id: str
    source: str  # "user_input", "cv_section", "derived"
    question: Optional[str] = None  # The clarifying question asked (if user_input)
    response: Optional[str] = None  # User's response (if user_input)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    added_by_agent: bool = False  # True if agent discovered this, not user

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        return {
            "evidence_id": self.evidence_id,
            "application_id": self.application_id,
            "source": self.source,
            "question": self.question,
            "response": self.response,
            "timestamp": self.timestamp,
            "added_by_agent": self.added_by_agent,
        }
