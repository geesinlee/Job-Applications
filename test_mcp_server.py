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