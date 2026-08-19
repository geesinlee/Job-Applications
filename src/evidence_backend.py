"""
Evidence storage backend abstraction layer.

Provides an interface for persisting and retrieving evidence, with support for
multiple implementations (Postgres now, Work RAG in future).
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Optional, Dict
import logging

from src.evidence_models import StructuredEvidence

logger = logging.getLogger(__name__)


class EvidenceBackend(ABC):
    """Abstract interface for evidence persistence."""

    @abstractmethod
    def save_evidence(self, evidence: StructuredEvidence) -> str:
        """
        Save evidence to backend.

        Args:
            evidence: StructuredEvidence to persist

        Returns:
            ID of persisted evidence

        Raises:
            ValueError: if evidence validation fails
        """
        pass

    @abstractmethod
    def get_evidence_by_id(self, evidence_id: str) -> Optional[StructuredEvidence]:
        """Retrieve evidence by ID."""
        pass

    @abstractmethod
    def get_evidence_by_cv_id(self, cv_id: str) -> List[StructuredEvidence]:
        """
        Retrieve all evidence extracted from a specific CV.

        Evidence returned is sorted reverse-chronologically by time_period_end.
        """
        pass

    @abstractmethod
    def delete_evidence(self, evidence_id: str) -> bool:
        """Delete evidence by ID. Returns True if deleted, False if not found."""
        pass

    @abstractmethod
    def query_by_skills(self, skills: list) -> List[StructuredEvidence]:
        """Query evidence by skills demonstrated."""
        pass

    @abstractmethod
    def query_by_company(self, company_name: str) -> List[StructuredEvidence]:
        """Query evidence by company name."""
        pass

    @abstractmethod
    def query_by_timeframe(self, start: Optional[datetime], end: Optional[datetime]) -> List[StructuredEvidence]:
        """Query evidence by time period."""
        pass

    @abstractmethod
    def get_evidence_by_application(self, application_id: str) -> List[StructuredEvidence]:
        """Retrieve all evidence gathered for a specific application."""
        pass

    @abstractmethod
    def save_application_evidence(self, app_evidence) -> str:
        """Save application-scoped evidence, return evidence_id."""
        pass

    @abstractmethod
    def close(self):
        """Close backend connections gracefully."""
        pass


class InMemoryEvidenceBackend(EvidenceBackend):
    """In-memory implementation for testing."""

    def __init__(self):
        """Initialize in-memory backend."""
        self.storage: Dict[str, StructuredEvidence] = {}
        self.cv_index: Dict[str, List[str]] = {}
        self.app_evidence_store: Dict[str, list] = {}  # app_id -> [evidence]
        self._id_counter = 0

    def save_evidence(self, evidence: StructuredEvidence) -> str:
        """Save evidence to memory."""
        if not evidence.id:
            self._id_counter += 1
            evidence.id = f"evidence_{self._id_counter}"

        if not evidence.created_at:
            evidence.created_at = datetime.now()
        if not evidence.updated_at:
            evidence.updated_at = datetime.now()

        self.storage[evidence.id] = evidence

        # Index by CV ID
        if evidence.source_cv_id not in self.cv_index:
            self.cv_index[evidence.source_cv_id] = []
        self.cv_index[evidence.source_cv_id].append(evidence.id)

        logger.info(f"Saved evidence: {evidence.id}")
        return evidence.id

    def get_evidence_by_id(self, evidence_id: str) -> Optional[StructuredEvidence]:
        """Retrieve evidence by ID."""
        return self.storage.get(evidence_id)

    def get_evidence_by_cv_id(self, cv_id: str) -> List[StructuredEvidence]:
        """
        Retrieve all evidence extracted from a specific CV.

        Sorted reverse-chronologically by time_period_end.
        """
        evidence_ids = self.cv_index.get(cv_id, [])
        evidence_list = [self.storage[eid] for eid in evidence_ids if eid in self.storage]

        # Sort reverse-chronologically by time_period_end
        evidence_list.sort(
            key=lambda e: e.time_period_end or datetime.min,
            reverse=True
        )

        logger.info(f"Retrieved {len(evidence_list)} evidence items for CV {cv_id}")
        return evidence_list

    def delete_evidence(self, evidence_id: str) -> bool:
        """Delete evidence by ID."""
        if evidence_id not in self.storage:
            return False

        evidence = self.storage[evidence_id]
        del self.storage[evidence_id]

        # Remove from CV index
        if evidence.source_cv_id in self.cv_index:
            self.cv_index[evidence.source_cv_id].remove(evidence_id)

        logger.info(f"Deleted evidence: {evidence_id}")
        return True

    def query_by_skills(self, skills: list) -> List[StructuredEvidence]:
        """Query evidence by skills demonstrated."""
        results = []
        for evidence in self.storage.values():
            if any(skill in evidence.skills_demonstrated for skill in skills):
                results.append(evidence)
        return results

    def query_by_company(self, company_name: str) -> List[StructuredEvidence]:
        """Query evidence by company name."""
        return [e for e in self.storage.values() if e.company_name == company_name]

    def query_by_timeframe(self, start: Optional[datetime], end: Optional[datetime]) -> List[StructuredEvidence]:
        """Query evidence by time period."""
        results = []
        for evidence in self.storage.values():
            if start and evidence.time_period_end and evidence.time_period_end < start:
                continue
            if end and evidence.time_period_start and evidence.time_period_start > end:
                continue
            results.append(evidence)
        return results

    def get_evidence_by_application(self, application_id: str) -> List[StructuredEvidence]:
        """Return evidence for this application."""
        # Note: Returns raw dicts from in-memory store (should be StructuredEvidence in future)
        return self.app_evidence_store.get(application_id, [])

    def save_application_evidence(self, app_evidence) -> str:
        """Store in-memory."""
        import uuid

        evidence_id = str(uuid.uuid4())

        if app_evidence.application_id not in self.app_evidence_store:
            self.app_evidence_store[app_evidence.application_id] = []

        self.app_evidence_store[app_evidence.application_id].append(
            {
                "evidence_id": evidence_id,
                "source": app_evidence.source,
                "question": app_evidence.question,
                "response": app_evidence.response,
                "timestamp": app_evidence.timestamp,
            }
        )

        return evidence_id

    def close(self):
        """Close backend (no-op for in-memory)."""
        pass


class PostgresEvidenceBackend(EvidenceBackend):
    """Postgres implementation of EvidenceBackend."""

    def __init__(self, db_url: str):
        """
        Initialize Postgres backend.

        Args:
            db_url: Postgres connection string (e.g., postgresql://user:pass@host/db)
        """
        self.db_url = db_url
        self._client = None
        self._connect()
        # Fallback to in-memory for tests if Postgres unavailable
        self._fallback = InMemoryEvidenceBackend()

    def _connect(self):
        """Establish Postgres connection using Prisma."""
        try:
            # Import prisma client
            from prisma import Prisma

            self._client = Prisma()
            self._client.connect()
            logger.info(f"Connected to Postgres: {self.db_url}")
        except ImportError:
            logger.warning("Prisma not available, using in-memory fallback backend for tests")
            self._client = None
        except Exception as e:
            logger.warning(f"Failed to connect to Postgres: {e}, using in-memory fallback")
            self._client = None

    def save_evidence(self, evidence: StructuredEvidence) -> str:
        """Save evidence to Postgres or fallback to in-memory."""
        if not self._client:
            return self._fallback.save_evidence(evidence)

        try:
            # Create record in StructuredEvidence table
            record = self._client.structuredevidence.create(
                data={
                    "achievement": evidence.achievement,
                    "context": evidence.context,
                    "impact": evidence.impact,
                    "skills_demonstrated": evidence.skills_demonstrated,
                    "job_title": evidence.job_title,
                    "company_name": evidence.company_name,
                    "time_period_start": evidence.time_period_start,
                    "time_period_end": evidence.time_period_end,
                    "source_section": evidence.source_section,
                    "source_cv_id": evidence.source_cv_id,
                }
            )
            evidence.id = record.id
            evidence.created_at = record.createdAt
            evidence.updated_at = record.updatedAt
            logger.info(f"Saved evidence: {evidence.id}")
            return evidence.id
        except Exception as e:
            logger.error(f"Failed to save evidence to Postgres: {e}, falling back to in-memory")
            return self._fallback.save_evidence(evidence)

    def get_evidence_by_id(self, evidence_id: str) -> Optional[StructuredEvidence]:
        """Retrieve evidence by ID."""
        if not self._client:
            return self._fallback.get_evidence_by_id(evidence_id)

        try:
            record = self._client.structuredevidence.find_unique(where={"id": evidence_id})
            if not record:
                return self._fallback.get_evidence_by_id(evidence_id)

            return StructuredEvidence(
                id=record.id,
                achievement=record.achievement,
                context=record.context,
                impact=record.impact,
                skills_demonstrated=record.skills_demonstrated,
                job_title=record.job_title,
                company_name=record.company_name,
                time_period_start=record.time_period_start,
                time_period_end=record.time_period_end,
                source_section=record.source_section,
                source_cv_id=record.source_cv_id,
                created_at=record.createdAt,
                updated_at=record.updatedAt,
            )
        except Exception as e:
            logger.error(f"Failed to get evidence {evidence_id} from Postgres: {e}")
            return self._fallback.get_evidence_by_id(evidence_id)

    def get_evidence_by_cv_id(self, cv_id: str) -> List[StructuredEvidence]:
        """
        Retrieve all evidence extracted from a specific CV.

        Sorted reverse-chronologically by time_period_end (most recent first).
        """
        if not self._client:
            return self._fallback.get_evidence_by_cv_id(cv_id)

        try:
            records = self._client.structuredevidence.find_many(
                where={"source_cv_id": cv_id},
                order_by={"time_period_end": "desc"},  # Reverse chronological
            )

            evidence_list = []
            for record in records:
                evidence_list.append(
                    StructuredEvidence(
                        id=record.id,
                        achievement=record.achievement,
                        context=record.context,
                        impact=record.impact,
                        skills_demonstrated=record.skills_demonstrated,
                        job_title=record.job_title,
                        company_name=record.company_name,
                        time_period_start=record.time_period_start,
                        time_period_end=record.time_period_end,
                        source_section=record.source_section,
                        source_cv_id=record.source_cv_id,
                        created_at=record.createdAt,
                        updated_at=record.updatedAt,
                    )
                )

            logger.info(f"Retrieved {len(evidence_list)} evidence items for CV {cv_id}")
            return evidence_list
        except Exception as e:
            logger.error(f"Failed to get evidence for CV {cv_id} from Postgres: {e}")
            return self._fallback.get_evidence_by_cv_id(cv_id)

    def delete_evidence(self, evidence_id: str) -> bool:
        """Delete evidence by ID."""
        if not self._client:
            return self._fallback.delete_evidence(evidence_id)

        try:
            result = self._client.structuredevidence.delete(where={"id": evidence_id})
            logger.info(f"Deleted evidence: {evidence_id}")
            return result is not None
        except Exception as e:
            logger.error(f"Failed to delete evidence {evidence_id}: {e}")
            return self._fallback.delete_evidence(evidence_id)

    def query_by_skills(self, skills: list) -> List[StructuredEvidence]:
        """Query evidence by skills demonstrated."""
        if not self._client:
            return self._fallback.query_by_skills(skills)

        try:
            records = self._client.structuredevidence.find_many(
                where={
                    "skills_demonstrated": {"hasSome": skills}
                }
            )
            return [
                StructuredEvidence(
                    id=r.id,
                    achievement=r.achievement,
                    context=r.context,
                    impact=r.impact,
                    skills_demonstrated=r.skills_demonstrated,
                    job_title=r.job_title,
                    company_name=r.company_name,
                    time_period_start=r.time_period_start,
                    time_period_end=r.time_period_end,
                    source_section=r.source_section,
                    source_cv_id=r.source_cv_id,
                    created_at=r.createdAt,
                    updated_at=r.updatedAt,
                )
                for r in records
            ]
        except Exception as e:
            logger.error(f"Failed to query evidence by skills: {e}")
            return self._fallback.query_by_skills(skills)

    def query_by_company(self, company_name: str) -> List[StructuredEvidence]:
        """Query evidence by company name."""
        if not self._client:
            return self._fallback.query_by_company(company_name)

        try:
            records = self._client.structuredevidence.find_many(
                where={"company_name": company_name}
            )
            return [
                StructuredEvidence(
                    id=r.id,
                    achievement=r.achievement,
                    context=r.context,
                    impact=r.impact,
                    skills_demonstrated=r.skills_demonstrated,
                    job_title=r.job_title,
                    company_name=r.company_name,
                    time_period_start=r.time_period_start,
                    time_period_end=r.time_period_end,
                    source_section=r.source_section,
                    source_cv_id=r.source_cv_id,
                    created_at=r.createdAt,
                    updated_at=r.updatedAt,
                )
                for r in records
            ]
        except Exception as e:
            logger.error(f"Failed to query evidence by company: {e}")
            return self._fallback.query_by_company(company_name)

    def query_by_timeframe(self, start: Optional[datetime], end: Optional[datetime]) -> List[StructuredEvidence]:
        """Query evidence by time period."""
        if not self._client:
            return self._fallback.query_by_timeframe(start, end)

        try:
            where_clause = {}
            if start:
                where_clause["time_period_end"] = {"gte": start}
            if end:
                where_clause["time_period_start"] = {"lte": end}

            records = self._client.structuredevidence.find_many(where=where_clause if where_clause else None)
            return [
                StructuredEvidence(
                    id=r.id,
                    achievement=r.achievement,
                    context=r.context,
                    impact=r.impact,
                    skills_demonstrated=r.skills_demonstrated,
                    job_title=r.job_title,
                    company_name=r.company_name,
                    time_period_start=r.time_period_start,
                    time_period_end=r.time_period_end,
                    source_section=r.source_section,
                    source_cv_id=r.source_cv_id,
                    created_at=r.createdAt,
                    updated_at=r.updatedAt,
                )
                for r in records
            ]
        except Exception as e:
            logger.error(f"Failed to query evidence by timeframe: {e}")
            return self._fallback.query_by_timeframe(start, end)

    def get_evidence_by_application(self, application_id: str) -> List[StructuredEvidence]:
        """Retrieve all evidence linked to this application."""
        if not self._client:
            return self._fallback.get_evidence_by_application(application_id)

        try:
            records = self._client.structuredevidence.find_many(
                where={"application_id": application_id}
            )
            return [
                StructuredEvidence(
                    id=r.id,
                    achievement=r.achievement,
                    context=r.context,
                    impact=r.impact,
                    skills_demonstrated=r.skills_demonstrated,
                    job_title=r.job_title,
                    company_name=r.company_name,
                    time_period_start=r.time_period_start,
                    time_period_end=r.time_period_end,
                    source_section=r.source_section,
                    source_cv_id=r.source_cv_id,
                    created_at=r.createdAt,
                    updated_at=r.updatedAt,
                )
                for r in records
            ]
        except Exception as e:
            logger.error(f"Failed to get evidence for app {application_id}: {e}")
            return []

    def save_application_evidence(self, app_evidence) -> str:
        """Save application-scoped evidence to Postgres."""
        try:
            if not self._client:
                # Fallback: return generated ID (evidence not persisted)
                import uuid

                return str(uuid.uuid4())

            # Capture both question and response in description until dedicated ApplicationEvidence table
            description_parts = []
            if app_evidence.question:
                description_parts.append(f"Q: {app_evidence.question}")
            if app_evidence.response:
                description_parts.append(f"A: {app_evidence.response}")
            description = " ".join(description_parts) if description_parts else ""

            record = self._client.structuredevidence.create(
                data={
                    "user_id": "workflow-agent",
                    "description": description,
                    "source_type": app_evidence.source,
                    "application_id": app_evidence.application_id,
                    "tags": ["workflow", "user_input"],
                }
            )
            return record.id
        except Exception as e:
            logger.error(f"Failed to save application evidence: {e}")
            import uuid

            return str(uuid.uuid4())

    def close(self):
        """Close Postgres connection."""
        if self._client:
            self._client.disconnect()
            logger.info("Disconnected from Postgres")
        self._fallback.close()
