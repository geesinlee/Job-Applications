from dataclasses import dataclass, field
from typing import List, Optional, Dict
from datetime import datetime, timezone
from enum import Enum


def _utc_now() -> str:
    """Return current UTC time in ISO 8601 format with Z suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class RequirementType(str, Enum):
    """Types of requirements extracted from job descriptions."""
    COMPETENCY = "competency"
    TECHNOLOGY = "technology"
    GEOGRAPHY = "geography"
    YEARS_EXPERIENCE = "years_experience"
    SENIORITY = "seniority"


class ConfidenceLevel(str, Enum):
    """Confidence levels for JD requirement extraction."""
    LEVEL_A = "LEVEL_A"
    LEVEL_B = "LEVEL_B"


class EvidenceConfidence(str, Enum):
    """Confidence levels for evidence quality."""
    LEVEL_A = "LEVEL_A"
    LEVEL_B = "LEVEL_B"
    LEVEL_C = "LEVEL_C"
    LEVEL_D = "LEVEL_D"


class MatchType(str, Enum):
    """Types of requirement matching strategies."""
    DETERMINISTIC = "deterministic"
    SEMANTIC = "semantic"


class GapStatus(str, Enum):
    """Status of requirement coverage."""
    COVERED = "covered"
    PARTIAL = "partial"
    MISSING = "missing"


@dataclass
class Requirement:
    """Represents a single requirement extracted from a job description.

    Fields:
        requirement_id: Unique identifier (UUID) for this requirement
        statement: Plain-text requirement statement (e.g., "5+ years enterprise sales")
        type: Category of requirement (competency, technology, geography, etc.)
        source_jd_field: Which JD field this came from (required_skills, preferred_skills, etc.)
        confidence: How confident the JD is about this requirement (LEVEL_A or LEVEL_B)
        confidence_threshold: Similarity threshold for matching (LEVEL_A→0.8, LEVEL_B→0.7)
        quantified: Optional numeric values if requirement is quantifiable ({"years": 5} or {"percentage": 50})
        extracted_at: ISO 8601 timestamp when requirement was extracted
    """
    requirement_id: str                    # Unique ID (UUID)
    statement: str                         # "5+ years enterprise sales"
    type: RequirementType                  # Requirement category
    source_jd_field: str                   # "required_skills" | "preferred_skills" | "years_of_experience"
    confidence: ConfidenceLevel            # How confident JD is about requirement
    confidence_threshold: float            # 0.0-1.0, similarity threshold for matching (LEVEL_A→0.8, LEVEL_B→0.7)
    quantified: Optional[Dict[str, int | float]] = None      # {"years": 5} or {"percentage": 50}
    extracted_at: str = field(default_factory=_utc_now)


@dataclass
class JobRequirements:
    """Collection of requirements extracted from a single job description.

    Fields:
        jd_id: Unique identifier for the job description
        company: Company name that posted the job
        role_title: Job title/role being advertised
        requirements: List of individual requirements extracted from JD
        extracted_at: ISO 8601 timestamp when requirements were extracted
    """
    jd_id: str                             # Unique identifier for the job description
    company: str                           # Company name
    role_title: str                        # Job title/role
    requirements: List[Requirement] = field(default_factory=list)  # Individual requirements
    extracted_at: str = field(default_factory=_utc_now)


@dataclass
class RequirementMatch:
    """Evidence that matches a requirement from a career record.

    Fields:
        requirement_id: ID of the requirement being matched
        evidence_id: Unique identifier for the evidence/career record
        evidence_statement: Plain-text evidence statement from career history
        similarity_score: Semantic similarity score (0.0-1.0) between requirement and evidence
        match_type: How the match was determined (deterministic vs. semantic)
        evidence_confidence: Quality/reliability level of the evidence (LEVEL_A through LEVEL_D)
        matched_at: ISO 8601 timestamp when match was created
    """
    requirement_id: str                    # ID of matched requirement
    evidence_id: str                       # ID of the evidence/career record
    evidence_statement: str                # Plain-text evidence from career history
    similarity_score: float                # 0.0-1.0 semantic similarity
    match_type: MatchType                  # Matching strategy (deterministic or semantic)
    evidence_confidence: EvidenceConfidence  # Quality level of the evidence
    matched_at: str = field(default_factory=_utc_now)


@dataclass
class Gap:
    """Gap analysis result for a single requirement.

    Fields:
        requirement_id: ID of the requirement being analyzed
        requirement_statement: Plain-text requirement statement
        type: Requirement type (matches requirement.type enum)
        status: Coverage status: covered (fully matched), partial (some matches), or missing (no matches)
        matched_evidence: List of RequirementMatch objects that satisfy this requirement
        reasoning: Explanation of the gap analysis result
        analyzed_at: ISO 8601 timestamp when gap analysis was performed
    """
    requirement_id: str                    # ID of the requirement
    requirement_statement: str             # Requirement text being analyzed
    type: RequirementType                  # Requirement type
    status: GapStatus                      # Coverage status
    matched_evidence: List[RequirementMatch] = field(default_factory=list)  # Matching evidence
    reasoning: str = ""                    # Explanation of the gap analysis
    analyzed_at: str = field(default_factory=_utc_now)
