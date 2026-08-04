"""Integration tests for the job-applications MCP server."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent


class TestCreateApplication:
    def test_create_with_markdown_jd(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        monkeypatch.setattr("job_applications_mcp_server.ARTEFACTS_DIR", tmp_path)
        from job_applications_mcp_server import create_application
        jd_file = tmp_path / "test_jd.md"
        jd_file.write_text("# Senior Developer\nWe need a developer...")
        result = create_application("TestCo", str(jd_file))
        assert result["company"] == "TestCo"
        assert result["role_title"] == "Senior Developer"
        assert result["jd_length"] > 0
        assert (tmp_path / "TestCo" / "JD.md").exists()

    def test_create_existing_folder(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        monkeypatch.setattr("job_applications_mcp_server.ARTEFACTS_DIR", tmp_path)
        from job_applications_mcp_server import create_application
        company_dir = tmp_path / "ExistingCo"
        company_dir.mkdir()
        (company_dir / "existing.txt").write_text("data")
        jd_file = tmp_path / "jd.md"
        jd_file.write_text("# Role")
        result = create_application("ExistingCo", str(jd_file))
        assert result["company"] == "ExistingCo"
        assert "existing.txt" in result["existing_files"]

    def test_create_missing_jd(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        monkeypatch.setattr("job_applications_mcp_server.ARTEFACTS_DIR", tmp_path)
        from job_applications_mcp_server import create_application
        result = create_application("TestCo", "/nonexistent/path/jd.pdf")
        assert "error" in result

    def test_create_with_role_title_override(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        monkeypatch.setattr("job_applications_mcp_server.ARTEFACTS_DIR", tmp_path)
        from job_applications_mcp_server import create_application
        jd_file = tmp_path / "jd.md"
        jd_file.write_text("# Some Title\nContent...")
        result = create_application("TestCo", str(jd_file), role_title="Custom Role")
        assert result["role_title"] == "Custom Role"


class TestPathResolver:
    """Unit tests for _resolve_company_folder / _make_role_slug (Task 2)."""

    def test_make_role_slug(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        monkeypatch.setattr("job_applications_mcp_server.ARTEFACTS_DIR", tmp_path)
        from job_applications_mcp_server import _make_role_slug
        assert _make_role_slug("Enterprise AE - Strategic Accounts") == "enterprise-ae-strategic-accounts"
        assert _make_role_slug("Senior  Developer") == "senior-developer"

    def test_legacy_folder_resolves_to_root(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        monkeypatch.setattr("job_applications_mcp_server.ARTEFACTS_DIR", tmp_path)
        from job_applications_mcp_server import _resolve_company_folder
        company_dir = tmp_path / "Gartner"
        company_dir.mkdir()
        (company_dir / "JD.md").write_text("# Analyst")
        empty_tracker = {"schema_version": "1.0", "applications": []}
        assert _resolve_company_folder("Gartner", None, empty_tracker) == company_dir
        assert _resolve_company_folder("Gartner", "Analyst", empty_tracker) == company_dir

    def test_single_new_role_resolves_to_root(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        monkeypatch.setattr("job_applications_mcp_server.ARTEFACTS_DIR", tmp_path)
        from job_applications_mcp_server import _resolve_company_folder
        empty_tracker = {"schema_version": "1.0", "applications": []}
        result = _resolve_company_folder("BrandNewCo", None, empty_tracker)
        assert result == tmp_path / "BrandNewCo"

    def test_two_roles_use_separate_slug_subfolders(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        monkeypatch.setattr("job_applications_mcp_server.ARTEFACTS_DIR", tmp_path)
        from job_applications_mcp_server import _resolve_company_folder
        empty_tracker = {"schema_version": "1.0", "applications": []}
        role_a = _resolve_company_folder("Salesforce", "Enterprise AE", empty_tracker)
        role_b = _resolve_company_folder("Salesforce", "Solutions Engineer", empty_tracker)
        assert role_a == tmp_path / "Salesforce" / "enterprise-ae"
        assert role_b == tmp_path / "Salesforce" / "solutions-engineer"
        assert role_a != role_b

    def test_ambiguous_role_raises_when_multiple_records_and_no_title(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        monkeypatch.setattr("job_applications_mcp_server.ARTEFACTS_DIR", tmp_path)
        from job_applications_mcp_server import _resolve_company_folder, AmbiguousRoleError
        tracker = {
            "schema_version": "1.0",
            "applications": [
                {"company": "Salesforce", "role_title": "Enterprise AE"},
                {"company": "Salesforce", "role_title": "Solutions Engineer"},
            ],
        }
        with pytest.raises(AmbiguousRoleError) as exc_info:
            _resolve_company_folder("Salesforce", None, tracker)
        assert exc_info.value.company == "Salesforce"
        assert set(exc_info.value.roles) == {"Enterprise AE", "Solutions Engineer"}


class TestGetApplicationStatus:
    def test_status_nonexistent_company(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        monkeypatch.setattr("job_applications_mcp_server.ARTEFACTS_DIR", tmp_path)
        from job_applications_mcp_server import get_application_status
        result = get_application_status("NonexistentCo")
        assert result["exists"] is False

    def test_status_ambiguous_role_without_title(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        monkeypatch.setattr("job_applications_mcp_server.ARTEFACTS_DIR", tmp_path)
        from job_applications_mcp_server import get_application_status, _save_tracker
        _save_tracker({
            "schema_version": "1.0",
            "applications": [
                {"company": "Salesforce", "role_title": "Enterprise AE"},
                {"company": "Salesforce", "role_title": "Solutions Engineer"},
            ],
        })
        result = get_application_status("Salesforce")
        assert result["error"] == "ambiguous_role"
        assert set(result["roles"]) == {"Enterprise AE", "Solutions Engineer"}

    def test_status_with_role_title_resolves_correct_subfolder(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        monkeypatch.setattr("job_applications_mcp_server.ARTEFACTS_DIR", tmp_path)
        from job_applications_mcp_server import get_application_status, _save_tracker
        _save_tracker({
            "schema_version": "1.0",
            "applications": [
                {"company": "Salesforce", "role_title": "Enterprise AE"},
                {"company": "Salesforce", "role_title": "Solutions Engineer"},
            ],
        })
        role_dir = tmp_path / "Salesforce" / "enterprise-ae"
        role_dir.mkdir(parents=True)
        (role_dir / "JD.md").write_text("# Enterprise AE")
        result = get_application_status("Salesforce", role_title="Enterprise AE")
        assert result["exists"] is True
        assert result["steps"]["job_description"] is True

    def test_status_with_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        monkeypatch.setattr("job_applications_mcp_server.ARTEFACTS_DIR", tmp_path)
        from job_applications_mcp_server import get_application_status
        company_dir = tmp_path / "TestCo"
        company_dir.mkdir()
        (company_dir / "JD.md").write_text("# JD")
        (company_dir / "research.md").write_text("# Research")
        result = get_application_status("TestCo")
        assert result["exists"] is True
        assert result["steps"]["job_description"] is True
        assert result["steps"]["research"] is True
        assert result["steps"]["territory_map"] is False

    def test_status_all_completed(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        monkeypatch.setattr("job_applications_mcp_server.ARTEFACTS_DIR", tmp_path)
        from job_applications_mcp_server import get_application_status
        company_dir = tmp_path / "CompleteCo"
        company_dir.mkdir()
        (company_dir / "JD.md").write_text("# JD")
        (company_dir / "research.md").write_text("# Research")
        (company_dir / "territory_map.md").write_text("# Map")
        (company_dir / "Cover_Letter.md").write_text("# Letter")
        (company_dir / "pitch.md").write_text("# Pitch")
        (company_dir / "CV_tailored.md").write_text("# CV")
        result = get_application_status("CompleteCo")
        assert result["next_action"] == "All steps completed!"

    def test_status_reads_tracker_when_present(self, tmp_path):
        from job_applications_mcp_server import get_application_status, _save_tracker
        company_dir = tmp_path / "TestCo"
        company_dir.mkdir()
        (company_dir / "JD.md").write_text("# JD")
        app = {
            "id": "app1", "company": "TestCo", "role_title": "Engineer",
            "stage": "applied", "date_created": "2026-01-01T00:00:00Z",
            "history": [], "followups": [],
        }
        _save_tracker({"schema_version": "1.0", "applications": [app]})
        result = get_application_status("TestCo", role_title="Engineer")
        assert result["tracked"] is True
        assert result["stage"] == "applied"
        assert result["application_id"] == "app1"

    def test_status_untracked_falls_back(self, tmp_path):
        from job_applications_mcp_server import get_application_status
        company_dir = tmp_path / "LegacyCo"
        company_dir.mkdir()
        (company_dir / "JD.md").write_text("# JD")
        result = get_application_status("LegacyCo")
        assert result["tracked"] is False


class TestUpdateStage:
    """Task 3: stage machine transitions, follow-up creation/cancellation."""

    def _seed_app(self, company="TestCo", role_title="Engineer", stage="new"):
        from job_applications_mcp_server import _create_application_record, _save_tracker
        app = _create_application_record(company, role_title, "/tmp/jd.md")
        app["stage"] = stage
        app["history"] = [{"stage": stage, "at": "2026-01-01T00:00:00Z"}]
        _save_tracker({"schema_version": "1.0", "applications": [app]})
        return app

    def test_valid_transition(self, tmp_path):
        self._seed_app(stage="new")
        from job_applications_mcp_server import update_stage
        result = update_stage("TestCo", "Engineer", "applied")
        assert result["ok"] is True
        assert result["previous_stage"] == "new"
        assert result["new_stage"] == "applied"

    def test_all_valid_transitions(self, tmp_path):
        from job_applications_mcp_server import update_stage, VALID_TRANSITIONS
        for stage, next_stages in VALID_TRANSITIONS.items():
            for next_stage in next_stages:
                self._seed_app(stage=stage)
                result = update_stage("TestCo", "Engineer", next_stage)
                assert result["ok"] is True, f"{stage} -> {next_stage} should be valid"

    def test_all_invalid_transitions(self, tmp_path):
        from job_applications_mcp_server import update_stage, VALID_STAGES, VALID_TRANSITIONS
        for stage, allowed in VALID_TRANSITIONS.items():
            invalid = VALID_STAGES - allowed - {stage}
            for bad_stage in invalid:
                self._seed_app(stage=stage)
                result = update_stage("TestCo", "Engineer", bad_stage)
                assert result["ok"] is False, f"{stage} -> {bad_stage} should be invalid"
                assert result["error"] == "invalid_transition"

    def test_terminal_stage_blocks_all_transitions(self, tmp_path):
        from job_applications_mcp_server import update_stage, VALID_STAGES
        for terminal in ("accepted", "rejected", "withdrawn"):
            for target in VALID_STAGES:
                self._seed_app(stage=terminal)
                result = update_stage("TestCo", "Engineer", target)
                assert result["ok"] is False
                assert result["error"] == "invalid_transition"

    def test_application_not_found(self, tmp_path):
        from job_applications_mcp_server import update_stage, _save_tracker
        _save_tracker({"schema_version": "1.0", "applications": []})
        result = update_stage("Nope", "Nobody", "applied")
        assert result["ok"] is False
        assert result["error"] == "application_not_found"

    def test_invalid_stage_name_rejected(self, tmp_path):
        self._seed_app(stage="new")
        from job_applications_mcp_server import update_stage
        result = update_stage("TestCo", "Engineer", "not_a_real_stage")
        assert result["ok"] is False
        assert result["error"] == "invalid_stage"

    def test_followup_created_on_applied(self, tmp_path):
        self._seed_app(stage="new")
        from job_applications_mcp_server import update_stage, _load_tracker, _find_application
        update_stage("TestCo", "Engineer", "applied")
        tracker = _load_tracker()
        app = _find_application(tracker, "TestCo", "Engineer")
        pending = [f for f in app["followups"] if f["status"] == "pending"]
        assert len(pending) == 1
        assert pending[0]["action_type"] == "send_follow_up_email"

    def test_followup_deduplication(self, tmp_path):
        from job_applications_mcp_server import _auto_create_followup
        app = self._seed_app(stage="applied")
        _auto_create_followup(app, "applied")
        _auto_create_followup(app, "applied")
        pending = [
            f for f in app["followups"]
            if f["action_type"] == "send_follow_up_email" and f["status"] == "pending"
        ]
        assert len(pending) == 1

    def test_followup_email_cancelled_on_interview(self, tmp_path):
        self._seed_app(stage="new")
        from job_applications_mcp_server import update_stage, _load_tracker, _find_application
        update_stage("TestCo", "Engineer", "applied")
        update_stage("TestCo", "Engineer", "screening")
        update_stage("TestCo", "Engineer", "interview_r1")
        tracker = _load_tracker()
        app = _find_application(tracker, "TestCo", "Engineer")
        email_followups = [f for f in app["followups"] if f["action_type"] == "send_follow_up_email"]
        assert len(email_followups) == 1
        assert email_followups[0]["status"] == "cancelled"
        thank_you = [f for f in app["followups"] if f["action_type"] == "send_thank_you_note"]
        assert len(thank_you) == 1
        assert thank_you[0]["status"] == "pending"


class TestListApplications:
    def test_empty(self, tmp_path):
        from job_applications_mcp_server import list_applications, _save_tracker
        _save_tracker({"schema_version": "1.0", "applications": []})
        result = list_applications()
        assert result["count"] == 0
        assert result["applications"] == []

    def test_sorted_by_date_created_desc(self, tmp_path):
        from job_applications_mcp_server import list_applications, _save_tracker
        apps = [
            {"id": "1", "company": "A", "role_title": "R1", "stage": "new", "date_created": "2026-01-01T00:00:00Z", "history": [], "followups": []},
            {"id": "2", "company": "B", "role_title": "R2", "stage": "new", "date_created": "2026-03-01T00:00:00Z", "history": [], "followups": []},
            {"id": "3", "company": "C", "role_title": "R3", "stage": "new", "date_created": "2026-02-01T00:00:00Z", "history": [], "followups": []},
        ]
        _save_tracker({"schema_version": "1.0", "applications": apps})
        result = list_applications()
        assert [a["id"] for a in result["applications"]] == ["2", "3", "1"]

    def test_filter_by_company(self, tmp_path):
        from job_applications_mcp_server import list_applications, _save_tracker
        apps = [
            {"id": "1", "company": "Salesforce", "role_title": "AE", "stage": "new", "date_created": "2026-01-01T00:00:00Z", "history": [], "followups": []},
            {"id": "2", "company": "Gartner", "role_title": "Analyst", "stage": "new", "date_created": "2026-01-02T00:00:00Z", "history": [], "followups": []},
        ]
        _save_tracker({"schema_version": "1.0", "applications": apps})
        result = list_applications(company="salesforce")
        assert result["count"] == 1
        assert result["applications"][0]["company"] == "Salesforce"

    def test_filter_by_stage(self, tmp_path):
        from job_applications_mcp_server import list_applications, _save_tracker
        apps = [
            {"id": "1", "company": "A", "role_title": "R1", "stage": "applied", "date_created": "2026-01-01T00:00:00Z", "history": [], "followups": []},
            {"id": "2", "company": "B", "role_title": "R2", "stage": "new", "date_created": "2026-01-02T00:00:00Z", "history": [], "followups": []},
        ]
        _save_tracker({"schema_version": "1.0", "applications": apps})
        result = list_applications(stage="applied")
        assert result["count"] == 1
        assert result["applications"][0]["id"] == "1"

    def test_multiple_roles_note(self, tmp_path):
        from job_applications_mcp_server import list_applications, _save_tracker
        apps = [
            {"id": "1", "company": "Salesforce", "role_title": "Enterprise AE", "stage": "new", "date_created": "2026-01-01T00:00:00Z", "history": [], "followups": []},
            {"id": "2", "company": "Salesforce", "role_title": "Solutions Engineer", "stage": "new", "date_created": "2026-01-02T00:00:00Z", "history": [], "followups": []},
        ]
        _save_tracker({"schema_version": "1.0", "applications": apps})
        result = list_applications(company="Salesforce")
        assert result["count"] == 2
        assert "note" in result


class TestGetDueFollowups:
    def _app_with_followup(self, due_date, status="pending", action_type="send_follow_up_email"):
        return {
            "id": "app1", "company": "TestCo", "role_title": "Engineer",
            "stage": "applied", "date_created": "2026-01-01T00:00:00Z", "history": [],
            "followups": [{
                "id": "f1", "action_type": action_type, "due_date": due_date,
                "status": status, "completed_at": None,
            }],
        }

    def test_due_today_included(self, tmp_path):
        from job_applications_mcp_server import get_due_followups, _save_tracker, _days_from_now_utc
        today = _days_from_now_utc(0)
        _save_tracker({"schema_version": "1.0", "applications": [self._app_with_followup(today)]})
        result = get_due_followups()
        assert result["count"] == 1
        assert result["due_followups"][0]["overdue"] is False

    def test_overdue_flagged(self, tmp_path):
        from job_applications_mcp_server import get_due_followups, _save_tracker, _days_from_now_utc
        past = _days_from_now_utc(-5)
        _save_tracker({"schema_version": "1.0", "applications": [self._app_with_followup(past)]})
        result = get_due_followups()
        assert result["count"] == 1
        assert result["due_followups"][0]["overdue"] is True

    def test_future_excluded(self, tmp_path):
        from job_applications_mcp_server import get_due_followups, _save_tracker, _days_from_now_utc
        future = _days_from_now_utc(5)
        _save_tracker({"schema_version": "1.0", "applications": [self._app_with_followup(future)]})
        result = get_due_followups()
        assert result["count"] == 0

    def test_completed_excluded(self, tmp_path):
        from job_applications_mcp_server import get_due_followups, _save_tracker, _days_from_now_utc
        past = _days_from_now_utc(-1)
        _save_tracker({"schema_version": "1.0", "applications": [self._app_with_followup(past, status="completed")]})
        result = get_due_followups()
        assert result["count"] == 0

    def test_sorted_ascending(self, tmp_path):
        from job_applications_mcp_server import get_due_followups, _save_tracker, _days_from_now_utc
        app1 = self._app_with_followup(_days_from_now_utc(-1))
        app1["id"] = "app1"
        app1["followups"][0]["id"] = "f1"
        app2 = self._app_with_followup(_days_from_now_utc(-10))
        app2["id"] = "app2"
        app2["followups"][0]["id"] = "f2"
        _save_tracker({"schema_version": "1.0", "applications": [app1, app2]})
        result = get_due_followups()
        assert [d["followup_id"] for d in result["due_followups"]] == ["f2", "f1"]


class TestMarkFollowupComplete:
    def test_marks_completed(self, tmp_path):
        from job_applications_mcp_server import mark_followup_complete, _save_tracker, _load_tracker
        app = {
            "id": "app1", "company": "TestCo", "role_title": "Engineer",
            "stage": "applied", "date_created": "2026-01-01T00:00:00Z", "history": [],
            "followups": [{"id": "f1", "action_type": "send_follow_up_email", "due_date": "2026-01-08", "status": "pending", "completed_at": None}],
        }
        _save_tracker({"schema_version": "1.0", "applications": [app]})
        result = mark_followup_complete("app1", "f1")
        assert result["ok"] is True
        tracker = _load_tracker()
        f = tracker["applications"][0]["followups"][0]
        assert f["status"] == "completed"
        assert f["completed_at"] is not None

    def test_followup_not_found(self, tmp_path):
        from job_applications_mcp_server import mark_followup_complete, _save_tracker
        app = {"id": "app1", "company": "TestCo", "role_title": "Engineer", "stage": "applied", "date_created": "2026-01-01T00:00:00Z", "history": [], "followups": []}
        _save_tracker({"schema_version": "1.0", "applications": [app]})
        result = mark_followup_complete("app1", "nope")
        assert result["ok"] is False
        assert result["error"] == "followup_not_found"

    def test_application_not_found(self, tmp_path):
        from job_applications_mcp_server import mark_followup_complete, _save_tracker
        _save_tracker({"schema_version": "1.0", "applications": []})
        result = mark_followup_complete("nope", "nope")
        assert result["ok"] is False
        assert result["error"] == "application_not_found"


class TestIngestJd:
    """Task 4: JD ingestion from file/URL + structured field extraction."""

    def test_ingest_from_markdown_file(self, tmp_path):
        from job_applications_mcp_server import ingest_jd, _load_tracker
        jd_file = tmp_path / "jd.md"
        jd_file.write_text(
            "# Senior Sales Engineer\n"
            "Location: Singapore\n"
            "Employment Type: Full-time\n"
            "Requires 5 years of experience\n"
            "Required Skills:\n- Python\n- SQL\n"
            "Preferred Skills:\n- AWS\n"
        )
        result = ingest_jd("TestCo", "Senior Sales Engineer", jd_path=str(jd_file))
        assert result["ok"] is True
        assert result["stage"] == "new"
        assert result["fields"]["location"] == "Singapore"
        assert result["fields"]["employment_type"] == "Full-time"
        assert result["fields"]["years_of_experience"] == 5
        assert result["fields"]["required_skills"] == ["Python", "SQL"]
        assert result["fields"]["preferred_skills"] == ["AWS"]
        assert (Path(result["folder_path"]) / "JD.md").exists()
        tracker = _load_tracker()
        assert len(tracker["applications"]) == 1

    def test_ingest_from_pdf_file(self, tmp_path, monkeypatch):
        from job_applications_mcp_server import ingest_jd
        pdf_file = tmp_path / "jd.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake")
        monkeypatch.setattr(
            "job_applications_mcp_server._extract_pdf_text",
            lambda p: "Senior Sales Engineer\nGreat role",
        )
        result = ingest_jd("TestCo", "Senior Sales Engineer", jd_path=str(pdf_file))
        assert result["ok"] is True
        assert result["jd_length"] > 0

    def test_ingest_zero_text_pdf(self, tmp_path, monkeypatch):
        from job_applications_mcp_server import ingest_jd
        pdf_file = tmp_path / "jd.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake")
        monkeypatch.setattr("job_applications_mcp_server._extract_pdf_text", lambda p: "")
        result = ingest_jd("TestCo", "Some Role", jd_path=str(pdf_file))
        assert result["ok"] is False
        assert result["error"] == "zero_text_pdf"

    def test_ingest_file_not_found(self, tmp_path):
        from job_applications_mcp_server import ingest_jd
        result = ingest_jd("TestCo", "Some Role", jd_path=str(tmp_path / "nope.md"))
        assert result["ok"] is False
        assert result["error"] == "file_not_found"

    def test_ingest_unsupported_format(self, tmp_path):
        from job_applications_mcp_server import ingest_jd
        bad_file = tmp_path / "jd.docx"
        bad_file.write_text("data")
        result = ingest_jd("TestCo", "Some Role", jd_path=str(bad_file))
        assert result["ok"] is False
        assert result["error"] == "unsupported_format"

    def test_ingest_both_sources_given(self, tmp_path):
        from job_applications_mcp_server import ingest_jd
        jd_file = tmp_path / "jd.md"
        jd_file.write_text("# Role")
        result = ingest_jd(
            "TestCo", "Some Role", jd_path=str(jd_file), jd_url="http://example.com/jd"
        )
        assert result["ok"] is False
        assert result["error"] == "both_sources_given"

    def test_ingest_no_source_given(self, tmp_path):
        from job_applications_mcp_server import ingest_jd
        result = ingest_jd("TestCo", "Some Role")
        assert result["ok"] is False
        assert result["error"] == "no_source_given"

    def test_ingest_from_url_mocked(self, tmp_path, monkeypatch):
        from job_applications_mcp_server import ingest_jd
        monkeypatch.setattr(
            "job_applications_mcp_server._ingest_jd_url",
            lambda url: "Senior Sales Engineer\nLocation: Remote\n",
        )
        result = ingest_jd("TestCo", "Senior Sales Engineer", jd_url="https://example.com/job/123")
        assert result["ok"] is True
        assert result["fields"]["location"] == "Remote"
        assert (Path(result["folder_path"]) / "JD.md").exists()

    def test_ingest_url_error(self, tmp_path, monkeypatch):
        import requests
        from job_applications_mcp_server import ingest_jd

        def _raise(url):
            raise requests.RequestException("connection refused")

        monkeypatch.setattr("job_applications_mcp_server._ingest_jd_url", _raise)
        result = ingest_jd("TestCo", "Some Role", jd_url="https://example.com/job/404")
        assert result["ok"] is False
        assert result["error"] == "url_error"

    def test_ingest_null_fields_when_absent(self, tmp_path):
        from job_applications_mcp_server import ingest_jd
        jd_file = tmp_path / "jd.md"
        jd_file.write_text("Just some plain text with nothing structured in it at all really.")
        result = ingest_jd("TestCo", "Mystery Role", jd_path=str(jd_file))
        assert result["ok"] is True
        assert result["fields"]["company_name"] is None
        assert result["fields"]["location"] is None
        assert result["fields"]["employment_type"] is None
        assert result["fields"]["years_of_experience"] is None
        assert result["fields"]["required_skills"] == []
        assert result["fields"]["preferred_skills"] == []

    def test_ingest_from_pasted_text(self, tmp_path):
        from job_applications_mcp_server import ingest_jd, _load_tracker
        jd_content = (
            "# Senior Account Executive\n"
            "Location: Singapore\n"
            "Employment Type: Full-time\n"
            "Requires 8 years of experience\n"
            "Required Skills:\n- Enterprise Sales\n- Public Sector\n"
        )
        result = ingest_jd("TestCo", "Senior Account Executive", jd_text=jd_content)
        assert result["ok"] is True
        assert result["stage"] == "new"
        assert result["fields"]["location"] == "Singapore"
        assert result["fields"]["years_of_experience"] == 8
        assert result["fields"]["required_skills"] == ["Enterprise Sales", "Public Sector"]
        assert (Path(result["folder_path"]) / "JD.md").exists()
        assert (Path(result["folder_path"]) / "JD.md").read_text() == jd_content
        tracker = _load_tracker()
        assert len(tracker["applications"]) == 1

    def test_ingest_pasted_text_with_reference_url(self, tmp_path):
        from job_applications_mcp_server import ingest_jd, _load_tracker
        jd_content = "# Product Manager\nLocation: Remote\n"
        result = ingest_jd(
            "AcmeCorp", "Product Manager",
            jd_text=jd_content,
            jd_url="https://acme.com/jobs/pm-123",
        )
        assert result["ok"] is True
        assert result["jd_source_url"] == "https://acme.com/jobs/pm-123"
        tracker = _load_tracker()
        app = tracker["applications"][0]
        assert app["jd_source_url"] == "https://acme.com/jobs/pm-123"
        # Content should be the pasted text, not fetched from URL
        assert (Path(result["folder_path"]) / "JD.md").read_text() == jd_content

    def test_ingest_pasted_text_no_reference_url(self, tmp_path):
        from job_applications_mcp_server import ingest_jd, _load_tracker
        jd_content = "# Data Engineer\nSpark, Python, SQL\n"
        result = ingest_jd("DataCo", "Data Engineer", jd_text=jd_content)
        assert result["ok"] is True
        assert "jd_source_url" not in result
        tracker = _load_tracker()
        app = tracker["applications"][0]
        assert "jd_source_url" not in app

    def test_ingest_pasted_text_with_file_path_is_error(self, tmp_path):
        from job_applications_mcp_server import ingest_jd
        result = ingest_jd(
            "TestCo", "Some Role",
            jd_path=str(tmp_path / "jd.md"),
            jd_text="Some pasted text",
        )
        assert result["ok"] is False
        assert result["error"] == "both_sources_given"

    def test_ingest_pasted_text_with_url_and_file_path_is_error(self, tmp_path):
        from job_applications_mcp_server import ingest_jd
        result = ingest_jd(
            "TestCo", "Some Role",
            jd_path=str(tmp_path / "jd.md"),
            jd_text="Pasted text",
            jd_url="https://example.com/jd",
        )
        assert result["ok"] is False
        assert result["error"] == "both_sources_given"

    def test_duplicate_ingest_preserves_stage(self, tmp_path):
        from job_applications_mcp_server import ingest_jd, update_stage, _load_tracker
        jd_file = tmp_path / "jd.md"
        jd_file.write_text("# Senior Sales Engineer\nFirst version")
        first = ingest_jd("TestCo", "Senior Sales Engineer", jd_path=str(jd_file))
        app_id = first["application_id"]
        update_stage("TestCo", "Senior Sales Engineer", "applied")

        jd_file2 = tmp_path / "jd_v2.md"
        jd_file2.write_text("# Senior Sales Engineer\nUpdated version")
        second = ingest_jd("TestCo", "Senior Sales Engineer", jd_path=str(jd_file2))
        assert second["application_id"] == app_id
        assert second["stage"] == "applied"
        tracker = _load_tracker()
        assert len(tracker["applications"]) == 1
        assert (Path(second["folder_path"]) / "JD.md").read_text().strip() == "# Senior Sales Engineer\nUpdated version"


CV_FIXTURE = """# Jane Doe

Singapore | jane@example.com

---

## SALES ENGINEER

Summary paragraph here.

---

## PROFESSIONAL EXPERIENCE

### Acme Corp | Senior Sales Engineer | Jan 2020 – Present

- Did great things
- Closed big deals

### Beta Inc | Sales Engineer | 2015 – 2019

- Did other things

---

## EDUCATION & CERTIFICATIONS

- **Bachelor of Science (Computer Science)** — State University

---

## TECHNICAL SKILLS

- **Cloud:** AWS, Azure
- **Languages:** English, Spanish
"""


class TestComputeYearsOfExperience:
    def test_non_overlapping_sum(self):
        from job_applications_mcp_server import _compute_years_of_experience
        work_exp = [
            {"start": "2010-01", "end": "2015-01"},
            {"start": "2015-01", "end": "2020-01"},
        ]
        assert _compute_years_of_experience(work_exp) == 10

    def test_overlapping_intervals_not_double_counted(self):
        from job_applications_mcp_server import _compute_years_of_experience
        work_exp = [
            {"start": "2010-01", "end": "2020-01"},
            {"start": "2015-01", "end": "2018-01"},
        ]
        assert _compute_years_of_experience(work_exp) == 10

    def test_missing_dates_skipped(self):
        from job_applications_mcp_server import _compute_years_of_experience
        work_exp = [{"start": None, "end": "2020-01"}, {"start": "2010-01", "end": "2012-01"}]
        assert _compute_years_of_experience(work_exp) == 2

    def test_empty_list(self):
        from job_applications_mcp_server import _compute_years_of_experience
        assert _compute_years_of_experience([]) == 0


class TestTopNSkills:
    def test_ranks_by_frequency(self):
        from job_applications_mcp_server import _top_n_skills
        work_exp = [
            {"description": "Used python and sql extensively"},
            {"description": "More python work, some aws"},
        ]
        skills = ["python", "sql", "aws", "docker"]
        ranked = _top_n_skills(work_exp, skills, n=3)
        assert ranked[0] == "python"
        assert len(ranked) == 3
        assert "docker" not in ranked

    def test_respects_n(self):
        from job_applications_mcp_server import _top_n_skills
        skills = ["a", "b", "c", "d", "e", "f"]
        ranked = _top_n_skills([], skills, n=5)
        assert len(ranked) == 5


class TestSeedProfileFromCv:
    def test_parses_fixture_cv(self, tmp_path):
        from job_applications_mcp_server import _seed_profile_from_cv
        cv_file = tmp_path / "cv.md"
        cv_file.write_text(CV_FIXTURE)
        profile = _seed_profile_from_cv(cv_file)
        assert profile["headline"] == "SALES ENGINEER"
        assert len(profile["work_experience"]) == 2
        first = profile["work_experience"][0]
        assert first["company"] == "Acme Corp"
        assert first["title"] == "Senior Sales Engineer"
        assert first["start"] == "2020-01"
        assert first["end"] == "present"
        second = profile["work_experience"][1]
        assert second["company"] == "Beta Inc"
        assert second["start"] == "2015"
        assert second["end"] == "2019"
        assert profile["current_role"] == {"title": "Senior Sales Engineer", "company": "Acme Corp"}
        assert profile["education"] == [{
            "institution": "State University",
            "degree": "Bachelor of Science",
            "field": "Computer Science",
            "start": None,
            "end": None,
        }]
        assert profile["skills"] == ["aws", "azure", "english", "spanish"]


class TestUpdateProfile:
    def test_seed_from_cv_creates_profile(self, tmp_path):
        from job_applications_mcp_server import update_profile, _load_profile
        cv_file = tmp_path / "cv.md"
        cv_file.write_text(CV_FIXTURE)
        result = update_profile("cv", cv_path=str(cv_file))
        assert result["ok"] is True
        assert result["work_experience_count"] == 2
        profile = _load_profile()
        assert profile["skills"] == ["aws", "azure", "english", "spanish"]

    def test_cv_path_not_found(self, tmp_path):
        from job_applications_mcp_server import update_profile
        result = update_profile("cv", cv_path=str(tmp_path / "nope.md"))
        assert result["ok"] is False
        assert result["error"] == "file_not_found"

    def test_session_requires_text(self):
        from job_applications_mcp_server import update_profile
        result = update_profile("session")
        assert result["ok"] is False
        assert result["error"] == "text_required"

    def test_unsupported_source(self):
        from job_applications_mcp_server import update_profile
        result = update_profile("carrier_pigeon")
        assert result["ok"] is False
        assert result["error"] == "unsupported_source"

    def test_session_merge_fills_gap_without_overwriting(self, tmp_path):
        from job_applications_mcp_server import update_profile, _load_profile
        cv_file = tmp_path / "cv.md"
        cv_file.write_text(CV_FIXTURE)
        update_profile("cv", cv_path=str(cv_file))

        session_text = "Name\nHeadline Two\n\nSkills\npython, negotiation\n"
        result = update_profile("session", text=session_text)
        assert result["ok"] is True
        profile = _load_profile()
        assert "python" in profile["skills"]
        assert "aws" in profile["skills"]


class TestRefreshProfileFromLinkedin:
    def test_linkedin_merge_wins_conflict_and_logs(self, tmp_path):
        from job_applications_mcp_server import update_profile, refresh_profile_from_linkedin, _load_profile
        cv_file = tmp_path / "cv.md"
        cv_file.write_text(CV_FIXTURE)
        update_profile("cv", cv_path=str(cv_file))

        linkedin_text = (
            "Jane Doe\n"
            "Senior Sales Leader\n"
            "\n"
            "Experience\n"
            "Senior Sales Engineer\n"
            "Acme Corp\n"
            "Jan 2021 - Present\n"
            "Updated role description\n"
            "\n"
            "Skills\n"
            "python, negotiation\n"
        )
        result = refresh_profile_from_linkedin(text=linkedin_text)
        assert result["ok"] is True
        assert result["conflicts_flagged"] >= 1

        profile = _load_profile()
        acme = next(e for e in profile["work_experience"] if e["company"] == "Acme Corp")
        assert acme["start"] == "2021-01"
        assert acme["_source"] == "linkedin"
        conflict = next(c for c in profile["conflicts"] if "start" in c["field_path"])
        assert conflict["linkedin_value"] == "2021-01"
        assert conflict["cv_value"] == "2020-01"
        assert "python" in profile["skills"]
        assert "aws" in profile["skills"]

    def test_no_source_given(self):
        from job_applications_mcp_server import refresh_profile_from_linkedin
        result = refresh_profile_from_linkedin()
        assert result["ok"] is False
        assert result["error"] == "no_source_given"

    def test_multiple_sources_given(self):
        from job_applications_mcp_server import refresh_profile_from_linkedin
        result = refresh_profile_from_linkedin(url="http://example.com", text="Experience\nSkills")
        assert result["ok"] is False
        assert result["error"] == "multiple_sources_given"

    def test_file_not_found(self, tmp_path):
        from job_applications_mcp_server import refresh_profile_from_linkedin
        result = refresh_profile_from_linkedin(file_path=str(tmp_path / "nope.txt"))
        assert result["ok"] is False
        assert result["error"] == "file_not_found"

    def test_invalid_format_rejected(self):
        from job_applications_mcp_server import refresh_profile_from_linkedin
        result = refresh_profile_from_linkedin(text="just some random text with no sections")
        assert result["ok"] is False
        assert result["error"] == "invalid_linkedin_format"


class TestGetProfileSummary:
    def test_empty_profile_requires_setup(self):
        from job_applications_mcp_server import get_profile_summary
        result = get_profile_summary()
        assert result["ok"] is True
        assert result["setup_required"] is True

    def test_populated_profile_returns_summary(self, tmp_path):
        from job_applications_mcp_server import update_profile, get_profile_summary
        cv_file = tmp_path / "cv.md"
        cv_file.write_text(CV_FIXTURE)
        update_profile("cv", cv_path=str(cv_file))
        result = get_profile_summary()
        assert result["ok"] is True
        assert result["setup_required"] is False
        assert result["headline"] == "SALES ENGINEER"
        assert result["current_role"] == {"title": "Senior Sales Engineer", "company": "Acme Corp"}
        assert isinstance(result["years_of_experience"], int)
        assert len(result["top_skills"]) <= 5
        assert len(result["education"]) == 1


JD_FIXTURE = (
    "# Senior Sales Engineer\n"
    "Location: Singapore\n"
    "Employment Type: Full-time\n"
    "Requires 5 years of experience\n"
    "Required Skills:\n- Python\n- Kubernetes\n"
    "Preferred Skills:\n- AWS\n- Snowflake\n"
)


def _seed_profile(tmp_path):
    from job_applications_mcp_server import update_profile
    cv_file = tmp_path / "cv.md"
    cv_file.write_text(CV_FIXTURE)
    update_profile("cv", cv_path=str(cv_file))


def _ingest_test_jd(tmp_path, company="TestCo", role_title="Senior Sales Engineer", text=JD_FIXTURE):
    from job_applications_mcp_server import ingest_jd
    jd_file = tmp_path / "jd.md"
    jd_file.write_text(text)
    return ingest_jd(company, role_title, jd_path=str(jd_file))


class TestScoreMatch:
    def test_errors_when_jd_not_ingested(self):
        from job_applications_mcp_server import score_match
        result = score_match("Nowhere Inc", "Ghost Role")
        assert result["ok"] is False
        assert result["error"] == "jd_not_ingested"

    def test_errors_when_profile_not_initialised(self, tmp_path):
        from job_applications_mcp_server import score_match
        _ingest_test_jd(tmp_path)
        result = score_match("TestCo", "Senior Sales Engineer")
        assert result["ok"] is False
        assert result["error"] == "profile_not_initialised"

    def test_returns_context_dict_with_weights(self, tmp_path):
        from job_applications_mcp_server import score_match, MATCH_SCORE_WEIGHTS
        _ingest_test_jd(tmp_path)
        _seed_profile(tmp_path)
        result = score_match("TestCo", "Senior Sales Engineer")
        assert result["ok"] is True
        assert result["weights"] == MATCH_SCORE_WEIGHTS
        assert result["jd_fields"]["required_skills"] == ["Python", "Kubernetes"]
        assert result["profile_summary"]["skills"] == ["aws", "azure", "english", "spanish"]
        assert set(result["output_schema"]["sub_scores"]) == set(MATCH_SCORE_WEIGHTS)


class TestSaveMatchScore:
    VALID_SUB_SCORES = {
        "required_skills_match": 80,
        "years_of_experience_match": 90,
        "seniority_alignment": 70,
        "industry_domain_alignment": 60,
        "preferred_skills_match": 50,
    }

    def test_errors_when_app_not_found(self):
        from job_applications_mcp_server import save_match_score
        result = save_match_score(
            "Nowhere Inc", "Ghost Role", 80, self.VALID_SUB_SCORES, "reasoning", [], [], []
        )
        assert result["ok"] is False
        assert result["error"] == "jd_not_ingested"

    def test_rejects_out_of_range_overall(self, tmp_path):
        from job_applications_mcp_server import save_match_score
        _ingest_test_jd(tmp_path)
        result = save_match_score(
            "TestCo", "Senior Sales Engineer", 150, self.VALID_SUB_SCORES, "reasoning", [], [], []
        )
        assert result["ok"] is False
        assert result["error"] == "invalid_score"
        assert result["field"] == "overall"

    def test_rejects_missing_sub_score_dimension(self, tmp_path):
        from job_applications_mcp_server import save_match_score
        _ingest_test_jd(tmp_path)
        incomplete = dict(self.VALID_SUB_SCORES)
        del incomplete["seniority_alignment"]
        result = save_match_score(
            "TestCo", "Senior Sales Engineer", 80, incomplete, "reasoning", [], [], []
        )
        assert result["ok"] is False
        assert result["error"] == "invalid_score"
        assert "seniority_alignment" in result["missing_dimensions"]

    def test_persists_match_score(self, tmp_path):
        from job_applications_mcp_server import save_match_score, _load_tracker
        _ingest_test_jd(tmp_path)
        result = save_match_score(
            "TestCo", "Senior Sales Engineer", 80, self.VALID_SUB_SCORES,
            "Strong match overall.", ["Python depth"], ["No Snowflake"], ["Snowflake"],
        )
        assert result["ok"] is True
        assert result["computed_at"]
        tracker = _load_tracker()
        app = tracker["applications"][0]
        assert app["match_score"]["overall"] == 80
        assert app["match_score"]["missing_skills"] == ["Snowflake"]
        assert app["match_score"]["computed_at"] == result["computed_at"]


class TestAnalyseGaps:
    def test_errors_when_jd_not_ingested(self):
        from job_applications_mcp_server import analyse_gaps
        result = analyse_gaps("Nowhere Inc", "Ghost Role")
        assert result["ok"] is False
        assert result["error"] == "jd_not_ingested"

    def test_errors_when_base_cv_missing(self, tmp_path, monkeypatch):
        import job_applications_mcp_server as m
        monkeypatch.setattr(m, "BASE_CV_PATH", tmp_path / "does_not_exist.md")
        _ingest_test_jd(tmp_path)
        _seed_profile(tmp_path)
        result = m.analyse_gaps("TestCo", "Senior Sales Engineer")
        assert result["ok"] is False
        assert result["error"] == "base_cv_not_found"

    def test_errors_when_profile_not_initialised(self, tmp_path, monkeypatch):
        import job_applications_mcp_server as m
        base_cv = tmp_path / "base_cv.md"
        base_cv.write_text("# Base CV\nSome content")
        monkeypatch.setattr(m, "BASE_CV_PATH", base_cv)
        _ingest_test_jd(tmp_path)
        result = m.analyse_gaps("TestCo", "Senior Sales Engineer")
        assert result["ok"] is False
        assert result["error"] == "profile_not_initialised"

    def test_returns_context_with_missing_skills_from_score(self, tmp_path, monkeypatch):
        import job_applications_mcp_server as m
        base_cv = tmp_path / "base_cv.md"
        base_cv.write_text("# Base CV\nSome content")
        monkeypatch.setattr(m, "BASE_CV_PATH", base_cv)
        _ingest_test_jd(tmp_path)
        _seed_profile(tmp_path)
        m.save_match_score(
            "TestCo", "Senior Sales Engineer", 80, TestSaveMatchScore.VALID_SUB_SCORES,
            "reasoning", [], [], ["Snowflake"],
        )
        result = m.analyse_gaps("TestCo", "Senior Sales Engineer")
        assert result["ok"] is True
        assert result["missing_skills"] == ["Snowflake"]
        assert result["base_cv_content"] == "# Base CV\nSome content"
        assert "gap_id" in result["gap_schema"]


class TestSaveGapAnalysis:
    def test_rejects_empty_gaps(self, tmp_path):
        from job_applications_mcp_server import save_gap_analysis
        _ingest_test_jd(tmp_path)
        result = save_gap_analysis("TestCo", "Senior Sales Engineer", [])
        assert result["ok"] is False
        assert result["error"] == "invalid_gaps"

    def test_rejects_missing_category_with_excerpt(self, tmp_path):
        from job_applications_mcp_server import save_gap_analysis
        _ingest_test_jd(tmp_path)
        gaps = [{
            "gap_id": "g1", "category": "missing", "jd_criterion": "Snowflake",
            "affected_cv_section": "Skills", "current_text_excerpt": "should be null",
            "recommendation": "Add Snowflake experience",
        }]
        result = save_gap_analysis("TestCo", "Senior Sales Engineer", gaps)
        assert result["ok"] is False
        assert result["error"] == "invalid_gap_entry"
        assert result["field"] == "current_text_excerpt"

    def test_rejects_understated_without_excerpt(self, tmp_path):
        from job_applications_mcp_server import save_gap_analysis
        _ingest_test_jd(tmp_path)
        gaps = [{
            "gap_id": "g1", "category": "understated", "jd_criterion": "Python",
            "affected_cv_section": "Experience", "current_text_excerpt": None,
            "recommendation": "Move Python bullet earlier",
        }]
        result = save_gap_analysis("TestCo", "Senior Sales Engineer", gaps)
        assert result["ok"] is False
        assert result["error"] == "invalid_gap_entry"
        assert result["field"] == "current_text_excerpt"

    def test_saves_valid_gaps(self, tmp_path):
        from job_applications_mcp_server import save_gap_analysis
        result_ingest = _ingest_test_jd(tmp_path)
        gaps = [
            {
                "gap_id": "g1", "category": "missing", "jd_criterion": "Snowflake",
                "affected_cv_section": "Skills", "current_text_excerpt": None,
                "recommendation": "Add Snowflake experience",
            },
            {
                "gap_id": "g2", "category": "understated", "jd_criterion": "Python",
                "affected_cv_section": "Experience", "current_text_excerpt": "Used Python occasionally",
                "recommendation": "Move Python bullet earlier",
            },
        ]
        result = save_gap_analysis("TestCo", "Senior Sales Engineer", gaps)
        assert result["ok"] is True
        assert result["gaps_saved"] == 2
        path = Path(result["path"])
        assert path.exists()
        assert path.name == "gap_analysis.md"
        content = path.read_text()
        assert "Snowflake" in content
        assert "Used Python occasionally" in content


class TestGenerateLearningProgram:
    def test_errors_when_no_match_score(self, tmp_path):
        from job_applications_mcp_server import generate_learning_program
        _ingest_test_jd(tmp_path)
        result = generate_learning_program("TestCo", "Senior Sales Engineer")
        assert result["ok"] is False
        assert result["error"] == "no_match_score"

    def test_empty_missing_skills_returns_no_gaps(self, tmp_path):
        from job_applications_mcp_server import generate_learning_program, save_match_score
        _ingest_test_jd(tmp_path)
        save_match_score(
            "TestCo", "Senior Sales Engineer", 95, TestSaveMatchScore.VALID_SUB_SCORES,
            "Great fit", ["Python", "SQL"], [], [],
        )
        result = generate_learning_program("TestCo", "Senior Sales Engineer")
        assert result["ok"] is True
        assert result["no_gaps"] is True

    def test_priority_assignment_from_jd_fields(self, tmp_path):
        from job_applications_mcp_server import generate_learning_program, save_match_score
        _ingest_test_jd(tmp_path)
        save_match_score(
            "TestCo", "Senior Sales Engineer", 60, TestSaveMatchScore.VALID_SUB_SCORES,
            "Some gaps", [], [], ["Kubernetes", "AWS", "Terraform"],
        )
        result = generate_learning_program("TestCo", "Senior Sales Engineer")
        assert result["ok"] is True
        assert result["skill_priorities"]["Kubernetes"] == {"priority": "high", "completion_days": 30}
        assert result["skill_priorities"]["AWS"] == {"priority": "medium", "completion_days": 60}
        assert result["skill_priorities"]["Terraform"] == {"priority": "low", "completion_days": 90}


class TestSaveLearningProgram:
    VALID_ENTRY = {
        "skill": "Kubernetes", "resources": ["Kubernetes docs (free)", "CKA cert"],
        "hours": 40, "priority": "high", "completion_days": 30,
    }

    def test_rejects_invalid_hours(self, tmp_path):
        from job_applications_mcp_server import save_learning_program
        _ingest_test_jd(tmp_path)
        bad_entry = dict(self.VALID_ENTRY, hours=500)
        result = save_learning_program("TestCo", "Senior Sales Engineer", [bad_entry])
        assert result["ok"] is False
        assert result["error"] == "invalid_program_entry"
        assert result["field"] == "hours"

    def test_rejects_priority_completion_days_mismatch(self, tmp_path):
        from job_applications_mcp_server import save_learning_program
        _ingest_test_jd(tmp_path)
        bad_entry = dict(self.VALID_ENTRY, completion_days=90)
        result = save_learning_program("TestCo", "Senior Sales Engineer", [bad_entry])
        assert result["ok"] is False
        assert result["error"] == "invalid_program_entry"
        assert result["field"] == "completion_days"

    def test_saves_valid_program_sorted_by_priority(self, tmp_path):
        from job_applications_mcp_server import save_learning_program
        _ingest_test_jd(tmp_path)
        low_entry = {
            "skill": "Terraform", "resources": ["Terraform docs (free)"],
            "hours": 20, "priority": "low", "completion_days": 90,
        }
        result = save_learning_program(
            "TestCo", "Senior Sales Engineer", [low_entry, self.VALID_ENTRY]
        )
        assert result["ok"] is True
        assert result["entries_saved"] == 2
        path = Path(result["path"])
        assert path.name == "learning_program.md"
        content = path.read_text()
        assert content.index("Kubernetes") < content.index("Terraform")


class TestCompanyResearch:
    def test_research_template(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        monkeypatch.setattr("job_applications_mcp_server.ARTEFACTS_DIR", tmp_path)
        from job_applications_mcp_server import company_research
        company_dir = tmp_path / "TestCo"
        company_dir.mkdir()
        result = company_research("TestCo", focus="AI strategy")
        assert result["company"] == "TestCo"
        assert "AI strategy" in result["template"]
        assert len(result["next_steps"]) > 0

    def test_save_research(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        monkeypatch.setattr("job_applications_mcp_server.ARTEFACTS_DIR", tmp_path)
        from job_applications_mcp_server import save_research
        company_dir = tmp_path / "TestCo"
        company_dir.mkdir()
        result = save_research("TestCo", "# Test Research\n\nSome content.", focus="AI")
        assert result["saved"] is True
        assert (company_dir / "research.md").exists()

    def test_research_nonexistent_company(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        monkeypatch.setattr("job_applications_mcp_server.ARTEFACTS_DIR", tmp_path)
        from job_applications_mcp_server import company_research
        result = company_research("NoCompany")
        assert "error" in result


class TestMapTerritory:
    def test_territory_template(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        monkeypatch.setattr("job_applications_mcp_server.ARTEFACTS_DIR", tmp_path)
        from job_applications_mcp_server import map_territory
        company_dir = tmp_path / "TestCo"
        company_dir.mkdir()
        result = map_territory("TestCo", accounts=["MTI", "GovTech"])
        assert result["company"] == "TestCo"
        assert len(result["account_instructions"]) == 2
        assert any("MTI" in instr["account"] for instr in result["account_instructions"])

    def test_save_territory_map(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        monkeypatch.setattr("job_applications_mcp_server.ARTEFACTS_DIR", tmp_path)
        from job_applications_mcp_server import save_territory_map
        company_dir = tmp_path / "TestCo"
        company_dir.mkdir()
        result = save_territory_map("TestCo", "# Territory Map\n\nMTI contacts...")
        assert result["saved"] is True
        assert (company_dir / "territory_map.md").exists()

    def test_territory_nonexistent_company(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        monkeypatch.setattr("job_applications_mcp_server.ARTEFACTS_DIR", tmp_path)
        from job_applications_mcp_server import map_territory
        result = map_territory("NoCompany", accounts=["MTI"])
        assert "error" in result


class TestGenerateCoverLetter:
    def test_cover_letter_context(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        monkeypatch.setattr("job_applications_mcp_server.ARTEFACTS_DIR", tmp_path)
        from job_applications_mcp_server import generate_cover_letter
        company_dir = tmp_path / "TestCo"
        company_dir.mkdir()
        (company_dir / "JD.md").write_text("# Senior Developer\nJob desc...")
        (company_dir / "research.md").write_text("# Research\nCompany info...")
        result = generate_cover_letter("TestCo", tone="storyteller")
        assert result["company"] == "TestCo"
        assert result["source_files"]["jd"]["available"] is True
        assert result["source_files"]["research"]["available"] is True

    def test_save_cover_letter(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        monkeypatch.setattr("job_applications_mcp_server.ARTEFACTS_DIR", tmp_path)
        from job_applications_mcp_server import save_cover_letter
        company_dir = tmp_path / "TestCo"
        company_dir.mkdir()
        result = save_cover_letter("TestCo", "Dear Hiring Team,\n\nI am writing...")
        assert result["saved"] is True

    def test_cover_letter_tones(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        monkeypatch.setattr("job_applications_mcp_server.ARTEFACTS_DIR", tmp_path)
        from job_applications_mcp_server import generate_cover_letter
        company_dir = tmp_path / "TestCo"
        company_dir.mkdir()
        for tone in ["bold", "conservative", "storyteller"]:
            result = generate_cover_letter("TestCo", tone=tone)
            assert result["tone"] == tone
            assert result["tone_description"]  # not empty


class TestGeneratePitch:
    def test_pitch_context(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        monkeypatch.setattr("job_applications_mcp_server.ARTEFACTS_DIR", tmp_path)
        from job_applications_mcp_server import generate_pitch
        company_dir = tmp_path / "TestCo"
        company_dir.mkdir()
        (company_dir / "research.md").write_text("# Research")
        (company_dir / "territory_map.md").write_text("# Territory")
        result = generate_pitch("TestCo", format="bullet_points")
        assert result["format"] == "bullet_points"

    def test_save_pitch(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        monkeypatch.setattr("job_applications_mcp_server.ARTEFACTS_DIR", tmp_path)
        from job_applications_mcp_server import save_pitch
        company_dir = tmp_path / "TestCo"
        company_dir.mkdir()
        result = save_pitch("TestCo", "# Pitch\n\nKey messages...")
        assert result["saved"] is True

    def test_pitch_formats(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        monkeypatch.setattr("job_applications_mcp_server.ARTEFACTS_DIR", tmp_path)
        from job_applications_mcp_server import generate_pitch
        company_dir = tmp_path / "TestCo"
        company_dir.mkdir()
        for fmt in ["narrative", "bullet_points", "star_stories"]:
            result = generate_pitch("TestCo", format=fmt)
            assert result["format"] == fmt
            assert result["format_description"]


class TestTailorCv:
    def test_cv_context(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        monkeypatch.setattr("job_applications_mcp_server.ARTEFACTS_DIR", tmp_path)
        from job_applications_mcp_server import tailor_cv
        company_dir = tmp_path / "TestCo"
        company_dir.mkdir()
        (company_dir / "JD.md").write_text("# Developer\nRequirements...")
        (company_dir / "CV_Lee.md").write_text("# CV\n\nExperience details...")
        result = tailor_cv("TestCo")
        assert result["source_files"]["jd"]["available"] is True
        assert result["source_files"]["cv"]["available"] is True

    def test_save_tailored_cv(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        monkeypatch.setattr("job_applications_mcp_server.ARTEFACTS_DIR", tmp_path)
        from job_applications_mcp_server import save_tailored_cv
        company_dir = tmp_path / "TestCo"
        company_dir.mkdir()
        result = save_tailored_cv("TestCo", "# Tailored CV\n\nExperience...")
        assert result["saved"] is True
        assert (company_dir / "CV_tailored.md").exists()

    def test_cv_missing_jd(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        monkeypatch.setattr("job_applications_mcp_server.ARTEFACTS_DIR", tmp_path)
        from job_applications_mcp_server import tailor_cv
        company_dir = tmp_path / "NoJDCo"
        company_dir.mkdir()
        result = tailor_cv("NoJDCo")
        assert "JD.md" in " ".join(result["missing_sources"])


BASE_CV_WITH_FIGURES = (
    "# CV\n\nGrew ARR by 40% to $2M SGD region.\n\nManaged team of 5.\n"
)


class TestSaveTailoredCvProtection:
    def test_rejects_altered_protected_figures(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        monkeypatch.setattr("job_applications_mcp_server.ARTEFACTS_DIR", tmp_path)
        base_cv_file = tmp_path / "base_cv.md"
        base_cv_file.write_text(BASE_CV_WITH_FIGURES)
        monkeypatch.setattr("job_applications_mcp_server.BASE_CV_PATH", base_cv_file)
        from job_applications_mcp_server import save_tailored_cv
        company_dir = tmp_path / "TestCo"
        company_dir.mkdir()
        result = save_tailored_cv("TestCo", "# Tailored CV\n\nManaged team of 5.\n")
        assert result["error"] == "fabrication_detected"
        assert "Grew ARR by 40% to $2M SGD region." in result["altered_segments"]
        assert not (company_dir / "CV_tailored.md").exists()

    def test_accepts_content_preserving_protected_figures(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        monkeypatch.setattr("job_applications_mcp_server.ARTEFACTS_DIR", tmp_path)
        base_cv_file = tmp_path / "base_cv.md"
        base_cv_file.write_text(BASE_CV_WITH_FIGURES)
        monkeypatch.setattr("job_applications_mcp_server.BASE_CV_PATH", base_cv_file)
        from job_applications_mcp_server import save_tailored_cv
        company_dir = tmp_path / "TestCo"
        company_dir.mkdir()
        result = save_tailored_cv(
            "TestCo",
            "# Tailored CV\n\nGrew ARR by 40% to $2M SGD region.\n\nLed team of 5 engineers.\n",
        )
        assert result["saved"] is True
        assert (company_dir / "cv_diff_summary.md").exists()

    def test_auto_generates_diff_summary_when_none_supplied(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        monkeypatch.setattr("job_applications_mcp_server.ARTEFACTS_DIR", tmp_path)
        base_cv_file = tmp_path / "base_cv.md"
        base_cv_file.write_text(BASE_CV_WITH_FIGURES)
        monkeypatch.setattr("job_applications_mcp_server.BASE_CV_PATH", base_cv_file)
        from job_applications_mcp_server import save_tailored_cv
        company_dir = tmp_path / "TestCo"
        company_dir.mkdir()
        result = save_tailored_cv(
            "TestCo",
            "# Tailored CV\n\nGrew ARR by 40% to $2M SGD region.\n\nLed a cross-functional team.\n",
        )
        assert result["diff_entries"] > 0
        diff_text = (company_dir / "cv_diff_summary.md").read_text()
        assert "replace" in diff_text or "remove" in diff_text or "add" in diff_text

    def test_uses_caller_supplied_diff_summary(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        monkeypatch.setattr("job_applications_mcp_server.ARTEFACTS_DIR", tmp_path)
        from job_applications_mcp_server import save_tailored_cv
        company_dir = tmp_path / "TestCo"
        company_dir.mkdir()
        result = save_tailored_cv(
            "TestCo",
            "# Tailored CV\n\nExperience...",
            diff_summary=[{"section": "Summary", "change_type": "add", "description": "Added tailored intro"}],
        )
        assert result["diff_entries"] == 1
        diff_text = (company_dir / "cv_diff_summary.md").read_text()
        assert "[Summary] add: Added tailored intro" in diff_text

    def test_rejects_invalid_diff_change_type(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        monkeypatch.setattr("job_applications_mcp_server.ARTEFACTS_DIR", tmp_path)
        from job_applications_mcp_server import save_tailored_cv
        company_dir = tmp_path / "TestCo"
        company_dir.mkdir()
        result = save_tailored_cv(
            "TestCo",
            "content",
            diff_summary=[{"section": "Experience", "change_type": "bogus", "description": "x"}],
        )
        assert result["error"] == "invalid_diff_entry"
        assert result["field"] == "change_type"

    def test_rejects_diff_entry_missing_description(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        monkeypatch.setattr("job_applications_mcp_server.ARTEFACTS_DIR", tmp_path)
        from job_applications_mcp_server import save_tailored_cv
        company_dir = tmp_path / "TestCo"
        company_dir.mkdir()
        result = save_tailored_cv(
            "TestCo",
            "content",
            diff_summary=[{"section": "Experience", "change_type": "add"}],
        )
        assert result["error"] == "invalid_diff_entry"
        assert result["field"] == "section/description"


class TestCoverLetterVersioning:
    def test_first_save_has_no_backup(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        monkeypatch.setattr("job_applications_mcp_server.ARTEFACTS_DIR", tmp_path)
        from job_applications_mcp_server import save_cover_letter
        company_dir = tmp_path / "TestCo"
        company_dir.mkdir()
        result = save_cover_letter("TestCo", "Dear Hiring Team,\n\nFirst version...")
        assert result["saved"] is True
        assert result["backed_up_previous_to"] is None
        assert (company_dir / "Cover_Letter.md").exists()

    def test_second_save_backs_up_to_v1(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        monkeypatch.setattr("job_applications_mcp_server.ARTEFACTS_DIR", tmp_path)
        from job_applications_mcp_server import save_cover_letter
        company_dir = tmp_path / "TestCo"
        company_dir.mkdir()
        save_cover_letter("TestCo", "Dear Hiring Team,\n\nFirst version...")
        result = save_cover_letter("TestCo", "Dear Hiring Team,\n\nSecond version...")
        assert result["backed_up_previous_to"] == str(company_dir / "Cover_Letter_v1.md")
        assert "First version" in (company_dir / "Cover_Letter_v1.md").read_text()
        assert "Second version" in (company_dir / "Cover_Letter.md").read_text()

    def test_third_save_backs_up_to_v2(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        monkeypatch.setattr("job_applications_mcp_server.ARTEFACTS_DIR", tmp_path)
        from job_applications_mcp_server import save_cover_letter
        company_dir = tmp_path / "TestCo"
        company_dir.mkdir()
        save_cover_letter("TestCo", "Dear Hiring Team,\n\nFirst version...")
        save_cover_letter("TestCo", "Dear Hiring Team,\n\nSecond version...")
        result = save_cover_letter("TestCo", "Dear Hiring Team,\n\nThird version...")
        assert result["backed_up_previous_to"] == str(company_dir / "Cover_Letter_v2.md")
        assert (company_dir / "Cover_Letter_v1.md").exists()
        assert (company_dir / "Cover_Letter_v2.md").exists()
        assert "Third version" in (company_dir / "Cover_Letter.md").read_text()


class TestGenerateCoverLetterExtensions:
    def test_invalid_tone_returns_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        monkeypatch.setattr("job_applications_mcp_server.ARTEFACTS_DIR", tmp_path)
        from job_applications_mcp_server import generate_cover_letter
        company_dir = tmp_path / "TestCo"
        company_dir.mkdir()
        result = generate_cover_letter("TestCo", tone="aggressive")
        assert result["error"] == "invalid_tone"
        assert result["valid_tones"] == sorted(["bold", "conservative", "storyteller"])

    def test_warns_when_research_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        monkeypatch.setattr("job_applications_mcp_server.ARTEFACTS_DIR", tmp_path)
        from job_applications_mcp_server import generate_cover_letter
        company_dir = tmp_path / "TestCo"
        company_dir.mkdir()
        (company_dir / "JD.md").write_text("# JD\nRequirements...")
        result = generate_cover_letter("TestCo", tone="storyteller")
        assert "warning" in result
        assert "research" in result["warning"].lower()

    def test_no_warning_when_research_present(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        monkeypatch.setattr("job_applications_mcp_server.ARTEFACTS_DIR", tmp_path)
        from job_applications_mcp_server import generate_cover_letter
        company_dir = tmp_path / "TestCo"
        company_dir.mkdir()
        (company_dir / "JD.md").write_text("# JD\nRequirements...")
        (company_dir / "research.md").write_text("# Research\nCompany info...")
        result = generate_cover_letter("TestCo", tone="storyteller")
        assert "warning" not in result


class TestTailorCvContextExtensions:
    def test_includes_match_score_strengths_and_role_title(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        monkeypatch.setattr("job_applications_mcp_server.ARTEFACTS_DIR", tmp_path)
        monkeypatch.setattr("job_applications_mcp_server.TRACKER_PATH", tmp_path / "tracker.json")
        monkeypatch.setattr("job_applications_mcp_server.PROFILE_PATH", tmp_path / "profile.json")
        from job_applications_mcp_server import save_match_score, tailor_cv, MATCH_SCORE_WEIGHTS

        _ingest_test_jd(tmp_path)
        _seed_profile(tmp_path)
        sub_scores = {k: 80 for k in MATCH_SCORE_WEIGHTS}
        strengths = ["Strong Python background", "Led enterprise deals", "Cloud migration expert"]
        save_match_score(
            "TestCo", "Senior Sales Engineer", 85, sub_scores, "solid fit",
            strengths, ["Limited Kubernetes depth"], ["Kubernetes"],
        )
        (tmp_path / "TestCo" / "CV_Lee.md").write_text("# CV\n\nExperience details...")

        result = tailor_cv("TestCo")
        assert result["match_score_strengths"] == strengths
        assert "Senior Sales Engineer" in result["instructions"]

    def test_includes_gap_analysis_when_present(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        monkeypatch.setattr("job_applications_mcp_server.ARTEFACTS_DIR", tmp_path)
        from job_applications_mcp_server import tailor_cv
        company_dir = tmp_path / "TestCo"
        company_dir.mkdir()
        (company_dir / "JD.md").write_text("# JD\nRequirements...")
        (company_dir / "CV_Lee.md").write_text("# CV\n\nExperience details...")
        gap_content = "# Gap Analysis\n\n- Missing Kubernetes depth\n"
        (company_dir / "gap_analysis.md").write_text(gap_content)

        result = tailor_cv("TestCo")
        assert result["gap_analysis_available"] is True
        assert result["gap_analysis_content"] == gap_content

    def test_notes_absence_of_gap_analysis(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        monkeypatch.setattr("job_applications_mcp_server.ARTEFACTS_DIR", tmp_path)
        from job_applications_mcp_server import tailor_cv
        company_dir = tmp_path / "TestCo"
        company_dir.mkdir()
        (company_dir / "JD.md").write_text("# JD\nRequirements...")
        (company_dir / "CV_Lee.md").write_text("# CV\n\nExperience details...")

        result = tailor_cv("TestCo")
        assert result["gap_analysis_available"] is False
        assert "no gap_analysis.md" in result["instructions"].lower()


class TestExportDocument:
    def _setup(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        monkeypatch.setattr("job_applications_mcp_server.ARTEFACTS_DIR", tmp_path)
        monkeypatch.setattr("job_applications_mcp_server.TRACKER_PATH", tmp_path / "tracker.json")
        monkeypatch.setattr("job_applications_mcp_server.PROFILE_PATH", tmp_path / "profile.json")

    def test_invalid_document_type(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        from job_applications_mcp_server import export_document
        result = export_document("TestCo", "portfolio", "pdf")
        assert result["ok"] is False
        assert result["error"] == "invalid_document_type"
        assert result["valid_document_types"] == ["cover_letter", "tailored_cv"]

    def test_invalid_format(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        from job_applications_mcp_server import export_document
        result = export_document("TestCo", "tailored_cv", "rtf")
        assert result["ok"] is False
        assert result["error"] == "invalid_format"
        assert result["valid_formats"] == ["docx", "pdf"]

    def test_missing_source_file(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        from job_applications_mcp_server import export_document
        company_dir = tmp_path / "TestCo"
        company_dir.mkdir()
        result = export_document("TestCo", "tailored_cv", "docx")
        assert result["ok"] is False
        assert result["error"] == "source_file_missing"

    def test_missing_export_dep(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        import job_applications_mcp_server as m
        company_dir = tmp_path / "TestCo"
        company_dir.mkdir()
        (company_dir / "Cover_Letter.md").write_text("Dear Hiring Team,\n\nBody...")
        monkeypatch.setattr(m, "_check_export_deps", lambda fmt: [m.EXPORT_DEP_INSTALL["weasyprint"]])
        result = m.export_document("TestCo", "cover_letter", "pdf")
        assert result["ok"] is False
        assert result["error"] == "missing_export_dep"
        assert "pip install weasyprint" in result["missing_dependencies"][0]

    def test_docx_export_produces_output_with_expected_structure(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        from job_applications_mcp_server import export_document
        company_dir = tmp_path / "TestCo"
        company_dir.mkdir()
        (company_dir / "CV_tailored.md").write_text(
            "# Jane Doe\n\n## Experience\n\n- Did a thing\n- Did another thing\n\n### Skills\n\nPython, SQL\n"
        )
        result = export_document("TestCo", "tailored_cv", "docx")
        assert result["ok"] is True
        output_path = Path(result["output_path"])
        assert output_path.exists()

        from docx import Document
        from docx.shared import Cm
        document = Document(str(output_path))
        assert document.sections[0].left_margin == Cm(2.54)
        paragraph_texts = [p.text for p in document.paragraphs]
        assert "Jane Doe" in paragraph_texts
        assert "Experience" in paragraph_texts
        assert "Did a thing" in paragraph_texts

    def test_output_filename_format(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        from job_applications_mcp_server import export_document
        company_dir = tmp_path / "TestCo"
        company_dir.mkdir()
        (company_dir / "CV_tailored.md").write_text("# CV\n\nExperience...")
        result = export_document("TestCo", "tailored_cv", "docx")
        expected_date = __import__("datetime").datetime.now().strftime("%Y-%m-%d")
        assert Path(result["output_path"]).name == f"tailored_cv_TestCo_{expected_date}.docx"

    def test_docx_dep_check_reports_available(self):
        from job_applications_mcp_server import _check_export_deps
        assert _check_export_deps("docx") == []


class TestStartupValidation:
    """Task 1: startup creates files when absent, exits on missing BASE_DIR,
    env var override works.

    `_startup_validate()` runs at *module import time*, and the module is
    already imported (and cached in sys.modules) by earlier test classes in
    this file, so simply monkeypatching BASE_DIR and re-importing would not
    re-run startup validation. These tests instead launch a fresh subprocess
    per case so the env var is picked up at genuine module-import time.
    """

    def _run(self, code: str, env_overrides: dict) -> subprocess.CompletedProcess:
        env = {**os.environ, **env_overrides}
        return subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(_PROJECT_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_startup_creates_tracker_and_profile_when_absent(self, tmp_path):
        result = self._run(
            "import job_applications_mcp_server as m\n",
            {"JOB_APP_BASE_DIR": str(tmp_path)},
        )
        assert result.returncode == 0, result.stderr

        tracker_path = tmp_path / "tracker.json"
        profile_path = tmp_path / "profile.json"
        assert tracker_path.exists()
        assert profile_path.exists()

        assert json.loads(tracker_path.read_text()) == {
            "schema_version": "1.0",
            "applications": [],
        }
        assert json.loads(profile_path.read_text()) == {"schema_version": "1.0"}

    def test_startup_exits_on_missing_base_dir(self, tmp_path):
        missing_dir = tmp_path / "does_not_exist"
        result = self._run(
            "import job_applications_mcp_server\n",
            {"JOB_APP_BASE_DIR": str(missing_dir)},
        )
        assert result.returncode == 1
        assert "BASE_DIR not found" in result.stderr
        assert not missing_dir.exists()

    def test_env_var_override_changes_base_dir(self, tmp_path):
        result = self._run(
            "import job_applications_mcp_server as m\nprint(m.BASE_DIR)\n",
            {"JOB_APP_BASE_DIR": str(tmp_path)},
        )
        assert result.returncode == 0, result.stderr
        printed_path = result.stdout.strip().splitlines()[-1]
        assert Path(printed_path) == tmp_path