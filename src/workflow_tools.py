"""Gate 10 workflow MCP tools — evidence discovery and CV refinement."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional, Dict, List, TYPE_CHECKING
from datetime import datetime, timezone

from src.evidence_backend import EvidenceBackend
from src.evidence_service import JDAnalyzer, EvidenceMatcher
from src.evidence_models import JDCriteria

if TYPE_CHECKING:
    from src.workflow_orchestrator import WorkflowOrchestrator

logger = logging.getLogger(__name__)


class WorkflowTools:
    """MCP tool implementations for Gate 10 workflow."""

    def __init__(self, backend: Optional[EvidenceBackend] = None, orchestrator: Optional[Any] = None):
        """Initialize with backend and orchestrator instances."""
        self.backend = backend
        self.orchestrator = orchestrator
        self.jd_analyzer = JDAnalyzer()
        self.matcher = EvidenceMatcher()

    def start_job_application_workflow(
        self,
        job_jd: str,
        application_id: str,
        user_name: str,
    ) -> Dict[str, Any]:
        """
        Initiate workflow: ingest JD, analyze, match evidence, identify gaps.

        Args:
            job_jd: Job description text or URL
            application_id: Unique application identifier (e.g., "acme-001")
            user_name: User name for personalization

        Returns:
            Dictionary with JD analysis, initial matches, gaps, and clarifying questions
        """
        try:
            logger.info(f"Starting workflow for application {application_id}")

            # Step 1: Extract company name and role from JD text
            company_name = self._extract_company_name(job_jd)
            role_title = self._extract_role_title(job_jd)
            logger.info(f"Extracted: company={company_name}, role={role_title}")

            # Step 2: Analyze JD using Gate 9 service
            jd_analysis = self.jd_analyzer.analyze(job_jd, company_name, role_title)
            logger.info(f"JD analysis complete: {len(jd_analysis.explicit_skills)} explicit skills")

            # Step 3: Retrieve all application evidence
            evidence_list = []
            if self.backend:
                try:
                    evidence_list = self.backend.get_evidence_by_application(application_id)
                    logger.info(f"Retrieved {len(evidence_list)} evidence items for application {application_id}")
                except Exception as e:
                    logger.warning(f"Failed to retrieve evidence from backend: {e}")

            # Step 4: Match evidence against JD
            matched = []
            if evidence_list:
                ranked_evidence = self.matcher.rank_evidence(evidence_list, jd_analysis)
                for ranked in ranked_evidence:
                    if ranked.match_score > 0:
                        matched.append({
                            "evidence_id": ranked.evidence.id,
                            "description": ranked.evidence.achievement,
                            "matched_skills": ranked.matched_skills,
                            "confidence_score": ranked.match_score,
                            "source": ranked.evidence.source_section
                        })

            # Sort by confidence descending
            matched.sort(key=lambda x: x["confidence_score"], reverse=True)
            logger.info(f"Matched {len(matched)} evidence items with confidence > 0")

            # Step 5: Identify gaps
            matched_skills = set()
            matched_criteria = set()
            for match in matched:
                matched_skills.update(match["matched_skills"])
                # Try to extract criteria names from matched evidence descriptions
                # This is a heuristic: if matched evidence mentions a criterion, mark it as matched
                for criterion in jd_analysis.critical_criteria:
                    if criterion.lower() in match["description"].lower():
                        matched_criteria.add(criterion)

            all_required_skills = jd_analysis.explicit_skills + jd_analysis.inferred_skills
            missing_skills = [s for s in all_required_skills
                              if not any(self._skill_match(s, ms) for ms in matched_skills)]

            # Compute missing criteria: criteria from JD that aren't covered by matched evidence
            # Include both critical_criteria and nice_to_have_criteria from JD analysis
            all_jd_criteria = set(jd_analysis.critical_criteria) | set(jd_analysis.nice_to_have_criteria)
            missing_criteria = list(all_jd_criteria - matched_criteria)

            coverage_percentage = (len(matched_skills) / max(len(jd_analysis.explicit_skills), 1)) * 100 if jd_analysis.explicit_skills else 0.0

            # Step 6: Generate clarifying questions
            questions = self._generate_clarifying_questions(
                jd_analysis, missing_skills, matched, user_name
            )

            # Step 7: Determine next steps
            next_steps = self._determine_next_steps(coverage_percentage, len(matched))

            result = {
                "application_id": application_id,
                "jd_analysis": {
                    "explicit_skills": jd_analysis.explicit_skills,
                    "inferred_skills": jd_analysis.inferred_skills,
                    "critical_criteria": jd_analysis.critical_criteria,
                    "nice_to_have_criteria": jd_analysis.nice_to_have_criteria,
                    "importance_ranking": jd_analysis.importance_ranking
                },
                "initial_matches": matched,
                "identified_gaps": {
                    "missing_skills": missing_skills,
                    "missing_criteria": missing_criteria,
                    "coverage_percentage": coverage_percentage
                },
                "clarifying_questions": questions,
                "next_steps": next_steps
            }

            logger.info(f"Workflow initiated for {application_id}: {coverage_percentage:.1f}% coverage")
            return result

        except Exception as e:
            logger.error(f"Error starting workflow for {application_id}: {e}", exc_info=True)
            return {
                "error": str(e),
                "application_id": application_id,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

    def _extract_company_name(self, jd_text: str) -> str:
        """Extract company name from JD text using simple heuristics."""
        # Look for common patterns like "Company:", "Hiring for:", etc.
        patterns = [
            r"Company:\s*([^\n]+)",
            r"About\s+([A-Z][A-Za-z0-9\s&.]*?)(?:\s+is\s+hiring|\n)",
            r"^([A-Z][A-Za-z0-9\s&.]+?)\s+(?:is\s+)?hiring",
        ]

        for pattern in patterns:
            match = re.search(pattern, jd_text, re.MULTILINE | re.IGNORECASE)
            if match:
                company = match.group(1).strip()
                # Clean up common suffixes
                company = re.sub(r"\s*(Inc|Ltd|LLC|Corp|Co|Corporation|Limited)\.?$", "", company, flags=re.IGNORECASE)
                if company and len(company) > 2:
                    return company

        # Fallback: use first line or "Unknown Company"
        first_line = jd_text.split("\n")[0].strip()
        if len(first_line) > 3:
            return first_line[:100]
        return "Unknown Company"

    def _extract_role_title(self, jd_text: str) -> str:
        """Extract role title from JD text using simple heuristics."""
        patterns = [
            r"Position:\s*([^\n]+)",
            r"Role:\s*([^\n]+)",
            r"Job Title:\s*([^\n]+)",
            r"^(Senior\s+[A-Za-z\s]+?)\s*(?:Role|Position|Required|Responsibilities)",
            r"^([A-Za-z\s]{3,50}?)\s+(?:Engineer|Manager|Developer|Lead|Director|Officer)",
        ]

        for pattern in patterns:
            match = re.search(pattern, jd_text, re.MULTILINE | re.IGNORECASE)
            if match:
                title = match.group(1).strip()
                if title and len(title) > 2:
                    return title[:100]

        # Fallback
        return "Job Title Unknown"

    @staticmethod
    def _skill_match(skill1: str, skill2: str) -> bool:
        """Check if two skills match (simple string matching with flexibility)."""
        s1_lower = skill1.lower()
        s2_lower = skill2.lower()
        return s1_lower in s2_lower or s2_lower in s1_lower or s1_lower == s2_lower

    def _generate_clarifying_questions(
        self,
        jd_analysis: JDCriteria,
        missing_skills: List[str],
        matched: List[Dict],
        user_name: str
    ) -> List[str]:
        """Generate top 3-5 clarifying questions based on gaps and JD."""
        questions = []

        # Top missing skills
        if missing_skills:
            top_missing = missing_skills[:2]
            skills_str = ", ".join(top_missing)
            questions.append(
                f"{user_name}, can you describe your experience with {skills_str}? "
                "This is important for this role."
            )

        # If coverage is low, ask about adjacent skills
        if not matched:
            questions.append(
                "Can you share achievements from roles involving the key skills this JD mentions? "
                "Even if from different roles, we can highlight relevant experience."
            )

        # Ask for context-specific details
        if jd_analysis.critical_criteria:
            first_criterion = jd_analysis.critical_criteria[0]
            questions.append(
                f"For the '{first_criterion}' requirement, "
                "can you share a specific example where you led or demonstrated this?"
            )

        # If some skills are important but not matched, ask about them
        important_unmatched = [
            skill for skill in jd_analysis.explicit_skills
            if jd_analysis.importance_ranking.get(skill, 0.5) >= 0.7
            and not any(self._skill_match(skill, m) for m in [match["description"] for match in matched])
        ]
        if important_unmatched and len(questions) < 4:
            skill = important_unmatched[0]
            questions.append(
                f"Tell me about your hands-on experience with {skill}. "
                "What's the most complex or impactful project you've done with it?"
            )

        # Add a closing/meta question
        if len(questions) < 5:
            questions.append(
                "Are there any other skills, achievements, or experiences you'd like to highlight "
                "that might not be obvious from your base CV?"
            )

        return questions[:5]  # Limit to 5 questions

    def _determine_next_steps(self, coverage_percentage: float, match_count: int) -> str:
        """Determine next workflow step based on coverage."""
        if coverage_percentage >= 80 and match_count >= 5:
            return "Ready to generate CV draft with strong evidence matches. Proceed to generate_cv_draft."
        elif coverage_percentage >= 50:
            return f"Fair coverage ({coverage_percentage:.0f}%). Answer clarifying questions to fill gaps before CV generation."
        else:
            return f"Low coverage ({coverage_percentage:.0f}%). Need to gather more evidence or re-frame existing evidence to match JD requirements."

    def generate_clarifying_questions(
        self,
        application_id: str,
        jd_analysis: dict,
        identified_gaps: dict,
        initial_matches: list,
        user_context: Optional[str] = None
    ) -> dict[str, Any]:
        """
        Generate intelligent clarifying questions to fill evidence gaps.

        Args:
            application_id: Unique application identifier
            jd_analysis: JD analysis output from start_job_application_workflow
            identified_gaps: Gaps dict from start_job_application_workflow
            initial_matches: Matched evidence from start_job_application_workflow
            user_context: Optional user background for personalization

        Returns:
            Dictionary with generated questions and strategy
        """
        try:
            logger.info(f"Generating clarifying questions for {application_id}")

            questions = []

            # Category 1: Questions for missing skills
            for skill in identified_gaps.get("missing_skills", [])[:3]:  # Top 3 skills
                importance = jd_analysis.get("importance_ranking", {}).get(skill, 0.5)
                question = self._create_skill_question(skill, importance)
                questions.append({
                    "question": question,
                    "gap_type": "missing_skill",
                    "importance": importance,
                    "suggested_prompt": f"Think about projects or roles where you've used similar technologies or approaches to {skill}.",
                    "expected_response_type": "achievement"
                })

            # Category 2: Questions for missing criteria
            for criterion in identified_gaps.get("missing_criteria", [])[:2]:  # Top 2 criteria
                question = self._create_criteria_question(criterion)
                questions.append({
                    "question": question,
                    "gap_type": "missing_criteria",
                    "importance": 0.8,  # Criteria usually high importance
                    "suggested_prompt": f"If you haven't directly done this, what's the closest you've come?",
                    "expected_response_type": "context"
                })

            # Category 3: Adjacent skills (inferred from JD but not in explicit skills)
            inferred = jd_analysis.get("inferred_skills", [])
            matched_skills_flat = set()
            for match in initial_matches:
                matched_skills_flat.update(match.get("matched_skills", []))

            for inferred_skill in inferred[:2]:
                if not any(self._skill_match(inferred_skill, ms) for ms in matched_skills_flat):
                    question = self._create_adjacent_skill_question(inferred_skill)
                    questions.append({
                        "question": question,
                        "gap_type": "adjacent_skill",
                        "importance": 0.6,
                        "suggested_prompt": f"Have you worked with related technologies or frameworks?",
                        "expected_response_type": "achievement"
                    })

            # Category 4: Depth/scope questions for existing matches
            if initial_matches:
                top_match = initial_matches[0]  # Strongest match
                depth_question = self._create_depth_question(top_match, jd_analysis)
                questions.append({
                    "question": depth_question,
                    "gap_type": "context",
                    "importance": 0.7,
                    "suggested_prompt": "Describe the scale, team size, and measurable impact of this achievement.",
                    "expected_response_type": "outcome"
                })

            # Limit to 5-7 questions
            questions = questions[:7]

            strategy = self._determine_questioning_strategy(
                identified_gaps, initial_matches, len(questions)
            )

            result = {
                "application_id": application_id,
                "clarifying_questions": questions,
                "strategy": strategy
            }

            logger.info(f"Generated {len(questions)} clarifying questions for {application_id}")
            return result

        except Exception as e:
            logger.error(f"Error generating clarifying questions for {application_id}: {e}")
            return {
                "error": str(e),
                "application_id": application_id
            }

    def _create_skill_question(self, skill: str, importance: float) -> str:
        """Create a question about a missing skill."""
        if importance > 0.8:
            return f"Tell me about your most relevant experience with {skill}. What projects or roles?"
        else:
            return f"Have you worked with {skill} in any capacity? Even side projects count."

    def _create_criteria_question(self, criterion: str) -> str:
        """Create a question about a missing criteria."""
        return f"The role emphasizes {criterion}. Can you share an example where you demonstrated this?"

    def _create_adjacent_skill_question(self, skill: str) -> str:
        """Create a question about an adjacent/inferred skill."""
        return f"Have you worked with {skill} or similar technologies? Tell me about that experience."

    def _create_depth_question(self, match: dict, jd_analysis: dict) -> str:
        """Create a depth question for a strong match."""
        matched_skills = ", ".join(match.get("matched_skills", [])[:2])
        return f"Your experience with {matched_skills} is strong. Can you quantify the impact? (metrics, team size, outcomes?)"

    def _determine_questioning_strategy(
        self, identified_gaps: dict, initial_matches: list, question_count: int
    ) -> str:
        """Determine and explain the questioning strategy."""
        coverage = identified_gaps.get("coverage_percentage", 0)
        match_count = len(initial_matches)

        if coverage >= 80 and match_count >= 5:
            return f"Strong coverage detected ({coverage:.0f}%). Focus: deepen existing matches and explore adjacent skills. {question_count} questions should confirm depth."
        elif coverage >= 50:
            return f"Moderate coverage ({coverage:.0f}%). Focus: fill critical gaps and discover adjacent experience. {question_count} questions target high-priority skills."
        else:
            return f"Low coverage ({coverage:.0f}%). Focus: discover foundational experience and adjacent skills. {question_count} questions target skill discovery."
