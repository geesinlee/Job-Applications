"""Unit tests for Work-RAG cross-domain evidence adapter."""

import pytest
from unittest.mock import patch, MagicMock
from src.tools.work_rag_adapter import WorkRagQueryPlanner, WorkRagClient, CareerEvidenceEnricher


def test_query_planner_cleans_boilerplate_and_deduplicates():
    gaps = [
        {"requirement": "Must have proven track record in SAP ERP migration and architecture"},
        {"requirement": "Experience in Singapore Public Sector GovTech tender RFP"},
    ]
    missing_skills = ["SAP ERP", "GovTech Procurement"]

    queries = WorkRagQueryPlanner.plan_queries(
        company="Gartner",
        role_title="Enterprise Account Executive",
        gaps=gaps,
        missing_skills=missing_skills,
        max_queries=4,
    )

    assert len(queries) <= 4
    assert any("SAP ERP" in q for q in queries)
    assert any("GovTech" in q for q in queries)
    for q in queries:
        assert "proven track record" not in q.lower()
        assert "must have" not in q.lower()


def test_career_evidence_enricher_infers_stint_and_metrics():
    mock_results = [
        {
            "name": "GovTech - Workato Subscription Renewal.pdf",
            "logical_path": "GovTech - Workato Subscription Renewal.pdf",
            "company_context": "Workato",
            "created_at": "2026-01-21 07:06:52",
            "chunk_text": "Account Name The Government Technology Agency of Singapore (GovTech)\nClosed $150K ARR contract extension.",
            "citation": "[GovTech.pdf](GovTech.pdf)",
        },
        {
            "name": "VISEO_Sales_Performance.docx",
            "logical_path": "VISEO_Sales_Performance.docx",
            "company_context": "VISEO",
            "created_at": "2024-05-10",
            "chunk_text": "Managed SAP and Salesforce practice sales with 200% quota attainment.",
            "citation": "[VISEO.docx](VISEO.docx)",
        },
    ]

    items = CareerEvidenceEnricher.synthesize_evidence_items(mock_results, max_items=2)
    assert len(items) == 2
    assert items[0]["stint"] == "Workato"
    assert items[0]["confidence"] == "LEVEL_A"
    assert "GovTech" in items[0]["statement"]
    assert items[1]["stint"] == "VISEO"
    assert items[1]["confidence"] == "LEVEL_A"
    assert "200%" in items[1]["statement"]


def test_work_rag_client_circuit_breaker_on_error():
    client = WorkRagClient(base_url="http://invalid.local:9999", timeout=0.1)
    results = client.search_hybrid("test query", limit=1)
    assert results == []
