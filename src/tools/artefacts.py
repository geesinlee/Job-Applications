"""Artefacts, intelligence context-prep, and persistence tools for Job-Applications MCP server."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


def save_application_artefact(
    company: str,
    document_type: str,
    content: Union[str, dict],
    role_title: Optional[str] = None,
    section: Optional[str] = None,
    tone: Optional[str] = None,
    format: Optional[str] = None,
    tracker_loader: Optional[Callable[[], dict]] = None,
    tracker_saver: Optional[Callable[[dict], None]] = None,
    folder_resolver: Optional[Callable[[str, Optional[str], dict], Path]] = None,
) -> dict:
    """Save an application artefact (research, cover letter, pitch, gap analysis, notes, etc.).

    Args:
        company: Target employer name.
        document_type: Type of artefact:
            'research', 'territory_map', 'cover_letter', 'pitch',
            'gap_analysis', 'learning_program', 'interview_notes', 'match_score'.
        content: Markdown string content (or dict for structured match_score/gaps).
        role_title: Optional role title (required if multiple roles tracked at company).
        section: Section name when document_type is 'interview_notes' (e.g. 'Recruiter Screen').
        tone: Tone when document_type is 'cover_letter' ('conversational' or 'formal').
        format: Format when document_type is 'pitch' ('standard', 'star', or 'brief').
    """
    import job_applications_mcp_server as server

    doc_type = document_type.lower().strip()
    backend_name = "PostgreSQL" if getattr(server, "STORAGE_BACKEND", "file") == "postgres" else getattr(server, "STORAGE_BACKEND", "file")

    # Route to existing validated implementations in server to preserve 100% fidelity & tests
    if doc_type == "research":
        res = server.save_research(company=company, content=str(content), role_title=role_title)
    elif doc_type in ("territory_map", "territory"):
        res = server.save_territory_map(company=company, content=str(content), role_title=role_title)
    elif doc_type in ("cover_letter", "coverletter"):
        res = server.save_cover_letter(
            company=company,
            content=str(content),
            tone=tone or "conversational",
            role_title=role_title,
        )
    elif doc_type == "pitch":
        res = server.save_pitch(
            company=company,
            content=str(content),
            format=format or "standard",
            role_title=role_title,
        )
    elif doc_type in ("gap_analysis", "gaps"):
        res = server.save_gap_analysis(company=company, role_title=role_title or "", gaps=content)
    elif doc_type in ("learning_program", "learning"):
        res = server.save_learning_program(company=company, role_title=role_title or "", program=content)
    elif doc_type in ("interview_notes", "notes"):
        res = server.save_interview_notes(
            company=company,
            content=str(content),
            section=section or "General Notes",
            role_title=role_title,
        )
    elif doc_type in ("match_score", "score"):
        if isinstance(content, dict):
            res = server.save_match_score(
                company=company,
                role_title=role_title or "",
                overall=content.get("overall", 0),
                sub_scores=content.get("sub_scores", {}),
                reasoning=content.get("reasoning", ""),
                strengths=content.get("strengths", []),
                gaps=content.get("gaps", []),
                missing_skills=content.get("missing_skills", []),
            )
        else:
            return {"ok": False, "error": "match_score_requires_dict", "hint": "content must be a dict with overall, sub_scores, reasoning, etc."}
    else:
        return {
            "ok": False,
            "error": "unsupported_document_type",
            "supported_types": [
                "research",
                "territory_map",
                "cover_letter",
                "pitch",
                "gap_analysis",
                "learning_program",
                "interview_notes",
                "match_score",
            ],
        }
    if isinstance(res, dict):
        res.setdefault("backend", backend_name)
    return res
