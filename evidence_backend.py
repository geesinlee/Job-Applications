"""EvidenceBackend abstraction layer for evidence persistence.

Provides abstract interface and PostgreSQL implementation for storing and
querying structured evidence extracted from CVs.
"""

from abc import ABC, abstractmethod
from typing import Optional, List
from datetime import datetime
import json

from evidence_models import StructuredEvidence

# psycopg2 is optional — only required when using PostgresEvidenceBackend with DATABASE_URL
try:
    import psycopg2
    import psycopg2.extras
    from psycopg2.extensions import connection as psycopg2_connection
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False
    psycopg2 = None
    psycopg2_connection = None


class EvidenceBackend(ABC):
    """Abstract base class for evidence persistence backends.

    Defines the interface for saving and querying evidence.
    Future implementations could include: SQLite, MySQL, Elasticsearch, Firestore, etc.
    """

    @abstractmethod
    def save_evidence(self, evidence: StructuredEvidence) -> str:
        """Save evidence and return its ID.

        Args:
            evidence: StructuredEvidence instance to persist.

        Returns:
            ID of the saved evidence.
        """
        pass

    @abstractmethod
    def get_evidence_by_id(self, evidence_id: str) -> Optional[StructuredEvidence]:
        """Retrieve evidence by ID.

        Args:
            evidence_id: ID of the evidence to retrieve.

        Returns:
            StructuredEvidence if found, None otherwise.
        """
        pass

    @abstractmethod
    def get_evidence_by_cv_id(self, cv_id: str) -> List[StructuredEvidence]:
        """Retrieve all evidence for a specific CV.

        Args:
            cv_id: ID of the source CVRecord.

        Returns:
            List of StructuredEvidence instances for this CV.
        """
        pass

    @abstractmethod
    def query_by_skills(self, skills: List[str]) -> List[StructuredEvidence]:
        """Query evidence matching specific skills.

        Args:
            skills: List of skills to match.

        Returns:
            List of evidence containing ANY of the specified skills.
        """
        pass

    @abstractmethod
    def query_by_company(self, company_name: str) -> List[StructuredEvidence]:
        """Query evidence by company name.

        Args:
            company_name: Company name to search for.

        Returns:
            List of evidence from that company.
        """
        pass

    @abstractmethod
    def query_by_timeframe(self, start: datetime, end: datetime) -> List[StructuredEvidence]:
        """Query evidence by time period.

        Args:
            start: Start of time period.
            end: End of time period.

        Returns:
            List of evidence with overlapping time periods.
        """
        pass


class PostgresEvidenceBackend(EvidenceBackend):
    """PostgreSQL implementation of EvidenceBackend.

    Uses psycopg2 to connect to NAS Postgres database.
    Assumes StructuredEvidence table exists in the schema.
    """

    def __init__(self, database_url: str):
        """Initialize Postgres backend.

        Args:
            database_url: PostgreSQL connection string (e.g., postgresql://user:pass@host/db).

        Raises:
            ImportError: If psycopg2 is not installed.
            psycopg2.Error: If connection fails.
        """
        if not HAS_PSYCOPG2:
            raise ImportError("psycopg2 is required to use PostgresEvidenceBackend. Install it with: pip install psycopg2-binary")

        self.database_url = database_url
        self.connection = None

        try:
            self.connection = psycopg2.connect(database_url)
            self.connection.autocommit = True
        except psycopg2.Error as e:
            raise Exception(f"Failed to connect to database: {e}")

    def close(self) -> None:
        """Close database connection."""
        if self.connection:
            self.connection.close()
            self.connection = None

    def save_evidence(self, evidence: StructuredEvidence) -> str:
        """Save evidence to Postgres and return its ID.

        Args:
            evidence: StructuredEvidence instance to persist.

        Returns:
            ID of the saved evidence.
        """
        if not self.connection:
            raise RuntimeError("Database connection is closed")

        cursor = self.connection.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO structured_evidence
                (achievement, context, impact, skills_demonstrated, job_title, company_name,
                 time_period_start, time_period_end, source_section, source_cv_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    evidence.achievement,
                    evidence.context,
                    evidence.impact,
                    json.dumps(evidence.skills_demonstrated),
                    evidence.job_title,
                    evidence.company_name,
                    evidence.time_period_start,
                    evidence.time_period_end,
                    evidence.source_section,
                    evidence.source_cv_id
                )
            )
            result = cursor.fetchone()
            return str(result[0]) if result else None
        finally:
            cursor.close()

    def get_evidence_by_id(self, evidence_id: str) -> Optional[StructuredEvidence]:
        """Retrieve evidence by ID from Postgres.

        Args:
            evidence_id: ID of the evidence to retrieve.

        Returns:
            StructuredEvidence if found, None otherwise.
        """
        if not self.connection:
            raise RuntimeError("Database connection is closed")

        cursor = self.connection.cursor(cursor_factory=psycopg2.extras.DictCursor)
        try:
            cursor.execute(
                "SELECT * FROM structured_evidence WHERE id = %s",
                (evidence_id,)
            )
            row = cursor.fetchone()
            return self._row_to_evidence(row, "get_evidence_by_id") if row else None
        finally:
            cursor.close()

    def get_evidence_by_cv_id(self, cv_id: str) -> List[StructuredEvidence]:
        """Retrieve all evidence for a specific CV from Postgres.

        Args:
            cv_id: ID of the source CVRecord.

        Returns:
            List of StructuredEvidence instances for this CV.
        """
        if not self.connection:
            raise RuntimeError("Database connection is closed")

        cursor = self.connection.cursor(cursor_factory=psycopg2.extras.DictCursor)
        try:
            cursor.execute(
                "SELECT * FROM structured_evidence WHERE source_cv_id = %s",
                (cv_id,)
            )
            rows = cursor.fetchall()
            return [self._row_to_evidence(row, "get_evidence_by_cv_id") for row in rows]
        finally:
            cursor.close()

    def query_by_skills(self, skills: List[str]) -> List[StructuredEvidence]:
        """Query evidence matching any of the specified skills from Postgres.

        Uses Postgres array operators: && for array overlap.

        Args:
            skills: List of skills to match.

        Returns:
            List of evidence containing ANY of the specified skills.
        """
        if not self.connection:
            raise RuntimeError("Database connection is closed")

        cursor = self.connection.cursor(cursor_factory=psycopg2.extras.DictCursor)
        try:
            cursor.execute(
                "SELECT * FROM structured_evidence WHERE skills_demonstrated && %s",
                (skills,)
            )
            rows = cursor.fetchall()
            return [self._row_to_evidence(row, "query_by_skills") for row in rows]
        finally:
            cursor.close()

    def query_by_company(self, company_name: str) -> List[StructuredEvidence]:
        """Query evidence by company name from Postgres.

        Args:
            company_name: Company name to search for.

        Returns:
            List of evidence from that company.
        """
        if not self.connection:
            raise RuntimeError("Database connection is closed")

        cursor = self.connection.cursor(cursor_factory=psycopg2.extras.DictCursor)
        try:
            cursor.execute(
                "SELECT * FROM structured_evidence WHERE company_name = %s",
                (company_name,)
            )
            rows = cursor.fetchall()
            return [self._row_to_evidence(row, "query_by_company") for row in rows]
        finally:
            cursor.close()

    def query_by_timeframe(self, start: datetime, end: datetime) -> List[StructuredEvidence]:
        """Query evidence by time period from Postgres.

        Finds evidence with overlapping time periods (start <= evidence.end AND end >= evidence.start).

        Args:
            start: Start of time period.
            end: End of time period.

        Returns:
            List of evidence with overlapping time periods.
        """
        if not self.connection:
            raise RuntimeError("Database connection is closed")

        cursor = self.connection.cursor(cursor_factory=psycopg2.extras.DictCursor)
        try:
            cursor.execute(
                """
                SELECT * FROM structured_evidence
                WHERE (time_period_start IS NULL OR time_period_start <= %s)
                  AND (time_period_end IS NULL OR time_period_end >= %s)
                """,
                (end, start)
            )
            rows = cursor.fetchall()
            return [self._row_to_evidence(row, "query_by_timeframe") for row in rows]
        finally:
            cursor.close()

    def _row_to_evidence(self, row, description: str) -> StructuredEvidence:
        """Helper to convert Postgres row to StructuredEvidence.

        Args:
            row: psycopg2 DictRow from database query.
            description: Operation description for error messages.

        Returns:
            StructuredEvidence instance populated from row.

        Raises:
            ValueError: If row data is malformed.
        """
        try:
            # Parse skills_demonstrated from JSON array stored in Postgres
            skills = json.loads(row['skills_demonstrated']) if isinstance(row['skills_demonstrated'], str) else row['skills_demonstrated']

            return StructuredEvidence(
                id=str(row['id']),
                achievement=row['achievement'],
                context=row['context'],
                impact=row['impact'],
                skills_demonstrated=skills,
                job_title=row['job_title'],
                company_name=row['company_name'],
                time_period_start=row['time_period_start'],
                time_period_end=row['time_period_end'],
                source_section=row['source_section'],
                source_cv_id=row['source_cv_id']
            )
        except (KeyError, ValueError, json.JSONDecodeError) as e:
            raise ValueError(f"Failed to convert row to StructuredEvidence in {description}: {e}")
