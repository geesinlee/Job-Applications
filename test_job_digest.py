"""Tests for job_digest.py — unit and integration tests."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from email_parser import JobCard
from job_digest import (
    _levenshtein,
    deduplicate_across_job_alerts,
    deduplicate_jobs,
    load_prefilter_keywords,
    load_tracker,
    prefilter_jobs,
    triage_jobs_with_llm,
    write_digest_markdown,
)


class FakeResponse:
    """Small requests.Response stand-in for digest tests."""

    def __init__(self, payload=None, status_code=200):
        self.payload = payload or {}
        self.status_code = status_code

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_tracker():
    """A tracker dict with two existing applications."""
    return {
        "schema_version": "1.0",
        "applications": [
            {
                "id": "aaa-111",
                "company": "Databricks",
                "role_title": "Account Executive, Public Sector (Singapore)",
                "stage": "rejected",
                "jd_source_url": "https://linkedin.com/jobs/view/999999",
            },
            {
                "id": "bbb-222",
                "company": "Example Services",
                "role_title": "Client Partner, Public Sector",
                "stage": "interview_r3",
            },
        ],
    }


@pytest.fixture
def sample_jobs():
    """A list of JobCard instances for testing."""
    return [
        JobCard(
            title="Senior Account Executive",
            company="Acme Corp",
            location="Singapore",
            url="https://linkedin.com/jobs/view/100001",
            snippet="Drive growth in APAC markets",
            source_email_id="msg-001",
            source_date="2026-08-05",
        ),
        JobCard(
            title="Account Executive, Public Sector (Singapore)",
            company="Databricks",
            location="Singapore",
            url="https://linkedin.com/jobs/view/999999",
            snippet="Sell data platform to government agencies",
            source_email_id="msg-002",
            source_date="2026-08-05",
        ),
        JobCard(
            title="Junior Developer",
            company="StartupXYZ",
            location="Remote",
            url="https://linkedin.com/jobs/view/100003",
            snippet="Write code for a small team",
            source_email_id="msg-003",
            source_date="2026-08-05",
        ),
        JobCard(
            title="VP of Sales",
            company="BigTech Inc",
            location="Singapore",
            url="https://linkedin.com/jobs/view/100004",
            snippet="Lead the sales organization across APAC",
            source_email_id="msg-004",
            source_date="2026-08-05",
        ),
        JobCard(
            title="Client Partner, Public Sector",
            company="Example Services",
            location="Singapore",
            url="https://linkedin.com/jobs/view/100005",
            snippet="Manage strategic government accounts",
            source_email_id="msg-005",
            source_date="2026-08-05",
        ),
    ]


# ---------------------------------------------------------------------------
# TestDeduplicateJobs
# ---------------------------------------------------------------------------

class TestDeduplicateJobs:
    """Tests for the deduplicate_jobs function."""

    def test_url_exact_match_is_tracked(self, sample_jobs, sample_tracker):
        """Jobs whose URL exactly matches a tracker record are already tracked."""
        result = deduplicate_jobs(sample_jobs, sample_tracker)
        # The Databricks job with URL matching jd_source_url
        already = result["already_tracked"]
        urls_already = [j.url for j in already]
        assert "https://linkedin.com/jobs/view/999999" in urls_already

    def test_exact_company_fuzzy_title_match_is_tracked(self, sample_jobs, sample_tracker):
        """Jobs with exact company + fuzzy title match are already tracked."""
        result = deduplicate_jobs(sample_jobs, sample_tracker)
        already = result["already_tracked"]
        matching = [j for j in already if j.company == "Example Services"]
        assert len(matching) >= 1

    def test_fuzzy_company_does_not_match(self):
        """Fuzzy company matching is NOT used — only exact company match."""
        tracker = {
            "schema_version": "1.0",
            "applications": [
                {
                    "id": "zzz-999",
                    "company": "Databricks",
                    "role_title": "Account Executive",
                    "stage": "applied",
                },
            ],
        }
        # Company "Databrick" (missing 's') should NOT match "Databricks" — exact only
        job = JobCard(
            title="Account Executive",
            company="Databrick",
            location="Singapore",
            url="https://example.com/diff-company",
            snippet="Sell stuff",
            source_email_id="m-diff",
            source_date="2026-08-05",
        )
        result = deduplicate_jobs([job], tracker)
        assert len(result["already_tracked"]) == 0
        assert len(result["new"]) == 1

    def test_new_job_not_tracked(self, sample_jobs, sample_tracker):
        """Jobs not in tracker appear in 'new'."""
        result = deduplicate_jobs(sample_jobs, sample_tracker)
        new_urls = [j.url for j in result["new"]]
        # Acme Corp job and BigTech VP should be new
        assert "https://linkedin.com/jobs/view/100001" in new_urls
        assert "https://linkedin.com/jobs/view/100004" in new_urls

    def test_counts_add_up(self, sample_jobs, sample_tracker):
        """Total new + already_tracked == total input jobs."""
        result = deduplicate_jobs(sample_jobs, sample_tracker)
        total = len(result["new"]) + len(result["already_tracked"])
        assert total == len(sample_jobs)

    def test_empty_tracker_marks_all_new(self, sample_jobs):
        """With an empty tracker, all jobs are 'new'."""
        empty_tracker = {"schema_version": "1.0", "applications": []}
        result = deduplicate_jobs(sample_jobs, empty_tracker)
        assert len(result["new"]) == len(sample_jobs)
        assert len(result["already_tracked"]) == 0

    def test_empty_jobs_list(self, sample_tracker):
        """Empty jobs list produces empty results."""
        result = deduplicate_jobs([], sample_tracker)
        assert result["new"] == []


class TestDeduplicateAcrossJobAlerts:
    """Tests for cross-alert deduplication by LinkedIn job ID."""

    def test_same_job_id_different_tracking_urls_deduplicates(self):
        jobs = [
            JobCard("Enterprise Sales Director (AI)", "Meta", "Singapore",
                    "https://www.linkedin.com/comm/jobs/view/4460886433/?tracking=a",
                    "", "m1", "2026-09-01"),
            JobCard("Enterprise Sales Director (AI)", "The Talent Lever", "Singapore",
                    "https://www.linkedin.com/comm/jobs/view/4460886433/?tracking=b",
                    "longer details", "m2", "2026-09-02"),
        ]

        result = deduplicate_across_job_alerts(jobs)

        assert len(result) == 1
        assert result[0].snippet == "longer details"


# ---------------------------------------------------------------------------
# TestLevenshtein
# ---------------------------------------------------------------------------

class TestLevenshtein:
    """Tests for the _levenshtein function."""

    def test_identical_strings(self):
        assert _levenshtein("hello", "hello") == 0

    def test_empty_strings(self):
        assert _levenshtein("", "") == 0
        assert _levenshtein("abc", "") == 3
        assert _levenshtein("", "abc") == 3

    def test_single_edit(self):
        assert _levenshtein("cat", "bat") == 1  # substitution
        assert _levenshtein("cat", "cats") == 1  # insertion
        assert _levenshtein("cats", "cat") == 1  # deletion

    def test_symmetry(self):
        assert _levenshtein("kitten", "sitting") == _levenshtein("sitting", "kitten")

    def test_near_match_within_threshold(self):
        # "Client Partner, Public Sector" vs "Client Partner, Public Sector" — exact
        assert _levenshtein("client partner, public sector", "client partner, public sector") == 0

    def test_case_matters_for_raw_function(self):
        # Raw function is case-sensitive; callers handle case normalization
        assert _levenshtein("Hello", "hello") == 1


# ---------------------------------------------------------------------------
# TestPrefilterJobs
# ---------------------------------------------------------------------------

class TestPrefilterJobs:
    """Tests for the prefilter_jobs function."""

    @staticmethod
    def _job(title, company, snippet="", url="https://example.com/job"):
        return JobCard(
            title=title,
            company=company,
            location="Singapore",
            url=url,
            snippet=snippet,
            source_email_id="m1",
            source_date="2026-08-05",
        )

    @pytest.mark.parametrize(
        "company",
        [
            "OpenAI",
            "Anthropic",
            "Palantir Technologies",
            "Mistral AI",
            "Confluent",
            "Snowflake",
            "Databricks",
        ],
    )
    def test_known_ai_company_and_enterprise_seller_pass(self, company):
        job = self._job("Enterprise Account Executive", company)
        result = prefilter_jobs([job], {})
        assert result["surfaced"] == [job]
        assert result["policy"] == "ai_company_and_enterprise_sales"

    def test_ai_adjacent_company_and_sales_leader_pass(self):
        job = self._job("Regional Sales Director, APAC", "Confluent")
        result = prefilter_jobs([job], {})
        assert result["surfaced"] == [job]

    def test_product_evidence_allows_unlisted_ai_company(self):
        job = self._job(
            "Strategic Account Executive",
            "New Model Co",
            "We build a generative AI platform for regulated enterprises.",
        )
        result = prefilter_jobs([job], {})
        assert result["surfaced"] == [job]

    def test_ai_sales_segment_in_title_is_product_evidence(self):
        job = self._job("Head of Enterprise Sales, AI/ML", "New Cloud Co")
        result = prefilter_jobs([job], {})
        assert result["surfaced"] == [job]

    def test_adjacent_product_evidence_allows_unlisted_company(self):
        job = self._job(
            "Head of Sales",
            "EventFlow",
            "Our real-time data streaming platform powers production AI workloads.",
        )
        result = prefilter_jobs([job], {})
        assert result["surfaced"] == [job]

    def test_generic_company_enterprise_sales_role_is_filtered(self):
        job = self._job(
            "Enterprise Account Executive",
            "Generic CRM Corp",
            "Sell our CRM suite to large businesses.",
        )
        result = prefilter_jobs([job], {})
        assert result["below_threshold"] == [job]
        assert "not identified as AI-core" in result["rejection_reasons"][job.url]

    def test_ai_company_non_sales_leadership_role_is_filtered(self):
        job = self._job("Senior Director of Engineering", "Anthropic")
        result = prefilter_jobs([job], {})
        assert result["below_threshold"] == [job]
        assert "not enterprise sales" in result["rejection_reasons"][job.url]

    def test_sales_engineering_role_is_filtered(self):
        job = self._job("Director of Sales Engineering", "Mistral AI")
        result = prefilter_jobs([job], {})
        assert result["below_threshold"] == [job]
        assert "not enterprise sales" in result["rejection_reasons"][job.url]

    def test_location_alone_does_not_qualify_job(self):
        job = self._job("Account Manager", "Generic Corp")
        result = prefilter_jobs(
            [job],
            {"locations": {"singapore"}, "skills": {"ai", "sales"}},
        )
        assert result["surfaced"] == []
        assert result["below_threshold"] == [job]

    def test_deployment_can_supply_target_company(self):
        job = self._job("VP of Sales", "Tenant Target Systems")
        result = prefilter_jobs(
            [job],
            {"ai_target_companies": {"tenant target"}},
        )
        assert result["surfaced"] == [job]

    def test_empty_jobs(self):
        """Empty jobs list returns empty surfaced and below_threshold."""
        result = prefilter_jobs([], {})
        assert result["surfaced"] == []
        assert result["below_threshold"] == []
        assert result["rejection_reasons"] == {}


class TestLlmTriage:
    """Tests for LLM-backed triage."""

    class FakeProvider:
        def generate_text(self, prompt, model=None, max_tokens=2000):
            return json.dumps([
                {
                    "url": "https://example.com/keep",
                    "surface": True,
                    "score": 91,
                    "company_fit": "ai_core",
                    "role_fit": "enterprise_sales",
                    "candidate_fit": "strong",
                    "reason": "AI company and enterprise sales fit.",
                },
                {
                    "url": "https://example.com/drop",
                    "surface": False,
                    "score": 20,
                    "company_fit": "unclear",
                    "role_fit": "no",
                    "candidate_fit": "weak",
                    "reason": "Academic/technical role, not enterprise sales.",
                },
            ])

    def test_llm_triage_surfaces_model_selected_jobs(self):
        keep = JobCard(
            title="Enterprise Account Executive",
            company="OpenAI",
            location="Singapore",
            url="https://example.com/keep",
            snippet="Sell AI products to large enterprises.",
            source_email_id="m1",
            source_date="2026-09-04",
        )
        drop = JobCard(
            title="Lecturer, Artificial Intelligence",
            company="Example University",
            location="Singapore",
            url="https://example.com/drop",
            snippet="Teach AI courses.",
            source_email_id="m2",
            source_date="2026-09-04",
        )

        result = triage_jobs_with_llm([keep, drop], "enterprise sales leader", provider=self.FakeProvider())

        assert result["policy"] == "llm_resume_triage"
        assert result["surfaced"] == [keep]
        assert result["below_threshold"] == [drop]
        assert "Academic/technical role" in result["rejection_reasons"][drop.url]

    def test_llm_triage_rejects_missing_decision(self):
        class EmptyProvider:
            def generate_text(self, prompt, model=None, max_tokens=2000):
                return "[]"

        job = JobCard(
            title="Enterprise Account Executive",
            company="OpenAI",
            location="Singapore",
            url="https://example.com/missing",
            snippet="Sell AI products.",
            source_email_id="m1",
            source_date="2026-09-04",
        )

        result = triage_jobs_with_llm([job], "enterprise sales leader", provider=EmptyProvider())

        assert result["surfaced"] == []
        assert result["below_threshold"] == [job]
        assert "did not return a decision" in result["rejection_reasons"][job.url]


# ---------------------------------------------------------------------------
# TestLoadTracker
# ---------------------------------------------------------------------------

class TestLoadTracker:
    """Tests for load_tracker."""

    def test_load_valid_tracker(self, tmp_path):
        """Loading a valid tracker.json returns the correct data."""
        tracker_file = tmp_path / "tracker.json"
        data = {"schema_version": "1.0", "applications": [{"company": "Test"}]}
        tracker_file.write_text(json.dumps(data), encoding="utf-8")
        result = load_tracker(tracker_file)
        assert result == data

    def test_load_missing_tracker(self, tmp_path):
        """Missing tracker.json returns empty schema."""
        result = load_tracker(tmp_path / "nonexistent.json")
        assert result == {"schema_version": "1.0", "applications": []}

    def test_load_invalid_json(self, tmp_path):
        """Invalid JSON in tracker.json returns empty schema."""
        tracker_file = tmp_path / "tracker.json"
        tracker_file.write_text("NOT VALID JSON{{{", encoding="utf-8")
        result = load_tracker(tracker_file)
        assert result == {"schema_version": "1.0", "applications": []}


# ---------------------------------------------------------------------------
# TestLoadPrefilterKeywords
# ---------------------------------------------------------------------------

class TestLoadPrefilterKeywords:
    """Tests for load_prefilter_keywords."""

    def test_loads_from_reference_cv(self, tmp_path):
        """Loading keywords from a synthetic reference CV extracts useful terms."""
        cv_path = tmp_path / "Reference_CV.md"
        cv_path.write_text(
            "# Example Candidate\n"
            "Senior enterprise sales leader in Singapore, SaaS, and public sector.\n\n"
            "## Technical Skills\n"
            "- **Languages:** Python, SQL\n"
            "- **Platforms:** Cloud services\n",
            encoding="utf-8",
        )

        keywords = load_prefilter_keywords(cv_path)
        assert "senior" in keywords["senior_titles"]
        assert "remote" in keywords["locations"]
        assert "openai" in keywords["ai_target_companies"]
        # Should have extracted some skills
        assert len(keywords["skills"]) > 0
        # Should have extracted some industries
        assert len(keywords["industries"]) > 0

    def test_fallback_when_missing(self, tmp_path):
        """Missing reference CV file falls back to basic keywords."""
        keywords = load_prefilter_keywords(tmp_path / "nonexistent.md")
        assert "senior" in keywords["senior_titles"]
        assert "remote" in keywords["locations"]
        # Skills and industries should be empty with fallback
        assert len(keywords["skills"]) == 0
        assert len(keywords["industries"]) == 0

    def test_extracts_skills_from_cv(self, tmp_path):
        """Skills section in a mock CV is extracted."""
        cv_content = """# Test CV

## Technical Skills

- **Cloud / AI:** Python, Snowflake, Kubernetes, AWS
- **Sales:** MEDDPICC, Consultative Selling
"""
        cv_file = tmp_path / "Reference_CV.md"
        cv_file.write_text(cv_content, encoding="utf-8")

        keywords = load_prefilter_keywords(cv_file)
        # Check that some skills were extracted
        # Skills are lowercased; check for known items
        all_skills_text = " ".join(keywords["skills"]).lower()
        assert "snowflake" in all_skills_text


# ---------------------------------------------------------------------------
# TestWriteDigestMarkdown
# ---------------------------------------------------------------------------

class TestWriteDigestMarkdown:
    """Tests for write_digest_markdown."""

    def test_creates_file(self, tmp_path):
        """Digest Markdown file is created."""
        digest_dir = tmp_path / "digests"
        surfaced = [
            JobCard(
                title="Senior Director",
                company="Acme Corp",
                location="Singapore",
                url="https://example.com/1",
                snippet="Lead teams",
                source_email_id="m1",
                source_date="2026-08-05",
            ),
        ]
        below_threshold = []
        stats = {"processed": 1, "surfaced": 1, "below_threshold": 0, "already_tracked": 0}

        path = write_digest_markdown(digest_dir, "2026-08-05", surfaced, below_threshold, stats)
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "# Job Discoveries — 2026-08-05" in content

    def test_contains_company_and_title(self, tmp_path):
        """Digest includes company and title of surfaced jobs."""
        digest_dir = tmp_path / "digests"
        surfaced = [
            JobCard(
                title="Senior Director",
                company="Acme Corp",
                location="Singapore",
                url="https://example.com/1",
                snippet="Lead teams",
                source_email_id="m1",
                source_date="2026-08-05",
            ),
        ]
        below_threshold = []
        stats = {"processed": 1, "surfaced": 1, "below_threshold": 0, "already_tracked": 0}

        path = write_digest_markdown(digest_dir, "2026-08-05", surfaced, below_threshold, stats)
        content = path.read_text(encoding="utf-8")
        assert "Acme Corp" in content
        assert "Senior Director" in content
        assert "### Acme Corp — Senior Director" in content

    def test_contains_below_threshold_section(self, tmp_path):
        """Digest includes 'Below Threshold' section."""
        digest_dir = tmp_path / "digests"
        surfaced = []
        below_threshold = [
            JobCard(
                title="Junior Dev",
                company="StartupXYZ",
                location="Remote",
                url="https://example.com/2",
                snippet="Write code",
                source_email_id="m2",
                source_date="2026-08-05",
            ),
        ]
        stats = {"processed": 1, "surfaced": 0, "below_threshold": 1, "already_tracked": 0}

        path = write_digest_markdown(digest_dir, "2026-08-05", surfaced, below_threshold, stats)
        content = path.read_text(encoding="utf-8")
        assert "## Below Threshold" in content
        assert "StartupXYZ" in content
        assert "Junior Dev" in content
        assert "Below pre-filter threshold" in content

    def test_writes_specific_rejection_reason(self, tmp_path):
        digest_dir = tmp_path / "digests"
        job = JobCard(
            title="Software Engineer",
            company="OpenAI",
            location="Remote",
            url="https://example.com/rejected",
            snippet="Build model infrastructure",
            source_email_id="m3",
            source_date="2026-08-05",
        )
        stats = {"processed": 1, "surfaced": 0, "below_threshold": 1, "already_tracked": 0}

        path = write_digest_markdown(
            digest_dir,
            "2026-08-05",
            [],
            [job],
            stats,
            rejection_reasons={job.url: "Role is not enterprise sales or sales leadership"},
        )

        content = path.read_text(encoding="utf-8")
        assert "**Reason:** Role is not enterprise sales or sales leadership" in content

    def test_stats_line(self, tmp_path):
        """Digest contains the stats summary line."""
        digest_dir = tmp_path / "digests"
        stats = {"processed": 10, "surfaced": 3, "below_threshold": 5, "already_tracked": 2}

        path = write_digest_markdown(digest_dir, "2026-08-05", [], [], stats)
        content = path.read_text(encoding="utf-8")
        assert "10 jobs processed" in content
        assert "3 surfaced" in content
        assert "5 below threshold" in content
        assert "2 already tracked" in content

    def test_empty_digest(self, tmp_path):
        """Empty digest (no emails found) is created correctly."""
        digest_dir = tmp_path / "digests"
        stats = {"processed": 0, "surfaced": 0, "below_threshold": 0, "already_tracked": 0}

        path = write_digest_markdown(digest_dir, "2026-08-05", [], [], stats)
        content = path.read_text(encoding="utf-8")
        assert "No jobs surfaced today" in content
        assert "0 jobs processed" in content

    def test_creates_digest_directory(self, tmp_path):
        """Digest directory is created if it doesn't exist."""
        digest_dir = tmp_path / "nested" / "digests"
        assert not digest_dir.exists()
        stats = {"processed": 0, "surfaced": 0, "below_threshold": 0, "already_tracked": 0}
        path = write_digest_markdown(digest_dir, "2026-08-05", [], [], stats)
        assert digest_dir.exists()
        assert path.exists()


# ---------------------------------------------------------------------------
# TestGmailHelpers
# ---------------------------------------------------------------------------

class TestExtractHtmlBody:
    """Tests for _extract_html_body."""

    def test_simple_html_body(self):
        from job_digest import _extract_html_body

        msg_data = {
            "payload": {
                "mimeType": "text/html",
                "body": {
                    "data": "PGgxPkhlbGxvPC9oMT4="
                },
            },
        }
        result = _extract_html_body(msg_data)
        assert result == "<h1>Hello</h1>"

    def test_multipart_with_html(self):
        from job_digest import _extract_html_body
        import base64

        html_content = "<h1>Job Alert</h1>"
        html_data = base64.urlsafe_b64encode(html_content.encode()).decode().rstrip("=")

        msg_data = {
            "payload": {
                "mimeType": "multipart/alternative",
                "parts": [
                    {
                        "mimeType": "text/plain",
                        "body": {"data": base64.urlsafe_b64encode(b"Plain text").decode().rstrip("=")},
                    },
                    {
                        "mimeType": "text/html",
                        "body": {"data": html_data},
                    },
                ],
            },
        }
        result = _extract_html_body(msg_data)
        assert "<h1>Job Alert</h1>" in result

    def test_fallback_to_plain_text(self):
        from job_digest import _extract_html_body
        import base64

        plain_data = base64.urlsafe_b64encode(b"Plain text content").decode().rstrip("=")

        msg_data = {
            "payload": {
                "mimeType": "multipart/alternative",
                "parts": [
                    {
                        "mimeType": "text/plain",
                        "body": {"data": plain_data},
                    },
                ],
            },
        }
        result = _extract_html_body(msg_data)
        assert "Plain text content" in result

    def test_no_body_data(self):
        from job_digest import _extract_html_body

        msg_data = {"payload": {"mimeType": "text/html", "body": {}}}
        result = _extract_html_body(msg_data)
        assert result is None


# ---------------------------------------------------------------------------
# TestFormatDigestEmail
# ---------------------------------------------------------------------------

class TestFormatDigestEmail:
    """Tests for _format_digest_email."""

    def test_email_format(self):
        from job_digest import _format_digest_email

        surfaced = [
            JobCard(
                title="Senior Director",
                company="Acme Corp",
                location="Singapore",
                url="https://example.com/1",
                snippet="Lead teams",
                source_email_id="m1",
                source_date="2026-08-05",
            ),
            JobCard(
                title="VP of Sales",
                company="BigTech Inc",
                location="Singapore",
                url="https://example.com/2",
                snippet="Lead sales",
                source_email_id="m2",
                source_date="2026-08-05",
            ),
        ]
        stats = {"processed": 5, "surfaced": 2, "below_threshold": 2, "already_tracked": 1}

        subject, body = _format_digest_email(surfaced, stats, "2026-08-05")
        # Subject: "Job Discoveries — YYYY-MM-DD: N new roles"
        assert "Job Discoveries" in subject
        assert "2026-08-05" in subject
        assert "2 new roles" in subject
        # Body: header, Top Matches with numbered list, Stats line, review prompt
        assert "Job Discoveries for 2026-08-05" in body
        assert "🔥 Top Matches:" in body
        assert "1. Acme Corp — Senior Director" in body
        assert "2. BigTech Inc — VP of Sales" in body
        assert "📊 Stats:" in body
        assert "5 processed" in body
        assert "2 surfaced" in body
        assert "2 below threshold" in body
        assert "1 already tracked" in body
        assert 'review_daily_discoveries("2026-08-05")' in body

    def test_email_format_no_surfaced(self):
        from job_digest import _format_digest_email

        stats = {"processed": 0, "surfaced": 0, "below_threshold": 0, "already_tracked": 0}
        subject, body = _format_digest_email([], stats, "2026-08-05")
        assert "0 new roles" in subject
        assert "(No relevant roles found today)" in body


# ---------------------------------------------------------------------------
# TestRunLock
# ---------------------------------------------------------------------------

class TestRunLock:
    """Tests for duplicate-invocation prevention."""

    def test_only_one_process_handle_can_hold_lock(self, tmp_path):
        from job_digest import _acquire_run_lock, _release_run_lock

        lock_path = tmp_path / ".job_digest.lock"
        first = _acquire_run_lock(lock_path)
        assert first is not None
        try:
            assert _acquire_run_lock(lock_path) is None
        finally:
            _release_run_lock(first)

        replacement = _acquire_run_lock(lock_path)
        assert replacement is not None
        _release_run_lock(replacement)

    def test_main_skips_when_another_run_holds_lock(self, tmp_path):
        from job_digest import main

        with patch("sys.argv", ["job_digest.py"]), \
             patch("job_digest._acquire_run_lock", return_value=None), \
             patch("job_digest.GmailAccountManager") as mock_manager, \
             patch("job_digest.LOG_PATH", tmp_path / "job_digest.log"):
            result = main()

        assert result == 0
        mock_manager.assert_not_called()
        assert "skipping duplicate invocation" in (tmp_path / "job_digest.log").read_text()


# ---------------------------------------------------------------------------
# TestDryRun
# ---------------------------------------------------------------------------

class TestDryRun:
    """Tests for the --dry-run flag."""

    def test_dry_run_exits_early(self):
        """--dry-run authenticates but does not write/send/trash."""
        from job_digest import main

        with patch("job_digest.GMAIL_ACCOUNTS_CONFIG", "test-config"), \
             patch("job_digest.GmailAccountManager") as MockMgr, \
             patch("job_digest.query_linkedin_emails") as mock_query:
            mock_mgr = MockMgr.return_value
            mock_acct = MagicMock()
            mock_acct.email = "test@gmail.com"
            mock_mgr.accounts = {"test": mock_acct}
            mock_mgr.get_access_token.return_value = "fake-token"
            mock_query.return_value = [{"id": "m1", "date": "2026-08-05", "html": "<html></html>"}]

            with patch("sys.argv", ["job_digest.py", "--dry-run"]), \
                 patch("builtins.print") as mock_print:
                # Need to also patch env var and module-level constants
                with patch("job_digest._read_last_run", return_value="2026-08-04"):
                    result = main()

            assert result == 0
            # dry-run should print stats and exit 0 without writing/sending/trashing
            assert mock_print.called

    def test_dry_run_does_not_write_digest(self, tmp_path):
        """--dry-run should not create any digest files."""
        from job_digest import main

        with patch("job_digest.GMAIL_ACCOUNTS_CONFIG", "test-config"), \
             patch("job_digest.GmailAccountManager") as MockMgr, \
             patch("job_digest.query_linkedin_emails") as mock_query, \
             patch("job_digest.DIGEST_DIR", tmp_path / "digests"), \
             patch("job_digest.LAST_RUN_FILE", tmp_path / ".last_run"):
            mock_mgr = MockMgr.return_value
            mock_acct = MagicMock()
            mock_acct.email = "test@gmail.com"
            mock_mgr.accounts = {"test": mock_acct}
            mock_mgr.get_access_token.return_value = "fake-token"
            mock_query.return_value = [{"id": "m1", "date": "2026-08-05", "html": "<html></html>"}]

            with patch("sys.argv", ["job_digest.py", "--dry-run"]), \
                 patch("job_digest._read_last_run", return_value="2026-08-04"):
                result = main()

            assert result == 0
            # No digest directory or files should be created
            assert not (tmp_path / "digests").exists()


# ---------------------------------------------------------------------------
# TestGmailPagination
# ---------------------------------------------------------------------------

class TestGmailPagination:
    """Tests for Gmail list pagination in the daily digest."""

    def test_query_linkedin_emails_fetches_all_pages(self):
        from job_digest import query_linkedin_emails

        mock_mgr = MagicMock()
        mock_mgr.get_access_token.return_value = "fake-token"
        calls = []

        def fake_get(url, headers=None, timeout=None):
            calls.append(url)
            if "/messages?" in url and "pageToken=next-1" not in url:
                return FakeResponse({
                    "messages": [{"id": "m1"}],
                    "nextPageToken": "next-1",
                })
            if "/messages?" in url:
                return FakeResponse({"messages": [{"id": "m2"}]})
            if "/messages/m1" in url:
                return FakeResponse({
                    "payload": {
                        "mimeType": "text/html",
                        "body": {"data": "PGh0bWw-b25lPC9odG1sPg"},
                        "headers": [{"name": "Date", "value": "Tue, 1 Sep 2026 08:00:00 +0800"}],
                    }
                })
            if "/messages/m2" in url:
                return FakeResponse({
                    "payload": {
                        "mimeType": "text/html",
                        "body": {"data": "PGh0bWw-dHdvPC9odG1sPg"},
                        "headers": [{"name": "Date", "value": "Wed, 2 Sep 2026 08:00:00 +0800"}],
                    }
                })
            raise AssertionError(f"unexpected URL: {url}")

        with patch("job_digest.requests.get", side_effect=fake_get):
            results = query_linkedin_emails(mock_mgr, "geesin", "2026-08-27")

        assert [result["id"] for result in results] == ["m1", "m2"]
        assert len([url for url in calls if "/messages?" in url]) == 2
        assert any("pageToken=next-1" in url for url in calls)


# ---------------------------------------------------------------------------
# TestFailureRecovery
# ---------------------------------------------------------------------------

class TestFailureRecovery:
    """Tests for durable failure state and retry-safe completion."""

    def test_delivery_failure_keeps_source_emails_and_last_run_marker(self, tmp_path):
        from job_digest import _run_pipeline

        captured_stats = {}

        def fake_write_digest(digest_dir, date_str, surfaced, below_threshold, stats, rejection_reasons=None):
            captured_stats.update(stats)
            return digest_dir / f"{date_str}.md"

        job = JobCard(
            title="Enterprise Account Executive",
            company="OpenAI",
            location="Singapore",
            url="https://linkedin.com/jobs/view/123",
            snippet="Sell AI products to enterprise customers",
            source_email_id="m1",
            source_date="2026-09-01",
        )

        with patch("job_digest.GMAIL_ACCOUNTS_CONFIG", "test-config"), \
             patch("job_digest.GmailAccountManager") as MockMgr, \
             patch("job_digest.query_linkedin_emails") as mock_query, \
             patch("job_digest.parse_linkedin_email", return_value=[job]), \
             patch("job_digest.write_digest_markdown", side_effect=fake_write_digest), \
             patch("job_digest._send_digest_email", return_value=False), \
             patch("job_digest.trash_emails") as mock_trash, \
             patch("job_digest.LAST_RUN_FILE", tmp_path / ".last_run"), \
             patch("job_digest.FAILURE_STATE_PATH", tmp_path / ".failure.json"), \
             patch("job_digest._read_last_run", return_value="2026-08-27"):
            mock_mgr = MockMgr.return_value
            mock_acct = MagicMock()
            mock_acct.email = "geesin@gmail.com"
            mock_mgr.accounts = {"geesin": mock_acct}
            mock_mgr.get_access_token.return_value = "fake-token"
            mock_query.return_value = [{"id": "m1", "date": "2026-09-01", "html": "<html></html>"}]

            result = _run_pipeline(MagicMock(dry_run=False), "2026-09-04")

        assert result == 1
        assert captured_stats["processed"] == 1
        assert not mock_trash.called
        assert not (tmp_path / ".last_run").exists()
        failure = json.loads((tmp_path / ".failure.json").read_text(encoding="utf-8"))
        assert failure["reason"] == "digest_delivery_failed"

    def test_success_after_failure_adds_recovery_note_and_clears_state(self, tmp_path):
        from job_digest import _run_pipeline

        failure_path = tmp_path / ".failure.json"
        failure_path.write_text(json.dumps({
            "first_failed_at": "2026-09-02T00:00:00+00:00",
            "last_failed_at": "2026-09-04T00:00:00+00:00",
            "failure_count": 3,
            "reason": "gmail_auth_failed",
            "detail": "Could not authenticate any configured Gmail account",
        }), encoding="utf-8")

        delivered = {}
        job = JobCard(
            title="Enterprise Account Executive",
            company="OpenAI",
            location="Singapore",
            url="https://linkedin.com/jobs/view/123",
            snippet="Sell AI products to enterprise customers",
            source_email_id="m1",
            source_date="2026-09-01",
        )

        def fake_send(subject, body):
            delivered["subject"] = subject
            delivered["body"] = body
            return True

        with patch("job_digest.GMAIL_ACCOUNTS_CONFIG", "test-config"), \
             patch("job_digest.GmailAccountManager") as MockMgr, \
             patch("job_digest.query_linkedin_emails") as mock_query, \
             patch("job_digest.parse_linkedin_email", return_value=[job]), \
             patch("job_digest.write_digest_markdown", return_value=tmp_path / "2026-09-04.md"), \
             patch("job_digest._send_digest_email", side_effect=fake_send), \
             patch("job_digest.trash_emails", return_value=1), \
             patch("job_digest.LAST_RUN_FILE", tmp_path / ".last_run"), \
             patch("job_digest.FAILURE_STATE_PATH", failure_path), \
             patch("job_digest._read_last_run", return_value="2026-08-27"):
            mock_mgr = MockMgr.return_value
            mock_acct = MagicMock()
            mock_acct.email = "geesin@gmail.com"
            mock_mgr.accounts = {"geesin": mock_acct}
            mock_mgr.get_access_token.return_value = "fake-token"
            mock_query.return_value = [{"id": "m1", "date": "2026-09-01", "html": "<html></html>"}]

            result = _run_pipeline(MagicMock(dry_run=False), "2026-09-04")

        assert result == 0
        assert "Recovery note:" in delivered["body"]
        assert "failed 3 time(s)" in delivered["body"]
        assert not failure_path.exists()
