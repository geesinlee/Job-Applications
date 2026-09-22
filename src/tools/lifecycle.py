"""Application lifecycle and tracker tools for Job-Applications MCP server."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


def list_applications(
    company: Optional[str] = None,
    stage: Optional[str] = None,
    include_closed: bool = False,
    tracker_loader: Optional[Callable[[], dict]] = None,
) -> dict:
    """List tracked job applications with pipeline status, elapsed days, and follow-ups.

    Args:
        company: Optional company name filter (case-insensitive substring match).
        stage: Optional pipeline stage filter (e.g. 'applied', 'interview_r1').
        include_closed: If True, include rejected, withrawn, and closed_won applications.
    """
    import job_applications_mcp_server as server

    if tracker_loader is None:
        tracker_loader = server._load_tracker

    tracker = tracker_loader()
    raw_apps = tracker.get("applications", [])
    now = datetime.now(timezone.utc)

    enriched_apps: List[Dict[str, Any]] = []

    for app in raw_apps:
        app_stage = app.get("stage", "")
        if not include_closed and app_stage in ("rejected", "closed_won", "withdrawn"):
            continue

        if stage and app_stage != stage:
            continue

        if company:
            app_comp = app.get("company", "").lower()
            if company.lower() != app_comp and company.lower() not in app_comp:
                continue

        date_created_str = app.get("date_created", "")
        elapsed_days = None
        if date_created_str:
            try:
                date_created = datetime.fromisoformat(date_created_str.replace("Z", "+00:00"))
                elapsed_days = (now - date_created).days
            except Exception:
                elapsed_days = None

        history = app.get("history", [])
        last_updated = history[-1].get("at", date_created_str) if history else date_created_str

        # Resolve LinkedIn URL
        linkedin_url = app.get("metadata", {}).get("linkedin_url") or app.get("jd_source_url")
        if not linkedin_url and hasattr(server, "_find_opportunity_url"):
            try:
                dc = datetime.fromisoformat(date_created_str.replace("Z", "+00:00")) if date_created_str else None
                linkedin_url = server._find_opportunity_url(
                    company=app.get("company"),
                    role_title=app.get("role_title"),
                    date_created=dc,
                )
            except Exception:
                linkedin_url = None

        next_followup = None
        for followup in app.get("followups", []):
            if followup.get("status") == "pending":
                next_followup = {
                    "id": followup.get("id"),
                    "action": followup.get("action_type", "unknown"),
                    "due_date": followup.get("due_date"),
                }
                break

        enriched = {
            "id": app.get("id"),
            "company": app.get("company"),
            "role_title": app.get("role_title"),
            "stage": app_stage,
            "interview_round": app.get("interview_round"),
            "date_created": date_created_str,
            "days_elapsed": elapsed_days,
            "linkedin_url": linkedin_url,
            "next_followup": next_followup,
            "last_updated": last_updated,
            "jd_path": app.get("jd_path"),
        }
        enriched_apps.append(enriched)

    enriched_apps.sort(key=lambda a: a.get("date_created") or "", reverse=True)

    result = {
        "ok": True,
        "count": len(enriched_apps),
        "total": len(enriched_apps),
        "applications": enriched_apps,
        "opportunities": enriched_apps,
    }

    if company and len({a["role_title"] for a in enriched_apps}) > 1:
        result["note"] = (
            f"Multiple roles tracked at {company}; pass role_title to company-scoped tools to disambiguate."
        )

    return result


def get_application_status(
    company: Optional[str] = None,
    role_title: Optional[str] = None,
    application_id: Optional[str] = None,
    tracker_loader: Optional[Callable[[], dict]] = None,
    artefacts_dir: Optional[Path] = None,
) -> dict:
    """Check comprehensive application status: workflow artifacts, pipeline stage, and follow-ups.

    Args:
        company: Target employer name.
        role_title: Optional role title (for disambiguation).
        application_id: Optional UUID identifier (can be used instead of company).
    """
    import job_applications_mcp_server as server

    if tracker_loader is None:
        tracker_loader = server._load_tracker
    if artefacts_dir is None:
        artefacts_dir = server.ARTEFACTS_DIR

    tracker = tracker_loader()
    app = None

    if application_id:
        for a in tracker.get("applications", []):
            if a.get("id") == application_id:
                app = a
                company = a.get("company")
                role_title = a.get("role_title")
                break
        if not app and not company:
            return {"ok": False, "error": "opportunity_not_found", "application_id": application_id}

    if not company:
        return {"ok": False, "error": "missing_identifier", "hint": "Provide company or application_id"}

    try:
        company_dir = server._resolve_company_folder(company, role_title, tracker)
    except server.AmbiguousRoleError as e:
        return {"ok": False, "error": "ambiguous_role", "company": e.company, "roles": e.roles}

    if not app:
        app = server._find_application(tracker, company, role_title)

    if not company_dir.exists():
        return {
            "ok": True,
            "company": company,
            "role_title": role_title or (app.get("role_title") if app else None),
            "exists": False,
            "next_steps": ["Call create_application first to set up the company folder."],
        }

    files = {f.name: f for f in company_dir.iterdir() if f.is_file()}
    cv_file = server._find_cv(company_dir)

    steps = {
        "job_description": "JD.md" in files,
        "research": "research.md" in files,
        "gap_analysis": "gap_analysis.md" in files,
        "tailored_cv": cv_file is not None,
        "cover_letter": "Cover_Letter.md" in files,
        "match_score": bool(app and app.get("match_score")),
        "interview_notes": "interview_notes.md" in files,
        "submitted": bool(app and app.get("stage") in ("applied", "interview_r1", "interview_r2", "interview_r3", "offer", "closed_won")),
    }

    # Determine next suggested steps
    next_steps = []
    if not steps["job_description"]:
        next_steps.append("Call ingest_jd or paste job description into JD.md.")
    elif not steps["research"]:
        next_steps.append("Run company_research to understand key business drivers.")
    elif not steps["match_score"]:
        next_steps.append("Run score_match to assess profile fit against JD.")
    elif not steps["gap_analysis"]:
        next_steps.append("Run analyse_gaps to identify positioning strategies.")
    elif not steps["tailored_cv"]:
        next_steps.append("Run start_job_application_workflow to produce an evidence-backed CV draft.")
    elif not steps["cover_letter"]:
        next_steps.append("Run generate_cover_letter to draft a tailored letter.")
    elif not steps["submitted"]:
        next_steps.append("Review materials and call mark_submitted upon submission.")
    else:
        next_steps.append("Application submitted. Monitor pipeline stage or log interview notes.")

    now = datetime.now(timezone.utc)
    date_created_str = app.get("date_created", "") if app else ""
    elapsed_days = None
    if date_created_str:
        try:
            dc = datetime.fromisoformat(date_created_str.replace("Z", "+00:00"))
            elapsed_days = (now - dc).days
        except Exception:
            elapsed_days = None

    result = {
        "ok": True,
        "company": company,
        "role_title": role_title or (app.get("role_title") if app else None),
        "exists": True,
        "application_id": app.get("id") if app else None,
        "id": app.get("id") if app else None,
        "stage": app.get("stage") if app else None,
        "interview_round": app.get("interview_round") if app else None,
        "days_elapsed": elapsed_days,
        "steps": steps,
        "next_steps": next_steps,
        "files_present": sorted(list(files.keys())),
        "history": app.get("history", []) if app else [],
        "followups": app.get("followups", []) if app else [],
        "outputs": app.get("outputs", {}) if app else {},
        "match_score": app.get("match_score") if app else None,
        "linkedin_url": app.get("metadata", {}).get("linkedin_url") or app.get("jd_source_url") if app else None,
    }
    return result


def update_application(
    company: Optional[str] = None,
    role_title: Optional[str] = None,
    new_stage: Optional[str] = None,
    application_id: Optional[str] = None,
    linkedin_url: Optional[str] = None,
    interview_round: Optional[str] = None,
    tracker_loader: Optional[Callable[[], dict]] = None,
    tracker_saver: Optional[Callable[[dict], None]] = None,
) -> dict:
    """Update an application's pipeline stage, LinkedIn URL, or interview round.

    Args:
        company: Target employer name.
        role_title: Role title (to disambiguate multiple roles at same employer).
        new_stage: New pipeline stage (e.g. 'interview_r1', 'applied', 'rejected').
        application_id: UUID of the application (alternative to company + role_title).
        linkedin_url: New or updated LinkedIn job posting URL.
        interview_round: Specific interview label/round.
    """
    import job_applications_mcp_server as server

    if tracker_loader is None:
        tracker_loader = server._load_tracker
    if tracker_saver is None:
        tracker_saver = server._save_tracker

    tracker = tracker_loader()
    app = None

    if application_id:
        for a in tracker.get("applications", []):
            if a.get("id") == application_id:
                app = a
                company = a.get("company")
                role_title = a.get("role_title")
                break
        if not app and not company:
            return {"ok": False, "error": "opportunity_not_found", "application_id": application_id}

    if not company:
        return {"ok": False, "error": "missing_identifier", "hint": "Provide company or application_id"}

    if not app:
        app = server._find_application(tracker, company, role_title)
    if not app:
        return {"ok": False, "error": "application_not_found", "company": company, "role_title": role_title}

    updated_fields = []

    if linkedin_url:
        if "metadata" not in app:
            app["metadata"] = {}
        app["metadata"]["linkedin_url"] = linkedin_url
        app["jd_source_url"] = linkedin_url
        updated_fields.append("linkedin_url")

    if interview_round is not None:
        app["interview_round"] = interview_round
        updated_fields.append("interview_round")

    if new_stage:
        current_stage = app.get("stage", "new")
        if not server._is_valid_stage(new_stage):
            return {
                "ok": False,
                "error": "invalid_stage",
                "valid_stages": [
                    "new", "applied", "screening", "interview_r1", "interview_r2",
                    "interview_r3", "offer", "rejected", "withdrawn", "closed_won",
                ],
            }

        allowed = server._allowed_next_stages(current_stage)
        can_advance = new_stage in allowed
        if not can_advance and server._is_interview_stage(current_stage) and server._is_interview_stage(new_stage):
            current_round = server._interview_round(current_stage)
            new_round = server._interview_round(new_stage)
            can_advance = current_round is not None and new_round is not None and new_round > current_round
        if not can_advance:
            return {
                "ok": False,
                "error": "invalid_transition",
                "current_stage": current_stage,
                "requested_stage": new_stage,
                "allowed_stages": sorted(allowed),
            }

        previous_stage = current_stage
        now = server._utc_now()
        app["stage"] = new_stage
        if "history" not in app:
            app["history"] = []
        app["history"].append({"stage": new_stage, "at": now})

        # Update interview round based on stage
        if server._is_interview_stage(new_stage):
            app["interview_round"] = server._interview_round(new_stage)
        elif new_stage in ("offer", "rejected", "withdrawn", "closed_won"):
            app["interview_round"] = None

        server._auto_create_followup(app, new_stage)
        if new_stage in ("rejected", "withdrawn", "closed_won"):
            server._cancel_followup_emails(app)

        updated_fields.append("stage")

    tracker_saver(tracker)

    result = {
        "ok": True,
        "application_id": app.get("id"),
        "id": app.get("id"),
        "company": app.get("company"),
        "role_title": app.get("role_title"),
        "stage": app.get("stage"),
        "updated_fields": updated_fields,
        "interview_round": app.get("interview_round"),
        "linkedin_url": app.get("metadata", {}).get("linkedin_url"),
    }
    if new_stage:
        result["previous_stage"] = previous_stage
        result["new_stage"] = new_stage
    return result
