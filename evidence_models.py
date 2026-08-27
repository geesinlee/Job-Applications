"""Evidence dataclasses for Gate 9 evidence extraction and CV assembly.

Defines in-memory models: StructuredEvidence, JDCriteria, RankedEvidence.
These are the core data structures for the evidence extraction and matching pipeline.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict


@dataclass
class StructuredEvidence:
    """Structured evidence extracted from ground-truth CV.

    Represents a single achievement/experience with quantified impact,
    demonstrated skills, and metadata (source CV, section, time period).

    Attributes:
        achievement: Brief description of what was accomplished.
        context: Broader context/role where achievement occurred.
        impact: Quantified or qualitative business/technical impact.
        skills_demonstrated: List of skills explicitly demonstrated.
        job_title: Job title during this achievement.
        company_name: Company/organization name.
        source_section: Section in source CV (e.g., "Experience", "Projects").
        source_cv_id: UUID of the source CVRecord.
        time_period_start: When the achievement started (optional).
        time_period_end: When the achievement ended (optional).
        id: Database ID (optional, set by backend on persistence).
    """
    achievement: str
    context: str
    impact: str
    skills_demonstrated: List[str]
    job_title: str
    company_name: str
    source_section: str
    source_cv_id: str
    time_period_start: Optional[datetime] = None
    time_period_end: Optional[datetime] = None
    id: Optional[str] = None


@dataclass
class JDCriteria:
    """Job description requirements extracted via LLM analysis.

    Represents the skill requirements, critical criteria, and importance
    ranking parsed from a job description.

    Attributes:
        explicit_skills: Skills explicitly mentioned in JD.
        inferred_skills: Skills inferred from role description.
        critical_criteria: Non-technical requirements (e.g., certifications, years of experience).
        importance_ranking: Dict mapping skill/criterion to importance score (0-1).
        company_name: Company hiring for this role.
        role_title: Job title/role being hired for.
    """
    explicit_skills: List[str]
    inferred_skills: List[str]
    critical_criteria: List[str]
    importance_ranking: Dict[str, float]
    company_name: str
    role_title: str


@dataclass
class RankedEvidence:
    """Evidence ranked and matched against a specific JD.

    Represents a piece of evidence with its match score against JD criteria,
    matched skills/criteria, and optional suggested rephrasing for the CV.

    Attributes:
        evidence: The StructuredEvidence being ranked.
        match_score: Numeric match score (0-1) against JD criteria.
        matched_skills: Skills from evidence that match JD requirements.
        matched_criteria: Criteria from JD that this evidence satisfies.
        suggested_rephrasing: Optional rephrased version tailored to JD language.
    """
    evidence: StructuredEvidence
    match_score: float
    matched_skills: List[str]
    matched_criteria: List[str]
    suggested_rephrasing: Optional[str] = None
