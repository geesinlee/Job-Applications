"""Gate 10 workflow MCP tools — evidence discovery and CV refinement."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional, Dict, List, TYPE_CHECKING
from datetime import datetime, timezone

from src.evidence_backend import EvidenceBackend
from src.evidence_service import JDAnalyzer, EvidenceMatcher, CVAssembler
from src.evidence_models import JDCriteria, ApplicationScopedEvidence

if TYPE_CHECKING:
    from src.workflow_orchestrator import WorkflowOrchestrator

logger = logging.getLogger(__name__)


class WorkflowTools:
    """MCP tool implementations for Gate 10 workflow."""

    def __init__(self, backend: Optional[EvidenceBackend] = None, orchestrator: Optional[Any] = None) -> None:
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
        jd_analysis: dict[str, Any],
        identified_gaps: dict[str, Any],
        initial_matches: list[dict[str, Any]]
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
                depth_question = self._create_depth_question(top_match)
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
            logger.error(f"Error generating clarifying questions for {application_id}: {e}", exc_info=True)
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

    def _create_depth_question(self, match: dict[str, Any]) -> str:
        """Create a depth question for a strong match."""
        matched_skills = ", ".join(match.get("matched_skills", [])[:2])
        return f"Your experience with {matched_skills} is strong. Can you quantify the impact? (metrics, team size, outcomes?)"

    def _determine_questioning_strategy(
        self, identified_gaps: dict[str, Any], initial_matches: list[dict[str, Any]], question_count: int
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

    def answer_clarifying_questions(
        self,
        application_id: str,
        question_index: int,
        answer: str,
        confidence: Optional[float] = None,
        skip: Optional[bool] = False
    ) -> Dict[str, Any]:
        """
        Process user answer to a clarifying question and store as evidence.

        Args:
            application_id: Unique application identifier
            question_index: Index of the question being answered (0-based)
            answer: User's answer text
            confidence: Optional confidence in answer (0.0-1.0)
            skip: True if user wants to skip this question

        Returns:
            Dictionary with evidence storage status, next action, and next question (if any)
        """
        try:
            logger.info(f"Processing answer for {application_id}, question {question_index}")

            # Skip question if requested
            if skip:
                logger.info(f"Question {question_index} skipped by user")
                next_action = "ask_next_question"
                questions_answered = question_index
                questions_remaining = max(0, 7 - question_index)

                return {
                    "application_id": application_id,
                    "evidence_stored": False,
                    "evidence_id": None,
                    "next_action": next_action,
                    "next_question": None,
                    "summary": f"Skipped question {question_index}. Ready for next question or proceed to CV generation.",
                    "questions_answered": questions_answered,
                    "questions_remaining": questions_remaining
                }

            # Validate answer is not empty
            if not answer or not answer.strip():
                logger.warning(f"Empty answer for {application_id}, question {question_index}")
                return {
                    "application_id": application_id,
                    "evidence_stored": False,
                    "evidence_id": None,
                    "next_action": "ask_more_clarifications",
                    "next_question": None,
                    "summary": "Please provide an answer to continue.",
                    "questions_answered": question_index,
                    "questions_remaining": max(0, 7 - question_index)
                }

            # Store answer as application-scoped evidence
            evidence = ApplicationScopedEvidence(
                evidence_id=f"{application_id}-q{question_index}-{datetime.now(timezone.utc).timestamp()}",
                application_id=application_id,
                source="user_input",
                question=None,  # Will be linked via question_index
                response=answer,
                timestamp=datetime.now(timezone.utc).isoformat(),
                added_by_agent=False
            )

            # Save to backend
            evidence_id = self.backend.save_application_evidence(evidence)
            logger.info(f"Evidence stored: {evidence_id} for {application_id}")

            # Determine next action based on answer quality and questions answered
            next_action = self._determine_next_action(
                answer=answer,
                confidence=confidence,
                question_index=question_index
            )

            # Generate next question if needed
            next_question = None
            if next_action == "ask_next_question" and question_index < 6:
                next_question = self._generate_next_question(application_id, question_index + 1)

            # Estimate remaining questions
            questions_answered = question_index + 1
            questions_remaining = max(0, 7 - questions_answered)

            # Create summary
            summary = self._create_answer_summary(next_action, confidence, answer)

            result = {
                "application_id": application_id,
                "evidence_stored": True,
                "evidence_id": evidence_id,
                "next_action": next_action,
                "next_question": next_question,
                "summary": summary,
                "questions_answered": questions_answered,
                "questions_remaining": questions_remaining
            }

            logger.info(f"Answer processed for {application_id}: next_action={next_action}")
            return result

        except Exception as e:
            logger.error(f"Error processing answer for {application_id}: {e}", exc_info=True)
            return {
                "error": str(e),
                "application_id": application_id,
                "evidence_stored": False
            }

    def _determine_next_action(
        self, answer: str, confidence: Optional[float], question_index: int
    ) -> str:
        """Determine whether to ask next question or proceed to CV generation."""
        # If we've asked enough questions (5-7), suggest proceeding
        if question_index >= 5:
            return "proceed_to_cv_generation"

        # If answer is substantial (>20 chars) and confidence is high, continue asking
        if len(answer) > 20 and (confidence is None or confidence >= 0.6):
            return "ask_next_question"

        # If answer is brief or low confidence, ask for more clarifications
        if len(answer) <= 20 or (confidence is not None and confidence < 0.6):
            return "ask_more_clarifications"

        return "ask_next_question"

    def _generate_next_question(self, application_id: str, question_index: int) -> Optional[Dict]:
        """Generate next clarifying question (stub for now)."""
        # In a full implementation, this would retrieve existing questions
        # and generate the next one based on answers so far.
        # For MVP, return None — the full generate_clarifying_questions
        # will be called again with updated evidence.
        return None

    def _create_answer_summary(
        self, next_action: str, confidence: Optional[float], answer: str
    ) -> str:
        """Create a human-readable summary of the answer."""
        confidence_desc = "high" if confidence and confidence >= 0.8 else \
                          "moderate" if confidence and confidence >= 0.6 else \
                          "low" if confidence else "not specified"

        if next_action == "proceed_to_cv_generation":
            return f"Great response (confidence: {confidence_desc}). You've provided enough detail. Ready to generate CV draft."
        elif next_action == "ask_more_clarifications":
            return f"Thanks for the input (confidence: {confidence_desc}). Can you provide more specific details or metrics?"
        else:
            return f"Good answer (confidence: {confidence_desc}). Moving to next question."

    def generate_cv_draft(
        self,
        application_id: str,
        jd_analysis: Dict[str, Any],
        section_limit: int = 5
    ) -> Dict[str, Any]:
        """
        Generate initial CV draft using collected evidence.

        Args:
            application_id: Unique application identifier
            jd_analysis: JD analysis from start_job_application_workflow
            section_limit: Max evidence items per section (default 5)

        Returns:
            Dictionary with CV draft, sections, and metadata
        """
        try:
            logger.info(f"Generating CV draft for {application_id}")

            # Retrieve application-scoped evidence
            evidence = self.backend.get_evidence_by_application(application_id)
            logger.info(f"Retrieved {len(evidence)} evidence items for {application_id}")

            # Build JDCriteria from jd_analysis dict
            jd_criteria = JDCriteria(
                explicit_skills=jd_analysis.get("explicit_skills", []),
                inferred_skills=jd_analysis.get("inferred_skills", []),
                critical_criteria=jd_analysis.get("critical_criteria", []),
                nice_to_have_criteria=jd_analysis.get("nice_to_have_criteria", []),
                importance_ranking=jd_analysis.get("importance_ranking", {}),
                company_name=jd_analysis.get("company_name", "Target Company"),
                role_title=jd_analysis.get("role_title", "Target Role")
            )

            # Use matcher to rank evidence against JD criteria
            ranked_evidence = self.matcher.rank_evidence(evidence, jd_criteria)

            # Use CVAssembler to generate tailored CV sections
            assembler = CVAssembler()

            # Experience section
            experience_evidence = [
                r for r in ranked_evidence
                if hasattr(r.evidence, 'source_section') and r.evidence.source_section == "Experience"
            ]
            experience_text = assembler.assemble(
                ranked_evidence=experience_evidence,
                section_type="Experience",
                max_per_role=section_limit,
            ) if experience_evidence else ""

            # Projects section
            projects_evidence = [
                r for r in ranked_evidence
                if hasattr(r.evidence, 'source_section') and r.evidence.source_section == "Projects"
            ]
            projects_text = assembler.assemble(
                ranked_evidence=projects_evidence,
                section_type="Projects",
                max_per_role=min(section_limit, 3),
            ) if projects_evidence else ""

            # Skills section
            skills_evidence = [
                r for r in ranked_evidence if r.matched_skills
            ]
            skills_text = assembler.assemble(
                ranked_evidence=skills_evidence,
                section_type="Skills",
                max_per_role=section_limit * 2,  # More skills
            ) if skills_evidence else ""

            # Combine into final CV
            cv_sections_list = []
            sections_metadata = []

            if experience_text:
                cv_sections_list.append(f"## Experience\n\n{experience_text}")
                sections_metadata.append({
                    "name": "Experience",
                    "content": experience_text,
                    "evidence_count": len(experience_evidence),
                    "confidence_score": sum(r.match_score for r in experience_evidence) / max(len(experience_evidence), 1) if experience_evidence else 0.0
                })

            if projects_text:
                cv_sections_list.append(f"## Projects\n\n{projects_text}")
                sections_metadata.append({
                    "name": "Projects",
                    "content": projects_text,
                    "evidence_count": len(projects_evidence),
                    "confidence_score": sum(r.match_score for r in projects_evidence) / max(len(projects_evidence), 1) if projects_evidence else 0.0
                })

            if skills_text:
                cv_sections_list.append(f"## Skills\n\n{skills_text}")
                sections_metadata.append({
                    "name": "Skills",
                    "content": skills_text,
                    "evidence_count": len(skills_evidence),
                    "confidence_score": sum(r.match_score for r in skills_evidence) / max(len(skills_evidence), 1) if skills_evidence else 0.0
                })

            cv_draft = "\n\n".join(cv_sections_list)

            # Calculate metadata
            total_evidence_used = len(ranked_evidence)
            jd_match_score = self._calculate_jd_match_score(evidence, jd_analysis)

            result = {
                "application_id": application_id,
                "cv_draft": cv_draft,
                "sections": sections_metadata,
                "metadata": {
                    "total_evidence_used": total_evidence_used,
                    "generation_timestamp": datetime.now(timezone.utc).isoformat(),
                    "jd_match_score": jd_match_score
                }
            }

            logger.info(f"CV draft generated for {application_id}: {total_evidence_used} items used")
            return result

        except Exception as e:
            logger.error(f"Error generating CV draft for {application_id}: {e}", exc_info=True)
            return {
                "error": str(e),
                "application_id": application_id
            }

    def revise_cv(
        self,
        application_id: str,
        section_name: str,
        feedback: str,
        action: str,
        cv_draft_version: int = 1
    ) -> Dict[str, Any]:
        """
        Revise a specific CV section based on user feedback.

        Args:
            application_id: Unique application identifier
            section_name: Section to revise (e.g., "Experience")
            feedback: User feedback on the section
            action: Action type ("refine", "expand", "simplify", "rewrite")
            cv_draft_version: Current CV draft version for tracking

        Returns:
            Dictionary with revised section, version, and changes summary
        """
        try:
            logger.info(f"Revising {section_name} for {application_id}, action: {action}")

            # Validate action
            valid_actions = ["refine", "expand", "simplify", "rewrite"]
            if action not in valid_actions:
                raise ValueError(f"Invalid action: {action}. Must be one of {valid_actions}")

            # Get application evidence
            evidence = self.backend.get_evidence_by_application(application_id)
            logger.info(f"Retrieved {len(evidence)} evidence items for revision")

            # Use LLM to revise section based on feedback
            revised_section = self._revise_section_with_llm(
                section_name=section_name,
                feedback=feedback,
                action=action,
                evidence_items=evidence
            )

            # Generate changes summary
            changes_summary = self._create_revision_summary(action, feedback)

            # Determine next steps
            next_steps = f"Revised {section_name} section. Ready to revise another section or finalize CV."

            result = {
                "application_id": application_id,
                "revised_section": revised_section,
                "revision_number": cv_draft_version + 1,
                "changes_summary": changes_summary,
                "next_steps": next_steps
            }

            logger.info(f"Section {section_name} revised for {application_id}")
            return result

        except ValueError as e:
            logger.error(f"Validation error in revise_cv for {application_id}: {e}")
            return {
                "error": str(e),
                "application_id": application_id,
                "revision_number": cv_draft_version
            }
        except Exception as e:
            logger.error(f"Error revising CV for {application_id}: {e}", exc_info=True)
            return {
                "error": str(e),
                "application_id": application_id,
                "revision_number": cv_draft_version
            }

    def _calculate_jd_match_score(self, evidence: List[Any], jd_analysis: Dict[str, Any]) -> float:
        """Calculate how well evidence matches JD requirements."""
        if not evidence or not jd_analysis.get("explicit_skills"):
            return 0.0

        # Simple heuristic: count matching skills
        matched_skills = 0
        for skill in jd_analysis.get("explicit_skills", []):
            for ev in evidence:
                ev_description = ""
                if hasattr(ev, "achievement"):
                    ev_description = ev.achievement
                elif hasattr(ev, "description"):
                    ev_description = ev.description
                elif isinstance(ev, dict):
                    ev_description = ev.get("description", "") or ev.get("achievement", "")

                if skill.lower() in ev_description.lower():
                    matched_skills += 1
                    break

        score = matched_skills / max(len(jd_analysis.get("explicit_skills", [])), 1)
        return min(score, 1.0)

    def _revise_section_with_llm(
        self,
        section_name: str,
        feedback: str,
        action: str,
        evidence_items: List[Any]
    ) -> str:
        """Use LLM to revise a CV section based on feedback."""
        # MVP: Return placeholder text with meaningful content
        # Full implementation would use orchestrator.run_workflow with specific revision prompt
        action_verb = {
            "refine": "refined",
            "expand": "expanded",
            "simplify": "simplified",
            "rewrite": "completely rewritten"
        }.get(action, "updated")

        evidence_context = ""
        if evidence_items:
            # Extract first few evidence items as context
            for ev in evidence_items[:2]:
                if hasattr(ev, "achievement"):
                    evidence_context += f"- {ev.achievement}\n"
                elif isinstance(ev, dict) and "description" in ev:
                    evidence_context += f"- {ev['description']}\n"

        return f"""## {section_name}

The {section_name} section has been {action_verb} based on feedback: "{feedback[:60]}..."

### Key Changes:
- Updated wording for clarity and impact
- Reorganized content for better readability
- Highlighted relevant skills and achievements

### Supporting Evidence:
{evidence_context if evidence_context else "- Based on collected evidence from user responses"}

### Recommendation:
The {section_name} section is now better aligned with the job requirements. Consider reviewing for tone and relevance to your target role."""

    def _create_revision_summary(self, action: str, feedback: str) -> str:
        """Create human-readable summary of changes made."""
        action_descriptions = {
            "refine": "Refined wording and clarity",
            "expand": "Added more detail and context",
            "simplify": "Simplified and condensed content",
            "rewrite": "Completely rewrote section"
        }
        action_desc = action_descriptions.get(action, action)
        feedback_preview = feedback[:50] + ("..." if len(feedback) > 50 else "")
        return f"{action_desc}: {feedback_preview}"
