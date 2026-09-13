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
        # Context-Prep pattern: No backend LLM analyzers needed

    def start_job_application_workflow(self, job_jd: str, application_id: str, user_name: str) -> dict:
        try:
            if not job_jd or not str(job_jd).strip():
                raise ValueError("Job description is required")
                
            company_name = self._extract_company_name(job_jd)
            role_title = self._extract_role_title(job_jd)
            
            prompt = f"""You are an expert career coach assisting {user_name} with an application for {role_title} at {company_name}.
Here is the job description:
<jd>
{job_jd}
</jd>
Please analyze the JD, extract explicitly requested skills and inferred skills, map them against the user's base CV, identify gaps, and generate a list of 5 clarifying questions.
Call the `generate_clarifying_questions` tool with your proposed questions when ready."""

            return {
                "ok": True,
                "application_id": application_id,
                "workflow_started": True,
                "initial_stage": "jd_analysis",
                "next_action": "generate_clarifying_questions",
                "system_prompt": prompt
            }
        except Exception as e:
            return {
                "ok": False,
                "error": str(e),
                "application_id": application_id
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

    
    def generate_clarifying_questions(self, application_id: str, jd_content: str) -> dict:
        try:
            company = self._extract_company_name(jd_content)
            role = self._extract_role_title(jd_content)
            
            prompt = f"""Please generate 5 clarifying questions for the applicant applying to {company} as a {role}.
Based on the JD provided previously, what evidence do we need from the user to demonstrate they are a good fit?
Present the questions to the user. When they reply, call `answer_clarifying_questions` with their answers."""
            return {
                "ok": True,
                "application_id": application_id,
                "questions": [],
                "question_count": 5,
                "next_action": "answer_clarifying_questions",
                "system_prompt": prompt
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}
    def answer_clarifying_questions(self, application_id: str, answers: dict) -> dict:
        try:
            if not answers:
                return {"ok": False, "error": "answers dict is required"}
                
            evidence_stored = sum(1 for a in answers.values() if a and str(a).strip())
            
            for k, v in answers.items():
                if v and str(v).strip():
                    from src.evidence_models import ApplicationScopedEvidence
                    from datetime import datetime, timezone
                    ev = ApplicationScopedEvidence(
                        evidence_id=f"{application_id}-{k}",
                        application_id=application_id,
                        source="user_input",
                        response=str(v),
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        added_by_agent=False
                    )
                    if self.backend:
                        self.backend.save_application_evidence(ev)

            return {
                "ok": True,
                "evidence_stored": evidence_stored,
                "next_action": "generate_cv_draft"
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def generate_cv_draft(self, application_id: str, jd_content: str, evidence_items: list) -> dict:
        try:
            if not jd_content and not evidence_items:
                return {"ok": False, "error": "missing cv data"}
                
            role = self._extract_role_title(jd_content) if jd_content else "Unknown Role"
            
            import os
            from pathlib import Path
            base_cv_env = os.getenv("JOB_APP_BASE_CV_PATH")
            base_cv_content = None
            if base_cv_env and Path(base_cv_env).exists():
                base_cv_content = Path(base_cv_env).read_text(encoding="utf-8")
            else:
                for candidate in [
                    Path(os.getenv("JOB_APP_ARTEFACTS_DIR", os.getenv("JOB_APP_BASE_DIR", ""))) / "base_cv" / "Reference_CV.md",
                    Path("/Volumes/job-app-data/base_cv/Reference_CV.md"),
                    Path("/mnt/job-app-data/base_cv/Reference_CV.md"),
                    Path(os.getcwd()) / "Base CV" / "Reference_CV.md",
                    Path(os.getcwd()) / "data" / "base_cv" / "Reference_CV.md",
                ]:
                    if candidate.exists() and candidate.is_file():
                        base_cv_content = candidate.read_text(encoding="utf-8")
                        break
            if not base_cv_content:
                base_cv_content = "Base CV not found."
            
            prompt = f"""Please write a tailored markdown CV draft for the {role} position.
App ID: {application_id}

Here is the user's BASE CV:
<base_cv>
{base_cv_content}
</base_cv>

Please merge and tailor the Base CV by incorporating the following NEW evidence:
<new_evidence>
{chr(10).join(evidence_items)}
</new_evidence>

Ensure the final CV is a single, complete markdown document that seamlessly integrates the new evidence into the existing experience and formatting of the Base CV.
When complete, call `revise_cv` or ask the user to confirm."""
            return {
                "ok": True,
                "cv_draft": "Draft to be generated by frontend LLM.",
                "draft_version": 1,
                "system_prompt": prompt
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}
    def revise_cv(self, application_id: str, cv_draft: str, revision_notes: str) -> dict:
        try:
            if not revision_notes:
                return {"ok": False, "error": "missing revision notes"}
            prompt = f"Please revise the current CV draft based on these notes:\n{revision_notes}\n\nWhen complete, ask the user to confirm using `confirm_cv`."
            return {
                "ok": True,
                "revised_cv": "Revision to be generated by frontend LLM.",
                "revision_version": 2,
                "changes_applied": 1,
                "next_action": "confirm_cv",
                "system_prompt": prompt
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}
    def confirm_cv(self, application_id: str, cv_draft: str, confirmed_by_user: bool) -> dict:
        try:
            saved_path = None
            if confirmed_by_user:
                import os
                from pathlib import Path
                target_base = None
                env_artefacts = os.getenv("JOB_APP_ARTEFACTS_DIR") or os.getenv("JOB_APP_BASE_DIR")
                if env_artefacts and Path(env_artefacts).exists():
                    target_base = Path(env_artefacts)
                else:
                    for nas_candidate in [Path("/Volumes/job-app-data"), Path("/mnt/job-app-data")]:
                        if nas_candidate.exists() and nas_candidate.is_dir():
                            target_base = nas_candidate
                            break
                if target_base:
                    dest_dir = target_base / application_id
                    dest_dir.mkdir(parents=True, exist_ok=True)
                    dest_file = dest_dir / f"cv_{application_id}.md"
                    dest_file.write_text(cv_draft, encoding="utf-8")
                    saved_path = str(dest_file)
                else:
                    saved_path = f"/tmp/cv_{application_id}.md"
            return {
                "ok": True,
                "confirmed": confirmed_by_user,
                "next_action": "proceed_to_submit" if confirmed_by_user else "revise_again",
                "saved_path": saved_path
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def get_workflow_state(self, application_id: str) -> dict:
        try:
            evidence_count = 0
            if self.backend:
                evidence = self.backend.get_evidence_by_application(application_id)
                if not evidence and hasattr(self.backend, 'get_evidence_by_cv_id'):
                    evidence = self.backend.get_evidence_by_cv_id(application_id)
                evidence_count = len(evidence)
                
            if evidence_count == 0:
                current_stage = "jd_analysis"
                progress_percent = 10
            elif evidence_count < 3:
                current_stage = "evidence_gathering"
                progress_percent = 30
            elif evidence_count < 8:
                current_stage = "cv_generation"
                progress_percent = 60
            else:
                current_stage = "cv_refinement"
                progress_percent = 85
                
            return {
                "ok": True,
                "application_id": application_id,
                "current_stage": current_stage,
                "progress_percent": progress_percent,
                "evidence_count": evidence_count,
                "questions_asked": 0,
                "summary": f"Workflow is in {current_stage} stage."
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}
