# evidence_service.py
"""
Career Evidence Service Layer.

Implements business logic for evidence management:
- CRUD operations
- Provenance tracking and verification
- Duplicate detection (deterministic + semantic)
- Contradiction detection and resolution
- Evidence querying and filtering

Does NOT interact with MCP or HTTP — pure business logic.
"""

import re
import uuid
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass

from evidence_persistence import EvidenceRepository

logger = logging.getLogger(__name__)


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class DuplicateCandidate:
    """Candidate for evidence duplication."""
    evidence_id: str
    statement: str
    similarity_score: float  # 0.0–1.0 for semantic; 1.0 for deterministic
    match_type: str  # "deterministic" or "semantic"


@dataclass
class Contradiction:
    """Detected contradiction between evidence items."""
    evidence_id_1: str
    evidence_id_2: str
    field: str  # e.g., "geographic_scope", "role_title"
    value_1: Any
    value_2: Any
    severity: str  # "high", "medium", "low"
    description: str
    requires_user_action: bool


# ============================================================================
# EVIDENCE SERVICE
# ============================================================================

class EvidenceService:
    """Business logic for career evidence management."""

    def __init__(self, repo: EvidenceRepository):
        self.repo = repo

    # ========================================================================
    # CRUD OPERATIONS
    # ========================================================================

    def create_evidence(
        self,
        statement: str,
        evidence_type: str,
        source_type: str,
        source_reference: str,
        confidence: str = "LEVEL_C",
        verification_status: str = "unverified",
        user_confirmed: bool = False,
        application_origin: Optional[Dict[str, Any]] = None,
        competencies: Optional[List[str]] = None,
        technologies: Optional[List[str]] = None,
        industries: Optional[List[str]] = None,
        geographies: Optional[List[str]] = None,
        metrics: Optional[Dict[str, Any]] = None,
        notes: str = "",
    ) -> Dict[str, Any]:
        """
        Create new evidence item.

        Validates metrics (if present) require verified_source.
        Does NOT check for duplicates (caller's responsibility).
        """
        # Validate metrics
        if metrics:
            for metric_name, metric_data in metrics.items():
                if isinstance(metric_data, dict) and metric_data:
                    if "verified_source" not in metric_data:
                        raise ValueError(
                            f"Metric '{metric_name}' requires verified_source field"
                        )

        evidence = {
            "evidence_id": str(uuid.uuid4()),
            "statement": statement,
            "evidence_type": evidence_type,
            "source_type": source_type,
            "source_reference": source_reference,
            "source_document_id": None,
            "source_date": datetime.utcnow().isoformat() + "Z",
            "first_captured_at": datetime.utcnow().isoformat() + "Z",
            "last_confirmed_at": datetime.utcnow().isoformat() + "Z",
            "application_origin": application_origin,
            "verification_status": verification_status,
            "confidence": confidence,
            "user_confirmed": user_confirmed,
            "supersedes": [],
            "superseded_by": [],
            "related_to": [],
            "competencies": competencies or [],
            "technologies": technologies or [],
            "industries": industries or [],
            "geographies": geographies or [],
            "metrics": metrics or {},
            "notes": notes,
            "created_by": "service",
            "created_at": datetime.utcnow().isoformat() + "Z",
            "last_modified_by": "service",
            "last_modified_at": datetime.utcnow().isoformat() + "Z",
        }

        self.repo.add_evidence(evidence)
        logger.info(f"Created evidence: {evidence['evidence_id']}")
        return evidence

    def get_evidence(self, evidence_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve evidence by ID."""
        return self.repo.get_evidence(evidence_id)

    def list_evidence(self, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """List evidence, optionally filtered."""
        return self.repo.list_evidence(filters)

    def update_evidence_verification(
        self,
        evidence_id: str,
        verification_status: str,
        user_confirmed: bool,
        notes: str = ""
    ) -> Optional[Dict[str, Any]]:
        """Update evidence verification status."""
        evidence = self.get_evidence(evidence_id)
        if not evidence:
            return None

        updates = {
            "verification_status": verification_status,
            "user_confirmed": user_confirmed,
            "last_confirmed_at": datetime.utcnow().isoformat() + "Z",
        }
        if notes:
            updates["notes"] = notes

        return self.repo.update_evidence(evidence_id, updates)

    def supersede_evidence(self, old_id: str, new_id: str) -> bool:
        """Mark old evidence as superseded by new evidence."""
        old = self.get_evidence(old_id)
        new = self.get_evidence(new_id)

        if not old or not new:
            return False

        # Update old evidence
        self.repo.update_evidence(old_id, {
            "verification_status": "superseded",
            "superseded_by": [new_id],
        })

        # Update new evidence
        self.repo.update_evidence(new_id, {
            "supersedes": [old_id],
        })

        logger.info(f"Superseded {old_id} with {new_id}")
        return True

    # ========================================================================
    # DUPLICATE DETECTION
    # ========================================================================

    def find_duplicates(
        self,
        statement: str,
        confidence_threshold: float = 0.85,
        all_evidence: Optional[List[Dict[str, Any]]] = None
    ) -> List[DuplicateCandidate]:
        """
        Find potential duplicate evidence.

        Pass 1: Deterministic (normalized text match)
        Pass 2: Semantic (similarity > threshold)

        Returns candidates ordered by similarity (highest first).
        """
        if all_evidence is None:
            all_evidence = self.list_evidence()

        candidates = []

        # Pass 1: Deterministic (normalized text)
        normalized_new = self._normalize_statement(statement)
        for evidence in all_evidence:
            normalized_existing = self._normalize_statement(evidence["statement"])
            if normalized_new == normalized_existing:
                candidates.append(
                    DuplicateCandidate(
                        evidence_id=evidence["evidence_id"],
                        statement=evidence["statement"],
                        similarity_score=1.0,
                        match_type="deterministic"
                    )
                )

        if candidates:
            return candidates  # Early exit if deterministic match found

        # Pass 2: Semantic (word overlap heuristic; could be LLM-based in real impl)
        similarity_scores = []
        for evidence in all_evidence:
            score = self._semantic_similarity(statement, evidence["statement"])
            if score > confidence_threshold:
                similarity_scores.append((evidence, score))

        # Sort by score (highest first)
        similarity_scores.sort(key=lambda x: x[1], reverse=True)
        candidates = [
            DuplicateCandidate(
                evidence_id=e["evidence_id"],
                statement=e["statement"],
                similarity_score=score,
                match_type="semantic"
            )
            for e, score in similarity_scores
        ]

        return candidates

    @staticmethod
    def _normalize_statement(statement: str) -> str:
        """Normalize statement for deterministic comparison."""
        # Remove extra whitespace, lowercase, remove trailing punctuation
        normalized = re.sub(r'\s+', ' ', statement).strip().lower()
        normalized = re.sub(r'[^\w\s]', '', normalized).strip()
        return normalized

    @staticmethod
    def _semantic_similarity(text1: str, text2: str) -> float:
        """
        Compute semantic similarity using word overlap heuristic.

        Returns 0.0–1.0 score.
        In production, would use embeddings or LLM similarity.
        """
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())

        if not words1 or not words2:
            return 0.0

        # Jaccard similarity
        intersection = len(words1 & words2)
        union = len(words1 | words2)
        return intersection / union if union > 0 else 0.0

    # ========================================================================
    # CONTRADICTION DETECTION
    # ========================================================================

    def detect_contradictions(
        self,
        new_statement: str,
        existing_evidence: Optional[List[Dict[str, Any]]] = None
    ) -> List[Contradiction]:
        """
        Detect contradictions between new statement and existing evidence.

        Returns list of detected contradictions (or empty if none).
        """
        if existing_evidence is None:
            existing_evidence = self.list_evidence()

        contradictions = []

        # Heuristic: look for common field patterns that might contradict
        # (In production, would be more sophisticated)

        for evidence in existing_evidence:
            # Check geographic scope
            contradiction = self._check_geographic_contradiction(new_statement, evidence)
            if contradiction:
                contradictions.append(contradiction)

            # Check role/title consistency
            contradiction = self._check_role_contradiction(new_statement, evidence)
            if contradiction:
                contradictions.append(contradiction)

        return contradictions

    @staticmethod
    def _check_geographic_contradiction(
        new_statement: str,
        existing_evidence: Dict[str, Any]
    ) -> Optional[Contradiction]:
        """Check for geographic scope contradiction."""
        new_lower = new_statement.lower()
        existing_lower = existing_evidence["statement"].lower()

        # Heuristic: detect geographic scope differences
        singapore_in_new = "singapore" in new_lower
        singapore_in_existing = "singapore" in existing_lower
        apac_in_new = "apac" in new_lower or "southeast asia" in new_lower
        apac_in_existing = "apac" in existing_lower or "southeast asia" in existing_lower

        # If one says "Singapore only" and the other says "APAC", that's a contradiction
        if singapore_in_existing and not apac_in_existing:
            if apac_in_new and not singapore_in_new:
                return Contradiction(
                    evidence_id_1=existing_evidence["evidence_id"],
                    evidence_id_2="<new>",
                    field="geographic_scope",
                    value_1="Singapore",
                    value_2="APAC",
                    severity="high",
                    description="Geographic scope differs: existing says Singapore, new says APAC",
                    requires_user_action=True
                )

        return None

    @staticmethod
    def _check_role_contradiction(
        new_statement: str,
        existing_evidence: Dict[str, Any]
    ) -> Optional[Contradiction]:
        """Check for role/title contradiction."""
        # Placeholder for role contradiction detection
        # (Would be more sophisticated in production)
        return None

    def resolve_contradiction(
        self,
        evidence_id_old: str,
        evidence_id_new: str,
        resolution: str  # "keep_old", "use_new", "merge"
    ) -> bool:
        """
        Resolve contradiction by user decision.

        - keep_old: marks new as duplicate/related, keeps old
        - use_new: marks old as superseded by new
        - merge: would create merged evidence (Gate 4 doesn't implement this)
        """
        if resolution == "keep_old":
            # Mark new as related to old
            self.repo.update_evidence(evidence_id_new, {
                "related_to": [evidence_id_old],
                "notes": "Duplicate/related to existing evidence"
            })
            logger.info(f"Resolved: kept {evidence_id_old}, marked {evidence_id_new} as related")
            return True

        elif resolution == "use_new":
            # Mark old as superseded by new
            return self.supersede_evidence(evidence_id_old, evidence_id_new)

        elif resolution == "merge":
            logger.warning("Merge resolution not yet implemented")
            return False

        return False

    # ========================================================================
    # EVIDENCE QUERYING
    # ========================================================================

    def query_evidence(
        self,
        competencies: Optional[List[str]] = None,
        technologies: Optional[List[str]] = None,
        industries: Optional[List[str]] = None,
        geographies: Optional[List[str]] = None,
        source_types: Optional[List[str]] = None,
        min_confidence: Optional[str] = None,
        verification_required: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Query evidence with multiple filters.

        Competencies/technologies/industries/geographies use OR logic within each field,
        AND logic between fields.

        Example:
            query_evidence(
                competencies=["Enterprise Sales", "AI"],  # OR
                industries=["SaaS"],                       # AND
                geographies=["Singapore"]                  # AND
            )
            → evidence with (Enterprise Sales OR AI) AND SaaS AND Singapore
        """
        all_evidence = self.list_evidence()
        results = []

        for evidence in all_evidence:
            # Check verification requirement
            if verification_required and not evidence.get("user_confirmed"):
                continue

            # Check confidence level
            if min_confidence:
                if not self._meets_confidence(evidence["confidence"], min_confidence):
                    continue

            # Check source types
            if source_types and evidence["source_type"] not in source_types:
                continue

            # Check competencies (OR logic)
            if competencies:
                if not any(c in evidence.get("competencies", []) for c in competencies):
                    continue

            # Check technologies (OR logic)
            if technologies:
                if not any(t in evidence.get("technologies", []) for t in technologies):
                    continue

            # Check industries (OR logic)
            if industries:
                if not any(i in evidence.get("industries", []) for i in industries):
                    continue

            # Check geographies (OR logic)
            if geographies:
                if not any(g in evidence.get("geographies", []) for g in geographies):
                    continue

            results.append(evidence)

        return results

    @staticmethod
    def _meets_confidence(evidence_confidence: str, min_confidence: str) -> bool:
        """Check if evidence meets minimum confidence level."""
        confidence_order = {"LEVEL_D": 0, "LEVEL_C": 1, "LEVEL_B": 2, "LEVEL_A": 3}
        return confidence_order.get(evidence_confidence, 0) >= confidence_order.get(min_confidence, 0)

    def get_evidence_for_application(
        self,
        application_id: str
    ) -> List[Dict[str, Any]]:
        """Get all evidence associated with an application."""
        return self.query_evidence(
            filters={"application_origin.application_id": application_id}
        )

    # ========================================================================
    # PROVENANCE & AUDIT
    # ========================================================================

    def get_evidence_provenance(self, evidence_id: str) -> Optional[Dict[str, Any]]:
        """
        Get full provenance chain for evidence.

        Returns: {
            fact: current evidence,
            source: where it came from,
            history: supersedes/superseded_by chain
        }
        """
        evidence = self.get_evidence(evidence_id)
        if not evidence:
            return None

        # Build provenance chain
        chain = {"current": evidence, "history": []}

        # Follow supersedes chain backward
        current = evidence
        while current.get("supersedes"):
            for old_id in current["supersedes"]:
                old = self.get_evidence(old_id)
                if old:
                    chain["history"].insert(0, {
                        "evidence_id": old_id,
                        "statement": old["statement"],
                        "status": "superseded",
                        "at": old.get("last_modified_at")
                    })
                    current = old
                    break

        # Follow superseded_by chain forward
        current = evidence
        while current.get("superseded_by"):
            for new_id in current["superseded_by"]:
                new = self.get_evidence(new_id)
                if new:
                    chain["history"].append({
                        "evidence_id": new_id,
                        "statement": new["statement"],
                        "status": "current",
                        "at": new.get("created_at")
                    })
                    current = new
                    break

        return {
            "fact": {
                "statement": evidence["statement"],
                "confidence": evidence["confidence"],
                "source_type": evidence["source_type"],
                "source_reference": evidence["source_reference"],
                "source_date": evidence["source_date"]
            },
            "verification": {
                "status": evidence["verification_status"],
                "user_confirmed": evidence["user_confirmed"],
                "first_captured": evidence["first_captured_at"],
                "last_confirmed": evidence["last_confirmed_at"]
            },
            "metrics": evidence.get("metrics", {}),
            "provenance_chain": chain
        }


# ============================================================================
# EVIDENCE VALIDATION
# ============================================================================

class EvidenceValidator:
    """Validates evidence for correctness and consistency."""

    @staticmethod
    def validate_cv_evidence_fidelity(cv_adapted_text: str, evidence_confidence: str) -> bool:
        """
        Validate that CV wording doesn't exceed evidence confidence.

        LEVEL_A/B: can use strong language ("expertise", "led", "built")
        LEVEL_C: must qualify ("exposure to", "experience with", "familiar with")
        LEVEL_D: cannot be used in CV

        Returns True if valid, False if fabrication detected.
        """
        strong_words = ["expertise", "expert", "led", "built", "designed", "architected",
                       "created", "invented", "pioneered", "groundbreaking"]
        qualifier_words = ["exposure", "experience", "familiar", "worked", "contributed"]

        cv_lower = cv_adapted_text.lower()

        if evidence_confidence == "LEVEL_D":
            return False  # Can never use LEVEL_D

        if evidence_confidence == "LEVEL_C":
            # Must be qualified
            if any(word in cv_lower for word in strong_words):
                return False
            return any(word in cv_lower for word in qualifier_words)

        # LEVEL_A/B can use strong language
        return True


# ============================================================================
# INTEGRATION
# ============================================================================

def create_evidence_service(data_dir: str = ".") -> EvidenceService:
    """Factory function to create evidence service with persistence."""
    repo = EvidenceRepository(data_dir)
    return EvidenceService(repo)
