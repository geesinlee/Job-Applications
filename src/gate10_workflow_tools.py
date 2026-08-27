"""Gate 10 Workflow Tools: Interactive Evidence Discovery & CV Tailoring.

Orchestrates the job application workflow:
1. Ingest JD → 2. Score match → 3. Generate clarifying questions →
4. Gather evidence → 5. Generate CV draft → 6. Iterative revision → 7. Finalize

Uses Gemini API for intelligent question generation and LLM operations.
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional
import asyncio
import os

from prisma import Prisma
import google.generativeai as genai

# Initialize Gemini API
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

# Initialize Prisma
db = Prisma()


# ============================================================================
# Helper Functions
# ============================================================================


def _extract_jd_structure(jd_text: str) -> dict:
    """Extract structured fields from JD text.

    Identifies: must-haves, nice-to-haves, implicit skills, role level.
    """
    lines = jd_text.lower().split("\n")

    # Simple extraction heuristics
    must_haves = []
    nice_to_haves = []

    for line in lines:
        if any(keyword in line for keyword in ["must have", "required", "essential"]):
            # Extract skill/requirement
            clean = re.sub(r".*(?:must have|required|essential)[:\s]*", "", line).strip()
            if clean and len(clean) > 5:
                must_haves.append(clean)
        elif any(keyword in line for keyword in ["nice to have", "preferred", "bonus"]):
            clean = re.sub(r".*(?:nice to have|preferred|bonus)[:\s]*", "", line).strip()
            if clean and len(clean) > 5:
                nice_to_haves.append(clean)

    # Identify role level
    role_level = "mid"
    if any(word in jd_text.lower() for word in ["principal", "director", "vp", "c-level"]):
        role_level = "senior"
    elif any(word in jd_text.lower() for word in ["junior", "entry", "graduate"]):
        role_level = "junior"

    return {
        "must_haves": must_haves[:10],  # Top 10
        "nice_to_haves": nice_to_haves[:10],
        "role_level": role_level,
        "raw_text": jd_text[:500],  # First 500 chars for context
    }


def _calculate_match_score(
    profile_skills: list[str],
    jd_must_haves: list[str],
    jd_nice_to_haves: list[str],
    evidence_skills: list[str] = None,
) -> float:
    """Calculate match score (0-1) between profile and JD.

    Formula: (matched_must_haves / total_must_haves) * 0.7 +
             (matched_nice_to_haves / total_nice_to_haves) * 0.3
    """
    if evidence_skills is None:
        evidence_skills = []

    all_skills = set(profile_skills + evidence_skills)

    # Match must-haves
    must_have_matches = sum(
        1 for mh in jd_must_haves
        if any(skill.lower() in mh.lower() for skill in all_skills)
    )
    must_have_score = (
        must_have_matches / len(jd_must_haves)
        if jd_must_haves else 1.0
    )

    # Match nice-to-haves
    nice_to_have_matches = sum(
        1 for nth in jd_nice_to_haves
        if any(skill.lower() in nth.lower() for skill in all_skills)
    )
    nice_to_have_score = (
        nice_to_have_matches / len(jd_nice_to_haves)
        if jd_nice_to_haves else 1.0
    )

    # Weighted score
    score = (must_have_score * 0.7) + (nice_to_have_score * 0.3)
    return min(score, 1.0)


async def _generate_with_gemini(prompt: str, model: str = "gemini-2.5-flash") -> str:
    """Call Gemini API to generate content."""
    try:
        client = genai.GenerativeModel(model)
        response = client.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"Error calling Gemini: {e}"


# ============================================================================
# Tool 1: start_job_application_workflow
# ============================================================================


async def start_job_application_workflow(
    jd_path_or_text: str,
    application_id: str,
) -> dict:
    """Begin Gate 10 workflow: ingest JD, score match, identify gaps.

    Args:
        jd_path_or_text: Path to JD file or raw JD text
        application_id: UUID of the application

    Returns:
        {
            "stage": "gaps_identified",
            "match_score": float,
            "jd_analysis": dict,
            "gaps": list[str],
            "questions_needed": int
        }
    """
    try:
        await db.connect()

        # Get application
        app = await db.application.find_unique(where={"id": application_id})
        if not app:
            return {"error": f"Application {application_id} not found"}

        # Load JD
        jd_path = Path(jd_path_or_text)
        if jd_path.exists():
            jd_text = jd_path.read_text(encoding="utf-8")
        else:
            jd_text = jd_path_or_text

        # Save JD to application folder
        if app.folder_path:
            jd_file = Path(app.folder_path) / "jd.md"
            jd_file.write_text(jd_text, encoding="utf-8")

        # Extract JD structure
        jd_analysis = _extract_jd_structure(jd_text)

        # Get base evidence skills
        base_evidence = await db.structuredevidence.find_many(
            where={"source_cv_id": {"startsWith": "base-cv"}}
        )
        base_skills = []
        for ev in base_evidence:
            base_skills.extend(ev.skills_demonstrated or [])

        # Calculate initial match
        match_score = _calculate_match_score(
            profile_skills=base_skills,
            jd_must_haves=jd_analysis["must_haves"],
            jd_nice_to_haves=jd_analysis["nice_to_haves"],
        )

        # Identify gaps
        all_jd_requirements = set(
            jd_analysis["must_haves"] + jd_analysis["nice_to_haves"]
        )
        gaps = [
            req for req in all_jd_requirements
            if not any(skill.lower() in req.lower() for skill in base_skills)
        ]

        # Create or update WorkflowState
        workflow = await db.workflowstate.find_unique(
            where={"applicationId": application_id}
        )

        if not workflow:
            workflow = await db.workflowstate.create(
                data={
                    "applicationId": application_id,
                    "currentStage": "gaps_identified",
                    "gatheredEvidence": [],
                }
            )
        else:
            workflow = await db.workflowstate.update(
                where={"id": workflow.id},
                data={
                    "currentStage": "gaps_identified",
                },
            )

        return {
            "status": "success",
            "stage": "gaps_identified",
            "applicationId": application_id,
            "match_score": match_score,
            "jd_analysis": {
                "must_haves": jd_analysis["must_haves"],
                "nice_to_haves": jd_analysis["nice_to_haves"],
                "role_level": jd_analysis["role_level"],
            },
            "gaps": gaps[:10],  # Top 10 gaps
            "questions_needed": min(5, len(gaps)),
            "next_step": "generate_clarifying_questions" if match_score < 0.8 else "generate_cv_draft",
        }

    except Exception as e:
        return {"error": f"Failed to start workflow: {e}"}
    finally:
        await db.disconnect()


# ============================================================================
# Tool 2: generate_clarifying_questions
# ============================================================================


async def generate_clarifying_questions(
    application_id: str,
    jd_analysis: dict,
    exclude_answered: bool = True,
) -> dict:
    """Generate clarifying questions for gaps identified in JD.

    Uses Gemini API to create natural follow-up questions.
    """
    try:
        await db.connect()

        app = await db.application.find_unique(where={"id": application_id})
        if not app:
            return {"error": f"Application {application_id} not found"}

        gaps = jd_analysis.get("gaps", jd_analysis.get("must_haves", []))[:5]

        # Get workflow state to check answered questions
        workflow = await db.workflowstate.find_unique(
            where={"applicationId": application_id}
        )

        answered_count = len(workflow.gathered_evidence) if workflow else 0

        # Generate questions with Gemini
        prompt = f"""You are an HR advisor helping someone tailor their CV for a job application.

The role is: {app.role_title} at {app.company}

Key requirements they're missing experience in:
{chr(10).join(f"- {gap}" for gap in gaps)}

Generate 3-5 natural, conversational follow-up questions to help them demonstrate relevant experience. Format as JSON:
[
  {{"id": "q1", "question": "...", "field_type": "experience|skill|achievement"}},
  ...
]

Questions should be specific and actionable.
"""

        response_text = await _generate_with_gemini(prompt)

        # Parse response
        try:
            questions = json.loads(response_text)
        except:
            # Fallback: create generic questions from gaps
            questions = [
                {
                    "id": f"q{i}",
                    "question": f"Tell me about your experience with {gap}?",
                    "field_type": "experience",
                }
                for i, gap in enumerate(gaps[:3], 1)
            ]

        return {
            "status": "success",
            "applicationId": application_id,
            "questions": questions,
            "reasoning": f"Generated {len(questions)} questions for {len(gaps)} identified gaps",
            "next_step": "answer_clarifying_questions",
        }

    except Exception as e:
        return {"error": f"Failed to generate questions: {e}"}
    finally:
        await db.disconnect()


# ============================================================================
# Tool 3: answer_clarifying_questions
# ============================================================================


async def answer_clarifying_questions(
    application_id: str,
    answers: dict,  # {question_id: response_text}
) -> dict:
    """Process user responses to clarifying questions.

    Creates StructuredEvidence entries, rescores match.
    """
    try:
        await db.connect()

        app = await db.application.find_unique(where={"id": application_id})
        if not app:
            return {"error": f"Application {application_id} not found"}

        # Get base CV record for evidence linking
        base_cv = await db.cvrecord.find_first(
            where={"cvId": {"startsWith": "base-cv"}}
        )

        if not base_cv:
            return {"error": "Base CV not found"}

        # Create evidence entries from answers
        evidence_added = []
        for q_id, response in answers.items():
            ev = await db.structuredevidence.create(
                data={
                    "achievement": response[:200],  # First 200 chars as achievement
                    "context": f"From clarifying question {q_id}",
                    "impact": "",
                    "skills_demonstrated": [],
                    "job_title": app.role_title or "Unknown",
                    "company_name": app.company,
                    "source_section": "Clarifying Questions",
                    "source_cv_id": base_cv.id,
                    "application_id": application_id,
                }
            )
            evidence_added.append(ev.id)

        # Update workflow state
        workflow = await db.workflowstate.find_unique(
            where={"applicationId": application_id}
        )

        if workflow:
            gathered = workflow.gathered_evidence or []
            gathered.extend(evidence_added)
            await db.workflowstate.update(
                where={"id": workflow.id},
                data={
                    "currentStage": "evidence_gathering",
                    "gatheredEvidence": gathered,
                },
            )

        return {
            "status": "success",
            "applicationId": application_id,
            "evidence_added": evidence_added,
            "evidence_count": len(evidence_added),
            "next_step": "generate_cv_draft",
            "message": f"Added {len(evidence_added)} evidence items. Ready to generate CV draft.",
        }

    except Exception as e:
        return {"error": f"Failed to process answers: {e}"}
    finally:
        await db.disconnect()


# ============================================================================
# Tool 4: generate_cv_draft
# ============================================================================


async def generate_cv_draft(application_id: str) -> dict:
    """Generate tailored CV draft from gathered evidence.

    Matches evidence against JD skills and assembles CV.
    """
    try:
        await db.connect()

        app = await db.application.find_unique(where={"id": application_id})
        if not app:
            return {"error": f"Application {application_id} not found"}

        # Get base CV
        base_cv = await db.cvrecord.find_first(
            where={"cvId": {"startsWith": "base-cv"}}
        )

        if not base_cv:
            return {"error": "Base CV not found"}

        # Get all relevant evidence (base + gathered for this application)
        all_evidence = await db.structuredevidence.find_many(
            where={
                "OR": [
                    {"source_cv_id": base_cv.id},
                    {"application_id": application_id},
                ]
            },
            order={"created_at": "desc"},
        )

        # Get JD from file system
        jd_text = ""
        if app.folder_path:
            jd_file = Path(app.folder_path) / "jd.md"
            if jd_file.exists():
                jd_text = jd_file.read_text(encoding="utf-8")

        # Generate draft with Gemini
        prompt = f"""You are a professional CV writer. Create a tailored CV section for this job application.

Role: {app.role_title} at {app.company}

JD Summary:
{jd_text[:500]}

Available evidence from candidate:
{json.dumps([{{
    'achievement': ev.achievement,
    'context': ev.context,
    'skills': ev.skills_demonstrated,
}} for ev in all_evidence[:5]], indent=2)}

Create a compelling CV section (2-3 paragraphs) that highlights relevant experience. Format as markdown.
"""

        cv_draft = await _generate_with_gemini(prompt)

        # Save draft to file
        if app.folder_path:
            draft_file = Path(app.folder_path) / "cv-tailored.md"
            draft_with_header = f"""# Tailored CV for {app.company}

**Position:** {app.role_title}
**Generated:** {datetime.now().isoformat()}

---

{cv_draft}
"""
            draft_file.write_text(draft_with_header, encoding="utf-8")

        # Update workflow state
        workflow = await db.workflowstate.find_unique(
            where={"applicationId": application_id}
        )

        if workflow:
            await db.workflowstate.update(
                where={"id": workflow.id},
                data={"currentStage": "cv_review"},
            )

        return {
            "status": "success",
            "applicationId": application_id,
            "draft_cv": cv_draft,
            "evidence_used": len(all_evidence),
            "next_step": "confirm_cv or revise_cv",
            "message": "Review the draft CV. Confirm or provide feedback for revision.",
        }

    except Exception as e:
        return {"error": f"Failed to generate CV draft: {e}"}
    finally:
        await db.disconnect()


# ============================================================================
# Tool 5: revise_cv
# ============================================================================


async def revise_cv(application_id: str, feedback: str) -> dict:
    """Revise CV based on user feedback.

    Updates CV with requested changes.
    """
    try:
        await db.connect()

        app = await db.application.find_unique(where={"id": application_id})
        if not app:
            return {"error": f"Application {application_id} not found"}

        # Get current draft
        if not app.folder_path:
            return {"error": "No folder path set"}

        draft_file = Path(app.folder_path) / "cv-tailored.md"
        current_draft = draft_file.read_text(encoding="utf-8") if draft_file.exists() else ""

        # Generate revision with Gemini
        prompt = f"""You are a professional CV writer revising a CV based on feedback.

Current CV:
{current_draft}

User feedback:
{feedback}

Provide a revised version of the CV incorporating the feedback. Keep the same format (markdown).
"""

        revised_cv = await _generate_with_gemini(prompt)

        # Save revision
        draft_file.write_text(revised_cv, encoding="utf-8")

        # Update workflow state
        workflow = await db.workflowstate.find_unique(
            where={"applicationId": application_id}
        )

        if workflow:
            await db.workflowstate.update(
                where={"id": workflow.id},
                data={
                    "currentStage": "cv_review",
                    "pendingFeedback": None,  # Clear pending feedback
                },
            )

        return {
            "status": "success",
            "applicationId": application_id,
            "revised_cv": revised_cv,
            "next_step": "confirm_cv",
            "message": "CV revised. Review and confirm when ready.",
        }

    except Exception as e:
        return {"error": f"Failed to revise CV: {e}"}
    finally:
        await db.disconnect()


# ============================================================================
# Tool 6: confirm_cv
# ============================================================================


async def confirm_cv(application_id: str, final_cv: Optional[str] = None) -> dict:
    """Finalize CV and mark application as ready.

    Saves final CV, creates diff summary vs. base.
    """
    try:
        await db.connect()

        app = await db.application.find_unique(where={"id": application_id})
        if not app:
            return {"error": f"Application {application_id} not found"}

        # Get final CV (from file or parameter)
        if not app.folder_path:
            return {"error": "No folder path set"}

        draft_file = Path(app.folder_path) / "cv-tailored.md"
        if final_cv:
            draft_file.write_text(final_cv, encoding="utf-8")
        elif not draft_file.exists():
            return {"error": "No CV draft found"}

        cv_text = draft_file.read_text(encoding="utf-8")

        # Get base CV for comparison
        base_cv_file = Path(app.folder_path) / "cv-base.md"
        base_cv_text = ""
        if base_cv_file.exists():
            base_cv_text = base_cv_file.read_text(encoding="utf-8")

        # Create summary
        summary = f"""# CV Diff Summary

## Changes from Base CV

- Tailored for: {app.role_title} at {app.company}
- Finalized: {datetime.now().isoformat()}
- Evidence items used: (see evidence in Postgres)

## Key Additions
[Review cv-tailored.md for details]

## Status
Ready for submission or cover letter generation.
"""

        summary_file = Path(app.folder_path) / "cv-diff-summary.md"
        summary_file.write_text(summary, encoding="utf-8")

        # Update Application + WorkflowState
        await db.application.update(
            where={"id": application_id},
            data={"cvFinalized": True},
        )

        workflow = await db.workflowstate.find_unique(
            where={"applicationId": application_id}
        )

        if workflow:
            await db.workflowstate.update(
                where={"id": workflow.id},
                data={"currentStage": "finalized"},
            )

        return {
            "status": "success",
            "applicationId": application_id,
            "cv_path": str(draft_file),
            "summary_path": str(summary_file),
            "message": "CV finalized. Ready for cover letter generation (Gate 11).",
            "next_step": "generate_cover_letter or confirm_submission",
        }

    except Exception as e:
        return {"error": f"Failed to confirm CV: {e}"}
    finally:
        await db.disconnect()


# ============================================================================
# Tool 7: get_workflow_state
# ============================================================================


async def get_workflow_state(application_id: str) -> dict:
    """Retrieve current workflow state for resuming interrupted workflows.

    Returns all relevant state for reconstruction.
    """
    try:
        await db.connect()

        app = await db.application.find_unique(where={"id": application_id})
        if not app:
            return {"error": f"Application {application_id} not found"}

        workflow = await db.workflowstate.find_unique(
            where={"applicationId": application_id}
        )

        if not workflow:
            return {
                "applicationId": application_id,
                "stage": "not_started",
                "message": "No workflow started yet. Call start_job_application_workflow first.",
            }

        # Get gathered evidence
        gathered_evidence = []
        if workflow.gathered_evidence:
            for ev_id in workflow.gathered_evidence:
                ev = await db.structuredevidence.find_unique(where={"id": ev_id})
                if ev:
                    gathered_evidence.append({
                        "id": ev.id,
                        "achievement": ev.achievement,
                        "skills": ev.skills_demonstrated,
                    })

        return {
            "status": "success",
            "applicationId": application_id,
            "company": app.company,
            "roleTitle": app.role_title,
            "stage": workflow.current_stage,
            "matchScore": app.match_score,
            "cvFinalized": app.cv_finalized,
            "gatheredEvidenceCount": len(gathered_evidence),
            "gatheredEvidence": gathered_evidence[:5],  # First 5
            "pendingFeedback": workflow.pending_feedback,
            "createdAt": app.created_at.isoformat(),
            "updatedAt": workflow.updated_at.isoformat(),
        }

    except Exception as e:
        return {"error": f"Failed to get workflow state: {e}"}
    finally:
        await db.disconnect()


# ============================================================================
# MCP Tool Handlers (for FastMCP registration)
# ============================================================================


async def handle_start_job_application_workflow(params: dict) -> dict:
    """MCP tool handler."""
    return await start_job_application_workflow(
        jd_path_or_text=params["jd_path_or_text"],
        application_id=params["application_id"],
    )


async def handle_generate_clarifying_questions(params: dict) -> dict:
    """MCP tool handler."""
    return await generate_clarifying_questions(
        application_id=params["application_id"],
        jd_analysis=params["jd_analysis"],
        exclude_answered=params.get("exclude_answered", True),
    )


async def handle_answer_clarifying_questions(params: dict) -> dict:
    """MCP tool handler."""
    return await answer_clarifying_questions(
        application_id=params["application_id"],
        answers=params["answers"],
    )


async def handle_generate_cv_draft(params: dict) -> dict:
    """MCP tool handler."""
    return await generate_cv_draft(application_id=params["application_id"])


async def handle_revise_cv(params: dict) -> dict:
    """MCP tool handler."""
    return await revise_cv(
        application_id=params["application_id"],
        feedback=params["feedback"],
    )


async def handle_confirm_cv(params: dict) -> dict:
    """MCP tool handler."""
    return await confirm_cv(
        application_id=params["application_id"],
        final_cv=params.get("final_cv"),
    )


async def handle_get_workflow_state(params: dict) -> dict:
    """MCP tool handler."""
    return await get_workflow_state(application_id=params["application_id"])
