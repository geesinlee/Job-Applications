#!/usr/bin/env python3
"""Sync legacy tracker records and company folders to Gate 10 evidence system.

1. Copies/syncs company folders from ~/Personal/Jobs to data/ (excluding .venv).
2. Verifies that all applications in tracker.json can resolve their JD content.
3. Tests Gate 10 workflow readiness (start_job_application_workflow & generate_clarifying_questions).
"""

import json
import logging
import os
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from job_applications_mcp_server import (
    _load_tracker,
    _resolve_jd_content,
    start_job_application_workflow,
    generate_clarifying_questions,
    get_opportunity,
    ARTEFACTS_DIR,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("sync_legacy_tracker")


def sync_artefacts_from_personal_jobs() -> int:
    """Sync company folders from ~/Personal/Jobs to data/ if present."""
    src_base = Path.home() / "Personal" / "Jobs"
    dst_base = ARTEFACTS_DIR.resolve()

    if not src_base.exists():
        logger.info(f"Source {src_base} does not exist. Skipping copy.")
        return 0

    synced_count = 0
    for item in src_base.iterdir():
        if item.name.startswith(".") or item.name == ".venv":
            continue
        dst = dst_base / item.name
        if item.is_dir():
            shutil.copytree(
                item,
                dst,
                ignore=shutil.ignore_patterns(".venv", "__pycache__", ".DS_Store"),
                dirs_exist_ok=True,
            )
            synced_count += 1
        elif item.is_file():
            if not dst.exists():
                shutil.copy2(item, dst)
                synced_count += 1

    logger.info(f"Synced {synced_count} folders/files from {src_base} to {dst_base}")
    return synced_count


def verify_and_sync_all_applications() -> dict:
    """Check each application in tracker.json for JD availability and Gate 10 readiness."""
    tracker = _load_tracker()
    apps = tracker.get("applications", [])
    logger.info(f"Checking {len(apps)} applications in tracker...")

    results = {
        "total": len(apps),
        "jd_resolved": 0,
        "workflow_ready": 0,
        "details": [],
    }

    for app in apps:
        app_id = app.get("id")
        company = app.get("company")
        role_title = app.get("role_title")
        stage = app.get("stage")

        jd_text = _resolve_jd_content(app_id)
        has_jd = jd_text is not None and len(jd_text.strip()) > 0

        wf_ready = False
        if has_jd:
            results["jd_resolved"] += 1
            # Test workflow tools
            q_res = generate_clarifying_questions(application_id=app_id)
            if q_res.get("ok"):
                wf_ready = True
                results["workflow_ready"] += 1

        status_entry = {
            "id": app_id,
            "company": company,
            "role_title": role_title,
            "stage": stage,
            "jd_resolved": has_jd,
            "jd_length": len(jd_text) if jd_text else 0,
            "gate10_ready": wf_ready,
        }
        results["details"].append(status_entry)
        status_sym = "✅" if wf_ready else ("⚠️" if has_jd else "❌")
        logger.info(f"  {status_sym} [{company}] {role_title} (stage: {stage}) -> JD: {has_jd}, Gate10: {wf_ready}")

    return results


def main():
    logger.info("Starting legacy tracker -> Gate 10 synchronization...")
    sync_artefacts_from_personal_jobs()
    report = verify_and_sync_all_applications()
    logger.info(f"Completed sync. Total: {report['total']}, JD Resolved: {report['jd_resolved']}, Gate 10 Ready: {report['workflow_ready']}")

    # Specifically check PwC
    pwc_status = next((d for d in report["details"] if d["company"] == "PwC"), None)
    if pwc_status and pwc_status["gate10_ready"]:
        logger.info("SUCCESS: PwC application is fully synced and Gate 10 ready!")
    else:
        logger.error(f"PwC status check failed: {pwc_status}")
        sys.exit(1)


if __name__ == "__main__":
    main()
