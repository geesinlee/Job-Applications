"""Discovery tools for Job-Applications MCP server.

Parses LinkedIn job discovery digests and ingests surfaced opportunities.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


def list_job_discoveries(
    date_str: str = "",
    limit: Optional[int] = None,
    days_back: int = 1,
    include_below_threshold: bool = False,
    artefacts_dir: Optional[Path] = None,
) -> dict:
    """List new job opportunities discovered from LinkedIn feed.

    Supports querying a specific digest date (e.g. '2026-08-06') or looking back
    a number of days from today.

    Args:
        date_str: Specific ISO date (YYYY-MM-DD) to inspect. If empty, uses days_back from today.
        limit: Maximum number of opportunities to return (default: all).
        days_back: Number of days to look back when date_str is empty (default: 1).
        include_below_threshold: Include rejected cards and their reasons.
        artefacts_dir: Directory containing 'digests/' folder.
    """
    try:
        if artefacts_dir is None:
            import job_applications_mcp_server as server
            artefacts_dir = server.ARTEFACTS_DIR

        digest_dir = artefacts_dir / "digests"
        if not digest_dir.exists():
            return {
                "ok": False,
                "error": "Digest directory not found",
                "total": 0,
                "discoveries": [],
                "backend": "none",
            }

        if date_str:
            target_dates = [date_str]
        else:
            today = date.today()
            target_dates = [(today - timedelta(days=i)).isoformat() for i in range(days_back)]

        discoveries: List[Dict[str, Any]] = []
        surfaced: List[Dict[str, Any]] = []
        below_threshold: List[Dict[str, Any]] = []

        for t_date in target_dates:
            digest_file = digest_dir / f"{t_date}.md"
            if not digest_file.exists():
                continue

            content = digest_file.read_text(encoding="utf-8")
            lines = content.split("\n")

            in_below_section = False
            current_job: Optional[Dict[str, Any]] = None

            for line in lines:
                stripped = line.strip()
                if stripped.startswith("## Below Threshold"):
                    in_below_section = True
                    if current_job:
                        _append_job(current_job, discoveries, surfaced, below_threshold)
                        current_job = None
                    continue
                if stripped.startswith("## ") and not stripped.startswith("## Below"):
                    in_below_section = False
                    if current_job:
                        _append_job(current_job, discoveries, surfaced, below_threshold)
                        current_job = None
                    continue
                if stripped.startswith("*"):
                    if current_job:
                        _append_job(current_job, discoveries, surfaced, below_threshold)
                        current_job = None
                    continue

                if line.startswith("### "):
                    if current_job:
                        _append_job(current_job, discoveries, surfaced, below_threshold)
                    header = line.lstrip("# ").strip()
                    if " — " in header:
                        comp, title = header.split(" — ", 1)
                    else:
                        comp, title = "", header
                    cat = "below_threshold" if in_below_section else "surfaced"
                    current_job = {
                        "company": comp.strip(),
                        "role_title": title.strip(),
                        "title": title.strip(),
                        "category": cat,
                        "date": t_date,
                    }
                elif current_job is not None:
                    if stripped.startswith("- **Location:**"):
                        current_job["location"] = stripped.replace("- **Location:**", "").strip()
                    elif stripped.startswith("- **URL:**"):
                        current_job["url"] = stripped.replace("- **URL:**", "").strip()
                    elif stripped.startswith("- **Snippet:**"):
                        current_job["snippet"] = stripped.replace("- **Snippet:**", "").strip()
                    elif stripped.startswith("- **Category:**"):
                        current_job["category"] = stripped.replace("- **Category:**", "").strip()
                    elif stripped.startswith("- **Reason:**"):
                        current_job["reason"] = stripped.replace("- **Reason:**", "").strip()

            if current_job:
                _append_job(current_job, discoveries, surfaced, below_threshold)

        if not include_below_threshold:
            filtered_discoveries = [d for d in discoveries if d.get("category") != "below_threshold"]
        else:
            filtered_discoveries = discoveries

        if limit is not None:
            filtered_discoveries = filtered_discoveries[:limit]

        query_date = date_str if date_str else date.today().isoformat()

        return {
            "ok": True,
            "total": len(filtered_discoveries),
            "total_surfaced": len(surfaced),
            "total_below_threshold": len(below_threshold),
            "date": query_date,
            "discoveries": filtered_discoveries,
            "surfaced": surfaced,
            "below_threshold": below_threshold,
            "backend": "filesystem",
            "hint": "Use score_match on individual jobs, then ingest_from_discovery to add to tracker.",
        }

    except Exception as e:
        logger.exception("Error listing job discoveries")
        return {
            "ok": False,
            "error": str(e),
            "total": 0,
            "discoveries": [],
            "backend": "error",
        }


def _append_job(
    job: Dict[str, Any],
    discoveries: List[Dict[str, Any]],
    surfaced: List[Dict[str, Any]],
    below_threshold: List[Dict[str, Any]],
) -> None:
    discoveries.append(job)
    if job.get("category") == "below_threshold":
        below_threshold.append(job)
    else:
        surfaced.append(job)


def ingest_from_discovery(
    company: str,
    date_str: str = "",
    artefacts_dir: Optional[Path] = None,
    tracker_loader: Optional[Callable[[], dict]] = None,
    tracker_saver: Optional[Callable[[dict], None]] = None,
    folder_resolver: Optional[Callable[[str, str, dict], Path]] = None,
    app_creator: Optional[Callable[[str, str, str], dict]] = None,
) -> dict:
    """Ingest a discovered job from the daily digest into the tracker."""
    import job_applications_mcp_server as server

    if artefacts_dir is None:
        artefacts_dir = server.ARTEFACTS_DIR
    if tracker_loader is None:
        tracker_loader = server._load_tracker
    if tracker_saver is None:
        tracker_saver = server._save_tracker
    if folder_resolver is None:
        folder_resolver = server._resolve_company_folder
    if app_creator is None:
        app_creator = server._create_application_record

    if not date_str:
        date_str = date.today().isoformat()

    digest_dir = artefacts_dir / "digests"
    digest_path = digest_dir / f"{date_str}.md"

    if not digest_path.exists():
        return {"ok": False, "error": "no_digest_found", "date": date_str}

    content = digest_path.read_text(encoding="utf-8")
    current_job = None
    jobs = []

    for line in content.split("\n"):
        if line.startswith("### "):
            header = line.lstrip("# ").strip()
            if " — " in header:
                comp, title = header.split(" — ", 1)
            else:
                comp, title = "", header
            current_job = {"company": comp.strip(), "title": title.strip()}
            jobs.append(current_job)
        elif current_job is not None:
            stripped = line.strip()
            if stripped.startswith("- **Location:**"):
                current_job["location"] = stripped.replace("- **Location:**", "").strip()
            elif stripped.startswith("- **URL:**"):
                current_job["url"] = stripped.replace("- **URL:**", "").strip()
            elif stripped.startswith("- **Snippet:**"):
                current_job["snippet"] = stripped.replace("- **Snippet:**", "").strip()

    company_lower = company.lower()
    match = None
    for job in jobs:
        if job["company"].lower() == company_lower:
            match = job
            break

    if not match:
        available = [j["company"] for j in jobs]
        return {
            "ok": False,
            "error": "job_not_found",
            "company": company,
            "available_companies": available,
        }

    tracker = tracker_loader()
    for app in tracker.get("applications", []):
        if app.get("company", "").lower() == company_lower:
            return {
                "ok": False,
                "error": "already_tracked",
                "company": company,
                "existing_id": app.get("id"),
                "existing_stage": app.get("stage"),
            }

    try:
        company_dir = folder_resolver(match["company"], match["title"], tracker)
    except server.AmbiguousRoleError as e:
        return {"ok": False, "error": "ambiguous_role", "company": e.company, "roles": e.roles}

    company_dir.mkdir(parents=True, exist_ok=True)

    jd_lines = [
        f"# {match['title']}",
        "",
        f"**Company:** {match['company']}",
        f"**Location:** {match.get('location', 'Not specified')}",
        f"**Source:** LinkedIn job discovery ({date_str})",
    ]
    if match.get("url"):
        jd_lines.append(f"**URL:** {match['url']}")
    jd_lines.append("")
    jd_lines.append(match.get("snippet", "No description available."))
    jd_lines.append("")
    jd_content = "\n".join(jd_lines)

    jd_path = company_dir / "JD.md"
    jd_path.write_text(jd_content, encoding="utf-8")

    new_app = app_creator(match["company"], match["title"], str(jd_path))
    if match.get("url"):
        new_app["jd_source_url"] = match["url"]
    tracker["applications"].append(new_app)
    tracker_saver(tracker)

    return {
        "ok": True,
        "application_id": new_app["id"],
        "company": match["company"],
        "role_title": match["title"],
        "stage": "new",
        "folder_path": str(company_dir),
        "jd_path": str(jd_path),
        "hint": "Use score_match for full LLM-based matching, then save_application_artefact to record results.",
    }
