"""Profile and Base CV tools for Job-Applications MCP server."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


def get_cv(
    document_type: str = "base",
    base_cv_path: Optional[Path] = None,
    ref_cv_path: Optional[Path] = None,
) -> dict:
    """Retrieve base or reference CV markdown content.

    Args:
        document_type: 'base' for master ground-truth CV, or 'reference' for keyword pre-filtering CV.
        base_cv_path: Optional override path for base CV.
        ref_cv_path: Optional override path for reference CV.
    """
    import job_applications_mcp_server as server

    if document_type.lower() in ("base", "master"):
        path = base_cv_path or server.BASE_CV_PATH
    elif document_type.lower() in ("reference", "ref"):
        path = ref_cv_path or Path(
            os.environ.get(
                "JOB_APP_REFERENCE_CV_PATH",
                str(server.ARTEFACTS_DIR / "base_cv" / "Reference_CV.md"),
            )
        )
    else:
        return {
            "ok": False,
            "error": "invalid_document_type",
            "hint": "document_type must be 'base' or 'reference'",
        }

    try:
        if not path.exists():
            return {
                "ok": False,
                "error": f"{document_type}_cv_not_found",
                "path": str(path),
                "hint": f"Ensure {path} exists or configure appropriate environment variable.",
            }
        content = path.read_text(encoding="utf-8")
        return {
            "ok": True,
            "document_type": document_type,
            "cv_path": str(path),
            "cv_content": content,
            "content_length": len(content),
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "cv_path": str(path)}


def get_profile_summary(profile_loader: Optional[Callable[[], dict]] = None) -> dict:
    """Return a condensed view of profile.json: current role, experience, top skills, education."""
    import job_applications_mcp_server as server

    if profile_loader is None:
        profile_loader = server._load_profile

    profile = profile_loader()
    if not profile.get("work_experience") and not profile.get("skills"):
        return {"ok": True, "setup_required": True}

    return {
        "ok": True,
        "setup_required": False,
        "headline": profile.get("headline"),
        "current_role": profile.get("current_role"),
        "years_of_experience": server._compute_years_of_experience(profile.get("work_experience", [])),
        "top_skills": server._top_n_skills(
            profile.get("work_experience", []), profile.get("skills", []), n=5
        ),
        "education": profile.get("education", []),
        "last_updated": profile.get("last_updated", {}),
    }


def update_profile(
    source: str,
    cv_path: Optional[str] = None,
    text: Optional[str] = None,
    profile_loader: Optional[Callable[[], dict]] = None,
    profile_saver: Optional[Callable[[dict], None]] = None,
    base_cv_path: Optional[Path] = None,
) -> dict:
    """Seed or update profile.json from a CV file or freeform session notes."""
    import job_applications_mcp_server as server

    if profile_loader is None:
        profile_loader = server._load_profile
    if profile_saver is None:
        profile_saver = server._save_profile
    if base_cv_path is None:
        base_cv_path = server.BASE_CV_PATH

    if source == "cv":
        path = Path(cv_path) if cv_path else base_cv_path
        if not path.exists():
            return {"ok": False, "error": "file_not_found", "cv_path": str(path)}
        incoming = server._seed_profile_from_cv(path)
    elif source == "session":
        if not text:
            return {"ok": False, "error": "text_required"}
        incoming = server._parse_linkedin_export(text)
    else:
        return {"ok": False, "error": "unsupported_source", "source": source}

    existing = profile_loader()
    merged = server._merge_profile(existing, incoming, source)
    profile_saver(merged)

    fields_updated = sum(
        1
        for section in ("work_experience", "education", "certifications", "skills")
        if json.dumps(existing.get(section), sort_keys=True)
        != json.dumps(merged.get(section), sort_keys=True)
    )

    return {
        "ok": True,
        "source": source,
        "fields_updated": fields_updated,
        "work_experience_count": len(merged.get("work_experience", [])),
        "education_count": len(merged.get("education", [])),
        "skills_count": len(merged.get("skills", [])),
        "conflicts_count": len(merged.get("conflicts", [])),
    }


def refresh_profile_from_linkedin(
    url: Optional[str] = None,
    file_path: Optional[str] = None,
    text: Optional[str] = None,
    profile_loader: Optional[Callable[[], dict]] = None,
    profile_saver: Optional[Callable[[dict], None]] = None,
) -> dict:
    """Merge a LinkedIn profile export (URL, file, or pasted text) into profile.json."""
    import job_applications_mcp_server as server

    if profile_loader is None:
        profile_loader = server._load_profile
    if profile_saver is None:
        profile_saver = server._save_profile

    sources_given = sum(1 for s in (url, file_path, text) if s)
    if sources_given == 0:
        return {"ok": False, "error": "no_source_given"}
    if sources_given > 1:
        return {"ok": False, "error": "multiple_sources_given"}

    if url:
        try:
            import requests

            raw_text = server._ingest_jd_url(url)
        except Exception as e:
            return {"ok": False, "error": "url_blocked_or_unreachable", "detail": str(e)}
    elif file_path:
        source_path = Path(file_path)
        if not source_path.exists():
            return {"ok": False, "error": "file_not_found", "file_path": file_path}
        suffix = source_path.suffix.lower()
        if suffix == ".pdf":
            raw_text = server._extract_pdf_text(source_path)
        elif suffix in (".txt", ".md"):
            raw_text = source_path.read_text(encoding="utf-8")
        else:
            return {"ok": False, "error": "unsupported_format", "file_path": file_path}
    else:
        raw_text = text

    if not raw_text or not raw_text.strip():
        return {"ok": False, "error": "empty_content"}

    lowered = raw_text.lower()
    if not any(marker in lowered for marker in ("experience", "education", "skills")):
        return {"ok": False, "error": "invalid_linkedin_format"}

    incoming = server._parse_linkedin_export(raw_text)
    existing = profile_loader()
    conflicts_before = len(existing.get("conflicts", []))
    merged = server._merge_profile(existing, incoming, "linkedin")
    profile_saver(merged)

    return {
        "ok": True,
        "work_experience_extracted": len(incoming.get("work_experience", [])),
        "education_extracted": len(incoming.get("education", [])),
        "skills_extracted": len(incoming.get("skills", [])),
        "conflicts_flagged": len(merged.get("conflicts", [])) - conflicts_before,
    }
