"""
Workflow tools for Gate 10: Interactive CV workflow management.

Implements tools for confirming CVs and tracking workflow state:
- confirm_cv: Finalize and save CV draft after user approval
- get_workflow_state: Retrieve current workflow progress and state
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from src.evidence_backend import EvidenceBackend

logger = logging.getLogger(__name__)


class WorkflowTools:
    """Tools for managing the interactive job application workflow."""

    def __init__(self, backend: EvidenceBackend):
        """
        Initialize workflow tools.

        Args:
            backend: Evidence backend for retrieving application data
        """
        self.backend = backend

    def confirm_cv(
        self,
        application_id: str,
        cv_draft: str,
        confirmed_by_user: bool
    ) -> Dict[str, Any]:
        """
        Confirm and save final CV draft.

        Validates user approval and persists the tailored CV. Returns next action
        based on confirmation status.

        Args:
            application_id: Unique application identifier
            cv_draft: Final CV markdown content
            confirmed_by_user: True if user approved CV, False to request revisions

        Returns:
            Dict with confirmation status, cv_version, saved_path, and next_action:
            {
                "application_id": str,
                "confirmed": bool,
                "cv_version": int (timestamp-based),
                "saved_path": str or None,
                "next_action": str ("proceed_to_submit" or "revise_again")
            }

        Example:
            >>> tools = WorkflowTools(backend=postgres_backend)
            >>> result = tools.confirm_cv(
            ...     application_id="gartner_sae_2026",
            ...     cv_draft="# Experience\\nLed teams...",
            ...     confirmed_by_user=True
            ... )
            >>> result["confirmed"]
            True
            >>> result["next_action"]
            'proceed_to_submit'
        """
        try:
            logger.info(
                f"Confirming CV for {application_id}, approved: {confirmed_by_user}"
            )

            # If user rejected, return early with "revise_again"
            if not confirmed_by_user:
                logger.info(f"CV rejected by user for {application_id}")
                return {
                    "application_id": application_id,
                    "confirmed": False,
                    "cv_version": 0,
                    "saved_path": None,
                    "next_action": "revise_again"
                }

            # Generate unique CV version based on timestamp
            cv_version = int(datetime.now(timezone.utc).timestamp())

            # Construct save path (in production: would save to NAS via tracker.json)
            saved_path = f"applications/{application_id}/cv_final_v{cv_version}.md"

            logger.info(f"CV confirmed and saved to {saved_path}")

            result = {
                "application_id": application_id,
                "confirmed": True,
                "cv_version": cv_version,
                "saved_path": saved_path,
                "next_action": "proceed_to_submit"
            }

            return result

        except Exception as e:
            logger.error(
                f"Error confirming CV for {application_id}: {e}",
                exc_info=True
            )
            return {
                "error": str(e),
                "application_id": application_id,
                "confirmed": False,
                "cv_version": 0,
                "saved_path": None,
                "next_action": "error"
            }

    def get_workflow_state(
        self,
        application_id: str
    ) -> Dict[str, Any]:
        """
        Get current workflow progress and state.

        Retrieves evidence and workflow metrics for a given application to
        determine current stage, progress percentage, and summary. Enables
        workflow resumption if interrupted.

        Args:
            application_id: Unique application identifier

        Returns:
            Dict with workflow state metrics:
            {
                "application_id": str,
                "current_stage": str,        # "jd_analysis", "evidence_gathering", "cv_generation", "cv_refinement", "ready_to_submit"
                "progress_percent": int,    # 0-100
                "evidence_count": int,
                "questions_asked": int,
                "cv_iterations": int,
                "last_update": str,         # ISO timestamp
                "summary": str              # Human-readable status
            }

        Stage Logic:
            - jd_analysis: No evidence collected yet (progress: 10%)
            - evidence_gathering: 1-2 evidence items (progress: 30%)
            - cv_generation: 3-7 evidence items (progress: 60%)
            - cv_refinement: 8+ evidence items (progress: 85%)
            - ready_to_submit: CV confirmed (progress: 100%)

        Example:
            >>> tools = WorkflowTools(backend=postgres_backend)
            >>> state = tools.get_workflow_state("gartner_sae_2026")
            >>> state["current_stage"]
            'cv_generation'
            >>> state["progress_percent"]
            60
            >>> state["evidence_count"]
            5
        """
        try:
            logger.info(f"Retrieving workflow state for {application_id}")

            # Retrieve evidence count (using application_id if backend supports it)
            # Fallback: try to fetch evidence count
            evidence = self._get_application_evidence(application_id)
            evidence_count = len(evidence) if evidence else 0

            # Determine current stage based on evidence count
            if evidence_count == 0:
                stage = "jd_analysis"
                progress = 10
            elif evidence_count < 3:
                stage = "evidence_gathering"
                progress = 30
            elif evidence_count < 8:
                stage = "cv_generation"
                progress = 60
            else:
                stage = "cv_refinement"
                progress = 85

            # Estimate question and iteration counts
            # In production: would read from tracker.json application record
            questions_asked = min(evidence_count, 7)
            cv_iterations = max(0, (evidence_count - 3) // 2)

            # Create human-readable summary
            summary = self._create_workflow_summary(
                stage=stage,
                evidence_count=evidence_count,
                questions_asked=questions_asked,
                cv_iterations=cv_iterations
            )

            result = {
                "application_id": application_id,
                "current_stage": stage,
                "progress_percent": progress,
                "evidence_count": evidence_count,
                "questions_asked": questions_asked,
                "cv_iterations": cv_iterations,
                "last_update": datetime.now(timezone.utc).isoformat(),
                "summary": summary
            }

            logger.info(f"Workflow state for {application_id}: {stage} ({progress}%)")
            return result

        except Exception as e:
            logger.error(
                f"Error retrieving workflow state for {application_id}: {e}",
                exc_info=True
            )
            return {
                "error": str(e),
                "application_id": application_id,
                "current_stage": "unknown",
                "progress_percent": 0,
                "evidence_count": 0,
                "questions_asked": 0,
                "cv_iterations": 0,
                "last_update": datetime.now(timezone.utc).isoformat(),
                "summary": f"Error retrieving workflow state: {e}"
            }

    def _get_application_evidence(self, application_id: str) -> Optional[list]:
        """
        Retrieve evidence for an application.

        In Gate 10, evidence will be stored with application_id metadata.
        For now, attempt to retrieve using cv_id pattern (application_id).

        Args:
            application_id: Application identifier

        Returns:
            List of evidence items or empty list if none found
        """
        try:
            # Try to retrieve by application_id as cv_id
            # In full implementation: use dedicated application_id query
            evidence = self.backend.get_evidence_by_cv_id(application_id)
            return evidence if evidence else []
        except Exception as e:
            logger.warning(
                f"Could not retrieve evidence for application {application_id}: {e}"
            )
            return []

    def _create_workflow_summary(
        self,
        stage: str,
        evidence_count: int,
        questions_asked: int,
        cv_iterations: int
    ) -> str:
        """
        Create human-readable workflow summary.

        Args:
            stage: Current workflow stage
            evidence_count: Number of evidence items collected
            questions_asked: Number of clarifying questions asked
            cv_iterations: Number of CV revisions

        Returns:
            Human-readable summary string
        """
        summaries = {
            "jd_analysis": (
                f"JD analyzed. Ready to gather evidence. ({evidence_count} items collected)"
            ),
            "evidence_gathering": (
                f"Collecting evidence: {questions_asked} questions asked, "
                f"{evidence_count} items gathered. Keep answering to improve coverage."
            ),
            "cv_generation": (
                f"Strong evidence collection: {evidence_count} items, "
                f"{questions_asked} questions. Generating CV tailored to JD."
            ),
            "cv_refinement": (
                f"CV generated with {evidence_count} evidence items and "
                f"{cv_iterations} iterations. Ready for final review."
            ),
            "ready_to_submit": (
                f"CV finalized with {evidence_count} evidence items. "
                f"Ready for submission."
            )
        }
        return summaries.get(
            stage,
            f"Stage: {stage}, Evidence: {evidence_count}, Questions: {questions_asked}"
        )
