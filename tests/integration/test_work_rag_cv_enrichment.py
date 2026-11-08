"""Integration test for Work-RAG CV enrichment in Gate 10 workflow."""

import pytest
from unittest.mock import patch, MagicMock
from src.workflow_tools import WorkflowTools
import job_applications_mcp_server as server


def test_generate_cv_draft_renders_work_rag_evidence():
    tools = WorkflowTools()
    work_rag_evidence = [
        {
            "statement": "Closed 14+ competitive displacements against Boomi across APJ.",
            "stint": "Workato",
            "source_reference": "Sales_Flash_Deal_Intelligence_Analysis.docx",
            "confidence": "LEVEL_A",
        }
    ]

    res = tools.generate_cv_draft(
        application_id="app-123",
        jd_content="Looking for Enterprise Sales Director with competitive displacement experience.",
        evidence_items=["Closed key account at Gartner"],
        work_rag_evidence=work_rag_evidence,
    )

    assert res["ok"] is True
    assert res["work_rag_evidence_count"] == 1
    prompt = res["system_prompt"]
    assert "<work_rag_evidence>" in prompt
    assert "[Workato]" in prompt
    assert "Closed 14+ competitive displacements against Boomi" in prompt
    assert "Sales_Flash_Deal_Intelligence_Analysis.docx" in prompt


def test_enrich_gaps_from_work_rag_tool():
    mock_chunks = [
        {
            "name": "GovTech_Project.docx",
            "company_context": "Workato",
            "chunk_text": "GovTech project deliverable for whole of government integration.",
            "created_at": "2025-11-15",
            "citation": "GovTech_Project.docx",
        }
    ]

    with patch("src.tools.work_rag_adapter.WorkRagClient.search_hybrid", return_value=mock_chunks):
        res = server.enrich_gaps_from_work_rag(
            company="TestCompany",
            role_title="Enterprise Account Executive",
            custom_queries=["GovTech integration"],
        )

        assert res["ok"] is True
        assert len(res["evidence_items"]) == 1
        assert res["evidence_items"][0]["stint"] == "Workato"
        assert "GovTech" in res["evidence_items"][0]["statement"]
