# evidence_persistence.py
"""
Persistence layer for Career Evidence Repository.

Handles reading/writing evidence.json, tracker.json (extended), and cv_versions.json.
Implements reversible migrations and schema versioning.

NO business logic here — only I/O and schema management.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional
import logging

logger = logging.getLogger(__name__)


# ============================================================================
# CONSTANTS
# ============================================================================

EVIDENCE_REPO_VERSION = "1.0"
TRACKER_SCHEMA_V1 = "1.0"  # Legacy (pre-evidence)
TRACKER_SCHEMA_V2 = "2.0"  # Current (post-migration)
CV_VERSIONS_REPO_VERSION = "1.0"


# ============================================================================
# SCHEMA DEFAULTS
# ============================================================================

def get_default_evidence_repo() -> Dict[str, Any]:
    """Default empty evidence repository structure."""
    return {
        "schema_version": EVIDENCE_REPO_VERSION,
        "evidence_repository": {
            "evidence_list": []
        }
    }


def get_default_cv_versions_repo() -> Dict[str, Any]:
    """Default empty CV versions repository structure."""
    return {
        "schema_version": CV_VERSIONS_REPO_VERSION,
        "cv_records": []
    }


def get_extended_application_defaults() -> Dict[str, Any]:
    """Defaults for v2.0 application record fields."""
    return {
        "requirements_extracted_at": None,
        "requirements": [],
        "requirement_analysis_quality": None,
        "gap_interview_phase": "not_started",
        "gap_interview_questions": [],
        "gap_interview_answers": [],
        "evidence_selected": [],
        "evidence_omitted": [],
        "cv_records": [],
        "cv_draft_count": 0,
        "cv_approved_at": None,
        "cv_final_id": None,
        "discovered_at": None,  # Will be backfilled from date_created
        "applied_at": None,
        "significant_decisions": [],
    }


# ============================================================================
# EVIDENCE REPOSITORY OPERATIONS
# ============================================================================

class EvidenceRepository:
    """Handles persistence of Career Evidence."""

    def __init__(self, data_dir: str = "."):
        self.data_dir = Path(data_dir)
        self.evidence_path = self.data_dir / "evidence.json"

    def load(self) -> Dict[str, Any]:
        """Load evidence repository. Creates if not exists."""
        if not self.evidence_path.exists():
            logger.info(f"Creating new evidence repository at {self.evidence_path}")
            repo = get_default_evidence_repo()
            self.save(repo)
            return repo

        try:
            with open(self.evidence_path, 'r') as f:
                repo = json.load(f)
            logger.debug(f"Loaded evidence repo with {len(repo.get('evidence_repository', {}).get('evidence_list', []))} items")
            return repo
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse evidence.json: {e}")
            raise ValueError(f"Corrupted evidence.json: {e}")

    def save(self, repo: Dict[str, Any]) -> None:
        """Save evidence repository to disk."""
        self.evidence_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.evidence_path, 'w') as f:
            json.dump(repo, f, indent=2)
        logger.debug(f"Saved evidence repo to {self.evidence_path}")

    def add_evidence(self, evidence: Dict[str, Any]) -> None:
        """Add evidence item to repository."""
        repo = self.load()
        repo["evidence_repository"]["evidence_list"].append(evidence)
        self.save(repo)
        logger.debug(f"Added evidence: {evidence['evidence_id']}")

    def get_evidence(self, evidence_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve evidence by ID."""
        repo = self.load()
        for evidence in repo["evidence_repository"]["evidence_list"]:
            if evidence["evidence_id"] == evidence_id:
                return evidence
        return None

    def list_evidence(self, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """List all evidence, optionally filtered."""
        repo = self.load()
        evidence_list = repo["evidence_repository"]["evidence_list"]

        if not filters:
            return evidence_list

        # Simple filtering: all filter keys must match
        filtered = []
        for evidence in evidence_list:
            match = True
            for key, value in filters.items():
                if key not in evidence:
                    match = False
                    break
                if isinstance(value, list):
                    # For list fields (competencies, geographies, etc.), check if any match
                    if not any(v in evidence[key] for v in value):
                        match = False
                        break
                else:
                    if evidence[key] != value:
                        match = False
                        break
            if match:
                filtered.append(evidence)

        return filtered

    def update_evidence(self, evidence_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update evidence item."""
        repo = self.load()
        for i, evidence in enumerate(repo["evidence_repository"]["evidence_list"]):
            if evidence["evidence_id"] == evidence_id:
                # Update specified fields, preserve others
                evidence.update(updates)
                evidence["last_modified_at"] = datetime.utcnow().isoformat() + "Z"
                self.save(repo)
                logger.debug(f"Updated evidence: {evidence_id}")
                return evidence
        logger.warning(f"Evidence not found: {evidence_id}")
        return None


# ============================================================================
# CV VERSIONS REPOSITORY OPERATIONS
# ============================================================================

class CVVersionsRepository:
    """Handles persistence of CV versions."""

    def __init__(self, data_dir: str = "."):
        self.data_dir = Path(data_dir)
        self.cv_versions_path = self.data_dir / "cv_versions.json"

    def load(self) -> Dict[str, Any]:
        """Load CV versions repository. Creates if not exists."""
        if not self.cv_versions_path.exists():
            logger.info(f"Creating new CV versions repository at {self.cv_versions_path}")
            repo = get_default_cv_versions_repo()
            self.save(repo)
            return repo

        try:
            with open(self.cv_versions_path, 'r') as f:
                repo = json.load(f)
            logger.debug(f"Loaded CV versions repo with {len(repo.get('cv_records', []))} records")
            return repo
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse cv_versions.json: {e}")
            raise ValueError(f"Corrupted cv_versions.json: {e}")

    def save(self, repo: Dict[str, Any]) -> None:
        """Save CV versions repository to disk."""
        self.cv_versions_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.cv_versions_path, 'w') as f:
            json.dump(repo, f, indent=2)
        logger.debug(f"Saved CV versions repo to {self.cv_versions_path}")

    def add_cv_record(self, cv_record: Dict[str, Any]) -> None:
        """Add CV version record to repository."""
        repo = self.load()
        repo["cv_records"].append(cv_record)
        self.save(repo)
        logger.debug(f"Added CV record: {cv_record['cv_record_id']}")

    def get_cv_record(self, cv_record_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve CV record by ID."""
        repo = self.load()
        for record in repo["cv_records"]:
            if record["cv_record_id"] == cv_record_id:
                return record
        return None

    def list_cv_records(self, application_id: str) -> List[Dict[str, Any]]:
        """List all CV records for an application."""
        repo = self.load()
        return [r for r in repo["cv_records"] if r["application_id"] == application_id]

    def update_cv_record(self, cv_record_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update CV record."""
        repo = self.load()
        for i, record in enumerate(repo["cv_records"]):
            if record["cv_record_id"] == cv_record_id:
                record.update(updates)
                record["last_modified_at"] = datetime.utcnow().isoformat() + "Z"
                self.save(repo)
                logger.debug(f"Updated CV record: {cv_record_id}")
                return record
        logger.warning(f"CV record not found: {cv_record_id}")
        return None


# ============================================================================
# TRACKER OPERATIONS (Extended for v2.0)
# ============================================================================

class TrackerRepository:
    """Handles persistence of application tracker (extended for v2.0)."""

    def __init__(self, tracker_path: str = "tracker.json"):
        self.tracker_path = Path(tracker_path)

    def load(self) -> Dict[str, Any]:
        """Load tracker. Expects tracker.json to exist (created at startup)."""
        if not self.tracker_path.exists():
            raise FileNotFoundError(f"tracker.json not found at {self.tracker_path}")

        try:
            with open(self.tracker_path, 'r') as f:
                tracker = json.load(f)
            return tracker
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse tracker.json: {e}")
            raise ValueError(f"Corrupted tracker.json: {e}")

    def save(self, tracker: Dict[str, Any]) -> None:
        """Save tracker to disk."""
        with open(self.tracker_path, 'w') as f:
            json.dump(tracker, f, indent=2)
        logger.debug(f"Saved tracker to {self.tracker_path}")

    def get_schema_version(self) -> str:
        """Get tracker schema version."""
        tracker = self.load()
        return tracker.get("schema_version", TRACKER_SCHEMA_V1)

    def is_migrated(self) -> bool:
        """Check if tracker has been migrated to v2.0."""
        return self.get_schema_version() == TRACKER_SCHEMA_V2

    def extend_application(self, app: Dict[str, Any]) -> Dict[str, Any]:
        """Add v2.0 fields to application if missing (no overwrite of existing values)."""
        defaults = get_extended_application_defaults()
        for key, default_value in defaults.items():
            if key not in app:
                app[key] = default_value

        # Backfill discovered_at from date_created if not set
        if app.get("discovered_at") is None:
            app["discovered_at"] = app.get("date_created")

        return app

    def migrate_to_v2(self) -> None:
        """Migrate tracker.json from v1.0 to v2.0 (non-destructive)."""
        tracker = self.load()
        current_version = tracker.get("schema_version", TRACKER_SCHEMA_V1)

        if current_version == TRACKER_SCHEMA_V2:
            logger.info("Tracker already at v2.0, no migration needed")
            return

        if current_version != TRACKER_SCHEMA_V1:
            raise ValueError(f"Unknown tracker schema version: {current_version}")

        logger.info("Migrating tracker from v1.0 to v2.0...")

        # Extend all applications with v2.0 fields
        for app in tracker.get("applications", []):
            self.extend_application(app)

        # Update schema version
        tracker["schema_version"] = TRACKER_SCHEMA_V2

        # Save
        self.save(tracker)
        logger.info("Migration to v2.0 complete")

    def revert_to_v1(self) -> None:
        """Revert tracker from v2.0 to v1.0 (removes v2.0 fields, keeps v1.0 fields)."""
        tracker = self.load()

        if tracker.get("schema_version") != TRACKER_SCHEMA_V2:
            logger.info("Tracker not at v2.0, no revert needed")
            return

        logger.warning("Reverting tracker from v2.0 to v1.0 (new fields will be dropped)")

        # Remove v2.0 fields from all applications
        v2_fields = set(get_extended_application_defaults().keys())
        for app in tracker.get("applications", []):
            for field in v2_fields:
                if field in app:
                    del app[field]

        # Update schema version
        tracker["schema_version"] = TRACKER_SCHEMA_V1

        # Save
        self.save(tracker)
        logger.info("Revert to v1.0 complete")


# ============================================================================
# BASELINE EVIDENCE IMPORT
# ============================================================================

class BaselineEvidenceImporter:
    """One-time import of baseline evidence from existing profile.json and CV files."""

    def __init__(self, profile_path: str, evidence_repo: EvidenceRepository):
        self.profile_path = Path(profile_path)
        self.evidence_repo = evidence_repo

    def import_baseline_evidence(self) -> int:
        """
        Import baseline evidence from profile.json.
        Returns number of evidence items created.
        """
        if not self.profile_path.exists():
            logger.warning(f"profile.json not found at {self.profile_path}, skipping baseline import")
            return 0

        try:
            with open(self.profile_path, 'r') as f:
                profile = json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse profile.json: {e}")
            return 0

        count = 0

        # Import work experiences
        for work_exp in profile.get("work_experience", []):
            evidence = {
                "evidence_id": self._generate_id(),
                "statement": self._format_work_experience(work_exp),
                "evidence_type": "work_experience",
                "source_type": work_exp.get("_source", "baseline_cv"),
                "source_reference": f"profile.json: {work_exp.get('company', 'Unknown')}",
                "source_document_id": None,
                "source_date": datetime.utcnow().isoformat() + "Z",
                "first_captured_at": datetime.utcnow().isoformat() + "Z",
                "last_confirmed_at": datetime.utcnow().isoformat() + "Z",
                "application_origin": None,
                "verification_status": "user_confirmed",
                "confidence": "LEVEL_B",  # From profile: somewhat strong
                "user_confirmed": True,
                "supersedes": [],
                "superseded_by": [],
                "related_to": [],
                "competencies": [],
                "technologies": [],
                "industries": [],
                "geographies": [],
                "metrics": {},
                "notes": "Imported from baseline profile",
                "created_by": "baseline_import",
                "created_at": datetime.utcnow().isoformat() + "Z",
                "last_modified_by": "baseline_import",
                "last_modified_at": datetime.utcnow().isoformat() + "Z",
            }
            self.evidence_repo.add_evidence(evidence)
            count += 1

        # Import education
        for education in profile.get("education", []):
            evidence = {
                "evidence_id": self._generate_id(),
                "statement": self._format_education(education),
                "evidence_type": "skill",
                "source_type": education.get("_source", "baseline_cv"),
                "source_reference": f"profile.json: {education.get('institution', 'Unknown')}",
                "source_document_id": None,
                "source_date": datetime.utcnow().isoformat() + "Z",
                "first_captured_at": datetime.utcnow().isoformat() + "Z",
                "last_confirmed_at": datetime.utcnow().isoformat() + "Z",
                "application_origin": None,
                "verification_status": "user_confirmed",
                "confidence": "LEVEL_A",  # Education is strong evidence
                "user_confirmed": True,
                "supersedes": [],
                "superseded_by": [],
                "related_to": [],
                "competencies": [],
                "technologies": [],
                "industries": [],
                "geographies": [],
                "metrics": {},
                "notes": "Imported from baseline profile",
                "created_by": "baseline_import",
                "created_at": datetime.utcnow().isoformat() + "Z",
                "last_modified_by": "baseline_import",
                "last_modified_at": datetime.utcnow().isoformat() + "Z",
            }
            self.evidence_repo.add_evidence(evidence)
            count += 1

        # Import skills
        for skill in profile.get("skills", []):
            evidence = {
                "evidence_id": self._generate_id(),
                "statement": f"Skill: {skill}",
                "evidence_type": "skill",
                "source_type": "baseline_cv",
                "source_reference": "profile.json: skills list",
                "source_document_id": None,
                "source_date": datetime.utcnow().isoformat() + "Z",
                "first_captured_at": datetime.utcnow().isoformat() + "Z",
                "last_confirmed_at": datetime.utcnow().isoformat() + "Z",
                "application_origin": None,
                "verification_status": "user_confirmed",
                "confidence": "LEVEL_C",  # General skill, not deep
                "user_confirmed": True,
                "supersedes": [],
                "superseded_by": [],
                "related_to": [],
                "competencies": [skill],
                "technologies": [skill] if skill.lower() in ["python", "salesforce", "java", "sql"] else [],
                "industries": [],
                "geographies": [],
                "metrics": {},
                "notes": "Imported from baseline profile",
                "created_by": "baseline_import",
                "created_at": datetime.utcnow().isoformat() + "Z",
                "last_modified_by": "baseline_import",
                "last_modified_at": datetime.utcnow().isoformat() + "Z",
            }
            self.evidence_repo.add_evidence(evidence)
            count += 1

        logger.info(f"Baseline evidence import complete: {count} items created")
        return count

    @staticmethod
    def _format_work_experience(work_exp: Dict[str, Any]) -> str:
        """Format work experience for statement."""
        company = work_exp.get("company", "Unknown")
        title = work_exp.get("title", "Unknown")
        start = work_exp.get("start", "")
        end = work_exp.get("end", "present")
        description = work_exp.get("description", "")

        period = f"{start}–{end}".replace("–present", "–Present")
        stmt = f"{title} at {company} ({period})"
        if description:
            stmt += f": {description}"

        return stmt

    @staticmethod
    def _format_education(education: Dict[str, Any]) -> str:
        """Format education for statement."""
        degree = education.get("degree", "")
        institution = education.get("institution", "Unknown")
        field = education.get("field", "")

        stmt = f"{degree} in {field} from {institution}" if field else f"{degree} from {institution}"
        return stmt

    @staticmethod
    def _generate_id() -> str:
        """Generate a UUID for evidence."""
        import uuid
        return str(uuid.uuid4())


# ============================================================================
# INTEGRATION: ONE-CALL MIGRATION
# ============================================================================

def perform_initial_migration(
    tracker_path: str = "tracker.json",
    profile_path: str = "profile.json",
    data_dir: str = "."
) -> Dict[str, Any]:
    """
    Perform initial migration to v2.0 with baseline evidence import.
    Safe, idempotent, reversible.

    Returns dict with migration results.
    """
    logger.info("Starting initial migration to v2.0...")

    tracker_repo = TrackerRepository(tracker_path)
    evidence_repo = EvidenceRepository(data_dir)
    cv_versions_repo = CVVersionsRepository(data_dir)

    # Step 1: Migrate tracker schema to v2.0
    tracker_repo.migrate_to_v2()

    # Step 2: Import baseline evidence
    importer = BaselineEvidenceImporter(profile_path, evidence_repo)
    evidence_count = importer.import_baseline_evidence()

    # Step 3: Create empty CV versions repo
    cv_repo = cv_versions_repo.load()  # This creates if not exists

    result = {
        "status": "success",
        "tracker_migrated_to": "v2.0",
        "evidence_items_created": evidence_count,
        "cv_versions_repo_initialized": True,
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }

    logger.info(f"Migration complete: {result}")
    return result
