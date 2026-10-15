#!/usr/bin/env python3
"""
Bootstrap script for Career Evidence Repository.

1. Ensures evidence.json exists in the configured data directory (seeded from profile.json).
2. Ingests verified career evidence items (VISEO practice leadership, NCS China/HK, cross-functional squads).
3. Enriches profile.json with verified practice & regional management experience.
"""

import json
import logging
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from evidence_persistence import EvidenceRepository, BaselineEvidenceImporter
from evidence_service import EvidenceService

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("bootstrap_evidence_pool")


def bootstrap_evidence_pool(data_dir: Path | str | None = None) -> dict:
    if data_dir is None:
        env_dir = os.environ.get("JOB_APP_ARTEFACTS_DIR") or os.environ.get("JOB_APP_BASE_DIR")
        if env_dir and Path(env_dir).exists():
            data_path = Path(env_dir)
        else:
            candidates = [Path("/mnt/job-app-data"), Path("/Volumes/job-app-data"), PROJECT_ROOT / "data"]
            data_path = next((c for c in candidates if c.exists() and c.is_dir()), PROJECT_ROOT / "data")
    else:
        data_path = Path(data_dir)

    data_path.mkdir(parents=True, exist_ok=True)
    profile_path = data_path / "profile.json"
    evidence_path = data_path / "evidence.json"

    logger.info(f"Target data directory: {data_path}")

    if not profile_path.exists():
        fallback_profiles = [
            PROJECT_ROOT / "profile.json",
            PROJECT_ROOT / "data" / "profile.json",
            Path("/mnt/job-app-data/profile.json"),
            Path("/Volumes/job-app-data/profile.json"),
        ]
        for fp in fallback_profiles:
            if fp.exists() and fp.is_file():
                logger.info(f"Copying baseline profile from {fp} to {profile_path}")
                profile_path.write_text(fp.read_text(encoding="utf-8"), encoding="utf-8")
                break

    repo = EvidenceRepository(data_dir=str(data_path))
    service = EvidenceService(repo=repo)

    current_evidence = repo.list_evidence()
    baseline_imported = 0
    if not current_evidence and profile_path.exists():
        logger.info(f"Evidence repository empty. Importing baseline evidence from {profile_path}...")
        importer = BaselineEvidenceImporter(str(profile_path), repo)
        baseline_imported = importer.import_baseline_evidence()
        logger.info(f"Imported {baseline_imported} baseline evidence items.")
    else:
        logger.info(f"Evidence repository already contains {len(current_evidence)} items.")

    significant_items = [
        {
            "statement": "Managed and guided practice sales managers under Salesforce, Digital, SAP, and Retail Solutions practices at VISEO SAS, orchestrating cross-functional teams across sales ops, technical presales, architecture, and delivery to achieve 200–400% quota over consecutive years.",
            "evidence_type": "work_experience",
            "source_reference": "User verified experience: VISEO practice leadership",
            "competencies": ["Sales Management", "Practice Leadership", "Quota Over-achievement", "Cross-functional Squad Orchestration"],
            "technologies": ["Salesforce", "SAP", "Digital Solutions", "Retail Solutions"],
            "industries": ["Public Sector", "Enterprise IT Services"],
            "geographies": ["Singapore", "Malaysia"],
            "notes": "Verified by candidate during ServiceNow Sales Director customization (2026-09-13)",
        },
        {
            "statement": "Managed regional sales managers based in China and Hong Kong at NCS Group, leading commercial bids and client engagements for Smart City and Operational Technology (OT) solutions.",
            "evidence_type": "work_experience",
            "source_reference": "User verified experience: NCS China/HK leadership",
            "competencies": ["Regional Sales Management", "Cross-border Leadership", "Tender Leadership", "OT & Smart City Commercial Strategy"],
            "technologies": ["Smart City Platforms", "Operational Technology (OT)", "AI/ML"],
            "industries": ["Public Sector", "Smart Cities"],
            "geographies": ["Singapore", "China", "Hong Kong"],
            "notes": "Verified by candidate during ServiceNow Sales Director customization (2026-09-13)",
        },
        {
            "statement": "Orchestrated complex cross-functional squads spanning Sales Operations, Solution Architecture, Delivery, Support, and Customer Success to deliver high-stakes government engagements across MTI, MAS, GovTech, IMDA, Synapxe, and JTC.",
            "evidence_type": "work_experience",
            "source_reference": "User verified experience: Cross-functional leadership",
            "competencies": ["Cross-functional Leadership", "Complex Stakeholder Engagement", "Public Sector Procurement", "Full-Lifecycle Delivery"],
            "technologies": ["Cloud", "SaaS", "Enterprise Architecture"],
            "industries": ["Singapore Public Sector"],
            "geographies": ["Singapore"],
            "notes": "Verified by candidate during ServiceNow Sales Director customization (2026-09-13)",
        },
    ]

    added_evidence_ids = []
    for item in significant_items:
        dupes = service.find_duplicates(item["statement"])
        if not dupes or dupes[0].similarity_score < 0.85:
            ev = service.create_evidence(
                statement=item["statement"],
                evidence_type=item["evidence_type"],
                source_type="user_confirmed_experience",
                source_reference=item["source_reference"],
                confidence="LEVEL_A",
                verification_status="user_confirmed",
                user_confirmed=True,
                competencies=item["competencies"],
                technologies=item["technologies"],
                industries=item["industries"],
                geographies=item["geographies"],
                notes=item["notes"],
            )
            added_evidence_ids.append(ev["evidence_id"])
            logger.info(f"Added significant evidence: {item["statement"][:70]}... (ID: {ev["evidence_id"]})")
        else:
            logger.info(f"Evidence item already present: {item["statement"][:50]}...")

    profile_updated = False
    if profile_path.exists():
        try:
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            for exp in profile.get("work_experience", []):
                company_name = exp.get("company", "")
                if "VISEO" in company_name:
                    desc = exp.get("description", "")
                    if "practice sales managers" not in desc.lower():
                        exp["description"] = (
                            "Managed and guided practice sales managers under each Practice "
                            "(Salesforce, Digital, SAP, Retail Solutions). " + desc
                        )
                        profile_updated = True
                elif "NCS" in company_name:
                    desc = exp.get("description", "")
                    if "china and hk" not in desc.lower() and "regional sales" not in desc.lower():
                        exp["description"] = (
                            "Managed regional sales managers based in China and HK "
                            "on Smart City and Operational Technology (OT) solutions. " + desc
                        )
                        profile_updated = True

            if profile_updated:
                profile_path.write_text(json.dumps(profile, indent=2), encoding="utf-8")
                logger.info("Enriched profile.json with verified practice & regional management experience.")
        except Exception as e:
            logger.warning(f"Could not update profile.json: {e}")

    total_evidence_count = len(repo.list_evidence())
    return {
        "ok": True,
        "data_dir": str(data_path),
        "baseline_imported": baseline_imported,
        "significant_evidence_added": len(added_evidence_ids),
        "total_evidence_count": total_evidence_count,
        "profile_updated": profile_updated,
    }


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else None
    result = bootstrap_evidence_pool(target)
    print(json.dumps(result, indent=2))
