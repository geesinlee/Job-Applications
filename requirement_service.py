from dataclasses import dataclass, field
from typing import List, Optional, Dict
from datetime import datetime, timezone
from enum import Enum
import uuid


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
    INDUSTRY = "industry"


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


class RequirementService:
    """Service for extracting and matching job requirements against evidence."""

    def __init__(self, evidence_service):
        """Initialize with EvidenceService dependency.

        Args:
            evidence_service: EvidenceService instance for querying evidence.

        Raises:
            ValueError: If evidence_service is None.
        """
        if evidence_service is None:
            raise ValueError("evidence_service is required")
        self.evidence = evidence_service

    def extract_requirements(self, jd_fields: Dict) -> JobRequirements:
        """Extract structured requirements from JD fields.

        Args:
            jd_fields: Dict with keys like 'required_skills', 'preferred_skills',
                      'years_of_experience', 'industry', 'seniority_level'.

        Returns:
            JobRequirements object with list of Requirement objects.
        """
        requirements_list = []

        # Extract required_skills (LEVEL_A, threshold 0.8)
        for skill in jd_fields.get("required_skills", []):
            req = Requirement(
                requirement_id=str(uuid.uuid4()),
                statement=skill,
                type=RequirementType.COMPETENCY,
                source_jd_field="required_skills",
                confidence=ConfidenceLevel.LEVEL_A,
                confidence_threshold=0.8,
            )
            requirements_list.append(req)

        # Extract preferred_skills (LEVEL_B, threshold 0.7)
        for skill in jd_fields.get("preferred_skills", []):
            req = Requirement(
                requirement_id=str(uuid.uuid4()),
                statement=skill,
                type=RequirementType.COMPETENCY,
                source_jd_field="preferred_skills",
                confidence=ConfidenceLevel.LEVEL_B,
                confidence_threshold=0.7,
            )
            requirements_list.append(req)

        # Extract years_of_experience (LEVEL_A, quantified)
        years = jd_fields.get("years_of_experience")
        if years is not None:
            req = Requirement(
                requirement_id=str(uuid.uuid4()),
                statement=f"{years}+ years",
                type=RequirementType.YEARS_EXPERIENCE,
                source_jd_field="years_of_experience",
                confidence=ConfidenceLevel.LEVEL_A,
                confidence_threshold=0.8,
                quantified={"years": years},
            )
            requirements_list.append(req)

        # Extract industry (LEVEL_B, threshold 0.6)
        for industry in jd_fields.get("industry", []):
            req = Requirement(
                requirement_id=str(uuid.uuid4()),
                statement=industry,
                type=RequirementType.INDUSTRY,
                source_jd_field="industry",
                confidence=ConfidenceLevel.LEVEL_B,
                confidence_threshold=0.6,
            )
            requirements_list.append(req)

        # Extract seniority_level (LEVEL_A)
        seniority = jd_fields.get("seniority_level")
        if seniority is not None:
            req = Requirement(
                requirement_id=str(uuid.uuid4()),
                statement=seniority,
                type=RequirementType.SENIORITY,
                source_jd_field="seniority_level",
                confidence=ConfidenceLevel.LEVEL_A,
                confidence_threshold=0.8,
            )
            requirements_list.append(req)

        return JobRequirements(
            jd_id=str(uuid.uuid4()),
            company="",  # Will be set by caller
            role_title="",  # Will be set by caller
            requirements=requirements_list,
        )

    def match_requirement(self, requirement: Requirement) -> List[RequirementMatch]:
        """Find evidence matching a single requirement using semantic similarity.

        Calls evidence_service.query_evidence() with requirement statement.
        Uses Gate 4's semantic matching (deterministic + semantic word-overlap).

        Args:
            requirement: Requirement object to match.

        Returns:
            List of RequirementMatch objects (empty if no matches).
        """
        raise NotImplementedError()

    def identify_gaps(self, requirements: JobRequirements, evidence_matches: Dict) -> List[Gap]:
        """Classify requirement coverage based on evidence matches.

        For each requirement:
        - covered: matched_evidence count >= 1 AND max(similarity) >= requirement.confidence_threshold
        - partial: matched_evidence count >= 1 AND max(similarity) < requirement.confidence_threshold
        - missing: no matched evidence

        Args:
            requirements: JobRequirements object.
            evidence_matches: Dict mapping requirement_id → List[RequirementMatch].

        Returns:
            List of Gap objects with status and reasoning.
        """
        raise NotImplementedError()
