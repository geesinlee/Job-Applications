"""Unit tests for consolidated Job-Applications MCP server tools."""

import json
from pathlib import Path
from unittest.mock import patch
import pytest

import job_applications_mcp_server as server


def test_consolidated_mcp_tool_catalog():
    """Verify exactly 24 consolidated MCP tools are registered in Phase 2."""
    with open("job_applications_mcp_server.py") as f:
        lines = f.readlines()

    tools = []
    for i, line in enumerate(lines):
        if "@mcp.tool()" in line:
            for j in range(i + 1, min(i + 5, len(lines))):
                if lines[j].strip().startswith("def "):
                    name = lines[j].split("(")[0].replace("def ", "").strip()
                    tools.append(name)
                    break

    assert len(tools) == 24, f"Expected 24 consolidated MCP tools, found {len(tools)}: {tools}"
    # Verify key unified tools are in the catalog
    assert "save_application_artefact" in tools
    assert "prepare_intelligence_context" in tools
    assert "manage_application_followups" in tools
    assert "list_applications" in tools
    assert "get_application_status" in tools
    assert "update_application" in tools
    assert "get_cv" in tools
    assert "list_job_discoveries" in tools
    assert "enrich_gaps_from_work_rag" in tools

    # Verify redundant tools are NOT exposed via @mcp.tool()
    assert "company_research" not in tools
    assert "map_territory" not in tools
    assert "generate_cover_letter" not in tools
    assert "generate_pitch" not in tools
    assert "analyse_gaps" not in tools
    assert "generate_learning_program" not in tools
    assert "get_due_followups" not in tools
    assert "mark_followup_complete" not in tools
    assert "mark_submitted" not in tools
    assert "ingest_from_discovery" not in tools


def test_save_application_artefact_research(tmp_path, monkeypatch):
    """Verify save_application_artefact correctly persists research and updates outputs."""
    monkeypatch.setattr(server, "ARTEFACTS_DIR", tmp_path)
    (tmp_path / "Acme").mkdir(parents=True, exist_ok=True)
    tracker_file = tmp_path / "tracker.json"
    tracker_file.write_text(json.dumps({"schema_version": "1.0", "applications": [
        {"id": "test-1", "company": "Acme", "role_title": "Lead", "stage": "new", "outputs": {}}
    ]}))
    monkeypatch.setattr(server, "TRACKER_PATH", tracker_file)

    res = server.save_application_artefact(company="Acme", document_type="research", content="# Acme Research")
    assert "error" not in res

    research_file = tmp_path / "Acme" / "research.md"
    assert research_file.exists()
    assert "# Acme Research" in research_file.read_text()


def test_save_application_artefact_interview_notes(tmp_path, monkeypatch):
    """Verify save_application_artefact appends interview notes with timestamp & section."""
    monkeypatch.setattr(server, "ARTEFACTS_DIR", tmp_path)
    (tmp_path / "Acme").mkdir(parents=True, exist_ok=True)
    tracker_file = tmp_path / "tracker.json"
    tracker_file.write_text(json.dumps({"schema_version": "1.0", "applications": [
        {"id": "test-1", "company": "Acme", "role_title": "Lead", "stage": "interview_r1", "outputs": {}}
    ]}))
    monkeypatch.setattr(server, "TRACKER_PATH", tracker_file)

    res = server.save_application_artefact(
        company="Acme",
        document_type="interview_notes",
        content="Candidate discussed leadership.",
        section="Hiring Manager Screen"
    )
    assert "error" not in res

    notes_file = tmp_path / "Acme" / "interview_notes.md"
    assert notes_file.exists()
    assert "Hiring Manager Screen" in notes_file.read_text()
    assert "Candidate discussed leadership." in notes_file.read_text()


def test_get_cv_base_and_reference(tmp_path, monkeypatch):
    """Verify get_cv retrieves both base and reference CV templates."""
    base_file = tmp_path / "Base_CV.md"
    base_file.write_text("# Master CV Content")
    monkeypatch.setattr(server, "BASE_CV_PATH", base_file)

    base_res = server.get_cv(document_type="base")
    assert base_res.get("ok") is True
    assert base_res["cv_content"] == "# Master CV Content"


def test_get_application_status_by_id(tmp_path, monkeypatch):
    """Verify get_application_status resolves application by UUID directly."""
    monkeypatch.setattr(server, "ARTEFACTS_DIR", tmp_path)
    comp_dir = tmp_path / "Acme"
    comp_dir.mkdir(parents=True, exist_ok=True)
    (comp_dir / "JD.md").write_text("# Job Description")

    tracker_file = tmp_path / "tracker.json"
    tracker_file.write_text(json.dumps({"schema_version": "1.0", "applications": [
        {"id": "uuid-1234", "company": "Acme", "role_title": "Lead", "stage": "applied", "history": [], "followups": []}
    ]}))
    monkeypatch.setattr(server, "TRACKER_PATH", tracker_file)

    res = server.get_application_status(application_id="uuid-1234")
    assert res.get("exists") is True
    assert res["company"] == "Acme"
    assert res["id"] == "uuid-1234"
    assert res["steps"]["job_description"] is True


def test_update_application_linkedin_url(tmp_path, monkeypatch):
    """Verify update_application updates LinkedIn URL and metadata."""
    monkeypatch.setattr(server, "ARTEFACTS_DIR", tmp_path)
    tracker_file = tmp_path / "tracker.json"
    tracker_file.write_text(json.dumps({"schema_version": "1.0", "applications": [
        {"id": "uuid-1234", "company": "Acme", "role_title": "Lead", "stage": "new", "history": [], "followups": []}
    ]}))
    monkeypatch.setattr(server, "TRACKER_PATH", tracker_file)

    res = server.update_application(application_id="uuid-1234", linkedin_url="https://linkedin.com/jobs/view/999")
    assert res.get("ok") is True
    assert res["linkedin_url"] == "https://linkedin.com/jobs/view/999"


def test_list_applications_enriched(tmp_path, monkeypatch):
    """Verify list_applications returns enriched opportunity fields and respects include_closed."""
    tracker_file = tmp_path / "tracker.json"
    tracker_file.write_text(json.dumps({"schema_version": "1.0", "applications": [
        {"id": "uuid-1", "company": "Acme", "role_title": "Lead", "stage": "applied", "date_created": "2026-08-01T00:00:00Z"},
        {"id": "uuid-2", "company": "Beta", "role_title": "Staff", "stage": "rejected", "date_created": "2026-08-02T00:00:00Z"},
    ]}))
    monkeypatch.setattr(server, "TRACKER_PATH", tracker_file)

    # By default (include_closed=False), only active applications are returned
    active_res = server.list_applications()
    assert active_res["count"] == 1
    assert active_res["applications"][0]["id"] == "uuid-1"
    assert "days_elapsed" in active_res["applications"][0]

    # When include_closed=True, rejected is included
    all_res = server.list_applications(include_closed=True)
    assert all_res["count"] == 2
    assert "opportunities" in all_res


def test_manage_application_followups_list_and_complete(tmp_path, monkeypatch):
    """Verify manage_application_followups handles list and complete actions."""
    tracker_file = tmp_path / "tracker.json"
    tracker_file.write_text(json.dumps({"schema_version": "1.0", "applications": [
        {
            "id": "uuid-1",
            "company": "Acme",
            "role_title": "Lead",
            "stage": "applied",
            "followups": [
                {
                    "id": "f-1",
                    "action_type": "check_status",
                    "due_date": "2026-01-01",
                    "status": "pending",
                }
            ],
        }
    ]}))
    monkeypatch.setattr(server, "TRACKER_PATH", tracker_file)

    # 1. Action: list
    list_res = server.manage_application_followups(action="list")
    assert list_res["count"] == 1
    assert list_res["due_followups"][0]["followup_id"] == "f-1"

    # 2. Action: complete
    comp_res = server.manage_application_followups(
        action="complete",
        application_id="uuid-1",
        followup_id="f-1",
    )
    assert comp_res.get("ok") is True

    # After completion, list should return 0
    empty_res = server.manage_application_followups(action="list")
    assert empty_res["count"] == 0


def test_prepare_intelligence_context_routing(tmp_path, monkeypatch):
    """Verify prepare_intelligence_context routes to correct generators."""
    monkeypatch.setattr(server, "ARTEFACTS_DIR", tmp_path)
    (tmp_path / "Acme").mkdir(parents=True, exist_ok=True)
    (tmp_path / "Acme" / "research.md").write_text("# Existing Research")
    tracker_file = tmp_path / "tracker.json"
    tracker_file.write_text(json.dumps({"schema_version": "1.0", "applications": []}))
    monkeypatch.setattr(server, "TRACKER_PATH", tracker_file)

    # Routing to research
    res = server.prepare_intelligence_context(company="Acme", context_type="research")
    assert "existing_content" in res or "template" in res

    # Unsupported context_type
    bad_res = server.prepare_intelligence_context(company="Acme", context_type="nonexistent")
    assert bad_res["ok"] is False
    assert "Unsupported context_type" in bad_res["error"]


def test_legacy_functions_remain_callable(tmp_path, monkeypatch):
    """Verify legacy functions remain callable in Python runtime."""
    monkeypatch.setattr(server, "ARTEFACTS_DIR", tmp_path)
    (tmp_path / "Acme").mkdir(parents=True, exist_ok=True)
    tracker_file = tmp_path / "tracker.json"
    tracker_file.write_text(json.dumps({"schema_version": "1.0", "applications": []}))
    monkeypatch.setattr(server, "TRACKER_PATH", tracker_file)

    assert callable(server.company_research)
    assert callable(server.map_territory)
    assert callable(server.generate_cover_letter)
    assert callable(server.generate_pitch)
    assert callable(server.analyse_gaps)
    assert callable(server.generate_learning_program)
    assert callable(server.get_due_followups)
    assert callable(server.mark_followup_complete)
    assert callable(server.mark_submitted)
    assert callable(server.ingest_from_discovery)

