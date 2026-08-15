"""Unit tests for RequirementService.extract_requirements method.

Tests verify extraction of structured requirements from job description fields.
Uses TDD: tests written first, verify fail, implement, verify pass.
"""

import pytest
from unittest.mock import Mock
from requirement_service import (
    RequirementService,
    JobRequirements,
    Requirement,
    RequirementType,
    ConfidenceLevel,
)


@pytest.fixture
def mock_evidence_service():
    """Mock EvidenceService for dependency injection."""
    return Mock()


@pytest.fixture
def requirement_service(mock_evidence_service):
    """Create RequirementService with mock evidence service."""
    return RequirementService(evidence_service=mock_evidence_service)


class TestExtractRequirements:
    """Tests for RequirementService.extract_requirements method."""

    def test_extract_required_skills(self, requirement_service):
        """Test that required_skills become LEVEL_A competencies with threshold 0.8."""
        jd_fields = {
            "required_skills": ["Python", "SQL", "AWS"],
        }

        result = requirement_service.extract_requirements(jd_fields)

        # Verify result is JobRequirements
        assert isinstance(result, JobRequirements)

        # Filter for required_skills requirements
        required_skill_reqs = [
            r
            for r in result.requirements
            if r.source_jd_field == "required_skills"
        ]

        # Assert we have 3 required skills
        assert len(required_skill_reqs) == 3

        # Verify each requirement has correct properties
        for req in required_skill_reqs:
            assert isinstance(req, Requirement)
            assert req.type == RequirementType.COMPETENCY
            assert req.confidence == ConfidenceLevel.LEVEL_A
            assert req.confidence_threshold == 0.8
            assert req.source_jd_field == "required_skills"
            assert req.statement in ["Python", "SQL", "AWS"]

    def test_extract_preferred_skills(self, requirement_service):
        """Test that preferred_skills become LEVEL_B competencies with threshold 0.7."""
        jd_fields = {
            "preferred_skills": ["Docker", "Kubernetes"],
        }

        result = requirement_service.extract_requirements(jd_fields)

        # Filter for preferred_skills requirements
        preferred_skill_reqs = [
            r
            for r in result.requirements
            if r.source_jd_field == "preferred_skills"
        ]

        # Assert we have 2 preferred skills
        assert len(preferred_skill_reqs) == 2

        # Verify each requirement has correct properties
        for req in preferred_skill_reqs:
            assert isinstance(req, Requirement)
            assert req.type == RequirementType.COMPETENCY
            assert req.confidence == ConfidenceLevel.LEVEL_B
            assert req.confidence_threshold == 0.7
            assert req.source_jd_field == "preferred_skills"
            assert req.statement in ["Docker", "Kubernetes"]

    def test_extract_years_of_experience(self, requirement_service):
        """Test that years_of_experience becomes quantified with LEVEL_A and threshold 0.8."""
        jd_fields = {
            "years_of_experience": 5,
        }

        result = requirement_service.extract_requirements(jd_fields)

        # Filter for years_of_experience requirement
        years_reqs = [
            r
            for r in result.requirements
            if r.source_jd_field == "years_of_experience"
        ]

        # Assert we have 1 years requirement
        assert len(years_reqs) == 1

        req = years_reqs[0]
        assert isinstance(req, Requirement)
        assert req.type == RequirementType.YEARS_EXPERIENCE
        assert req.confidence == ConfidenceLevel.LEVEL_A
        assert req.confidence_threshold == 0.8
        assert req.source_jd_field == "years_of_experience"
        assert req.quantified == {"years": 5}
        assert "5" in req.statement  # Statement should contain the years value

    def test_extract_industry_and_seniority(self, requirement_service):
        """Test that industry and seniority fields are extracted with correct levels."""
        jd_fields = {
            "industry": ["Technology", "Finance"],
            "seniority_level": "Senior",
        }

        result = requirement_service.extract_requirements(jd_fields)

        # Filter for industry requirements
        industry_reqs = [
            r for r in result.requirements if r.source_jd_field == "industry"
        ]

        # Assert we have 2 industry requirements
        assert len(industry_reqs) == 2

        for req in industry_reqs:
            assert isinstance(req, Requirement)
            assert req.type == RequirementType.INDUSTRY
            assert req.confidence == ConfidenceLevel.LEVEL_B
            assert req.confidence_threshold == 0.6
            assert req.statement in ["Technology", "Finance"]

        # Filter for seniority requirement
        seniority_reqs = [
            r
            for r in result.requirements
            if r.source_jd_field == "seniority_level"
        ]

        # Assert we have 1 seniority requirement
        assert len(seniority_reqs) == 1

        seniority_req = seniority_reqs[0]
        assert isinstance(seniority_req, Requirement)
        assert seniority_req.type == RequirementType.SENIORITY
        assert seniority_req.confidence == ConfidenceLevel.LEVEL_A
        assert seniority_req.confidence_threshold == 0.8
        assert seniority_req.statement == "Senior"

    def test_extract_empty_jd(self, requirement_service):
        """Test that empty JD returns JobRequirements with len(requirements)==0."""
        jd_fields = {}

        result = requirement_service.extract_requirements(jd_fields)

        # Verify result is JobRequirements
        assert isinstance(result, JobRequirements)

        # Assert no requirements extracted
        assert len(result.requirements) == 0

    def test_extract_combined_fields(self, requirement_service):
        """Test extraction of all fields together."""
        jd_fields = {
            "required_skills": ["Python", "SQL"],
            "preferred_skills": ["Docker"],
            "years_of_experience": 3,
            "industry": ["Technology"],
            "seniority_level": "Mid-level",
        }

        result = requirement_service.extract_requirements(jd_fields)

        # Verify we extracted all fields
        assert len(result.requirements) == 6  # 2 + 1 + 1 + 1 + 1

        # Verify all requirement_ids are unique
        requirement_ids = [r.requirement_id for r in result.requirements]
        assert len(requirement_ids) == len(set(requirement_ids))

        # Verify all requirements have extracted_at timestamp
        for req in result.requirements:
            assert req.extracted_at is not None
            assert "T" in req.extracted_at  # ISO 8601 format
