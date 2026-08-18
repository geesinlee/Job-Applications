"""Unit tests for evidence dataclasses.

Tests StructuredEvidence, JDCriteria, and RankedEvidence models per Gate 9 design.
"""

import pytest
from datetime import datetime
from evidence_models import StructuredEvidence, JDCriteria, RankedEvidence


class TestStructuredEvidenceCreation:
    """Test StructuredEvidence dataclass initialization and fields."""

    def test_structured_evidence_creation(self):
        """Should create StructuredEvidence with required and optional fields."""
        evidence = StructuredEvidence(
            achievement="Led cross-functional team to deliver cloud migration",
            context="DXC Client Partner role managing enterprise infrastructure",
            impact="Reduced infrastructure costs by 30% and deployment time from 6 weeks to 2 weeks",
            skills_demonstrated=["Cloud Architecture", "AWS", "Team Leadership", "Project Management"],
            job_title="Senior Cloud Architect",
            company_name="DXC Technology",
            source_section="Experience",
            source_cv_id="cv_12345",
            time_period_start=datetime(2020, 1, 15),
            time_period_end=datetime(2023, 6, 30)
        )

        assert evidence.achievement == "Led cross-functional team to deliver cloud migration"
        assert evidence.context == "DXC Client Partner role managing enterprise infrastructure"
        assert evidence.impact == "Reduced infrastructure costs by 30% and deployment time from 6 weeks to 2 weeks"
        assert evidence.skills_demonstrated == ["Cloud Architecture", "AWS", "Team Leadership", "Project Management"]
        assert evidence.job_title == "Senior Cloud Architect"
        assert evidence.company_name == "DXC Technology"
        assert evidence.source_section == "Experience"
        assert evidence.source_cv_id == "cv_12345"
        assert evidence.time_period_start == datetime(2020, 1, 15)
        assert evidence.time_period_end == datetime(2023, 6, 30)
        assert evidence.id is None  # optional id should be None before persistence
        assert evidence.time_period_start is not None
        assert evidence.time_period_end is not None

    def test_structured_evidence_with_optional_fields_none(self):
        """Should allow optional fields (id, time_period_start/end) to be None."""
        evidence = StructuredEvidence(
            achievement="Built microservices platform",
            context="Startup scaling phase",
            impact="Enabled 10x traffic increase",
            skills_demonstrated=["Python", "Kubernetes"],
            job_title="Backend Engineer",
            company_name="TechStartup Inc",
            source_section="Projects",
            source_cv_id="cv_98765"
            # time_period_start, time_period_end, id not provided
        )

        assert evidence.achievement == "Built microservices platform"
        assert evidence.time_period_start is None
        assert evidence.time_period_end is None
        assert evidence.id is None


class TestJDCriteriaCreation:
    """Test JDCriteria dataclass initialization and fields."""

    def test_jd_criteria_creation(self):
        """Should create JDCriteria with all required fields."""
        criteria = JDCriteria(
            explicit_skills=["Python", "AWS", "PostgreSQL"],
            inferred_skills=["Team Leadership", "Cloud Architecture"],
            critical_criteria=["5+ years cloud experience", "AWS certification preferred"],
            importance_ranking={"Python": 0.95, "AWS": 0.90, "PostgreSQL": 0.75},
            company_name="Acme Corp",
            role_title="Senior Cloud Engineer"
        )

        assert criteria.explicit_skills == ["Python", "AWS", "PostgreSQL"]
        assert criteria.inferred_skills == ["Team Leadership", "Cloud Architecture"]
        assert criteria.critical_criteria == ["5+ years cloud experience", "AWS certification preferred"]
        assert criteria.importance_ranking == {"Python": 0.95, "AWS": 0.90, "PostgreSQL": 0.75}
        assert criteria.company_name == "Acme Corp"
        assert criteria.role_title == "Senior Cloud Engineer"

    def test_jd_criteria_empty_lists(self):
        """Should allow empty lists for skills/criteria."""
        criteria = JDCriteria(
            explicit_skills=[],
            inferred_skills=[],
            critical_criteria=[],
            importance_ranking={},
            company_name="Minimal Corp",
            role_title="Role"
        )

        assert criteria.explicit_skills == []
        assert criteria.inferred_skills == []
        assert criteria.critical_criteria == []
        assert criteria.importance_ranking == {}


class TestRankedEvidenceCreation:
    """Test RankedEvidence dataclass initialization and fields."""

    def test_ranked_evidence_creation(self):
        """Should create RankedEvidence with evidence, match_score, and matched items."""
        evidence = StructuredEvidence(
            achievement="Led cloud migration",
            context="Enterprise scaling",
            impact="30% cost reduction",
            skills_demonstrated=["AWS", "Team Leadership"],
            job_title="Cloud Architect",
            company_name="DXC",
            source_section="Experience",
            source_cv_id="cv_123"
        )

        ranked = RankedEvidence(
            evidence=evidence,
            match_score=0.92,
            matched_skills=["AWS", "Cloud Architecture"],
            matched_criteria=["5+ years cloud experience"],
            suggested_rephrasing="Architected and led enterprise cloud migration project, reducing infrastructure costs by 30%"
        )

        assert ranked.evidence == evidence
        assert ranked.match_score == 0.92
        assert ranked.matched_skills == ["AWS", "Cloud Architecture"]
        assert ranked.matched_criteria == ["5+ years cloud experience"]
        assert ranked.suggested_rephrasing == "Architected and led enterprise cloud migration project, reducing infrastructure costs by 30%"

    def test_ranked_evidence_without_rephrasing(self):
        """Should allow suggested_rephrasing to be None."""
        evidence = StructuredEvidence(
            achievement="Managed team",
            context="Corporate role",
            impact="Team grew from 2 to 10",
            skills_demonstrated=["Management"],
            job_title="Manager",
            company_name="Corp",
            source_section="Experience",
            source_cv_id="cv_456"
        )

        ranked = RankedEvidence(
            evidence=evidence,
            match_score=0.75,
            matched_skills=["Team Leadership"],
            matched_criteria=[]
            # suggested_rephrasing not provided
        )

        assert ranked.match_score == 0.75
        assert ranked.suggested_rephrasing is None
