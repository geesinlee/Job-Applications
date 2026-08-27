"""Tests for LinkedIn job-alert email parser."""

from __future__ import annotations

import pytest

from email_parser import JobCard, parse_linkedin_email


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

DIGEST_HTML = """\
<html><body>
<div>
  <h1>5 jobs matching your search for Data Engineer</h1>
  <div class="job-card">
    <a href="https://www.linkedin.com/jobs/view/4001">Senior Data Engineer</a>
    <span class="company">Acme Corp</span>
    <span class="location">Singapore</span>
    <p class="snippet">Build large-scale data pipelines using Spark and Airflow on AWS.</p>
  </div>
  <div class="job-card">
    <a href="https://www.linkedin.com/jobs/view/4002">Data Engineer - Analytics</a>
    <span class="company">Beta Inc</span>
    <span class="location">Remote, APAC</span>
    <p class="snippet">Design and maintain real-time analytics dashboards and ETL workflows for stakeholders across the region.</p>
  </div>
  <div class="job-card">
    <a href="https://www.linkedin.com/jobs/view/4003">Staff Data Engineer</a>
    <span class="company">Gamma Ltd</span>
    <p class="snippet">Lead the data platform team. No location listed.</p>
  </div>
</div>
</body></html>
"""

SINGLE_JOB_HTML = """\
<html><body>
<div>
  <h2>New job for you</h2>
  <div class="job-card">
    <a href="https://www.linkedin.com/jobs/view/5001">Platform Engineer</a>
    <span class="company">Delta Co</span>
    <span class="location">Singapore, Central Region</span>
    <p class="snippet">Join our platform team to build internal developer tools.</p>
  </div>
</div>
</body></html>
"""

RECOMMENDED_JOB_HTML = """\
<html><body>
<div>
  <h2>Recommended job for you</h2>
  <div>
    <a href="https://www.linkedin.com/jobs/view/6001">ML Engineer</a>
    <span class="company">Epsilon AI</span>
    <span class="location">Remote</span>
    <p class="snippet">Work on production ML systems.</p>
  </div>
</div>
</body></html>
"""

SEARCH_URL_HTML = """\
<html><body>
<div>
  <div class="job-card">
    <a href="https://www.linkedin.com/jobs/search/?keywords=Data+Engineer&amp;currentJobId=7001">Data Engineer</a>
    <span class="company">Zeta Corp</span>
    <span class="location">Hybrid - Singapore</span>
    <p class="snippet">Hybrid role in SG.</p>
  </div>
</div>
</body></html>
"""

NO_JOBS_HTML = """\
<html><body>
<p>Your search did not match any jobs. Try different keywords.</p>
</body></html>
"""

MALFORMED_HTML = """\
<html><body>
<div class="broken"><a href="https://www.linkedin.com/jobs/view/9999"
</div>
</body></html>
"""

EMPTY_STRING = ""

LONG_SNIPPET_HTML = """\
<html><body>
<div class="job-card">
  <a href="https://www.linkedin.com/jobs/view/8001">Data Scientist</a>
  <span class="company">Eta Labs</span>
  <span class="location">Singapore</span>
  <p class="snippet">Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id est laborum.</p>
</div>
</body></html>
"""

NO_SNIPPET_HTML = """\
<html><body>
<div class="job-card">
  <a href="https://www.linkedin.com/jobs/view/8002">Product Manager</a>
  <span class="company">Theta Inc</span>
  <span class="location">Singapore</span>
</div>
</body></html>
"""

NO_COMPANY_HTML = """\
<html><body>
<div class="job-card">
  <a href="https://www.linkedin.com/jobs/view/8003">DevOps Engineer</a>
  <span class="location">Singapore</span>
  <p class="snippet">CI/CD pipelines and infrastructure.</p>
</div>
</body></html>
"""

NO_LOCATION_HTML = """\
<html><body>
<div class="job-card">
  <a href="https://www.linkedin.com/jobs/view/8004">Cloud Architect</a>
  <span class="company">Iota Systems</span>
  <p class="snippet">Design cloud architectures.</p>
</div>
</body></html>
"""


# ---------------------------------------------------------------------------
# Test: parse_linkedin_email — digest format
# ---------------------------------------------------------------------------


class TestParseDigestEmail:
    """Extract multiple jobs from a digest-style LinkedIn alert email."""

    def test_extracts_all_jobs(self) -> None:
        cards = parse_linkedin_email(DIGEST_HTML, "msg123", "2026-08-06T09:00:00Z")
        assert len(cards) == 3

    def test_title_and_url_correct(self) -> None:
        cards = parse_linkedin_email(DIGEST_HTML, "msg123", "2026-08-06T09:00:00Z")
        assert cards[0].title == "Senior Data Engineer"
        assert cards[0].url == "https://www.linkedin.com/jobs/view/4001"
        assert cards[1].title == "Data Engineer - Analytics"
        assert cards[1].url == "https://www.linkedin.com/jobs/view/4002"

    def test_company_extracted(self) -> None:
        cards = parse_linkedin_email(DIGEST_HTML, "msg123", "2026-08-06T09:00:00Z")
        assert cards[0].company == "Acme Corp"
        assert cards[1].company == "Beta Inc"
        assert cards[2].company == "Gamma Ltd"

    def test_location_extracted(self) -> None:
        cards = parse_linkedin_email(DIGEST_HTML, "msg123", "2026-08-06T09:00:00Z")
        assert cards[0].location == "Singapore"
        assert cards[1].location == "Remote, APAC"

    def test_missing_location_is_none(self) -> None:
        cards = parse_linkedin_email(DIGEST_HTML, "msg123", "2026-08-06T09:00:00Z")
        assert cards[2].location is None

    def test_snippet_extracted(self) -> None:
        cards = parse_linkedin_email(DIGEST_HTML, "msg123", "2026-08-06T09:00:00Z")
        assert cards[0].snippet == "Build large-scale data pipelines using Spark and Airflow on AWS."

    def test_source_email_id_and_date(self) -> None:
        cards = parse_linkedin_email(DIGEST_HTML, "msg42", "2026-08-01T12:00:00Z")
        assert cards[0].source_email_id == "msg42"
        assert cards[0].source_date == "2026-08-01T12:00:00Z"


# ---------------------------------------------------------------------------
# Test: parse_linkedin_email — single-job format
# ---------------------------------------------------------------------------


class TestParseSingleJobEmail:
    """Extract a single job from 'New job for you' / 'Recommended job' emails."""

    def test_single_job_extracted(self) -> None:
        cards = parse_linkedin_email(SINGLE_JOB_HTML, "msg200", "2026-08-06T10:00:00Z")
        assert len(cards) == 1
        assert cards[0].title == "Platform Engineer"
        assert cards[0].company == "Delta Co"

    def test_recommended_job_format(self) -> None:
        cards = parse_linkedin_email(RECOMMENDED_JOB_HTML, "msg300", "2026-08-06T11:00:00Z")
        assert len(cards) == 1
        assert cards[0].title == "ML Engineer"
        assert cards[0].company == "Epsilon AI"

    def test_search_url_format(self) -> None:
        cards = parse_linkedin_email(SEARCH_URL_HTML, "msg400", "2026-08-06T12:00:00Z")
        assert len(cards) == 1
        assert "7001" in cards[0].url
        assert cards[0].company == "Zeta Corp"


# ---------------------------------------------------------------------------
# Test: edge cases
# ---------------------------------------------------------------------------


class TestParseEdgeCases:
    """Handle empty, malformed, and missing-field HTML gracefully."""

    def test_empty_html_returns_empty_list(self) -> None:
        cards = parse_linkedin_email(EMPTY_STRING, "msg0", "2026-08-06T00:00:00Z")
        assert cards == []

    def test_no_jobs_html_returns_empty_list(self) -> None:
        cards = parse_linkedin_email(NO_JOBS_HTML, "msg1", "2026-08-06T00:00:00Z")
        assert cards == []

    def test_malformed_html_returns_empty_list(self) -> None:
        cards = parse_linkedin_email(MALFORMED_HTML, "msg2", "2026-08-06T00:00:00Z")
        assert cards == []

    def test_missing_location_defaults_to_none(self) -> None:
        cards = parse_linkedin_email(NO_LOCATION_HTML, "msg5", "2026-08-06T00:00:00Z")
        assert cards[0].location is None

    def test_missing_snippet_defaults_to_empty_string(self) -> None:
        cards = parse_linkedin_email(NO_SNIPPET_HTML, "msg6", "2026-08-06T00:00:00Z")
        assert cards[0].snippet == ""

    def test_missing_company_defaults_to_unknown(self) -> None:
        cards = parse_linkedin_email(NO_COMPANY_HTML, "msg7", "2026-08-06T00:00:00Z")
        assert cards[0].company == "Unknown"

    def test_long_snippet_truncated(self) -> None:
        cards = parse_linkedin_email(LONG_SNIPPET_HTML, "msg8", "2026-08-06T00:00:00Z")
        assert len(cards[0].snippet) <= 200
        if len(cards[0].snippet) == 200:
            # Ends with "..." when truncated
            assert cards[0].snippet.endswith("...")

    def test_none_html_raises_or_returns_empty(self) -> None:
        """Passing None as html should not crash — return empty list."""
        cards = parse_linkedin_email(None, "msg9", "2026-08-06T00:00:00Z")  # type: ignore[arg-type]
        assert cards == []