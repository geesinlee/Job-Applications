"""Tests for review_daily_discoveries and ingest_from_discovery MCP tools."""

import json
import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

# Import the MCP server module
import job_applications_mcp_server as mcp_server


@pytest.fixture
def tmp_artefacts(tmp_path):
    """Create a temporary artefacts directory with a digest file."""
    digests_dir = tmp_path / "digests"
    digests_dir.mkdir(parents=True, exist_ok=True)
    return tmp_path


@pytest.fixture
def sample_digest(tmp_artefacts):
    """Write a sample daily digest markdown file."""
    digest_dir = tmp_artefacts / "digests"
    today = date.today().isoformat()
    content = f"""# Job Discoveries — {today}

## Surfaced for Review

### Thoughtworks — Senior Consultant
- **Location:** Singapore
- **URL:** https://thoughtworks.com/jobs/123
- **Snippet:** We are looking for a Senior Consultant...
- **Category:** surfaced

---

### Gartner — VP Sales
- **Location:** Singapore
- **URL:** https://gartner.com/jobs/456
- **Snippet:** Gartner is seeking a VP of Sales...
- **Category:** surfaced

---

## Below Threshold

### Acme Corp — Junior Developer
- **Location:** Remote
- **URL:** https://acme.com/jobs/789
- **Snippet:** Entry-level position...
- **Reason:** Below pre-filter threshold
"""
    (digest_dir / f"{today}.md").write_text(content, encoding="utf-8")
    return today


class TestReviewDailyDiscoveries:
    """Tests for the review_daily_discoveries MCP tool."""

    def test_returns_surfaced_jobs(self, tmp_artefacts, sample_digest):
        with patch.object(mcp_server, "ARTEFACTS_DIR", tmp_artefacts):
            result = mcp_server.review_daily_discoveries(sample_digest)
        assert result["ok"] is True
        assert result["total_surfaced"] == 2
        assert result["total_below_threshold"] == 1
        companies = [j["company"] for j in result["surfaced"]]
        assert "Thoughtworks" in companies
        assert "Gartner" in companies

    def test_returns_below_threshold_jobs(self, tmp_artefacts, sample_digest):
        with patch.object(mcp_server, "ARTEFACTS_DIR", tmp_artefacts):
            result = mcp_server.review_daily_discoveries(sample_digest)
        assert result["ok"] is True
        below = result["below_threshold"]
        assert len(below) == 1
        assert below[0]["company"] == "Acme Corp"
        assert below[0].get("reason") == "Below pre-filter threshold"

    def test_parses_job_details(self, tmp_artefacts, sample_digest):
        with patch.object(mcp_server, "ARTEFACTS_DIR", tmp_artefacts):
            result = mcp_server.review_daily_discoveries(sample_digest)
        thoughtworks = [j for j in result["surfaced"] if j["company"] == "Thoughtworks"][0]
        assert thoughtworks["title"] == "Senior Consultant"
        assert thoughtworks["location"] == "Singapore"
        assert "thoughtworks.com" in thoughtworks["url"]

    def test_no_digest_file(self, tmp_artefacts):
        with patch.object(mcp_server, "ARTEFACTS_DIR", tmp_artefacts):
            result = mcp_server.review_daily_discoveries("2099-01-01")
        assert result["ok"] is False
        assert result["error"] == "no_digest_found"

    def test_defaults_to_today(self, tmp_artefacts, sample_digest):
        with patch.object(mcp_server, "ARTEFACTS_DIR", tmp_artefacts):
            result = mcp_server.review_daily_discoveries("")  # Empty string → today
        assert result["ok"] is True
        assert result["date"] == sample_digest


class TestIngestFromDiscovery:
    """Tests for the ingest_from_discovery MCP tool."""

    def test_creates_tracker_entry(self, tmp_artefacts, sample_digest):
        tracker_path = tmp_artefacts / "tracker.json"
        tracker_path.write_text(
            json.dumps({"schema_version": "1.0", "applications": []}),
            encoding="utf-8",
        )
        with (
            patch.object(mcp_server, "ARTEFACTS_DIR", tmp_artefacts),
            patch.object(mcp_server, "TRACKER_PATH", tracker_path),
            patch.object(mcp_server, "_nas_sync"),  # skip NAS sync
        ):
            result = mcp_server.ingest_from_discovery("Thoughtworks", sample_digest)
        assert result["ok"] is True
        assert result["company"] == "Thoughtworks"
        assert result["role_title"] == "Senior Consultant"
        assert result["stage"] == "new"
        assert "jd_path" in result

        # Verify tracker was updated
        tracker = json.loads(tracker_path.read_text(encoding="utf-8"))
        apps = tracker["applications"]
        assert len(apps) == 1
        assert apps[0]["company"] == "Thoughtworks"
        assert apps[0]["role_title"] == "Senior Consultant"

    def test_creates_jd_file(self, tmp_artefacts, sample_digest):
        tracker_path = tmp_artefacts / "tracker.json"
        tracker_path.write_text(
            json.dumps({"schema_version": "1.0", "applications": []}),
            encoding="utf-8",
        )
        with (
            patch.object(mcp_server, "ARTEFACTS_DIR", tmp_artefacts),
            patch.object(mcp_server, "TRACKER_PATH", tracker_path),
            patch.object(mcp_server, "_nas_sync"),
        ):
            result = mcp_server.ingest_from_discovery("Gartner", sample_digest)
        assert result["ok"] is True

        # Verify JD.md was created
        jd_path = Path(result["jd_path"])
        assert jd_path.exists()
        content = jd_path.read_text(encoding="utf-8")
        assert "VP Sales" in content
        assert "gartner.com" in content

    def test_company_not_found_in_digest(self, tmp_artefacts, sample_digest):
        with patch.object(mcp_server, "ARTEFACTS_DIR", tmp_artefacts):
            result = mcp_server.ingest_from_discovery("Nonexistent Corp", sample_digest)
        assert result["ok"] is False
        assert result["error"] == "job_not_found"
        assert "available_companies" in result

    def test_already_tracked(self, tmp_artefacts, sample_digest):
        tracker_path = tmp_artefacts / "tracker.json"
        tracker_data = {
            "schema_version": "1.0",
            "applications": [
                {
                    "id": "existing-1",
                    "company": "Thoughtworks",
                    "role_title": "Senior Consultant",
                    "stage": "new",
                }
            ],
        }
        tracker_path.write_text(json.dumps(tracker_data), encoding="utf-8")

        with (
            patch.object(mcp_server, "ARTEFACTS_DIR", tmp_artefacts),
            patch.object(mcp_server, "TRACKER_PATH", tracker_path),
        ):
            result = mcp_server.ingest_from_discovery("Thoughtworks", sample_digest)
        assert result["ok"] is False
        assert result["error"] == "already_tracked"

    def test_no_digest_file(self, tmp_artefacts):
        with patch.object(mcp_server, "ARTEFACTS_DIR", tmp_artefacts):
            result = mcp_server.ingest_from_discovery("Thoughtworks", "2099-01-01")
        assert result["ok"] is False
        assert result["error"] == "no_digest_found"