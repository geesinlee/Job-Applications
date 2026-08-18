"""Unit tests for Gate 9 components to improve coverage."""

import pytest
from datetime import datetime
from src.evidence_backend import InMemoryEvidenceBackend
from src.evidence_models import StructuredEvidence, JDCriteria, RankedEvidence
from src.evidence_service import EvidenceMatcher, CVAssembler


class TestInMemoryEvidenceBackend:
    """Tests for InMemoryEvidenceBackend."""

    @pytest.fixture
    def backend(self):
        """Create fresh backend for each test."""
        return InMemoryEvidenceBackend()

    def test_save_and_retrieve_evidence(self, backend):
        """Should save evidence and retrieve it by ID."""
        evidence = StructuredEvidence(
            achievement="Built system",
            context="Production environment",
            impact="10x speedup",
            skills_demonstrated=["Python", "System Design"],
            job_title="Engineer",
            company_name="Corp",
            source_section="Experience",
            source_cv_id="cv_123"
        )

        eid = backend.save_evidence(evidence)
        assert eid is not None
        assert evidence.id == eid

        retrieved = backend.get_evidence_by_id(eid)
        assert retrieved is not None
        assert retrieved.achievement == evidence.achievement

    def test_get_evidence_by_cv_id_reverse_chronological(self, backend):
        """Should return evidence sorted reverse-chronologically."""
        cv_id = "cv_test"

        # Save in mixed order
        e1 = StructuredEvidence(
            achievement="A1", context="c1", impact="i1",
            skills_demonstrated=["S1"],
            job_title="Engineer", company_name="Corp",
            source_section="Experience", source_cv_id=cv_id,
            time_period_start=datetime(2020, 1, 1),
            time_period_end=datetime(2020, 12, 31)
        )
        e2 = StructuredEvidence(
            achievement="A2", context="c2", impact="i2",
            skills_demonstrated=["S2"],
            job_title="Senior", company_name="Corp",
            source_section="Experience", source_cv_id=cv_id,
            time_period_start=datetime(2021, 1, 1),
            time_period_end=datetime(2022, 12, 31)
        )
        e3 = StructuredEvidence(
            achievement="A3", context="c3", impact="i3",
            skills_demonstrated=["S3"],
            job_title="Lead", company_name="Corp",
            source_section="Experience", source_cv_id=cv_id,
            time_period_start=datetime(2019, 1, 1),
            time_period_end=datetime(2019, 12, 31)
        )

        backend.save_evidence(e1)
        backend.save_evidence(e2)
        backend.save_evidence(e3)

        loaded = backend.get_evidence_by_cv_id(cv_id)
        assert len(loaded) == 3
        # Should be in reverse chronological order
        assert loaded[0].time_period_end == datetime(2022, 12, 31)
        assert loaded[1].time_period_end == datetime(2020, 12, 31)
        assert loaded[2].time_period_end == datetime(2019, 12, 31)

    def test_delete_evidence(self, backend):
        """Should delete evidence."""
        evidence = StructuredEvidence(
            achievement="Test", context="c", impact="i",
            skills_demonstrated=["S"],
            job_title="Role", company_name="Corp",
            source_section="Experience", source_cv_id="cv_123"
        )

        eid = backend.save_evidence(evidence)
        assert backend.get_evidence_by_id(eid) is not None

        deleted = backend.delete_evidence(eid)
        assert deleted is True
        assert backend.get_evidence_by_id(eid) is None

    def test_delete_nonexistent_evidence(self, backend):
        """Should return False when deleting nonexistent evidence."""
        deleted = backend.delete_evidence("nonexistent_id")
        assert deleted is False


class TestEvidenceMatcher:
    """Tests for EvidenceMatcher component."""

    @pytest.fixture
    def matcher(self):
        """Create matcher for tests."""
        return EvidenceMatcher()

    def test_match_with_skill_overlap(self, matcher):
        """Should rank evidence based on skill overlap with JD."""
        evidence_list = [
            StructuredEvidence(
                achievement="Built Python service",
                context="Microservices",
                impact="High throughput",
                skills_demonstrated=["Python", "Kubernetes", "Docker"],
                job_title="Engineer", company_name="Corp",
                source_section="Experience", source_cv_id="cv_1"
            ),
            StructuredEvidence(
                achievement="Managed databases",
                context="DBA work",
                impact="High availability",
                skills_demonstrated=["PostgreSQL", "MySQL"],
                job_title="DBA", company_name="Corp",
                source_section="Experience", source_cv_id="cv_1"
            )
        ]

        jd = JDCriteria(
            explicit_skills=["Python", "Kubernetes"],
            inferred_skills=["System Design"],
            critical_criteria=["5+ years experience"],
            importance_ranking={"Python": 0.9, "Kubernetes": 0.8, "Docker": 0.7},
            company_name="Target", role_title="Engineer"
        )

        ranked = matcher.match(evidence_list, jd)
        assert len(ranked) == 2
        # First should have higher score (more skill matches)
        assert ranked[0].match_score >= ranked[1].match_score
        assert "Python" in ranked[0].matched_skills

    def test_match_with_no_overlap(self, matcher):
        """Should still assign scores even with no skill overlap."""
        evidence_list = [
            StructuredEvidence(
                achievement="COBOL programming",
                context="Legacy systems",
                impact="System maintained",
                skills_demonstrated=["COBOL"],
                job_title="Programmer", company_name="Corp",
                source_section="Experience", source_cv_id="cv_1"
            )
        ]

        jd = JDCriteria(
            explicit_skills=["Python", "Go"],
            inferred_skills=["Kubernetes"],
            critical_criteria=["5+ years experience"],
            importance_ranking={"Python": 0.9, "Go": 0.8},
            company_name="Target", role_title="Engineer"
        )

        ranked = matcher.match(evidence_list, jd)
        assert len(ranked) == 1
        assert 0.0 <= ranked[0].match_score <= 1.0


class TestCVAssembler:
    """Tests for CVAssembler component."""

    @pytest.fixture
    def assembler(self):
        """Create assembler for tests."""
        return CVAssembler()

    def test_assemble_with_deduplication(self, assembler):
        """Should deduplicate verbatim achievements."""
        evidence1 = StructuredEvidence(
            achievement="Led team to success",
            context="Corp A", impact="Good outcome",
            skills_demonstrated=["Leadership"],
            job_title="Manager", company_name="Corp A",
            source_section="Experience", source_cv_id="cv_1"
        )
        evidence2 = StructuredEvidence(
            achievement="Led team to success",  # Same!
            context="Corp B", impact="Great outcome",
            skills_demonstrated=["Leadership"],
            job_title="Manager", company_name="Corp B",
            source_section="Experience", source_cv_id="cv_1"
        )

        ranked = [
            RankedEvidence(evidence1, 0.9, [], []),
            RankedEvidence(evidence2, 0.8, [], [])
        ]

        assembled = assembler.assemble(ranked, section_type="Experience")
        # Count occurrences of the achievement
        count = assembled.count("Led team to success")
        assert count <= 1, "Verbatim achievement should appear at most once"

    def test_assemble_groups_by_role(self, assembler):
        """Should group evidence by company and role."""
        evidence_list = [
            StructuredEvidence(
                achievement="Built API",
                context="Context", impact="Impact",
                skills_demonstrated=["Python"],
                job_title="Engineer", company_name="Corp A",
                source_section="Experience", source_cv_id="cv_1"
            ),
            StructuredEvidence(
                achievement="Led team",
                context="Context", impact="Impact",
                skills_demonstrated=["Leadership"],
                job_title="Manager", company_name="Corp B",
                source_section="Experience", source_cv_id="cv_1"
            )
        ]

        ranked = [RankedEvidence(e, 0.9, [], []) for e in evidence_list]
        assembled = assembler.assemble(ranked, section_type="Experience")

        # Both roles should be mentioned
        assert "Engineer" in assembled or "Corp A" in assembled
        assert "Manager" in assembled or "Corp B" in assembled

    def test_assemble_respects_max_per_role(self, assembler):
        """Should respect max_per_role limit."""
        evidence_list = [
            StructuredEvidence(
                achievement=f"Achievement {i}",
                context="Context", impact="Impact",
                skills_demonstrated=["Skill"],
                job_title="Engineer", company_name="Corp",
                source_section="Experience", source_cv_id="cv_1"
            )
            for i in range(5)
        ]

        ranked = [RankedEvidence(e, 0.9, [], []) for e in evidence_list]
        assembled = assembler.assemble(ranked, section_type="Experience", max_per_role=2)

        # Count achievements
        count = sum(1 for i in range(5) if f"Achievement {i}" in assembled)
        assert count <= 2, f"Should have at most 2 items per role, got {count}"

    def test_assemble_empty_evidence(self, assembler):
        """Should handle empty evidence list."""
        assembled = assembler.assemble([], section_type="Experience")
        assert "Experience" in assembled
        assert "No relevant experience" in assembled
