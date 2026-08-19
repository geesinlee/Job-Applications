"""
Evidence extraction and CV generation service layer.

Implements LLM-driven components and orchestration services for evidence extraction
from ground-truth CVs and intelligent CV assembly via JD matching.

Components:
- EvidenceExtractor: Extract structured evidence from CV sections using LLM
- JDAnalyzer: Analyze job descriptions and extract criteria using LLM
- EvidenceMatcher: Match evidence against JD criteria
- CVAssembler: Assemble tailored CV from matched evidence

Orchestration:
- EvidenceExtractionService: Bootstrap workflow (extract all CV sections)
- CVGenerationService: Per-JD workflow (analyze JD, match, assemble)
"""

import json
import logging
import os
from datetime import datetime
from typing import Dict, List, Optional

try:
    import anthropic
except ImportError:
    anthropic = None

from src.evidence_models import StructuredEvidence, JDCriteria, RankedEvidence

logger = logging.getLogger(__name__)


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================


def _parse_json_response(response_text: str):
    """Parse JSON from LLM response, handling markdown code fences."""
    text = response_text.strip()

    # Remove markdown code fences if present
    if text.startswith("```"):
        # Extract content between ``` markers
        lines = text.split("\n")
        if lines[0].startswith("```"):
            # Remove first line (opening ```)
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            # Remove last line (closing ```)
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    return json.loads(text)


# ============================================================================
# Task 4: EVIDENCE EXTRACTOR
# ============================================================================


class EvidenceExtractor:
    """Extracts structured evidence from CV sections using LLM."""

    def __init__(self, model: str = None):
        """Initialize with LLM model."""
        if model is None:
            self.model = os.getenv("EVIDENCE_LLM_MODEL", "claude-haiku-4-5-20251001")
        else:
            self.model = model
        if anthropic:
            self.client = anthropic.Anthropic()
        else:
            self.client = None
            logger.warning("anthropic not installed; will use mock extraction")

    def extract(
        self,
        cv_text: str,
        cv_id: str,
        section: str,
        job_title: Optional[str] = None,
        company_name: Optional[str] = None,
        time_period_start: Optional[datetime] = None,
        time_period_end: Optional[datetime] = None,
    ) -> List[StructuredEvidence]:
        """
        Extract structured evidence from CV text.

        Returns a list of StructuredEvidence objects, one per distinct achievement/project.
        """

        if not self.client:
            # Mock mode: return simple extraction
            return self._mock_extract(
                cv_text, cv_id, section, job_title, company_name, time_period_start, time_period_end
            )

        prompt = f"""
You are an expert at parsing resumes/CVs and extracting evidence of achievements.

Given the following CV section text, extract 3-5 distinct, concrete achievements or projects.

For each achievement, structure it as JSON with:
- "achievement": brief, specific statement of what was accomplished (e.g., "Led migration from monolith to microservices")
- "context": the business/technical context or environment
- "impact": quantified or specific outcome (e.g., "reduced latency by 40%")
- "skills_demonstrated": list of relevant technical/soft skills inferred from the achievement

CV Section ({section}):
{cv_text}

Return a JSON array of objects, e.g.:
[
  {{
    "achievement": "...",
    "context": "...",
    "impact": "...",
    "skills_demonstrated": ["skill1", "skill2", ...]
  }},
  ...
]

Return ONLY the JSON array, no other text.
"""

        try:
            response = self.client.messages.create(
                model=self.model, max_tokens=2000, messages=[{"role": "user", "content": prompt}]
            )

            response_text = response.content[0].text

            # Parse JSON response
            try:
                extracted_list = _parse_json_response(response_text)
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(f"Could not parse LLM response: {response_text} ({e})")
                return []

            # Convert to StructuredEvidence objects
            evidence_objects = []
            for item in extracted_list:
                evidence = StructuredEvidence(
                    achievement=item.get("achievement", ""),
                    context=item.get("context", ""),
                    impact=item.get("impact", ""),
                    skills_demonstrated=item.get("skills_demonstrated", []),
                    job_title=job_title or "",
                    company_name=company_name or "",
                    time_period_start=time_period_start,
                    time_period_end=time_period_end,
                    source_section=section,
                    source_cv_id=cv_id,
                )
                evidence_objects.append(evidence)

            return evidence_objects
        except Exception as e:
            logger.error(f"Error extracting evidence: {e}")
            return []

    def _mock_extract(
        self,
        cv_text: str,
        cv_id: str,
        section: str,
        job_title: Optional[str],
        company_name: Optional[str],
        time_period_start: Optional[datetime],
        time_period_end: Optional[datetime],
    ) -> List[StructuredEvidence]:
        """Mock extraction when LLM is not available."""
        # Simple heuristic: split by bullet points and create evidence
        lines = [l.strip() for l in cv_text.split("\n") if l.strip()]
        evidence_list = []

        for i, line in enumerate(lines[:3]):  # Extract up to 3 items
            if line:
                evidence = StructuredEvidence(
                    achievement=line[:100],
                    context=cv_text[:50],
                    impact="Improved efficiency",
                    skills_demonstrated=["Python", "System Design"],
                    job_title=job_title or "",
                    company_name=company_name or "",
                    time_period_start=time_period_start,
                    time_period_end=time_period_end,
                    source_section=section,
                    source_cv_id=cv_id,
                )
                evidence_list.append(evidence)

        return evidence_list


# ============================================================================
# Task 5: JD ANALYZER
# ============================================================================


class JDAnalyzer:
    """Analyzes job descriptions and extracts criteria using LLM."""

    def __init__(self, model: str = None):
        """Initialize with LLM model."""
        if model is None:
            self.model = os.getenv("JD_ANALYZER_LLM_MODEL", "claude-haiku-4-5-20251001")
        else:
            self.model = model
        if anthropic:
            self.client = anthropic.Anthropic()
        else:
            self.client = None
            logger.warning("anthropic not installed; will use mock analysis")

    def analyze(
        self, jd_text: str, company_name: str, role_title: str
    ) -> JDCriteria:
        """
        Analyze job description and extract criteria.

        Returns JDCriteria with explicit skills, inferred skills, critical criteria,
        and importance ranking.
        """

        if not self.client:
            return self._mock_analyze(jd_text, company_name, role_title)

        prompt = f"""
You are an expert at analyzing job descriptions and extracting structured requirements.

Analyze the following job description and extract:
1. Explicit skills mentioned (e.g., Python, Kubernetes, SQL)
2. Inferred skills (implied from context, e.g., "system design" from "building scalable systems")
3. Critical criteria (must-haves, shown as requirements)
4. Importance ranking (0-1) for each skill/criterion

Job Description:
Company: {company_name}
Role: {role_title}

{jd_text}

Return a JSON object with:
{{
  "explicit_skills": ["skill1", "skill2", ...],
  "inferred_skills": ["inferred1", "inferred2", ...],
  "critical_criteria": ["5+ years experience", "microservices", ...],
  "importance_ranking": {{"skill1": 0.9, "skill2": 0.7, ...}}
}}

Return ONLY the JSON object, no other text.
"""

        try:
            response = self.client.messages.create(
                model=self.model, max_tokens=2000, messages=[{"role": "user", "content": prompt}]
            )

            response_text = response.content[0].text

            try:
                parsed = _parse_json_response(response_text)
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(f"Could not parse JD analysis: {response_text} ({e})")
                return self._mock_analyze(jd_text, company_name, role_title)

            return JDCriteria(
                explicit_skills=parsed.get("explicit_skills", []),
                inferred_skills=parsed.get("inferred_skills", []),
                critical_criteria=parsed.get("critical_criteria", []),
                importance_ranking=parsed.get("importance_ranking", {}),
                company_name=company_name,
                role_title=role_title,
            )
        except Exception as e:
            logger.error(f"Error analyzing JD: {e}")
            return self._mock_analyze(jd_text, company_name, role_title)

    def _mock_analyze(
        self, jd_text: str, company_name: str, role_title: str
    ) -> JDCriteria:
        """Mock analysis when LLM is not available."""
        return JDCriteria(
            explicit_skills=["Python", "System Design", "Kubernetes"],
            inferred_skills=["Distributed Systems", "Microservices"],
            critical_criteria=["5+ years experience", "scalable systems"],
            importance_ranking={
                "Python": 0.9,
                "System Design": 0.85,
                "Kubernetes": 0.8,
                "Distributed Systems": 0.75,
            },
            company_name=company_name,
            role_title=role_title,
        )


# ============================================================================
# Task 6: EVIDENCE MATCHER
# ============================================================================


class EvidenceMatcher:
    """Matches evidence against JD criteria."""

    def rank_evidence(
        self, evidence_list: List[StructuredEvidence], jd_criteria: JDCriteria
    ) -> List[RankedEvidence]:
        """
        Rank evidence items against JD criteria.

        Returns list of RankedEvidence, sorted by match_score (highest first).
        """
        ranked = []

        for evidence in evidence_list:
            match_score, matched_skills, matched_criteria = self._compute_match_score(
                evidence, jd_criteria
            )

            suggested_rephrasing = self._suggest_rephrasing(evidence, jd_criteria)

            ranked_evidence = RankedEvidence(
                evidence=evidence,
                match_score=match_score,
                matched_skills=matched_skills,
                matched_criteria=matched_criteria,
                suggested_rephrasing=suggested_rephrasing,
            )
            ranked.append(ranked_evidence)

        # Sort by match score (highest first)
        ranked.sort(key=lambda r: r.match_score, reverse=True)
        return ranked

    def _compute_match_score(
        self, evidence: StructuredEvidence, jd_criteria: JDCriteria
    ) -> tuple[float, List[str], List[str]]:
        """Compute match score between evidence and JD criteria."""
        matched_skills = []
        matched_criteria = []
        total_importance = 0.0
        matched_importance = 0.0

        # Check skill matches
        all_jd_skills = jd_criteria.explicit_skills + jd_criteria.inferred_skills
        for skill in evidence.skills_demonstrated:
            for jd_skill in all_jd_skills:
                if self._skill_match(skill, jd_skill):
                    matched_skills.append(jd_skill)
                    importance = jd_criteria.importance_ranking.get(jd_skill, 0.5)
                    matched_importance += importance
                    break

        # Accumulate total importance
        for skill in all_jd_skills:
            total_importance += jd_criteria.importance_ranking.get(skill, 0.5)

        # Check criteria matches
        evidence_text = (
            f"{evidence.achievement} {evidence.context} {evidence.impact}".lower()
        )
        for criterion in jd_criteria.critical_criteria:
            if self._criterion_match(evidence_text, criterion):
                matched_criteria.append(criterion)

        # Compute final score
        skill_score = matched_importance / total_importance if total_importance > 0 else 0
        criteria_score = len(matched_criteria) / len(jd_criteria.critical_criteria) if jd_criteria.critical_criteria else 0
        match_score = (skill_score + criteria_score) / 2

        return max(0, min(1, match_score)), matched_skills, matched_criteria

    @staticmethod
    def _skill_match(evidence_skill: str, jd_skill: str) -> bool:
        """Check if two skills match (simple string matching with flexibility)."""
        ev_lower = evidence_skill.lower()
        jd_lower = jd_skill.lower()
        return ev_lower in jd_lower or jd_lower in ev_lower or ev_lower == jd_lower

    @staticmethod
    def _criterion_match(evidence_text: str, criterion: str) -> bool:
        """Check if evidence matches a criterion (simple heuristic)."""
        # Very simple: check if key words from criterion appear in evidence
        words = criterion.lower().split()
        return any(word in evidence_text for word in words if len(word) > 3)

    @staticmethod
    def _suggest_rephrasing(
        evidence: StructuredEvidence, jd_criteria: JDCriteria
    ) -> Optional[str]:
        """Suggest how to rephrase evidence to better match JD."""
        # Simple heuristic: use JD language in rephrasing
        jd_lang = " ".join(jd_criteria.explicit_skills[:2])
        if jd_lang:
            return f"{evidence.achievement} - leveraging {jd_lang}"
        return None


# ============================================================================
# Task 7: CV ASSEMBLER
# ============================================================================


class CVAssembler:
    """Assembles tailored CV sections from matched evidence."""

    def __init__(self):
        """Initialize assembler with deduplication tracking."""
        self.used_achievements = set()

    def assemble(
        self,
        ranked_evidence: List[RankedEvidence],
        section_type: str,
        max_per_role: int = 3,
    ) -> str:
        """
        Assemble a CV section from ranked evidence.

        Args:
            ranked_evidence: List of RankedEvidence sorted by match_score
            section_type: e.g., "Experience", "Projects", "Skills"
            max_per_role: Max items to include per role/company

        Returns:
            Formatted CV section text.
        """
        if not ranked_evidence:
            return ""

        if section_type == "Skills":
            return self._assemble_skills_section(ranked_evidence)
        elif section_type == "Experience":
            return self._assemble_experience_section(ranked_evidence, max_per_role)
        elif section_type == "Projects":
            return self._assemble_projects_section(ranked_evidence, max_per_role)
        else:
            return self._assemble_generic_section(ranked_evidence)

    def _assemble_experience_section(
        self, ranked_evidence: List[RankedEvidence], max_per_role: int
    ) -> str:
        """Assemble Experience section, grouped by company/role."""
        sections = {}
        for ranked in ranked_evidence:
            key = (ranked.evidence.company_name, ranked.evidence.job_title)
            if key not in sections:
                sections[key] = []
            if len(sections[key]) < max_per_role:
                sections[key].append(ranked)

        lines = []
        for (company, job_title), evidence_list in sections.items():
            if company or job_title:
                lines.append(f"\n**{job_title or 'Role'} at {company or 'Company'}**")
            for ranked in evidence_list:
                rephrased = (
                    ranked.suggested_rephrasing
                    or ranked.evidence.achievement
                )
                # Avoid verbatim repeats: skip if achievement already used
                if rephrased not in self.used_achievements:
                    lines.append(f"- {rephrased}")
                    self.used_achievements.add(rephrased)

        return "\n".join(lines)

    def _assemble_projects_section(
        self, ranked_evidence: List[RankedEvidence], max_per_role: int
    ) -> str:
        """Assemble Projects section."""
        lines = []
        for i, ranked in enumerate(ranked_evidence[:max_per_role]):
            rephrased = (
                ranked.suggested_rephrasing or ranked.evidence.achievement
            )
            # Avoid verbatim repeats
            if rephrased not in self.used_achievements:
                lines.append(f"- {rephrased}")
                self.used_achievements.add(rephrased)

        return "\n".join(lines)

    def _assemble_skills_section(
        self, ranked_evidence: List[RankedEvidence]
    ) -> str:
        """Assemble Skills section from all matched skills."""
        skills = set()
        for ranked in ranked_evidence:
            skills.update(ranked.evidence.skills_demonstrated)
        return ", ".join(sorted(skills)) if skills else ""

    def _assemble_generic_section(
        self, ranked_evidence: List[RankedEvidence]
    ) -> str:
        """Generic assembly for unknown section types."""
        lines = []
        for ranked in ranked_evidence:
            lines.append(f"- {ranked.evidence.achievement}")
        return "\n".join(lines)


# ============================================================================
# Task 8: EVIDENCE EXTRACTION SERVICE (BOOTSTRAP WORKFLOW)
# ============================================================================


class EvidenceExtractionService:
    """Orchestrates evidence extraction from a CV and persistence to backend."""

    def __init__(self, extractor: EvidenceExtractor, backend):
        """
        Initialize with extractor and backend.

        Args:
            extractor: EvidenceExtractor instance
            backend: EvidenceBackend instance (e.g., PostgresEvidenceBackend)
        """
        self.extractor = extractor
        self.backend = backend

    def extract_and_persist(self, cv_id: str, cv_sections: dict) -> int:
        """
        Extract evidence from CV sections and persist to backend.

        Args:
            cv_id: ID of the ground-truth CV record
            cv_sections: dict of {section_name: [section_item, ...]}
                Each section_item has: text, company, title, start_date, end_date (optional)

        Returns:
            Total count of evidence items persisted
        """

        total_extracted = 0

        for section_name, section_items in cv_sections.items():
            for item in section_items:
                text = item.get("text", "")
                company_name = item.get("company", "")
                job_title = item.get("title")
                start_date = item.get("start_date")
                end_date = item.get("end_date")

                if not text:
                    continue

                # Extract evidence from this section
                extracted = self.extractor.extract(
                    cv_text=text,
                    cv_id=cv_id,
                    section=section_name,
                    job_title=job_title,
                    company_name=company_name,
                    time_period_start=start_date,
                    time_period_end=end_date,
                )

                # Persist to backend
                for evidence in extracted:
                    self.backend.save_evidence(evidence)
                    total_extracted += 1

        return total_extracted


# ============================================================================
# Task 9: CV GENERATION SERVICE (PER-JD WORKFLOW)
# ============================================================================


class CVGenerationService:
    """Orchestrates CV generation from JD using evidence matching."""

    def __init__(
        self,
        analyzer: JDAnalyzer,
        matcher: EvidenceMatcher,
        assembler: CVAssembler,
        backend,
    ):
        """
        Initialize with components and backend.

        Args:
            analyzer: JDAnalyzer instance
            matcher: EvidenceMatcher instance
            assembler: CVAssembler instance
            backend: EvidenceBackend instance
        """
        self.analyzer = analyzer
        self.matcher = matcher
        self.assembler = assembler
        self.backend = backend

    def generate_cv(
        self,
        ground_truth_cv_id: str,
        jd_text: str,
        company_name: str,
        role_title: str,
    ) -> dict:
        """
        Generate a tailored CV for a job application.

        Args:
            ground_truth_cv_id: ID of the source ground-truth CV
            jd_text: Job description text
            company_name: Company name (for JD context)
            role_title: Role title (for JD context)

        Returns:
            dict with keys:
            - tailored_cv: formatted CV text
            - matched_evidence_count: number of evidence items matched
            - jd_analysis: JDCriteria object
        """

        # Step 1: Analyze JD
        jd_criteria = self.analyzer.analyze(
            jd_text=jd_text, company_name=company_name, role_title=role_title
        )

        # Step 2: Load evidence from ground-truth CV
        evidence_list = self.backend.get_evidence_by_cv_id(ground_truth_cv_id)

        # Step 3: Match evidence against JD
        ranked_evidence = self.matcher.rank_evidence(evidence_list, jd_criteria)

        # Step 4: Assemble CV sections
        # Experience section
        experience_evidence = [
            r for r in ranked_evidence
            if r.evidence.source_section == "Experience"
        ]
        experience_text = self.assembler.assemble(
            ranked_evidence=experience_evidence,
            section_type="Experience",
            max_per_role=3,
        )

        # Projects section
        projects_evidence = [
            r for r in ranked_evidence
            if r.evidence.source_section == "Projects"
        ]
        projects_text = self.assembler.assemble(
            ranked_evidence=projects_evidence,
            section_type="Projects",
            max_per_role=2,
        )

        # Skills section (use all matched skills)
        skills_evidence = [
            r for r in ranked_evidence if r.matched_skills
        ]
        skills_text = self.assembler.assemble(
            ranked_evidence=skills_evidence,
            section_type="Skills",
            max_per_role=50,
        )

        # Combine into final CV
        cv_sections = []
        if experience_text:
            cv_sections.append(f"## Experience\n\n{experience_text}")
        if projects_text:
            cv_sections.append(f"## Projects\n\n{projects_text}")
        if skills_text:
            cv_sections.append(f"## Skills\n\n{skills_text}")

        tailored_cv = "\n\n".join(cv_sections)

        return {
            "tailored_cv": tailored_cv,
            "matched_evidence_count": len(
                [r for r in ranked_evidence if r.match_score > 0]
            ),
            "jd_analysis": jd_criteria,
        }
