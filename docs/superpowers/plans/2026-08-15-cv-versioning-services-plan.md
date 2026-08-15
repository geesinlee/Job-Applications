# Gate 6: CV Versioning Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement CVVersioningService to generate draft CVs backed by evidence, enforce approval gates, and track CV history with traceability.

**Architecture:** Pure Python service (no MCP/HTTP) that uses RequirementService (Gate 5) and EvidenceService (Gate 4) to match evidence to JD requirements, generate draft CV content with evidence citations, enforce human approval before finalization, and maintain version history. Existing MCP tools (save_tailored_cv, tailor_cv) refactored to use this service internally.

**Tech Stack:** Python 3.11+, dataclasses for CV records, RequirementService + EvidenceService dependencies, pytest for testing, TDD approach.

---

## File Structure

**New Production Code:**
- `cv_versioning_service.py` — CVVersioningService class, CV record dataclasses, draft generation, approval workflow
- Modify `job_applications_mcp_server.py` — Import CVVersioningService, refactor save_tailored_cv and tailor_cv tools

**New Test Code:**
- `tests/unit/test_cv_versioning_service.py` — 20+ unit tests for draft generation, approval gates, version history
- `tests/acceptance/test_cv_workflow.py` — End-to-end CV workflow (draft → approve → final)

**Data Structures:**
- `CVRecord` dataclass — metadata: version, status (draft/approved/final), evidence_used, timestamp
- `CVDraft` dataclass — generated content + traceability (which evidence → which requirement)

---

## Task 1: Create CV Record Data Classes

**Files:**
- Create: `cv_versioning_service.py` (lines 1–120)
- Test: `tests/unit/test_cv_versioning_service.py` (lines 1–80)

**Purpose:** Define data structures for CV records, drafts, and versions.

- [ ] **Step 1: Create cv_versioning_service.py with CVRecord dataclass**

```python
# cv_versioning_service.py
from dataclasses import dataclass, field
from typing import List, Optional, Dict
from datetime import datetime, timezone
from enum import Enum
import uuid


def _utc_now() -> str:
    """Return current UTC time in ISO 8601 format with Z suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class CVStatus(str, Enum):
    """Status of a CV record."""
    DRAFT = "draft"
    APPROVED = "approved"
    FINAL = "final"


@dataclass
class CVEvidenceUsage:
    """Link between CV content and evidence used."""
    evidence_id: str                   # ID of evidence used
    requirement_id: str                # Requirement this evidence satisfies
    content_excerpt: str               # CV text that uses this evidence
    placement_section: str             # CV section (experience, skills, etc.)


@dataclass
class CVRecord:
    """Represents a single version of a CV."""
    cv_id: str                         # Unique ID (UUID)
    application_id: str                # Application this CV is for
    version: str                       # "draft_1", "draft_2", "final"
    status: CVStatus                   # draft | approved | final
    content: str                       # CV markdown/text content
    evidence_used: List[CVEvidenceUsage] = field(default_factory=list)  # Traceability
    created_at: str = field(default_factory=_utc_now)
    approved_by: Optional[str] = None  # Claude / user who approved
    approved_at: Optional[str] = None  # Timestamp of approval
    finalized_at: Optional[str] = None  # Timestamp when marked final
```

- [ ] **Step 2: Add CVDraft dataclass**

```python
@dataclass
class CVDraft:
    """Draft CV with coverage information."""
    content: str                       # Generated CV content
    evidence_used: List[CVEvidenceUsage]  # Evidence references
    requirements_covered: int          # Count of fully covered requirements
    requirements_partial: int          # Count of partially covered requirements
    requirements_missing: int          # Count of missing requirements
    coverage_percentage: float         # (covered / total) * 100
```

- [ ] **Step 3: Run syntax check**

Run: `python3 -c "from cv_versioning_service import CVRecord, CVStatus, CVDraft; print('OK')"`
Expected: OK

- [ ] **Step 4: Commit**

```bash
git add cv_versioning_service.py
git commit -m "feat: Gate 6 data classes (CVRecord, CVStatus, CVDraft)"
```

---

## Task 2: Create CVVersioningService Class Skeleton

**Files:**
- Modify: `cv_versioning_service.py` (lines 121–200)
- Test: `tests/unit/test_cv_versioning_service.py` (lines 81–150)

**Purpose:** Define the CVVersioningService class with method signatures and dependencies.

- [ ] **Step 1: Add CVVersioningService class header and __init__**

```python
from requirement_service import RequirementService
from evidence_service import EvidenceService


class CVVersioningService:
    """Service for generating and versioning CVs backed by evidence."""

    def __init__(self, requirement_service: RequirementService, evidence_service: EvidenceService):
        """Initialize with dependencies.

        Args:
            requirement_service: RequirementService for requirement extraction and matching.
            evidence_service: EvidenceService for evidence queries.

        Raises:
            ValueError: If either service is None.
        """
        if requirement_service is None:
            raise ValueError("requirement_service is required")
        if evidence_service is None:
            raise ValueError("evidence_service is required")
        self.requirement_service = requirement_service
        self.evidence_service = evidence_service
        self.cv_records: Dict[str, CVRecord] = {}  # In-memory store (will use persistence in Gate 7)
```

- [ ] **Step 2: Add method signatures**

```python
    def generate_draft_cv(self, application_id: str, jd_fields: Dict, profile: Dict) -> CVDraft:
        """Generate a draft CV by matching evidence to JD requirements.

        Args:
            application_id: ID of the application.
            jd_fields: Extracted JD fields (required_skills, industry, etc.).
            profile: Candidate profile with work_experience, skills, education.

        Returns:
            CVDraft with generated content and traceability.
        """
        raise NotImplementedError()

    def create_draft_record(self, application_id: str, content: str, evidence_used: List[CVEvidenceUsage]) -> CVRecord:
        """Create a draft CV record.

        Args:
            application_id: ID of the application.
            content: CV content (markdown).
            evidence_used: List of evidence usage references.

        Returns:
            CVRecord with status=draft.
        """
        raise NotImplementedError()

    def approve_draft(self, cv_id: str, approved_by: str) -> CVRecord:
        """Mark a draft as approved, enabling finalization.

        Args:
            cv_id: ID of the CV record.
            approved_by: User/Claude identifier approving the CV.

        Returns:
            CVRecord with status=approved.

        Raises:
            ValueError: If CV is not in draft status.
        """
        raise NotImplementedError()

    def finalize_cv(self, cv_id: str) -> CVRecord:
        """Mark an approved CV as final.

        Args:
            cv_id: ID of the CV record.

        Returns:
            CVRecord with status=final.

        Raises:
            ValueError: If CV is not approved.
        """
        raise NotImplementedError()

    def get_cv_record(self, cv_id: str) -> Optional[CVRecord]:
        """Retrieve a CV record by ID.

        Args:
            cv_id: ID of the CV record.

        Returns:
            CVRecord if found, None otherwise.
        """
        raise NotImplementedError()

    def get_cv_history(self, application_id: str) -> List[CVRecord]:
        """Get all CV versions for an application.

        Args:
            application_id: ID of the application.

        Returns:
            List of CVRecords (draft, approved, final) ordered by created_at.
        """
        raise NotImplementedError()
```

- [ ] **Step 3: Run syntax check**

Run: `python3 -c "from cv_versioning_service import CVVersioningService; print('OK')"`
Expected: OK

- [ ] **Step 4: Commit**

```bash
git add cv_versioning_service.py
git commit -m "feat: CVVersioningService class skeleton with method signatures"
```

---

## Task 3: Implement generate_draft_cv Method

**Files:**
- Create: `tests/unit/test_cv_versioning_service.py` (lines 151–350)
- Modify: `cv_versioning_service.py` (lines 201–350)

**Purpose:** Implement draft CV generation by matching evidence to requirements. Use TDD.

- [ ] **Step 1: Write failing test for basic draft generation**

```python
# tests/unit/test_cv_versioning_service.py
import pytest
from unittest.mock import Mock
from cv_versioning_service import CVVersioningService, CVDraft, CVRecord, CVStatus, CVEvidenceUsage
from requirement_service import Requirement, RequirementType, ConfidenceLevel


@pytest.fixture
def mock_requirement_service():
    """Mock RequirementService."""
    return Mock()


@pytest.fixture
def mock_evidence_service():
    """Mock EvidenceService."""
    return Mock()


@pytest.fixture
def cv_service(mock_requirement_service, mock_evidence_service):
    """Create CVVersioningService with mocks."""
    return CVVersioningService(mock_requirement_service, mock_evidence_service)


class TestGenerateDraftCV:
    """Tests for CVVersioningService.generate_draft_cv method."""

    def test_draft_generation_basic(self, cv_service, mock_requirement_service):
        """Test that generate_draft_cv returns CVDraft with basic properties."""
        mock_requirement_service.extract_requirements.return_value = Mock(
            requirements=[]
        )

        jd_fields = {
            "required_skills": ["Python", "AWS"],
        }
        profile = {
            "headline": "Sales Executive",
            "work_experience": [
                {
                    "title": "Account Executive",
                    "company": "Gartner",
                    "start": "2020-01",
                    "end": "present",
                    "description": "Managed enterprise accounts",
                }
            ],
            "skills": ["Python", "AWS", "SQL"],
        }

        draft = cv_service.generate_draft_cv("app_123", jd_fields, profile)

        assert isinstance(draft, CVDraft)
        assert draft.content != ""
        assert draft.evidence_used == []
        assert draft.requirements_covered >= 0
        assert draft.requirements_partial >= 0
        assert draft.requirements_missing >= 0
        assert 0 <= draft.coverage_percentage <= 100

    def test_draft_includes_evidence_traceability(self, cv_service, mock_requirement_service, mock_evidence_service):
        """Test that draft includes links between CV content and evidence."""
        # Setup requirements
        req1 = Mock(
            requirement_id="r1",
            statement="Python",
            type=RequirementType.COMPETENCY,
            confidence_threshold=0.8,
        )

        from requirement_service import JobRequirements
        mock_reqs = JobRequirements(
            jd_id="jd1",
            company="Test",
            role_title="Dev",
            requirements=[req1],
        )
        mock_requirement_service.extract_requirements.return_value = mock_reqs

        # Setup evidence matches
        from requirement_service import RequirementMatch, MatchType, EvidenceConfidence
        match = RequirementMatch(
            requirement_id="r1",
            evidence_id="e1",
            evidence_statement="Python expert",
            similarity_score=1.0,
            match_type=MatchType.DETERMINISTIC,
            evidence_confidence=EvidenceConfidence.LEVEL_A,
        )
        mock_requirement_service.match_requirement.return_value = [match]

        jd_fields = {"required_skills": ["Python"]}
        profile = {"skills": ["Python"]}

        draft = cv_service.generate_draft_cv("app_123", jd_fields, profile)

        assert len(draft.evidence_used) > 0
        assert draft.evidence_used[0].evidence_id == "e1"
        assert draft.evidence_used[0].requirement_id == "r1"
```

- [ ] **Step 2: Run tests to confirm they fail**

Run: `pytest tests/unit/test_cv_versioning_service.py::TestGenerateDraftCV -v`
Expected: FAIL with "NotImplementedError"

- [ ] **Step 3: Implement generate_draft_cv method**

```python
# cv_versioning_service.py
def generate_draft_cv(self, application_id: str, jd_fields: Dict, profile: Dict) -> CVDraft:
    """Generate a draft CV by matching evidence to JD requirements."""
    # Extract requirements from JD
    job_requirements = self.requirement_service.extract_requirements(jd_fields)

    # For each requirement, find matching evidence
    evidence_used = []
    covered_count = 0
    partial_count = 0
    missing_count = 0

    for requirement in job_requirements.requirements:
        matches = self.requirement_service.match_requirement(requirement)

        if not matches:
            missing_count += 1
        else:
            best_match = max(matches, key=lambda m: m.similarity_score)
            if best_match.similarity_score >= requirement.confidence_threshold:
                covered_count += 1
            else:
                partial_count += 1

            # Track evidence usage for traceability
            usage = CVEvidenceUsage(
                evidence_id=best_match.evidence_id,
                requirement_id=requirement.requirement_id,
                content_excerpt=best_match.evidence_statement,
                placement_section="experience",  # Simplified for now
            )
            evidence_used.append(usage)

    # Generate CV content (simplified: list profile work experience)
    cv_lines = ["# Tailored CV"]
    cv_lines.append(f"\n## Headline\n{profile.get('headline', 'Professional')}")
    cv_lines.append("\n## Experience")
    for exp in profile.get("work_experience", []):
        cv_lines.append(f"\n### {exp['title']} at {exp['company']}")
        cv_lines.append(f"{exp['start']} – {exp['end']}\n{exp.get('description', '')}")

    content = "\n".join(cv_lines)
    total_requirements = covered_count + partial_count + missing_count
    coverage_percentage = (
        (covered_count / total_requirements * 100)
        if total_requirements > 0
        else 0.0
    )

    return CVDraft(
        content=content,
        evidence_used=evidence_used,
        requirements_covered=covered_count,
        requirements_partial=partial_count,
        requirements_missing=missing_count,
        coverage_percentage=coverage_percentage,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_cv_versioning_service.py::TestGenerateDraftCV -v`
Expected: 2 tests PASS

- [ ] **Step 5: Commit**

```bash
git add cv_versioning_service.py tests/unit/test_cv_versioning_service.py
git commit -m "feat: implement generate_draft_cv with evidence traceability (2 tests)"
```

---

## Task 4: Implement Draft Creation and Approval Workflow

**Files:**
- Modify: `tests/unit/test_cv_versioning_service.py` (add lines ~350–500)
- Modify: `cv_versioning_service.py` (add lines ~351–450)

**Purpose:** Implement create_draft_record, approve_draft, finalize_cv methods. Use TDD.

- [ ] **Step 1: Write tests for draft creation, approval, finalization**

```python
# tests/unit/test_cv_versioning_service.py - add to TestGenerateDraftCV or new class

class TestCVWorkflow:
    """Tests for CV draft → approval → final workflow."""

    def test_create_draft_record(self, cv_service):
        """Test creating a draft CV record."""
        content = "# CV"
        evidence = []

        record = cv_service.create_draft_record("app_123", content, evidence)

        assert record.status == CVStatus.DRAFT
        assert record.application_id == "app_123"
        assert record.content == content
        assert record.approved_at is None
        assert record.finalized_at is None
        assert "draft_" in record.version

    def test_approve_draft(self, cv_service):
        """Test approving a draft CV."""
        record = cv_service.create_draft_record("app_123", "# CV", [])
        cv_id = record.cv_id

        approved = cv_service.approve_draft(cv_id, approved_by="test_user")

        assert approved.status == CVStatus.APPROVED
        assert approved.approved_by == "test_user"
        assert approved.approved_at is not None

    def test_finalize_cv(self, cv_service):
        """Test finalizing an approved CV."""
        record = cv_service.create_draft_record("app_123", "# CV", [])
        cv_service.approve_draft(record.cv_id, approved_by="test_user")

        final = cv_service.finalize_cv(record.cv_id)

        assert final.status == CVStatus.FINAL
        assert final.finalized_at is not None

    def test_cannot_finalize_unapproved_draft(self, cv_service):
        """Test that finalizing a draft without approval raises error."""
        record = cv_service.create_draft_record("app_123", "# CV", [])

        with pytest.raises(ValueError, match="Cannot finalize non-approved CV"):
            cv_service.finalize_cv(record.cv_id)

    def test_get_cv_record(self, cv_service):
        """Test retrieving a CV record by ID."""
        record = cv_service.create_draft_record("app_123", "# CV", [])

        retrieved = cv_service.get_cv_record(record.cv_id)

        assert retrieved is not None
        assert retrieved.cv_id == record.cv_id
        assert retrieved.status == CVStatus.DRAFT

    def test_get_cv_history(self, cv_service):
        """Test retrieving all CV versions for an application."""
        # Create multiple drafts and finalize
        r1 = cv_service.create_draft_record("app_123", "# CV v1", [])
        r2 = cv_service.create_draft_record("app_123", "# CV v2", [])
        cv_service.approve_draft(r2.cv_id, "user")
        cv_service.finalize_cv(r2.cv_id)

        history = cv_service.get_cv_history("app_123")

        assert len(history) >= 2
        assert any(r.status == CVStatus.DRAFT for r in history)
        assert any(r.status == CVStatus.FINAL for r in history)
```

- [ ] **Step 2: Run tests to confirm they fail**

Run: `pytest tests/unit/test_cv_versioning_service.py::TestCVWorkflow -v`
Expected: All FAIL with "NotImplementedError"

- [ ] **Step 3: Implement the workflow methods**

```python
# cv_versioning_service.py - in CVVersioningService class

def create_draft_record(self, application_id: str, content: str, evidence_used: List[CVEvidenceUsage]) -> CVRecord:
    """Create a draft CV record."""
    # Count existing drafts to version them
    existing_drafts = [
        r for r in self.cv_records.values()
        if r.application_id == application_id and r.status == CVStatus.DRAFT
    ]
    version_num = len(existing_drafts) + 1

    record = CVRecord(
        cv_id=str(uuid.uuid4()),
        application_id=application_id,
        version=f"draft_{version_num}",
        status=CVStatus.DRAFT,
        content=content,
        evidence_used=evidence_used,
    )

    self.cv_records[record.cv_id] = record
    return record

def approve_draft(self, cv_id: str, approved_by: str) -> CVRecord:
    """Mark a draft as approved."""
    record = self.cv_records.get(cv_id)
    if record is None:
        raise ValueError(f"CV record {cv_id} not found")
    if record.status != CVStatus.DRAFT:
        raise ValueError(f"Cannot approve non-draft CV (status: {record.status})")

    record.status = CVStatus.APPROVED
    record.approved_by = approved_by
    record.approved_at = _utc_now()

    self.cv_records[cv_id] = record
    return record

def finalize_cv(self, cv_id: str) -> CVRecord:
    """Mark an approved CV as final."""
    record = self.cv_records.get(cv_id)
    if record is None:
        raise ValueError(f"CV record {cv_id} not found")
    if record.status != CVStatus.APPROVED:
        raise ValueError(f"Cannot finalize non-approved CV (status: {record.status})")

    record.status = CVStatus.FINAL
    record.finalized_at = _utc_now()

    self.cv_records[cv_id] = record
    return record

def get_cv_record(self, cv_id: str) -> Optional[CVRecord]:
    """Retrieve a CV record by ID."""
    return self.cv_records.get(cv_id)

def get_cv_history(self, application_id: str) -> List[CVRecord]:
    """Get all CV versions for an application."""
    records = [
        r for r in self.cv_records.values()
        if r.application_id == application_id
    ]
    return sorted(records, key=lambda r: r.created_at)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_cv_versioning_service.py::TestCVWorkflow -v`
Expected: 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add cv_versioning_service.py tests/unit/test_cv_versioning_service.py
git commit -m "feat: implement draft creation and approval workflow (6 tests)"
```

---

## Task 5: Add Integration and Edge Case Tests

**Files:**
- Modify: `tests/unit/test_cv_versioning_service.py` (add lines ~500–650)

**Purpose:** Test full lifecycle, edge cases, and integration with RequirementService.

- [ ] **Step 1: Write full lifecycle test**

```python
class TestIntegrationAndEdgeCases:
    """Integration and edge case tests."""

    def test_full_cv_lifecycle(self, cv_service, mock_requirement_service, mock_evidence_service):
        """Full lifecycle: generate draft → create record → approve → finalize."""
        # Setup mocks
        from requirement_service import JobRequirements
        mock_requirement_service.extract_requirements.return_value = JobRequirements(
            jd_id="jd1", company="Test", role_title="Dev", requirements=[]
        )

        jd_fields = {"required_skills": ["Python"]}
        profile = {"headline": "Dev", "work_experience": [], "skills": ["Python"]}

        # Generate draft
        draft = cv_service.generate_draft_cv("app_123", jd_fields, profile)
        assert draft.content != ""

        # Create record from draft
        record = cv_service.create_draft_record("app_123", draft.content, draft.evidence_used)
        assert record.status == CVStatus.DRAFT

        # Approve
        approved = cv_service.approve_draft(record.cv_id, "reviewer")
        assert approved.status == CVStatus.APPROVED

        # Finalize
        final = cv_service.finalize_cv(record.cv_id)
        assert final.status == CVStatus.FINAL

        # Verify history
        history = cv_service.get_cv_history("app_123")
        assert len(history) == 1
        assert history[0].status == CVStatus.FINAL

    def test_multiple_draft_versions(self, cv_service):
        """Test creating multiple draft versions for same application."""
        r1 = cv_service.create_draft_record("app_123", "# V1", [])
        r2 = cv_service.create_draft_record("app_123", "# V2", [])

        assert r1.version == "draft_1"
        assert r2.version == "draft_2"
        assert r1.cv_id != r2.cv_id

    def test_evidence_traceability_preserved(self, cv_service):
        """Test that evidence usage is preserved through draft creation."""
        from cv_versioning_service import CVEvidenceUsage

        evidence = [
            CVEvidenceUsage(
                evidence_id="e1",
                requirement_id="r1",
                content_excerpt="Python experience",
                placement_section="experience",
            )
        ]

        record = cv_service.create_draft_record("app_123", "# CV", evidence)

        assert len(record.evidence_used) == 1
        assert record.evidence_used[0].evidence_id == "e1"
```

- [ ] **Step 2: Write edge case tests**

```python
    def test_approve_nonexistent_cv(self, cv_service):
        """Test that approving nonexistent CV raises error."""
        with pytest.raises(ValueError, match="not found"):
            cv_service.approve_draft("nonexistent_id", "user")

    def test_finalize_nonexistent_cv(self, cv_service):
        """Test that finalizing nonexistent CV raises error."""
        with pytest.raises(ValueError, match="not found"):
            cv_service.finalize_cv("nonexistent_id")

    def test_approve_already_approved(self, cv_service):
        """Test that approving an already-approved CV raises error."""
        record = cv_service.create_draft_record("app_123", "# CV", [])
        cv_service.approve_draft(record.cv_id, "user1")

        with pytest.raises(ValueError, match="non-draft"):
            cv_service.approve_draft(record.cv_id, "user2")

    def test_empty_evidence_list(self, cv_service):
        """Test that CVRecord can be created with empty evidence."""
        record = cv_service.create_draft_record("app_123", "# CV", [])

        assert record.evidence_used == []
        assert record.cv_id is not None
```

- [ ] **Step 3: Run all tests to verify they pass**

Run: `pytest tests/unit/test_cv_versioning_service.py -v`
Expected: 15+ tests PASS

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_cv_versioning_service.py
git commit -m "test: add integration and edge case tests (7 more tests)"
```

---

## Task 6: Refactor save_tailored_cv MCP Tool to Use CVVersioningService

**Files:**
- Modify: `job_applications_mcp_server.py` (lines ~1780–1850)

**Purpose:** Integrate CVVersioningService into save_tailored_cv tool without changing Claude workflow.

- [ ] **Step 1: Import CVVersioningService at top of job_applications_mcp_server.py**

```python
from cv_versioning_service import CVVersioningService
```

- [ ] **Step 2: Add helper function to initialize CVVersioningService**

```python
def _get_or_create_cv_service():
    """Lazy-load CVVersioningService instance.

    In Gate 7+, this will use persistent storage.
    For now, we create an instance that uses in-memory storage.
    """
    evidence_service = _get_or_create_evidence_service()
    requirement_service = RequirementService(evidence_service)
    return CVVersioningService(requirement_service, evidence_service)
```

- [ ] **Step 3: Refactor save_tailored_cv to use CVVersioningService**

Find the current save_tailored_cv function (around line 1780) and replace its body:

```python
@mcp.tool()
def save_tailored_cv(company: str, role_title: str, cv_content: str) -> dict:
    """Save a tailored CV for an application.

    Validates fabrication protection, creates draft CV record, updates application.

    Args:
        company: Target employer name.
        role_title: Role title identifying the application.
        cv_content: Tailored CV markdown content.
    """
    tracker = _load_tracker()
    app = _find_application(tracker, company, role_title)
    if app is None:
        return {"ok": False, "error": "application_not_found", "company": company, "role_title": role_title}

    # Validate fabrication protection (existing logic)
    base_cv_path = _resolve_company_folder(company, role_title, tracker) / BASE_CV_PATH.name
    if not base_cv_path.exists():
        return {"ok": False, "error": "base_cv_not_found"}

    base_cv_content = _read_file(base_cv_path)
    protected_lines = _protected_lines(base_cv_content)
    for protected in protected_lines:
        if protected not in cv_content:
            return {
                "ok": False,
                "error": "fabrication_detected",
                "message": f"Protected line missing or altered: {protected[:50]}...",
            }

    # Create draft CV record using CVVersioningService
    cv_service = _get_or_create_cv_service()
    draft_record = cv_service.create_draft_record(
        application_id=app["id"],
        content=cv_content,
        evidence_used=[]  # Will be populated in Gate 7 when evidence is linked
    )

    # Save to filesystem
    cv_path = _resolve_company_folder(company, role_title, tracker) / "CV_tailored.md"
    cv_path.write_text(cv_content, encoding="utf-8")

    # Record in tracker
    app["cv_records"] = app.get("cv_records", [])
    app["cv_records"].append({
        "cv_id": draft_record.cv_id,
        "version": draft_record.version,
        "status": draft_record.status.value,
        "saved_at": draft_record.created_at,
    })

    _save_tracker(tracker)

    return {
        "ok": True,
        "company": company,
        "role_title": role_title,
        "cv_id": draft_record.cv_id,
        "version": draft_record.version,
        "status": draft_record.status.value,
        "output_path": str(cv_path),
    }
```

- [ ] **Step 4: Run tests to verify no regression**

Run: `pytest tests/unit/test_mcp_server.py -v --tb=short`
Expected: All existing tests still PASS

- [ ] **Step 5: Commit**

```bash
git add job_applications_mcp_server.py
git commit -m "refactor: integrate CVVersioningService into save_tailored_cv MCP tool"
```

---

## Task 7: Run Full Test Suite and Verification

**Files:**
- No changes; verification only

**Purpose:** Ensure all tests pass, coverage >90%, server imports successfully.

- [ ] **Step 1: Run entire test suite**

Run: `pytest tests/unit/test_cv_versioning_service.py -v`
Expected: All 15+ tests PASS

- [ ] **Step 2: Check test coverage**

Run: `pytest tests/unit/test_cv_versioning_service.py --cov=cv_versioning_service --cov-report=term-missing`
Expected: Coverage > 90%

- [ ] **Step 3: Run MCP server sanity check**

Run: `python3 -c "import job_applications_mcp_server; print('✅ Server imports successfully')"`
Expected: ✅ Server imports successfully

- [ ] **Step 4: Check git status**

Run: `git status`
Expected: Working tree clean (only .coverage untracked)

- [ ] **Step 5: Review commits**

Run: `git log --oneline | head -10`
Expected: Gate 6 commits visible (at least 4)

- [ ] **Step 6: Final summary**

Verify:
- ✅ 15+ unit tests: ALL PASSING
- ✅ Coverage: >90%
- ✅ Server imports: NO ERRORS
- ✅ Git status: CLEAN
- ✅ Commits: All task commits recorded

---

## Summary

| Task | Component | Status | Tests |
|------|-----------|--------|-------|
| 1 | Data classes (CVRecord, CVStatus, CVDraft) | Design | 0 |
| 2 | CVVersioningService skeleton | Design | 0 |
| 3 | generate_draft_cv method | TDD | 2 |
| 4 | Draft creation + approval + finalization | TDD | 6 |
| 5 | Integration and edge case tests | TDD | 7+ |
| 6 | Refactor save_tailored_cv MCP tool | Refactor | 0 |
| 7 | Full test suite and verification | Verify | 15+ |

**Total:** 7 tasks, ~15+ test cases, 300+ lines of production code, 0 regression.

**Next Gate:** Gate 7 (Persistence & Migration) — migrate to SQLite, integrate with persistence layer, enable cross-application evidence reuse.
