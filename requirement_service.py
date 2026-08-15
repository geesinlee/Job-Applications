from dataclasses import dataclass, field
from typing import List, Optional, Dict
from datetime import datetime


@dataclass
class Requirement:
    """Represents a single requirement extracted from JD."""
    requirement_id: str                    # Unique ID (UUID)
    statement: str                         # "5+ years enterprise sales"
    type: str                              # "competency" | "technology" | "geography" | "years_experience" | "seniority"
    source_jd_field: str                   # "required_skills" | "preferred_skills" | "years_of_experience"
    confidence: str                        # "LEVEL_A" | "LEVEL_B" (how confident JD is about requirement)
    confidence_threshold: float            # 0.0-1.0, similarity threshold for matching (LEVEL_A→0.8, LEVEL_B→0.7)
    quantified: Optional[Dict] = None      # {"years": 5} or {"percentage": 50}
    extracted_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class JobRequirements:
    """Collection of requirements extracted from a single JD."""
    jd_id: str
    company: str
    role_title: str
    requirements: List[Requirement] = field(default_factory=list)
    extracted_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class RequirementMatch:
    """Evidence that matches a requirement."""
    requirement_id: str
    evidence_id: str
    evidence_statement: str
    similarity_score: float                # 0.0-1.0
    match_type: str                        # "deterministic" | "semantic"
    evidence_confidence: str               # "LEVEL_A" | "LEVEL_B" | "LEVEL_C" | "LEVEL_D"
    matched_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class Gap:
    """Gap analysis result for a single requirement."""
    requirement_id: str
    requirement_statement: str
    type: str                              # Same as requirement.type
    status: str                            # "covered" | "partial" | "missing"
    matched_evidence: List[RequirementMatch] = field(default_factory=list)
    reasoning: str = ""
    analysed_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
