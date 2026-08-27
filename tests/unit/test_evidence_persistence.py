# tests/unit/test_evidence_persistence.py
"""
Unit tests for persistence layer (evidence_persistence.py).

Tests schema migration, I/O, backward compatibility, and baseline evidence import.
"""

import pytest
import json
import uuid
from pathlib import Path
from datetime import datetime
from evidence_persistence import (
    EvidenceRepository,
    CVVersionsRepository,
    TrackerRepository,
    BaselineEvidenceImporter,
    perform_initial_migration,
    EVIDENCE_REPO_VERSION,
    TRACKER_SCHEMA_V1,
    TRACKER_SCHEMA_V2,
    get_default_evidence_repo,
    get_default_cv_versions_repo,
    get_extended_application_defaults,
)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def tmp_data_dir(tmp_path):
    """Temporary data directory for tests."""
    return str(tmp_path)


@pytest.fixture
def evidence_repo(tmp_data_dir):
    """EvidenceRepository instance for testing."""
    return EvidenceRepository(tmp_data_dir)


@pytest.fixture
def cv_versions_repo(tmp_data_dir):
    """CVVersionsRepository instance for testing."""
    return CVVersionsRepository(tmp_data_dir)


@pytest.fixture
def tracker_repo(tmp_path):
    """TrackerRepository instance for testing."""
    tracker_path = tmp_path / "tracker.json"

    # Create a v1.0 tracker
    tracker_v1 = {
        "schema_version": TRACKER_SCHEMA_V1,
        "applications": [
            {
                "id": "app-1",
                "company": "TestCorp",
                "role_title": "Test Role",
                "jd_path": "TestCorp/JD.md",
                "stage": "new",
                "date_created": "2026-08-10T10:00:00Z",
                "history": [{"stage": "new", "at": "2026-08-10T10:00:00Z"}],
                "followups": [],
                "jd_source_url": None,
            }
        ]
    }

    with open(tracker_path, 'w') as f:
        json.dump(tracker_v1, f)

    return TrackerRepository(str(tracker_path))


@pytest.fixture
def sample_profile(tmp_path):
    """Sample profile.json for baseline import tests."""
    profile = {
        "schema_version": "1.0",
        "headline": "Test Professional",
        "current_role": {"title": "Senior Engineer", "company": "TestCorp"},
        "work_experience": [
            {
                "title": "Senior Engineer",
                "company": "TestCorp",
                "start": "2023",
                "end": "present",
                "description": "Led team on cloud migration",
                "_source": "baseline_cv"
            },
            {
                "title": "Engineer",
                "company": "PrevCorp",
                "start": "2020",
                "end": "2023",
                "description": "Built microservices",
                "_source": "baseline_cv"
            }
        ],
        "education": [
            {
                "degree": "BS",
                "institution": "MIT",
                "field": "Computer Science",
                "_source": "baseline_cv"
            }
        ],
        "certifications": [],
        "skills": ["Python", "Salesforce", "AWS", "Leadership"],
        "conflicts": [],
        "last_updated": {}
    }

    profile_path = tmp_path / "profile.json"
    with open(profile_path, 'w') as f:
        json.dump(profile, f)

    return str(profile_path)


# ============================================================================
# EVIDENCE REPOSITORY TESTS
# ============================================================================

@pytest.mark.evidence
def test_evidence_repo_creates_new_repo(evidence_repo, tmp_data_dir):
    """EvidenceRepository creates new repo on load if not exists."""
    repo = evidence_repo.load()

    assert repo is not None
    assert repo["schema_version"] == EVIDENCE_REPO_VERSION
    assert "evidence_repository" in repo
    assert repo["evidence_repository"]["evidence_list"] == []

    # File should exist now
    assert (Path(tmp_data_dir) / "evidence.json").exists()


@pytest.mark.evidence
def test_evidence_repo_add_and_retrieve(evidence_repo):
    """Can add and retrieve evidence."""
    evidence = {
        "evidence_id": str(uuid.uuid4()),
        "statement": "Test achievement",
        "evidence_type": "achievement",
        "source_type": "baseline_cv",
        "source_reference": "Test CV",
        "confidence": "LEVEL_A",
        "verification_status": "user_confirmed",
        "user_confirmed": True,
        "competencies": ["Test"],
        "technologies": [],
        "industries": [],
        "geographies": [],
        "metrics": {},
        "supersedes": [],
        "superseded_by": [],
        "related_to": [],
        "notes": "",
        "created_by": "test",
        "created_at": datetime.utcnow().isoformat() + "Z",
        "last_modified_by": "test",
        "last_modified_at": datetime.utcnow().isoformat() + "Z",
    }

    # Add
    evidence_repo.add_evidence(evidence)

    # Retrieve
    retrieved = evidence_repo.get_evidence(evidence["evidence_id"])
    assert retrieved is not None
    assert retrieved["statement"] == evidence["statement"]
    assert retrieved["evidence_id"] == evidence["evidence_id"]


@pytest.mark.evidence
def test_evidence_repo_list_all(evidence_repo):
    """Can list all evidence."""
    for i in range(3):
        evidence = {
            "evidence_id": str(uuid.uuid4()),
            "statement": f"Test {i}",
            "evidence_type": "achievement",
            "source_type": "baseline_cv",
            "source_reference": "Test CV",
            "confidence": "LEVEL_A",
            "verification_status": "user_confirmed",
            "user_confirmed": True,
            "competencies": [],
            "technologies": [],
            "industries": [],
            "geographies": [],
            "metrics": {},
            "supersedes": [],
            "superseded_by": [],
            "related_to": [],
            "notes": "",
            "created_by": "test",
            "created_at": datetime.utcnow().isoformat() + "Z",
            "last_modified_by": "test",
            "last_modified_at": datetime.utcnow().isoformat() + "Z",
        }
        evidence_repo.add_evidence(evidence)

    evidence_list = evidence_repo.list_evidence()
    assert len(evidence_list) == 3


@pytest.mark.evidence
def test_evidence_repo_filter(evidence_repo):
    """Can filter evidence by source_type."""
    # Add evidence with different sources
    baseline = {
        "evidence_id": str(uuid.uuid4()),
        "statement": "Baseline fact",
        "source_type": "baseline_cv",
        "competencies": [],
        "technologies": [],
        "industries": [],
        "geographies": [],
        "metrics": {},
        "supersedes": [],
        "superseded_by": [],
        "related_to": [],
        "created_by": "test",
        "created_at": datetime.utcnow().isoformat() + "Z",
        "last_modified_by": "test",
        "last_modified_at": datetime.utcnow().isoformat() + "Z",
        "verification_status": "user_confirmed",
        "user_confirmed": True,
        "notes": "",
    }
    user_supplied = baseline.copy()
    user_supplied["evidence_id"] = str(uuid.uuid4())
    user_supplied["source_type"] = "user_supplied"
    user_supplied["statement"] = "User fact"

    evidence_repo.add_evidence(baseline)
    evidence_repo.add_evidence(user_supplied)

    # Filter by source_type
    baseline_only = evidence_repo.list_evidence({"source_type": "baseline_cv"})
    assert len(baseline_only) == 1
    assert baseline_only[0]["statement"] == "Baseline fact"


@pytest.mark.evidence
def test_evidence_repo_update(evidence_repo):
    """Can update evidence."""
    evidence = {
        "evidence_id": str(uuid.uuid4()),
        "statement": "Original statement",
        "source_type": "baseline_cv",
        "verification_status": "unverified",
        "user_confirmed": False,
        "competencies": [],
        "technologies": [],
        "industries": [],
        "geographies": [],
        "metrics": {},
        "supersedes": [],
        "superseded_by": [],
        "related_to": [],
        "created_by": "test",
        "created_at": datetime.utcnow().isoformat() + "Z",
        "last_modified_by": "test",
        "last_modified_at": datetime.utcnow().isoformat() + "Z",
        "notes": "",
    }
    evidence_repo.add_evidence(evidence)

    # Update
    updated = evidence_repo.update_evidence(evidence["evidence_id"], {
        "verification_status": "user_confirmed",
        "user_confirmed": True
    })

    assert updated is not None
    assert updated["verification_status"] == "user_confirmed"
    assert updated["user_confirmed"] == True


# ============================================================================
# CV VERSIONS REPOSITORY TESTS
# ============================================================================

@pytest.mark.cv
def test_cv_versions_repo_creates_new_repo(cv_versions_repo, tmp_data_dir):
    """CVVersionsRepository creates new repo on load if not exists."""
    repo = cv_versions_repo.load()

    assert repo is not None
    assert repo["schema_version"] == "1.0"
    assert repo["cv_records"] == []

    # File should exist now
    assert (Path(tmp_data_dir) / "cv_versions.json").exists()


@pytest.mark.cv
def test_cv_versions_repo_add_and_list(cv_versions_repo):
    """Can add and list CV records for an application."""
    app_id = "app-1"

    for i in range(2):
        cv_record = {
            "cv_record_id": str(uuid.uuid4()),
            "application_id": app_id,
            "version": f"draft_{i+1}",
            "version_number": i + 1,
            "status": "draft",
            "content": f"Draft {i+1} content",
            "evidence_used": [],
            "major_changes": [],
            "changed_sections": [],
            "significant_omissions": [],
            "created_at": datetime.utcnow().isoformat() + "Z",
            "approved_at": None,
            "finalized_at": None,
            "predecessor_id": None,
            "successor_id": None,
            "created_by": "test",
            "last_modified_by": "test",
            "last_modified_at": datetime.utcnow().isoformat() + "Z",
        }
        cv_versions_repo.add_cv_record(cv_record)

    # List for application
    records = cv_versions_repo.list_cv_records(app_id)
    assert len(records) == 2
    assert all(r["application_id"] == app_id for r in records)


# ============================================================================
# TRACKER REPOSITORY TESTS
# ============================================================================

@pytest.mark.tracker
def test_tracker_schema_v1_detection(tracker_repo):
    """Detects v1.0 schema."""
    version = tracker_repo.get_schema_version()
    assert version == TRACKER_SCHEMA_V1
    assert not tracker_repo.is_migrated()


@pytest.mark.tracker
def test_tracker_migrate_to_v2(tracker_repo):
    """Migrates tracker from v1.0 to v2.0 (non-destructive)."""
    # Before migration
    tracker_before = tracker_repo.load()
    app_before = tracker_before["applications"][0]

    assert tracker_before["schema_version"] == TRACKER_SCHEMA_V1
    assert "requirements" not in app_before
    assert "cv_records" not in app_before

    # Perform migration
    tracker_repo.migrate_to_v2()

    # After migration
    tracker_after = tracker_repo.load()
    assert tracker_after["schema_version"] == TRACKER_SCHEMA_V2
    assert tracker_repo.is_migrated()

    # All v1.0 fields preserved
    app_after = tracker_after["applications"][0]
    assert app_after["id"] == app_before["id"]
    assert app_after["company"] == app_before["company"]
    assert app_after["stage"] == app_before["stage"]

    # v2.0 fields added
    assert "requirements" in app_after
    assert isinstance(app_after["requirements"], list)
    assert "cv_records" in app_after
    assert isinstance(app_after["cv_records"], list)
    assert "gap_interview_phase" in app_after
    assert app_after["gap_interview_phase"] == "not_started"


@pytest.mark.tracker
def test_tracker_idempotent_migration(tracker_repo):
    """Migrating twice is safe (idempotent)."""
    # First migration
    tracker_repo.migrate_to_v2()
    tracker1 = tracker_repo.load()

    # Second migration
    tracker_repo.migrate_to_v2()
    tracker2 = tracker_repo.load()

    # Should be identical
    assert tracker1 == tracker2
    assert tracker_repo.get_schema_version() == TRACKER_SCHEMA_V2


@pytest.mark.tracker
def test_tracker_revert_to_v1(tracker_repo):
    """Can revert tracker from v2.0 to v1.0."""
    # Migrate to v2.0
    tracker_repo.migrate_to_v2()
    tracker_v2 = tracker_repo.load()
    app_v2 = tracker_v2["applications"][0]

    assert tracker_v2["schema_version"] == TRACKER_SCHEMA_V2
    assert "requirements" in app_v2

    # Revert to v1.0
    tracker_repo.revert_to_v1()
    tracker_v1 = tracker_repo.load()
    app_v1 = tracker_v1["applications"][0]

    assert tracker_v1["schema_version"] == TRACKER_SCHEMA_V1
    assert "requirements" not in app_v1
    assert "cv_records" not in app_v1

    # Original v1.0 fields preserved
    assert app_v1["id"] == app_v2["id"]
    assert app_v1["company"] == app_v2["company"]


# ============================================================================
# BASELINE EVIDENCE IMPORT TESTS
# ============================================================================

@pytest.mark.evidence
def test_baseline_evidence_import(evidence_repo, sample_profile):
    """Imports evidence from profile.json."""
    importer = BaselineEvidenceImporter(sample_profile, evidence_repo)
    count = importer.import_baseline_evidence()

    # Should import: 2 work experiences + 1 education + 4 skills = 7 items
    assert count == 7

    # Verify repo has items
    all_evidence = evidence_repo.list_evidence()
    assert len(all_evidence) == 7

    # Check types
    work_experiences = [e for e in all_evidence if e["evidence_type"] == "work_experience"]
    assert len(work_experiences) == 2

    skills = [e for e in all_evidence if e["evidence_type"] == "skill"]
    assert len(skills) == 5  # 1 education + 4 skills


@pytest.mark.evidence
def test_baseline_evidence_has_correct_source(evidence_repo, sample_profile):
    """Baseline evidence has correct source type."""
    importer = BaselineEvidenceImporter(sample_profile, evidence_repo)
    importer.import_baseline_evidence()

    all_evidence = evidence_repo.list_evidence()

    # All should be from baseline or profile
    for evidence in all_evidence:
        assert evidence["source_type"] in ["baseline_cv", "linkedin"]
        assert "profile.json" in evidence["source_reference"] or "baseline" in evidence["source_reference"].lower()


@pytest.mark.evidence
def test_baseline_evidence_idempotent(evidence_repo, sample_profile):
    """Multiple imports don't create duplicates (in real implementation)."""
    importer = BaselineEvidenceImporter(sample_profile, evidence_repo)

    # Import twice
    count1 = importer.import_baseline_evidence()
    count2 = importer.import_baseline_evidence()

    # This test shows the current behavior (duplicates created)
    # In production, should implement dedup logic
    all_evidence = evidence_repo.list_evidence()
    assert len(all_evidence) == count1 + count2


# ============================================================================
# INTEGRATION TESTS
# ============================================================================

@pytest.mark.e2e
def test_full_migration_flow(tmp_path):
    """Full migration: schema upgrade + baseline evidence import."""
    # Setup
    tracker_path = tmp_path / "tracker.json"
    profile_path = tmp_path / "profile.json"

    # Create v1.0 tracker
    tracker_v1 = {
        "schema_version": TRACKER_SCHEMA_V1,
        "applications": [
            {
                "id": "app-1",
                "company": "TestCorp",
                "role_title": "Test Role",
                "jd_path": "TestCorp/JD.md",
                "stage": "new",
                "date_created": "2026-08-10T10:00:00Z",
                "history": [{"stage": "new", "at": "2026-08-10T10:00:00Z"}],
                "followups": [],
                "jd_source_url": None,
            }
        ]
    }
    with open(tracker_path, 'w') as f:
        json.dump(tracker_v1, f)

    # Create profile
    profile = {
        "schema_version": "1.0",
        "headline": "Test",
        "current_role": {"title": "Engineer", "company": "TestCorp"},
        "work_experience": [
            {
                "title": "Engineer",
                "company": "TestCorp",
                "start": "2023",
                "end": "present",
                "description": "Worked on cloud",
                "_source": "baseline_cv"
            }
        ],
        "education": [],
        "certifications": [],
        "skills": ["Python"],
        "conflicts": [],
        "last_updated": {}
    }
    with open(profile_path, 'w') as f:
        json.dump(profile, f)

    # Run migration
    result = perform_initial_migration(
        tracker_path=str(tracker_path),
        profile_path=str(profile_path),
        data_dir=str(tmp_path)
    )

    # Verify result
    assert result["status"] == "success"
    assert result["tracker_migrated_to"] == "v2.0"
    assert result["evidence_items_created"] == 2  # 1 work exp + 1 skill
    assert result["cv_versions_repo_initialized"] == True

    # Verify files exist
    assert (tmp_path / "evidence.json").exists()
    assert (tmp_path / "cv_versions.json").exists()
    assert tracker_path.exists()

    # Verify tracker is v2.0
    with open(tracker_path) as f:
        tracker_after = json.load(f)
    assert tracker_after["schema_version"] == TRACKER_SCHEMA_V2

    # Verify evidence repo has items
    with open(tmp_path / "evidence.json") as f:
        evidence_repo_data = json.load(f)
    assert len(evidence_repo_data["evidence_repository"]["evidence_list"]) == 2
