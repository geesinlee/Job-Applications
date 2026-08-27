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
    RequirementMatch,
    MatchType,
    EvidenceConfidence,
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


class TestMatchRequirement:
    """Tests for RequirementService.match_requirement method."""

    def test_match_deterministic(self, requirement_service):
        """Test deterministic match when requirement statement exactly equals evidence statement."""
        # Setup mock to return exact match
        requirement_service.evidence.query_evidence.return_value = [
            {
                "evidence_id": "e1",
                "statement": "Python",
                "confidence": "LEVEL_A",
            }
        ]

        requirement = Requirement(
            requirement_id="r1",
            statement="Python",
            type=RequirementType.COMPETENCY,
            source_jd_field="required_skills",
            confidence=ConfidenceLevel.LEVEL_A,
            confidence_threshold=0.8,
        )

        matches = requirement_service.match_requirement(requirement)

        assert len(matches) == 1
        assert matches[0].requirement_id == "r1"
        assert matches[0].evidence_id == "e1"
        assert matches[0].match_type == MatchType.DETERMINISTIC
        assert matches[0].similarity_score == 1.0
        assert matches[0].evidence_confidence == EvidenceConfidence.LEVEL_A

    def test_match_semantic(self, requirement_service):
        """Test semantic match when requirement and evidence have partial word overlap."""
        requirement_service.evidence.query_evidence.return_value = [
            {
                "evidence_id": "e2",
                "statement": "Python experience and expertise",
                "confidence": "LEVEL_B",
            }
        ]

        requirement = Requirement(
            requirement_id="r2",
            statement="Python",
            type=RequirementType.COMPETENCY,
            source_jd_field="required_skills",
            confidence=ConfidenceLevel.LEVEL_A,
            confidence_threshold=0.7,
        )

        matches = requirement_service.match_requirement(requirement)

        assert len(matches) == 1
        assert matches[0].requirement_id == "r2"
        assert matches[0].evidence_id == "e2"
        assert matches[0].match_type == MatchType.SEMANTIC
        assert 0.0 < matches[0].similarity_score < 1.0
        assert matches[0].evidence_confidence == EvidenceConfidence.LEVEL_B

    def test_match_no_evidence(self, requirement_service):
        """Test that no matches returns empty list."""
        requirement_service.evidence.query_evidence.return_value = []

        requirement = Requirement(
            requirement_id="r3",
            statement="Rare Skill",
            type=RequirementType.COMPETENCY,
            source_jd_field="required_skills",
            confidence=ConfidenceLevel.LEVEL_A,
            confidence_threshold=0.8,
        )

        matches = requirement_service.match_requirement(requirement)

        assert len(matches) == 0
        assert isinstance(matches, list)


class TestIdentifyGaps:
    """Tests for RequirementService.identify_gaps method."""

    def test_gap_covered(self, requirement_service):
        """Gap is covered when similarity >= threshold."""
        from requirement_service import Gap, GapStatus

        matches = [
            RequirementMatch(
                requirement_id="r1",
                evidence_id="e1",
                evidence_statement="Python expert",
                similarity_score=0.95,
                match_type=MatchType.DETERMINISTIC,
                evidence_confidence=EvidenceConfidence.LEVEL_A,
            )
        ]

        requirement = Requirement(
            requirement_id="r1",
            statement="Python",
            type=RequirementType.COMPETENCY,
            source_jd_field="required_skills",
            confidence=ConfidenceLevel.LEVEL_A,
            confidence_threshold=0.8,
        )

        job_reqs = JobRequirements(
            jd_id="jd1",
            company="Test",
            role_title="Dev",
            requirements=[requirement],
        )

        gaps = requirement_service.identify_gaps(job_reqs, {"r1": matches})

        assert len(gaps) == 1
        assert gaps[0].status == GapStatus.COVERED
        assert gaps[0].requirement_id == "r1"
        assert len(gaps[0].matched_evidence) > 0
        assert gaps[0].reasoning != ""

    def test_gap_partial(self, requirement_service):
        """Gap is partial when similarity < threshold but > 0."""
        from requirement_service import GapStatus

        matches = [
            RequirementMatch(
                requirement_id="r2",
                evidence_id="e2",
                evidence_statement="Some Python experience",
                similarity_score=0.65,  # < 0.8 threshold
                match_type=MatchType.SEMANTIC,
                evidence_confidence=EvidenceConfidence.LEVEL_B,
            )
        ]

        requirement = Requirement(
            requirement_id="r2",
            statement="Python",
            type=RequirementType.COMPETENCY,
            source_jd_field="required_skills",
            confidence=ConfidenceLevel.LEVEL_A,
            confidence_threshold=0.8,
        )

        job_reqs = JobRequirements(
            jd_id="jd2",
            company="Test",
            role_title="Dev",
            requirements=[requirement],
        )

        gaps = requirement_service.identify_gaps(job_reqs, {"r2": matches})

        assert len(gaps) == 1
        assert gaps[0].status == GapStatus.PARTIAL
        assert gaps[0].requirement_id == "r2"

    def test_gap_missing(self, requirement_service):
        """Gap is missing when no evidence matches."""
        from requirement_service import GapStatus

        requirement = Requirement(
            requirement_id="r3",
            statement="Rare Skill",
            type=RequirementType.COMPETENCY,
            source_jd_field="required_skills",
            confidence=ConfidenceLevel.LEVEL_A,
            confidence_threshold=0.8,
        )

        job_reqs = JobRequirements(
            jd_id="jd3",
            company="Test",
            role_title="Dev",
            requirements=[requirement],
        )

        gaps = requirement_service.identify_gaps(job_reqs, {"r3": []})

        assert len(gaps) == 1
        assert gaps[0].status == GapStatus.MISSING
        assert gaps[0].requirement_id == "r3"
        assert len(gaps[0].matched_evidence) == 0


class TestIntegrationAndEdgeCases:
    """Integration and edge case tests for RequirementService."""

    def test_full_lifecycle(self, requirement_service):
        """Full pipeline: extract → match → identify gaps."""
        from requirement_service import GapStatus

        # Setup mock to return matches for Python but not Kubernetes
        def mock_query(competencies=None, technologies=None, **kwargs):
            if competencies and "Python" in competencies:
                return [
                    {
                        "evidence_id": "e1",
                        "statement": "Python",  # Exact match for deterministic
                        "confidence": "LEVEL_A",
                    }
                ]
            return []

        requirement_service.evidence.query_evidence.side_effect = mock_query

        jd_fields = {
            "required_skills": ["Python", "Kubernetes"],
        }

        # Extract
        requirements = requirement_service.extract_requirements(jd_fields)
        assert len(requirements.requirements) == 2

        # Match
        evidence_matches = {}
        for req in requirements.requirements:
            evidence_matches[req.requirement_id] = (
                requirement_service.match_requirement(req)
            )

        # Identify gaps
        gaps = requirement_service.identify_gaps(requirements, evidence_matches)

        python_gap = [g for g in gaps if "Python" in g.requirement_statement][0]
        assert python_gap.status == GapStatus.COVERED

        k8s_gap = [g for g in gaps if "Kubernetes" in g.requirement_statement][0]
        assert k8s_gap.status == GapStatus.MISSING

    def test_quantified_requirement_years(self, requirement_service):
        """Quantified years_of_experience requirement handled correctly."""
        jd_fields = {"years_of_experience": 10}

        requirements = requirement_service.extract_requirements(jd_fields)

        assert len(requirements.requirements) == 1
        assert requirements.requirements[0].quantified == {"years": 10}
        assert requirements.requirements[0].type == RequirementType.YEARS_EXPERIENCE

    def test_multiple_skills_same_type(self, requirement_service):
        """Multiple required skills create separate requirements."""
        jd_fields = {
            "required_skills": ["Python", "Go", "Rust"],
        }

        requirements = requirement_service.extract_requirements(jd_fields)

        assert len(requirements.requirements) == 3
        statements = [r.statement for r in requirements.requirements]
        assert "Python" in statements
        assert "Go" in statements
        assert "Rust" in statements
