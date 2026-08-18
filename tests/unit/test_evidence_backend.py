"""Unit tests for EvidenceBackend abstraction and PostgresEvidenceBackend.

Tests the backend interface and Postgres implementation for evidence persistence.
"""

import pytest
import os
from datetime import datetime
from evidence_models import StructuredEvidence, JDCriteria, RankedEvidence
from evidence_backend import EvidenceBackend, PostgresEvidenceBackend


class TestEvidenceBackendInterface:
    """Test that EvidenceBackend is a proper ABC."""

    def test_evidence_backend_cannot_instantiate(self):
        """Should not be able to instantiate abstract EvidenceBackend."""
        with pytest.raises(TypeError):
            backend = EvidenceBackend()


class TestPostgresEvidenceBackendSaveAndLoad:
    """Test save and load operations for evidence persistence."""

    @pytest.fixture
    def pg_backend(self):
        """Fixture to provide PostgresEvidenceBackend for tests.

        Skips if DATABASE_URL not set (expected for Mac dev).
        """
        db_url = os.environ.get("DATABASE_URL")
        if not db_url:
            pytest.skip("DATABASE_URL not set (expected for Mac dev)")

        backend = PostgresEvidenceBackend(db_url)
        yield backend
        backend.close()

    def test_save_and_load_evidence(self, pg_backend):
        """Should save evidence and retrieve it by ID."""
        evidence = StructuredEvidence(
            achievement="Led cloud migration project",
            context="DXC enterprise client",
            impact="Reduced infrastructure costs by 30% annually",
            skills_demonstrated=["AWS", "Cloud Architecture", "Team Leadership"],
            job_title="Senior Cloud Architect",
            company_name="DXC Technology",
            source_section="Experience",
            source_cv_id="cv_test_001",
            time_period_start=datetime(2020, 1, 1),
            time_period_end=datetime(2023, 12, 31)
        )

        # Save
        evidence_id = pg_backend.save_evidence(evidence)
        assert evidence_id is not None
        assert isinstance(evidence_id, str)

        # Load
        loaded = pg_backend.get_evidence_by_id(evidence_id)
        assert loaded is not None
        assert loaded.achievement == evidence.achievement
        assert loaded.company_name == evidence.company_name
        assert loaded.skills_demonstrated == evidence.skills_demonstrated
        assert loaded.id == evidence_id

    def test_query_by_cv_id(self, pg_backend):
        """Should query all evidence for a specific CV."""
        # Save two pieces of evidence for same CV
        cv_id = "cv_test_query_001"
        evidence1 = StructuredEvidence(
            achievement="Achievement 1",
            context="Context 1",
            impact="Impact 1",
            skills_demonstrated=["Skill1", "Skill2"],
            job_title="Title 1",
            company_name="Company A",
            source_section="Experience",
            source_cv_id=cv_id
        )
        evidence2 = StructuredEvidence(
            achievement="Achievement 2",
            context="Context 2",
            impact="Impact 2",
            skills_demonstrated=["Skill3"],
            job_title="Title 2",
            company_name="Company B",
            source_section="Projects",
            source_cv_id=cv_id
        )

        id1 = pg_backend.save_evidence(evidence1)
        id2 = pg_backend.save_evidence(evidence2)

        # Query by CV ID
        results = pg_backend.get_evidence_by_cv_id(cv_id)
        assert len(results) >= 2
        ids = [e.id for e in results]
        assert id1 in ids
        assert id2 in ids

    def test_query_by_skills(self, pg_backend):
        """Should query evidence matching specific skills."""
        evidence = StructuredEvidence(
            achievement="Built Kubernetes cluster",
            context="Infrastructure modernization",
            impact="Enabled containerized deployments",
            skills_demonstrated=["Kubernetes", "Docker", "AWS"],
            job_title="DevOps Engineer",
            company_name="TechCorp",
            source_section="Experience",
            source_cv_id="cv_test_skills_001"
        )

        pg_backend.save_evidence(evidence)

        # Query by skill
        results = pg_backend.query_by_skills(["Kubernetes"])
        assert len(results) > 0
        assert any("Kubernetes" in e.skills_demonstrated for e in results)

        # Query by multiple skills
        results = pg_backend.query_by_skills(["Kubernetes", "Docker"])
        assert len(results) > 0
        assert any("Kubernetes" in e.skills_demonstrated and "Docker" in e.skills_demonstrated for e in results)

    def test_query_by_company_and_timeframe(self, pg_backend):
        """Should query evidence by company name and time period."""
        company = "QueryTestCorp"
        evidence = StructuredEvidence(
            achievement="Managed legacy system",
            context="Corporate IT",
            impact="System uptime 99.9%",
            skills_demonstrated=["System Administration"],
            job_title="Senior SysAdmin",
            company_name=company,
            source_section="Experience",
            source_cv_id="cv_test_company_001",
            time_period_start=datetime(2019, 6, 1),
            time_period_end=datetime(2022, 12, 31)
        )

        pg_backend.save_evidence(evidence)

        # Query by company
        results = pg_backend.query_by_company(company)
        assert len(results) > 0
        assert any(e.company_name == company for e in results)

        # Query by timeframe
        results = pg_backend.query_by_timeframe(
            start=datetime(2019, 1, 1),
            end=datetime(2023, 1, 1)
        )
        assert len(results) > 0
        # Verify at least one result has overlapping timeframe
        assert any(
            e.time_period_start and e.time_period_start <= datetime(2022, 12, 31) and
            e.time_period_end and e.time_period_end >= datetime(2019, 6, 1)
            for e in results
        )


class TestPostgresEvidenceBackendErrorHandling:
    """Test error handling in PostgresEvidenceBackend."""

    def test_get_evidence_by_nonexistent_id(self):
        """Should return None for nonexistent evidence ID."""
        db_url = os.environ.get("DATABASE_URL")
        if not db_url:
            pytest.skip("DATABASE_URL not set (expected for Mac dev)")

        backend = PostgresEvidenceBackend(db_url)
        try:
            result = backend.get_evidence_by_id("nonexistent_id_12345")
            assert result is None
        finally:
            backend.close()

    def test_invalid_database_url(self):
        """Should raise error when database URL is invalid."""
        with pytest.raises(Exception):  # Could be connection error, URI error, etc.
            backend = PostgresEvidenceBackend("invalid://not-a-url")
            # Try to use the backend to trigger connection
            backend.query_by_company("test")
