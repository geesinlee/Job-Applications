"""Integration tests for the job-applications MCP server."""

import json
import tempfile
from pathlib import Path
import pytest


class TestCreateApplication:
    def test_create_with_markdown_jd(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
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
        from job_applications_mcp_server import create_application
        result = create_application("TestCo", "/nonexistent/path/jd.pdf")
        assert "error" in result

    def test_create_with_role_title_override(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        from job_applications_mcp_server import create_application
        jd_file = tmp_path / "jd.md"
        jd_file.write_text("# Some Title\nContent...")
        result = create_application("TestCo", str(jd_file), role_title="Custom Role")
        assert result["role_title"] == "Custom Role"


class TestGetApplicationStatus:
    def test_status_nonexistent_company(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        from job_applications_mcp_server import get_application_status
        result = get_application_status("NonexistentCo")
        assert result["exists"] is False

    def test_status_with_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
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
        from job_applications_mcp_server import company_research
        company_dir = tmp_path / "TestCo"
        company_dir.mkdir()
        result = company_research("TestCo", focus="AI strategy")
        assert result["company"] == "TestCo"
        assert "AI strategy" in result["template"]
        assert len(result["next_steps"]) > 0

    def test_save_research(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        from job_applications_mcp_server import save_research
        company_dir = tmp_path / "TestCo"
        company_dir.mkdir()
        result = save_research("TestCo", "# Test Research\n\nSome content.", focus="AI")
        assert result["saved"] is True
        assert (company_dir / "research.md").exists()

    def test_research_nonexistent_company(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        from job_applications_mcp_server import company_research
        result = company_research("NoCompany")
        assert "error" in result


class TestMapTerritory:
    def test_territory_template(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        from job_applications_mcp_server import map_territory
        company_dir = tmp_path / "TestCo"
        company_dir.mkdir()
        result = map_territory("TestCo", accounts=["MTI", "GovTech"])
        assert result["company"] == "TestCo"
        assert len(result["account_instructions"]) == 2
        assert any("MTI" in instr["account"] for instr in result["account_instructions"])

    def test_save_territory_map(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        from job_applications_mcp_server import save_territory_map
        company_dir = tmp_path / "TestCo"
        company_dir.mkdir()
        result = save_territory_map("TestCo", "# Territory Map\n\nMTI contacts...")
        assert result["saved"] is True
        assert (company_dir / "territory_map.md").exists()

    def test_territory_nonexistent_company(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        from job_applications_mcp_server import map_territory
        result = map_territory("NoCompany", accounts=["MTI"])
        assert "error" in result


class TestGenerateCoverLetter:
    def test_cover_letter_context(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
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
        from job_applications_mcp_server import save_cover_letter
        company_dir = tmp_path / "TestCo"
        company_dir.mkdir()
        result = save_cover_letter("TestCo", "Dear Hiring Team,\n\nI am writing...")
        assert result["saved"] is True

    def test_cover_letter_tones(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
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
        from job_applications_mcp_server import generate_pitch
        company_dir = tmp_path / "TestCo"
        company_dir.mkdir()
        (company_dir / "research.md").write_text("# Research")
        (company_dir / "territory_map.md").write_text("# Territory")
        result = generate_pitch("TestCo", format="bullet_points")
        assert result["format"] == "bullet_points"

    def test_save_pitch(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        from job_applications_mcp_server import save_pitch
        company_dir = tmp_path / "TestCo"
        company_dir.mkdir()
        result = save_pitch("TestCo", "# Pitch\n\nKey messages...")
        assert result["saved"] is True

    def test_pitch_formats(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
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
        from job_applications_mcp_server import save_tailored_cv
        company_dir = tmp_path / "TestCo"
        company_dir.mkdir()
        result = save_tailored_cv("TestCo", "# Tailored CV\n\nExperience...")
        assert result["saved"] is True
        assert (company_dir / "CV_tailored.md").exists()

    def test_cv_missing_jd(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        from job_applications_mcp_server import tailor_cv
        company_dir = tmp_path / "NoJDCo"
        company_dir.mkdir()
        result = tailor_cv("NoJDCo")
        assert "JD.md" in " ".join(result["missing_sources"])