#!/usr/bin/env python3
"""Full migration and initialization for Postgres-backed Job Applications.

Phases:
a) Base CV ingestion: Parse base CV, extract evidence, store in Postgres
b) Application migration: Convert tracker.json to Postgres schema
c) Evidence discovery: Scan existing company folders for evidence gaps
d) Cleanup: Deduplicate, consolidate, remove old formats

Usage:
    python3 scripts/migrate_to_postgres_full.py [--phase a|b|c|d|all]
"""

import argparse
import asyncio
import json
import logging
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    handlers=[
        logging.FileHandler("migration.log"),
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger(__name__)

# Paths (from environment or defaults)
_SRC_DIR = Path(__file__).resolve().parent.parent
BASE_DIR = Path(os.environ.get("JOB_APP_BASE_DIR", str(_SRC_DIR)))
ARTEFACTS_DIR = Path(os.environ.get("JOB_APP_ARTEFACTS_DIR", str(BASE_DIR)))
TRACKER_PATH = Path(os.environ.get("JOB_APP_TRACKER_PATH", str(BASE_DIR / "tracker.json")))

# Base CV path: support auto-detection of MD or PDF in base-cv folder
_BASE_CV_ENV = os.environ.get("JOB_APP_BASE_CV_PATH")
if _BASE_CV_ENV:
    BASE_CV_PATH = Path(_BASE_CV_ENV)
else:
    # Auto-detect: check base-cv folder first (new location), then DXC (legacy)
    base_cv_folder = BASE_DIR / "base-cv"
    if base_cv_folder.exists():
        # Look for any .md or .pdf file in base-cv folder
        for suffix in [".md", ".pdf"]:
            files = list(base_cv_folder.glob(f"*{suffix}"))
            if files:
                BASE_CV_PATH = files[0]  # Use first found
                break
        else:
            # Fallback to legacy DXC location
            BASE_CV_PATH = Path(ARTEFACTS_DIR / "DXC" / "CV LEE Gee Sin 2026 - DXC Client Partner Public Sector.md")
    else:
        # Legacy default
        BASE_CV_PATH = Path(ARTEFACTS_DIR / "DXC" / "CV LEE Gee Sin 2026 - DXC Client Partner Public Sector.md")

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:password@localhost/job_applications")


def load_tracker() -> dict:
    """Load tracker.json."""
    if not TRACKER_PATH.exists():
        return {"schema_version": "1.0", "applications": []}
    try:
        return json.loads(TRACKER_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        logger.error(f"Failed to load tracker.json: {e}")
        return {"schema_version": "1.0", "applications": []}


def _extract_pdf_text(pdf_path: Path) -> str:
    """Extract text from PDF file using pdfplumber (handles various PDF types)."""
    try:
        import pdfplumber
    except ImportError:
        logger.error("pdfplumber not installed. Install with: pip install pdfplumber")
        return ""

    try:
        text = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                extracted = page.extract_text()
                if extracted:
                    text.append(extracted)
        result = "\n".join(text)
        if not result.strip():
            logger.warning(f"No text extracted from PDF {pdf_path} - may be image-only or encrypted")
        return result
    except Exception as e:
        logger.error(f"Failed to extract text from PDF {pdf_path}: {e}")
        return ""


def parse_base_cv(cv_path: Path) -> list[dict]:
    """Parse base CV (MD or PDF) and extract evidence items.

    Supports both .md and .pdf files. For PDFs, extracts text first.

    Extracts:
    - Work experience (job_title, company_name, dates, description, skills)
    - Projects (title, description, skills, dates)
    - Education (degree, institution, year)
    - Skills (listed skills)

    Returns list of evidence dicts with:
    - achievement: main claim or accomplishment
    - context: role/project context
    - impact: quantified or qualitative impact
    - skills_demonstrated: list of skills
    - job_title: role or project name
    - company_name: employer or org
    - source_section: "Experience", "Projects", "Education", "Skills"
    - time_period_start: ISO date string or None
    - time_period_end: ISO date string or None
    """
    if not cv_path.exists():
        logger.error(f"Base CV not found: {cv_path}")
        return []

    # Extract content based on file type
    if cv_path.suffix.lower() == ".pdf":
        logger.info(f"Parsing PDF CV: {cv_path}")
        content = _extract_pdf_text(cv_path)
    else:
        logger.info(f"Parsing MD CV: {cv_path}")
        content = cv_path.read_text(encoding="utf-8")

    evidence = []

    # Parse markdown sections
    lines = content.split("\n")
    current_section = None
    section_content = []

    for line in lines:
        # Detect section headers (## or ###)
        if line.startswith("## "):
            if current_section and section_content:
                evidence.extend(_extract_from_section(current_section, "\n".join(section_content)))
            current_section = line[3:].strip()
            section_content = []
        else:
            section_content.append(line)

    # Process final section
    if current_section and section_content:
        evidence.extend(_extract_from_section(current_section, "\n".join(section_content)))

    logger.info(f"Extracted {len(evidence)} evidence items from base CV")
    return evidence


def _extract_from_section(section_name: str, content: str) -> list[dict]:
    """Extract evidence from a CV section."""
    evidence = []
    section_lower = section_name.lower()

    if any(word in section_lower for word in ["experience", "work", "employment"]):
        evidence.extend(_extract_experience(content))
    elif any(word in section_lower for word in ["project", "achievement"]):
        evidence.extend(_extract_projects(content))
    elif any(word in section_lower for word in ["education", "certification"]):
        evidence.extend(_extract_education(content))
    elif any(word in section_lower for word in ["skill", "competenc"]):
        evidence.extend(_extract_skills(content))

    return evidence


def _extract_experience(content: str) -> list[dict]:
    """Extract work experience entries."""
    evidence = []
    # Simple heuristic: bullet points under an experience section
    entries = content.split("\n-")
    for entry in entries:
        entry = entry.strip()
        if not entry or len(entry) < 20:
            continue

        # Try to parse dates
        date_match = re.search(r"(\d{4})\s*[-–]\s*(\d{4}|Present)", entry)
        start_date = None
        end_date = None
        if date_match:
            try:
                start_date = f"{date_match.group(1)}-01-01"
                end_str = date_match.group(2)
                end_date = "Present" if end_str == "Present" else f"{end_str}-12-31"
            except (ValueError, IndexError):
                pass

        evidence.append({
            "achievement": entry[:200],  # First 200 chars as achievement
            "context": entry,
            "impact": "",
            "skills_demonstrated": _extract_skills_from_text(entry),
            "job_title": "Professional Experience",
            "company_name": "Professional",
            "source_section": "Experience",
            "time_period_start": start_date,
            "time_period_end": end_date,
        })

    return evidence


def _extract_projects(content: str) -> list[dict]:
    """Extract project entries."""
    evidence = []
    entries = content.split("\n-")
    for entry in entries:
        entry = entry.strip()
        if not entry or len(entry) < 20:
            continue

        evidence.append({
            "achievement": entry[:200],
            "context": entry,
            "impact": "",
            "skills_demonstrated": _extract_skills_from_text(entry),
            "job_title": "Project",
            "company_name": "Self-Directed",
            "source_section": "Projects",
            "time_period_start": None,
            "time_period_end": None,
        })

    return evidence


def _extract_education(content: str) -> list[dict]:
    """Extract education entries."""
    evidence = []
    entries = content.split("\n-")
    for entry in entries:
        entry = entry.strip()
        if not entry or len(entry) < 10:
            continue

        date_match = re.search(r"(\d{4})", entry)
        year = None
        if date_match:
            year = f"{date_match.group(1)}-01-01"

        evidence.append({
            "achievement": entry,
            "context": entry,
            "impact": "",
            "skills_demonstrated": [],
            "job_title": "Education",
            "company_name": "Educational Institution",
            "source_section": "Education",
            "time_period_start": year,
            "time_period_end": year,
        })

    return evidence


def _extract_skills(content: str) -> list[dict]:
    """Extract skills from a skills section."""
    evidence = []
    # Split by comma or newline
    skills_list = re.split(r"[,\n]", content)
    for skill in skills_list:
        skill = skill.strip().lstrip("- ").strip()
        if not skill or len(skill) < 2:
            continue

        evidence.append({
            "achievement": f"Demonstrated proficiency in {skill}",
            "context": skill,
            "impact": "",
            "skills_demonstrated": [skill],
            "job_title": "Technical Skills",
            "company_name": "Professional",
            "source_section": "Skills",
            "time_period_start": None,
            "time_period_end": None,
        })

    return evidence


def _extract_skills_from_text(text: str) -> list[str]:
    """Extract likely skill keywords from text."""
    # Simple heuristic: look for capitalized words, programming language keywords, etc.
    common_skills = {
        "python", "java", "javascript", "sql", "aws", "gcp", "azure", "kubernetes",
        "docker", "rest", "graphql", "react", "vue", "angular", "nodejs", "django",
        "flask", "postgresql", "mongodb", "leadership", "communication", "agile",
        "scrum", "git", "linux", "windows", "macos", "css", "html", "typescript",
    }

    text_lower = text.lower()
    found_skills = []
    for skill in common_skills:
        if skill in text_lower:
            found_skills.append(skill)

    return found_skills


async def phase_a_base_cv_ingestion():
    """Phase a: Parse base CV and store in Postgres."""
    logger.info("=" * 80)
    logger.info("PHASE A: Base CV Ingestion")
    logger.info("=" * 80)

    if not BASE_CV_PATH.exists():
        logger.error(f"Base CV not found: {BASE_CV_PATH}")
        logger.error("Set JOB_APP_BASE_CV_PATH environment variable to a valid path")
        return False

    # Try to import Prisma client
    try:
        from prisma import Prisma
    except ImportError:
        logger.error("prisma package not installed. Install with: pip install prisma")
        return False

    logger.info(f"Parsing base CV: {BASE_CV_PATH}")
    evidence_list = parse_base_cv(BASE_CV_PATH)

    if not evidence_list:
        logger.warning("No evidence extracted from base CV")
        return False

    # Create Postgres records
    try:
        db = Prisma()
        await db.connect()

        # Create Application record for the base CV
        app = await db.application.create(
            data={"name": "base-cv-ground-truth"}
        )
        logger.info(f"Created application record: {app.id}")

        # Create CVRecord for base CV
        cv_record = await db.c_v_record.create(
            data={
                "cvId": "base-cv-v1",
                "applicationId": app.id,
                "version": "base",
                "status": "final",
                "content": BASE_CV_PATH.read_text(encoding="utf-8"),
                "finalizedAt": datetime.now(timezone.utc),
            }
        )
        logger.info(f"Created CVRecord: {cv_record.id}")

        # Store evidence
        inserted = 0
        for ev in evidence_list:
            try:
                structured_ev = await db.structured_evidence.create(
                    data={
                        "achievement": ev["achievement"],
                        "context": ev["context"],
                        "impact": ev.get("impact", ""),
                        "skills_demonstrated": ev["skills_demonstrated"],
                        "job_title": ev["job_title"],
                        "company_name": ev["company_name"],
                        "source_section": ev["source_section"],
                        "source_cv_id": cv_record.id,
                        "time_period_start": ev.get("time_period_start"),
                        "time_period_end": ev.get("time_period_end"),
                    }
                )
                inserted += 1
            except Exception as e:
                logger.warning(f"Failed to insert evidence: {e}")

        logger.info(f"Ingested {inserted}/{len(evidence_list)} evidence items into Postgres")
        await db.disconnect()
        return True

    except Exception as e:
        logger.error(f"Database error during phase A: {e}")
        return False


async def phase_b_application_migration():
    """Phase b: Migrate tracker.json applications to Postgres."""
    logger.info("=" * 80)
    logger.info("PHASE B: Application Migration")
    logger.info("=" * 80)

    tracker = load_tracker()
    applications = tracker.get("applications", [])

    if not applications:
        logger.info("No applications found in tracker.json")
        return True

    try:
        from prisma import Prisma
    except ImportError:
        logger.error("prisma package not installed")
        return False

    try:
        db = Prisma()
        await db.connect()

        migrated = 0
        for app_record in applications:
            try:
                company = app_record.get("company", "Unknown")
                role_title = app_record.get("role_title", "Unknown")
                app_id = app_record.get("id", str(uuid.uuid4()))

                # Check if already migrated
                existing = await db.application.find_unique(
                    where={"name": app_id}
                )
                if existing:
                    logger.debug(f"Application {app_id} already migrated")
                    continue

                # Create application
                app = await db.application.create(
                    data={"name": app_id}
                )
                logger.info(f"Migrated application: {company} - {role_title} ({app.id})")
                migrated += 1

            except Exception as e:
                logger.warning(f"Failed to migrate application {app_id}: {e}")

        logger.info(f"Migrated {migrated}/{len(applications)} applications")
        await db.disconnect()
        return True

    except Exception as e:
        logger.error(f"Database error during phase B: {e}")
        return False


def phase_c_evidence_discovery():
    """Phase c: Scan existing company folders for evidence gaps."""
    logger.info("=" * 80)
    logger.info("PHASE C: Evidence Discovery")
    logger.info("=" * 80)

    if not ARTEFACTS_DIR.exists():
        logger.error(f"Artefacts directory not found: {ARTEFACTS_DIR}")
        return False

    # Find company folders
    company_dirs = [d for d in ARTEFACTS_DIR.iterdir() if d.is_dir() and not d.name.startswith(".")]
    logger.info(f"Found {len(company_dirs)} company folders")

    discovered = 0
    for company_dir in company_dirs:
        # Look for CV files
        cv_files = list(company_dir.glob("CV*.md")) + list(company_dir.glob("CV*.pdf"))
        for cv_file in cv_files:
            if cv_file.suffix == ".md":
                evidence = parse_base_cv(cv_file)
                discovered += len(evidence)
                logger.info(f"  {company_dir.name}/{cv_file.name}: {len(evidence)} evidence items")

    logger.info(f"Discovered {discovered} additional evidence items from company folders")
    return True


def phase_d_cleanup():
    """Phase d: Deduplicate and consolidate."""
    logger.info("=" * 80)
    logger.info("PHASE D: Cleanup")
    logger.info("=" * 80)

    # Backup tracker.json
    if TRACKER_PATH.exists():
        backup_path = TRACKER_PATH.with_suffix(".json.backup")
        TRACKER_PATH.rename(backup_path)
        logger.info(f"Backed up tracker.json to {backup_path}")

    # Remove old plan files
    old_plans = list(ARTEFACTS_DIR.glob("**/gap_analysis.md")) + \
                list(ARTEFACTS_DIR.glob("**/learning_program.md")) + \
                list(ARTEFACTS_DIR.glob("**/.claude/"))

    for old_file in old_plans:
        try:
            if old_file.is_dir():
                import shutil
                shutil.rmtree(old_file)
            else:
                old_file.unlink()
            logger.info(f"  Removed: {old_file.relative_to(ARTEFACTS_DIR)}")
        except Exception as e:
            logger.warning(f"  Failed to remove {old_file}: {e}")

    logger.info("Cleanup complete")
    return True


async def main():
    parser = argparse.ArgumentParser(description="Migrate Job Applications to Postgres")
    parser.add_argument(
        "--phase",
        choices=["a", "b", "c", "d", "all"],
        default="all",
        help="Which phase to run (default: all)"
    )
    args = parser.parse_args()

    phases = {
        "a": ("Base CV Ingestion", phase_a_base_cv_ingestion),
        "b": ("Application Migration", phase_b_application_migration),
        "c": ("Evidence Discovery", phase_c_evidence_discovery),
        "d": ("Cleanup", phase_d_cleanup),
    }

    if args.phase == "all":
        phase_list = ["a", "b", "c", "d"]
    else:
        phase_list = [args.phase]

    logger.info("Job Applications Postgres Migration")
    logger.info(f"Database: {DATABASE_URL}")
    logger.info(f"Base CV: {BASE_CV_PATH}")
    logger.info(f"Tracker: {TRACKER_PATH}")

    results = {}
    for phase_key in phase_list:
        phase_name, phase_func = phases[phase_key]
        logger.info(f"\nRunning phase {phase_key}: {phase_name}...")
        try:
            if asyncio.iscoroutinefunction(phase_func):
                results[phase_key] = await phase_func()
            else:
                results[phase_key] = phase_func()
        except Exception as e:
            logger.error(f"Phase {phase_key} failed: {e}")
            results[phase_key] = False

    logger.info("\n" + "=" * 80)
    logger.info("MIGRATION SUMMARY")
    logger.info("=" * 80)
    for phase_key, success in results.items():
        status = "✓ PASS" if success else "✗ FAIL"
        phase_name = phases[phase_key][0]
        logger.info(f"{status} Phase {phase_key}: {phase_name}")

    all_passed = all(results.values())
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
