"""Interview context capture tools for Gate 10 workflow.

Captures Claude Desktop conversations (transcripts), extracts metadata,
and stores in both NAS file system and Postgres database.
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional
import asyncio

from prisma import Prisma

# Initialize Prisma (assumes DATABASE_URL env var is set)
db = Prisma()


async def log_interview_context(
    application_id: str,
    interview_round: str,  # "r1", "r2", "r3", etc.
    transcript: str,  # Raw conversation from Claude Desktop
    notes: Optional[str] = None,  # User-provided notes
) -> dict:
    """Log interview context from Claude Desktop conversation.

    Captures transcript, extracts questions/themes, creates InterviewContext record.

    Args:
        application_id: UUID of the application
        interview_round: Interview round (r1, r2, r3)
        transcript: Raw transcript from Claude Desktop
        notes: Optional user-provided notes

    Returns:
        {
            "status": "success",
            "interview_context_id": str,
            "transcript_path": str,
            "notes_path": str,
            "extracted": {
                "questions": [...],
                "key_themes": [...],
                "next_steps": str
            }
        }
    """
    try:
        await db.connect()

        # Get application + folder path
        app = await db.application.find_unique(where={"id": application_id})
        if not app:
            return {"error": f"Application {application_id} not found"}

        if not app.folder_path:
            return {"error": f"Application {application_id} has no folder_path set"}

        # Create interview round directory
        app_folder = Path(app.folder_path)
        interview_folder = app_folder / f"interview-{interview_round}"
        interview_folder.mkdir(parents=True, exist_ok=True)

        # Save transcript
        transcript_path = interview_folder / "transcript.md"
        transcript_with_header = f"""# {app.company} - {interview_round.upper()} Interview Transcript

**Date:** {datetime.now().isoformat()}
**Application:** {app.role_title} at {app.company}

---

{transcript}
"""
        transcript_path.write_text(transcript_with_header, encoding="utf-8")

        # Save notes if provided
        notes_path = None
        if notes:
            notes_path = interview_folder / "notes.md"
            notes_with_header = f"""# {app.company} - {interview_round.upper()} Interview Notes

**Date:** {datetime.now().isoformat()}

{notes}
"""
            notes_path.write_text(notes_with_header, encoding="utf-8")

        # Extract metadata from transcript
        extracted = _extract_interview_metadata(transcript)

        # Create InterviewContext record
        context = await db.interviewcontext.create(
            data={
                "applicationId": application_id,
                "interviewRound": interview_round,
                "transcriptPath": str(transcript_path.relative_to(app_folder)),
                "notesPath": str(notes_path.relative_to(app_folder)) if notes_path else None,
                "questions": extracted["questions"],
                "keyThemes": extracted["key_themes"],
                "nextSteps": extracted.get("next_steps"),
            }
        )

        # Create follow-ups.md (empty, for user to fill in)
        followups_path = interview_folder / "follow-ups.md"
        followups_path.write_text(
            f"""# {app.company} - {interview_round.upper()} Follow-ups

## Next Steps
{extracted.get('next_steps', '(to be determined)')}

## Action Items
- [ ] Task 1
- [ ] Task 2

## Timeline
[Document expected timeline for next steps]
""",
            encoding="utf-8",
        )

        return {
            "status": "success",
            "interview_context_id": context.id,
            "transcript_path": str(transcript_path),
            "notes_path": str(notes_path) if notes_path else None,
            "followups_path": str(followups_path),
            "extracted": {
                "questions": extracted["questions"],
                "key_themes": extracted["key_themes"],
                "next_steps": extracted.get("next_steps"),
            },
        }

    except Exception as e:
        return {"error": f"Failed to log interview context: {e}"}
    finally:
        await db.disconnect()


def _extract_interview_metadata(transcript: str) -> dict:
    """Extract questions, themes, and next steps from interview transcript.

    Uses simple heuristics to identify:
    - Questions (lines with ? and speaker attribution)
    - Key themes (recurring topics)
    - Next steps (phrases like "next time", "follow up", etc.)

    Args:
        transcript: Raw interview transcript

    Returns:
        {
            "questions": [...],
            "key_themes": [...],
            "next_steps": str
        }
    """
    lines = transcript.split("\n")
    questions = []
    all_text = transcript.lower()

    # Extract questions (simple heuristic: contains ? and speaker attribution)
    for line in lines:
        if "?" in line and len(line.strip()) > 10:
            # Try to extract the actual question
            clean_line = re.sub(r"^[a-z\s]+:", "", line, flags=re.IGNORECASE).strip()
            if clean_line and clean_line not in questions:
                questions.append(clean_line)

    # Identify key themes (topics mentioned multiple times)
    key_topics = {
        "leadership": ["lead", "team", "manage"],
        "technical": ["technical", "code", "system", "architecture"],
        "sales": ["revenue", "deal", "customer", "account"],
        "strategy": ["strategy", "roadmap", "vision", "plan"],
        "communication": ["communication", "presentation", "explain"],
        "experience": ["experience", "worked", "previous"],
    }

    themes = []
    for theme, keywords in key_topics.items():
        if any(keyword in all_text for keyword in keywords):
            themes.append(theme)

    # Extract next steps
    next_steps = None
    next_step_patterns = [
        r"next (?:step|stage|round|interview)[^\n]*",
        r"(?:we|you) will[^\n]*",
        r"(?:follow[- ]up|timeline)[^\n]*",
        r"(?:expected|scheduled) for[^\n]*",
    ]

    for pattern in next_step_patterns:
        match = re.search(pattern, all_text, re.IGNORECASE)
        if match:
            next_steps = match.group(0).strip()
            break

    return {
        "questions": questions[:5],  # Top 5 questions
        "key_themes": themes,
        "next_steps": next_steps or "No explicit next steps mentioned",
    }


async def get_interview_context(
    application_id: str, interview_round: str
) -> dict:
    """Retrieve interview context for an application + round.

    Args:
        application_id: UUID of the application
        interview_round: Interview round (r1, r2, r3)

    Returns:
        InterviewContext record or error
    """
    try:
        await db.connect()

        context = await db.interviewcontext.find_first(
            where={
                "applicationId": application_id,
                "interviewRound": interview_round,
            }
        )

        if not context:
            return {
                "error": f"No interview context found for {application_id} round {interview_round}"
            }

        return {
            "id": context.id,
            "applicationId": context.application_id,
            "interviewRound": context.interview_round,
            "transcriptPath": context.transcript_path,
            "notesPath": context.notes_path,
            "questions": context.questions,
            "keyThemes": context.key_themes,
            "nextSteps": context.next_steps,
            "createdAt": context.created_at.isoformat(),
        }

    except Exception as e:
        return {"error": f"Failed to retrieve interview context: {e}"}
    finally:
        await db.disconnect()


async def list_interview_contexts(application_id: str) -> dict:
    """List all interview contexts for an application.

    Args:
        application_id: UUID of the application

    Returns:
        List of InterviewContext records
    """
    try:
        await db.connect()

        contexts = await db.interviewcontext.find_many(
            where={"applicationId": application_id},
            order={"interviewRound": "asc"},
        )

        return {
            "applicationId": application_id,
            "interviews": [
                {
                    "id": c.id,
                    "round": c.interview_round,
                    "transcriptPath": c.transcript_path,
                    "keyThemes": c.key_themes,
                    "createdAt": c.created_at.isoformat(),
                }
                for c in contexts
            ],
        }

    except Exception as e:
        return {"error": f"Failed to list interview contexts: {e}"}
    finally:
        await db.disconnect()


# Async entry points for MCP integration
async def handle_log_interview_context(params: dict) -> dict:
    """MCP tool handler for log_interview_context."""
    return await log_interview_context(
        application_id=params["application_id"],
        interview_round=params["interview_round"],
        transcript=params["transcript"],
        notes=params.get("notes"),
    )


async def handle_get_interview_context(params: dict) -> dict:
    """MCP tool handler for get_interview_context."""
    return await get_interview_context(
        application_id=params["application_id"],
        interview_round=params["interview_round"],
    )


async def handle_list_interview_contexts(params: dict) -> dict:
    """MCP tool handler for list_interview_contexts."""
    return await list_interview_contexts(application_id=params["application_id"])


if __name__ == "__main__":
    # Test
    test_transcript = """
Claude: Tell me about your experience leading teams.

User: I've led teams of 5-15 engineers over the past 8 years, focusing on technical strategy and architecture.

Claude: What's your biggest accomplishment?

User: Migrated a legacy monolith to microservices, reducing deployment time from 2 hours to 10 minutes.

Claude: Next steps?

User: We'll do a technical assessment and then schedule a second round in two weeks.
"""

    result = asyncio.run(
        log_interview_context(
            application_id="test-app-123",
            interview_round="r1",
            transcript=test_transcript,
            notes="Strong technical background. Questions about scaling.",
        )
    )
    print(json.dumps(result, indent=2))
