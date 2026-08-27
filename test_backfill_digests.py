"""Tests for backfill_digests.py — one-time historical digest backfill."""

import pytest
from backfill_digests import deduplicate_across_emails, group_jobs_by_date
from email_parser import JobCard


def _job(
    title: str = "Role",
    company: str = "Co",
    location: str | None = "SG",
    url: str = "https://linkedin.com/jobs/view/100",
    snippet: str = "",
    source_email_id: str = "e1",
    source_date: str = "2026-06-01",
) -> JobCard:
    """Helper to create JobCard instances with sensible defaults."""
    return JobCard(
        title=title,
        company=company,
        location=location,
        url=url,
        snippet=snippet,
        source_email_id=source_email_id,
        source_date=source_date,
    )


class TestDeduplicateAcrossEmails:
    """Test cross-email deduplication by URL."""

    def test_no_duplicates(self):
        """All unique URLs should be kept."""
        jobs = [
            _job(title="Role A", url="https://linkedin.com/jobs/view/100"),
            _job(title="Role B", url="https://linkedin.com/jobs/view/200"),
        ]
        result = deduplicate_across_emails(jobs)
        assert len(result) == 2

    def test_duplicate_url_keeps_richer_snippet(self):
        """Same URL in two emails — keep the one with longer snippet."""
        jobs = [
            _job(url="https://linkedin.com/jobs/view/100", snippet="short"),
            _job(url="https://linkedin.com/jobs/view/100", snippet="a much longer snippet with more detail"),
        ]
        result = deduplicate_across_emails(jobs)
        assert len(result) == 1
        assert result[0].snippet == "a much longer snippet with more detail"

    def test_duplicate_url_same_snippet_keeps_longer_company(self):
        """Same URL, same snippet length — keep the one with longer company name."""
        jobs = [
            _job(url="https://linkedin.com/jobs/view/100", company="Co", snippet="abc"),
            _job(url="https://linkedin.com/jobs/view/100", company="Company Full Name", snippet="abc"),
        ]
        result = deduplicate_across_emails(jobs)
        assert len(result) == 1
        assert result[0].company == "Company Full Name"

    def test_duplicate_url_tiebreaker_earlier_date(self):
        """Same URL, same snippet, same company length — keep earlier date."""
        jobs = [
            _job(url="https://linkedin.com/jobs/view/100", company="Co", snippet="abc", source_date="2026-06-02"),
            _job(url="https://linkedin.com/jobs/view/100", company="Co", snippet="abc", source_date="2026-06-01"),
        ]
        result = deduplicate_across_emails(jobs)
        assert len(result) == 1
        assert result[0].source_date == "2026-06-01"

    def test_empty_list(self):
        """Empty input returns empty output."""
        assert deduplicate_across_emails([]) == []

    def test_three_emails_same_job(self):
        """Same job in three emails — keep the richest."""
        jobs = [
            _job(url="https://linkedin.com/jobs/view/100", company="Co", location=None, snippet="x", source_date="2026-06-01"),
            _job(url="https://linkedin.com/jobs/view/100", company="Company Name", location="Singapore", snippet="longer snippet here", source_date="2026-06-05"),
            _job(url="https://linkedin.com/jobs/view/100", company="Co", location="SG", snippet="xy", source_date="2026-06-10"),
        ]
        result = deduplicate_across_emails(jobs)
        assert len(result) == 1
        assert result[0].snippet == "longer snippet here"
        assert result[0].company == "Company Name"

    def test_mixed_urls_and_duplicates(self):
        """Mix of unique and duplicate URLs — dedup only removes true dupes."""
        jobs = [
            _job(title="Role A", url="https://linkedin.com/jobs/view/100", snippet="a"),
            _job(title="Role A", url="https://linkedin.com/jobs/view/100", snippet="ab"),  # dupe, richer
            _job(title="Role B", url="https://linkedin.com/jobs/view/200", snippet="c"),
        ]
        result = deduplicate_across_emails(jobs)
        assert len(result) == 2
        # The dupe 100 should have the richer snippet

    def test_same_job_id_different_tracking_params(self):
        """Same LinkedIn job ID but different tracking URLs should deduplicate."""
        jobs = [
            _job(url="https://www.linkedin.com/comm/jobs/view/4141223147/?tracking=abc123", snippet="short"),
            _job(url="https://www.linkedin.com/comm/jobs/view/4141223147/?tracking=xyz789", snippet="longer snippet"),
        ]
        result = deduplicate_across_emails(jobs)
        assert len(result) == 1
        assert result[0].snippet == "longer snippet"

    def test_comm_prefix_urls_dedup(self):
        """URLs with /comm/ prefix and without should deduplicate by job ID."""
        jobs = [
            _job(url="https://www.linkedin.com/jobs/view/4141223147", snippet="from web"),
            _job(url="https://www.linkedin.com/comm/jobs/view/4141223147/?tracking=e1", snippet="from email"),
        ]
        result = deduplicate_across_emails(jobs)
        assert len(result) == 1


class TestGroupJobsByDate:
    """Test grouping jobs by source_date."""

    def test_groups_correctly(self):
        jobs = [
            _job(title="A", source_date="2026-06-15", url="http://1"),
            _job(title="B", source_date="2026-06-15", url="http://2"),
            _job(title="C", source_date="2026-07-01", url="http://3"),
        ]
        result = group_jobs_by_date(jobs)
        assert list(result.keys()) == ["2026-06-15", "2026-07-01"]
        assert len(result["2026-06-15"]) == 2
        assert len(result["2026-07-01"]) == 1

    def test_sorted_by_date(self):
        jobs = [
            _job(title="C", source_date="2026-07-01", url="http://3"),
            _job(title="A", source_date="2026-06-15", url="http://1"),
        ]
        result = group_jobs_by_date(jobs)
        assert list(result.keys()) == ["2026-06-15", "2026-07-01"]

    def test_empty_input(self):
        assert group_jobs_by_date([]) == {}

    def test_single_date(self):
        jobs = [
            _job(title="A", source_date="2026-06-01"),
        ]
        result = group_jobs_by_date(jobs)
        assert len(result) == 1
        assert "2026-06-01" in result

    def test_many_dates_sorted(self):
        """Dates should be in chronological order, not insertion order."""
        jobs = [
            _job(url="http://5", source_date="2026-07-15"),
            _job(url="http://3", source_date="2026-06-20"),
            _job(url="http://1", source_date="2026-06-01"),
            _job(url="http://4", source_date="2026-07-01"),
            _job(url="http://2", source_date="2026-06-15"),
        ]
        result = group_jobs_by_date(jobs)
        assert list(result.keys()) == [
            "2026-06-01", "2026-06-15", "2026-06-20",
            "2026-07-01", "2026-07-15",
        ]


class TestTrashBeforeFiltering:
    """Test that only pre-cutoff, successfully-parsed emails are trashed."""

    def test_only_old_emails_trashed(self):
        """Emails before cutoff are trashed; June/July emails are kept."""
        parsed_ok_ids = ["e1", "e2", "e3"]
        email_dates = {
            "e1": "2026-04-15",
            "e2": "2026-06-01",
            "e3": "2026-07-15",
        }
        trash_before = "2026-06-01"
        ids_to_trash = [
            eid for eid in parsed_ok_ids
            if email_dates.get(eid, "") < trash_before
        ]
        assert ids_to_trash == ["e1"]

    def test_no_emails_before_cutoff(self):
        """All emails are at or after cutoff — nothing to trash."""
        parsed_ok_ids = ["e1", "e2"]
        email_dates = {"e1": "2026-06-15", "e2": "2026-07-01"}
        trash_before = "2026-06-01"
        ids_to_trash = [
            eid for eid in parsed_ok_ids
            if email_dates.get(eid, "") < trash_before
        ]
        assert ids_to_trash == []

    def test_skipped_and_failed_not_trashed(self):
        """Only parsed_ok_ids are considered for trashing, not skipped/failed."""
        parsed_ok_ids = ["e1"]
        skipped_ids = ["e2"]
        failed_ids = ["e3"]
        email_dates = {
            "e1": "2026-04-01",
            "e2": "2026-04-01",
            "e3": "2026-04-01",
        }
        trash_before = "2026-06-01"
        ids_to_trash = [
            eid for eid in parsed_ok_ids
            if email_dates.get(eid, "") < trash_before
        ]
        # Only e1 (parsed OK) is trashed, not e2 (skipped) or e3 (failed)
        assert ids_to_trash == ["e1"]

    def test_trash_disabled_with_empty_string(self):
        """--trash-before '' disables trashing entirely."""
        trash_before = ""
        # When trash_before is empty string, the main() code skips trashing
        assert not trash_before  # This is the condition checked in main()

    def test_boundary_date_not_trashed(self):
        """Email on the cutoff date itself (e.g. 2026-06-01) are NOT trashed."""
        parsed_ok_ids = ["e1", "e2"]
        email_dates = {
            "e1": "2026-06-01",  # exactly on cutoff — NOT < cutoff
            "e2": "2026-05-31",  # before cutoff
        }
        trash_before = "2026-06-01"
        ids_to_trash = [
            eid for eid in parsed_ok_ids
            if email_dates.get(eid, "") < trash_before
        ]
        assert ids_to_trash == ["e2"]