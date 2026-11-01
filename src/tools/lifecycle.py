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
            "applied_at": app.get("applied_at"),
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
        "backend": "PostgreSQL" if getattr(server, "STORAGE_BACKEND", "file") == "postgres" else getattr(server, "STORAGE_BACKEND", "file"),
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
        "backend": "PostgreSQL" if getattr(server, "STORAGE_BACKEND", "file") == "postgres" else getattr(server, "STORAGE_BACKEND", "file"),
    }
    return result


def update_application(
    company: Optional[str] = None,
    role_title: Optional[str] = None,
    new_stage: Optional[str] = None,
    application_id: Optional[str] = None,
    linkedin_url: Optional[str] = None,
    interview_round: Optional[str] = None,
    new_company: Optional[str] = None,
    new_role_title: Optional[str] = None,
    tracker_loader: Optional[Callable[[], dict]] = None,
    tracker_saver: Optional[Callable[[dict], None]] = None,
) -> dict:
    """Update an application's pipeline stage, LinkedIn URL, or interview round.

    Args:
        company: Target employer name. Used only as a lookup key to locate the record.
        role_title: Role title (to disambiguate multiple roles at same employer).
            Used only as a lookup key to locate the record.
        new_stage: New pipeline stage (e.g. 'interview_r1', 'applied', 'rejected').
        application_id: UUID of the application (alternative to company + role_title).
        linkedin_url: New or updated LinkedIn job posting URL.
        interview_round: Specific interview label/round.
        new_company: Rename target for the stored employer name. Distinct from the
            `company` lookup key: when provided, the located record's `company` is
            rewritten to this value and persisted.
        new_role_title: Rename target for the stored role title. Distinct from the
            `role_title` lookup key: when provided, the located record's `role_title`
            is rewritten to this value and persisted.
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

    # Rename write-back: applied only after `app` is resolved, so lookup
    # semantics (including the application_id branch) are untouched. Both
    # fields are rewritten before the single tracker_saver call so the change
    # is atomic with respect to persistence.
    rename_audit = []
    if new_company is not None and new_company != app.get("company"):
        old_company = app.get("company")
        app["company"] = new_company
        updated_fields.append("company")
        rename_audit.append(("company", old_company, new_company))
    if new_role_title is not None and new_role_title != app.get("role_title"):
        old_role_title = app.get("role_title")
        app["role_title"] = new_role_title
        updated_fields.append("role_title")
        rename_audit.append(("role_title", old_role_title, new_role_title))

    if rename_audit:
        if "audit" not in app or not isinstance(app.get("audit"), list):
            app["audit"] = []
        now = server._utc_now()
        for field, old_value, new_value in rename_audit:
            app["audit"].append({
                "action": "rename",
                "field": field,
                "old": old_value,
                "new": new_value,
                "at": now,
            })

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
        "backend": "PostgreSQL" if getattr(server, "STORAGE_BACKEND", "file") == "postgres" else getattr(server, "STORAGE_BACKEND", "file"),
    }
    if new_stage:
        result["previous_stage"] = previous_stage
        result["new_stage"] = new_stage
    return result


# Stages that mean a record has actually been applied. Interview rounds
# (interview_rN) are matched via regex; 'closed_won' is stale legacy naming
# kept defensively so old records are not falsely blocked. Terminal exits
# ('rejected'/'withdrawn') are resolved by _has_reached_applied via history.
_APPLIED_OR_LATER_STAGES = {"applied", "screening", "offer", "accepted", "closed_won"}


def _has_reached_applied(app: dict) -> bool:
    """Return True if this application record has actually been applied.

    Stage gate for set_applied_date. Direct membership covers records currently
    at an applied-or-later stage (interview_rN counts; import
    job_applications_mcp_server as server inside the body — repo idiom — and
    use server._is_interview_stage).

    The judgment call: 'rejected'/'withdrawn' are reachable both from 'new'
    (never applied) and from 'applied'+ (was applied). Only the record's
    'history' can tell them apart — a history entry with stage == 'applied'
    counts as proof; everything else is False.
    """
    import job_applications_mcp_server as server

    stage = app.get("stage") or ""
    if stage in _APPLIED_OR_LATER_STAGES or server._is_interview_stage(stage):
        return True
    if stage in ("rejected", "withdrawn"):
        return any(
            isinstance(entry, dict) and entry.get("stage") == "applied"
            for entry in app.get("history", [])
        )
    return False


def set_applied_date(
    application_id: str,
    applied_date: str,
    approved_by_user: bool = False,
    force: bool = False,
    reason: Optional[str] = None,
    tracker_loader: Optional[Callable[[], dict]] = None,
    tracker_saver: Optional[Callable[[dict], None]] = None,
) -> dict:
    """Set the actual date a job application was submitted (backdating support).

    date_created reflects when tracking started, not when the user applied.
    Strictly validated: ID-only lookup, stage gate, ISO-8601 within the last
    12 months (inclusive), no future dates, confirm-gate dry run by default,
    immutable once set (force=True to overwrite), audit entry per write.
    """
    import job_applications_mcp_server as server

    if tracker_loader is None:
        tracker_loader = server._load_tracker
    if tracker_saver is None:
        tracker_saver = server._save_tracker

    if not isinstance(application_id, str) or not application_id.strip():
        return {
            "ok": False,
            "error": "missing_application_id",
            "hint": "Provide the application UUID (get ids from list_applications).",
        }
    application_id = application_id.strip()

    if not isinstance(applied_date, str) or not applied_date.strip():
        return {
            "ok": False,
            "error": "missing_applied_date",
            "hint": "Provide the real application date, ISO-8601 (e.g. '2026-06-01').",
        }

    try:
        parsed = datetime.fromisoformat(applied_date.strip().replace("Z", "+00:00"))
    except ValueError:
        return {
            "ok": False,
            "error": "invalid_applied_date",
            "applied_date": applied_date,
            "expected_format": "ISO-8601, e.g. '2026-06-01' or '2026-06-01T09:30:00Z'",
        }
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        parsed = parsed.astimezone(timezone.utc)
    normalized = parsed.strftime("%Y-%m-%dT%H:%M:%SZ")

    now = datetime.now(timezone.utc)

    tracker = tracker_loader()
    app = None
    for a in tracker.get("applications", []):
        if a.get("id") == application_id:
            app = a
            break
    if app is None:
        return {
            "ok": False,
            "error": "application_not_found",
            "application_id": application_id,
            "hint": "Use list_applications to find the record id.",
        }

    if not _has_reached_applied(app):
        return {
            "ok": False,
            "error": "stage_not_applied",
            "application_id": application_id,
            "current_stage": app.get("stage"),
            "hint": "Only records at stage 'applied' or later can carry an applied date.",
        }

    if parsed > now:
        return {
            "ok": False,
            "error": "future_date",
            "applied_date": normalized,
            "today": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

    try:
        cutoff = now.replace(year=now.year - 1)
    except ValueError:  # Feb 29 -> non-leap target year
        cutoff = now.replace(year=now.year - 1, day=28)
    if parsed < cutoff:
        return {
            "ok": False,
            "error": "out_of_range",
            "applied_date": normalized,
            "earliest_allowed": cutoff.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "hint": "Backdating is limited to the last 12 months (boundary inclusive).",
        }

    current = app.get("applied_at")
    if current and not force:
        return {
            "ok": False,
            "error": "already_set",
            "application_id": application_id,
            "current_applied_at": current,
            "hint": "applied_at is immutable once set; pass force=True to overwrite.",
        }

    audit_entry = {
        "field": "applied_at",
        "old": current,
        "new": normalized,
        "at": server._utc_now(),
        "reason": reason,
        "forced": bool(force),
    }

    if not approved_by_user:
        return {
            "ok": False,
            "error": "requires_approval",
            "requires_review": True,
            "application_id": application_id,
            "company": app.get("company"),
            "role_title": app.get("role_title"),
            "stage": app.get("stage"),
            "preview": {
                "field": "applied_at",
                "current_applied_at": current,
                "new_applied_at": normalized,
                "is_overwrite": bool(current),
                "checks": {
                    "id_found": True,
                    "stage_at_or_after_applied": True,
                    "date_format": True,
                    "not_future": True,
                    "within_12_months": True,
                    "immutability": "ok_with_force" if current else "ok",
                },
            },
            "audit_would_append": audit_entry,
            "hint": "Validation passed. Re-run with approved_by_user=True to apply"
                    + (" (add force=True to overwrite the existing date)." if current else "."),
        }

    app["applied_at"] = normalized
    app.setdefault("audit", []).append(audit_entry)
    tracker_saver(tracker)

    return {
        "ok": True,
        "application_id": application_id,
        "company": app.get("company"),
        "role_title": app.get("role_title"),
        "stage": app.get("stage"),
        "applied_at": normalized,
        "previous_applied_at": current,
        "forced": bool(force),
        "audit_entry": audit_entry,
        "audit_count": len(app["audit"]),
    }
