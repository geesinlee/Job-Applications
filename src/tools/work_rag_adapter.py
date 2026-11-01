"""Work-RAG Cross-Domain Adapter.

Provides:
- WorkRagQueryPlanner: Extracts targeted semantic queries from JD gap items and missing skills.
- WorkRagClient: Tailscale FastMCP / HTTP client querying Work-RAG (search_hybrid, search_semantic).
- CareerEvidenceEnricher: Filters and synthesizes raw chunks into structured career evidence.
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

WORK_RAG_BASE_URL = os.getenv("WORK_RAG_BASE_URL", "http://gs-pi-4.tail210e4f.ts.net:8087")
# Token must come from the environment (.env) only. No hardcoded fallback:
# a baked-in secret violates the fleet Zero Plaintext Secret policy. Empty
# default is fail-closed (requests 401 rather than using an embedded token).
WORK_RAG_TOKEN = os.getenv("WORK_RAG_TOKEN", "")
WORK_RAG_TIMEOUT_SECONDS = float(os.getenv("WORK_RAG_TIMEOUT_SECONDS", "10.0"))


class WorkRagQueryPlanner:
    """Extracts focused queries from JD gap items and missing skills."""

    @staticmethod
    def clean_term(term: str) -> str:
        """Strip boilerplate phrasing from JD requirements."""
        text = re.sub(
            r"(?i)\b(must have|experience in|proven track record|demonstrated ability to|hands-on with|familiarity with|knowledge of|proficient in|responsible for|ability to|understanding of)\b",
            "",
            term,
        )
        return " ".join(text.split()).strip()

    @classmethod
    def plan_queries(
        cls,
        company: str,
        role_title: str,
        gaps: list[dict[str, Any]],
        missing_skills: list[str] | None = None,
        max_queries: int = 5,
    ) -> list[str]:
        """Generate targeted queries combining tech stack, domain/agency, and commercial wins."""
        queries: list[str] = []
        seen = set()

        # 1. Missing skills queries
        for s in (missing_skills or []):
            cleaned = cls.clean_term(s)
            if cleaned and cleaned.lower() not in seen:
                queries.append(cleaned)
                seen.add(cleaned.lower())
                if len(queries) >= max_queries:
                    return queries

        # 2. Requirement gap queries
        for g in gaps:
            req_stmt = g.get("requirement") or g.get("jd_criterion") or ""
            cleaned = cls.clean_term(req_stmt)
            if cleaned and cleaned.lower() not in seen:
                # Truncate overly long requirements to salient keywords
                words = cleaned.split()
                if len(words) > 8:
                    cleaned = " ".join(words[:8])
                if cleaned.lower() not in seen:
                    queries.append(cleaned)
                    seen.add(cleaned.lower())
            if len(queries) >= max_queries:
                break

        # Fallback if no specific queries generated
        if not queries and role_title:
            queries.append(f"{role_title} customer engagement architecture")

        return queries[:max_queries]


class WorkRagClient:
    """HTTP client querying Work-RAG over FastMCP JSON-RPC."""

    def __init__(
        self,
        base_url: str = WORK_RAG_BASE_URL,
        token: str = WORK_RAG_TOKEN,
        timeout: float = WORK_RAG_TIMEOUT_SECONDS,
    ):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def search_hybrid(
        self,
        query: str,
        limit: int = 3,
        classification: str | None = None,
    ) -> list[dict[str, Any]]:
        """Call Work-RAG search_hybrid via JSON-RPC."""
        args: dict[str, Any] = {"query": query, "limit": limit}
        if classification:
            args["classification"] = classification

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "search_hybrid", "arguments": args},
        }

        endpoint = f"{self.base_url}/mcp"
        req = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.token}",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                result = data.get("result", {})
                
                # Check for FastMCP tool result content
                if "content" in result and isinstance(result["content"], list):
                    for item in result["content"]:
                        if item.get("type") == "text":
                            try:
                                parsed = json.loads(item.get("text", "{}"))
                                return parsed.get("results", [])
                            except Exception:
                                pass
                if "results" in result:
                    return result["results"]
                return []
        except Exception as e:
            logger.warning("Work-RAG search_hybrid call failed (%s): %s", endpoint, e)
            return []


class CareerEvidenceEnricher:
    """Synthesizes raw Work-RAG search chunks into typed career evidence."""

    @staticmethod
    def infer_stint(chunk: dict[str, Any]) -> str:
        """Infer career stint/employer from context, logical path, or content."""
        ctx = chunk.get("company_context") or ""
        path = chunk.get("logical_path") or chunk.get("name") or ""
        text = chunk.get("chunk_text") or ""

        candidates = [ctx, path, text[:300]]
        full_sample = " ".join(candidates).lower()

        if "workato" in full_sample:
            return "Workato"
        if "viseo" in full_sample:
            return "VISEO"
        if "ncs" in full_sample:
            return "NCS"
        if "microsoft" in full_sample:
            return "Microsoft"
        if "pwc" in full_sample:
            return "PwC"
        return "Career Project"

    @classmethod
    def synthesize_evidence_items(
        cls,
        raw_results: list[dict[str, Any]],
        max_items: int = 4,
    ) -> list[dict[str, Any]]:
        """Transform search results into structured evidence with citations."""
        evidence_items: list[dict[str, Any]] = []
        seen_names = set()

        for res in raw_results:
            name = res.get("name") or "Work-RAG Archive"
            if name in seen_names:
                continue
            seen_names.add(name)

            chunk_text = res.get("chunk_text") or ""
            # Take salient snippet
            lines = [l.strip() for l in chunk_text.splitlines() if l.strip() and not l.startswith("Context:") and not l.startswith("##")]
            snippet = " ".join(lines[:3]) if lines else chunk_text[:250]
            if len(snippet) > 280:
                snippet = snippet[:277] + "..."

            stint = cls.infer_stint(res)
            citation = res.get("citation") or res.get("source_path") or name
            created = str(res.get("created_at") or "")[:10]
            date_label = f" ({created})" if created else ""

            # Check if metrics exist
            has_metrics = bool(re.search(r"(\$\d+|\d+%|\d+\+|\d+x\b|\d+ closed|\d+ deals|\d+ ARR|\d+ tasks)", snippet, re.IGNORECASE))

            evidence_items.append({
                "statement": snippet,
                "stint": stint,
                "source_type": "work_rag_retrieval",
                "source_reference": f"{citation}{date_label}",
                "confidence": "LEVEL_A" if has_metrics else "LEVEL_B",
                "metrics": {"quantified": True} if has_metrics else {},
                "user_confirmed": False,
            })

            if len(evidence_items) >= max_items:
                break

        return evidence_items
