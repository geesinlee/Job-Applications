"""Database persistence layer for CV versioning.

Provides abstraction for load/save operations.
Currently supports JSON (Gate 7) with Postgres (Gate 8) migration path.
"""

from typing import Dict, Optional
from cv_versioning_service import CVRecord, CVEvidenceUsage, CVStatus, _load_cv_records, _save_cv_records
from pathlib import Path
import os
import json


class DatabaseBackend:
    """Abstract database backend for CV records."""

    def load_cv_records(self) -> Dict[str, CVRecord]:
        """Load all CV records."""
        raise NotImplementedError()

    def save_cv_records(self, records: Dict[str, CVRecord]) -> None:
        """Save CV records."""
        raise NotImplementedError()


class FileBackend(DatabaseBackend):
    """File-based backend using JSON (Gate 7)."""

    def __init__(self, filepath: Path):
        """Initialize file backend.

        Args:
            filepath: Path to cv_records.json
        """
        self.filepath = filepath

    def load_cv_records(self) -> Dict[str, CVRecord]:
        """Load CV records from JSON file."""
        return _load_cv_records(self.filepath)

    def save_cv_records(self, records: Dict[str, CVRecord]) -> None:
        """Save CV records to JSON file."""
        _save_cv_records(records, self.filepath)


class PostgresBackend(DatabaseBackend):
    """PostgreSQL backend using Prisma ORM (Gate 8)."""

    def __init__(self, database_url: Optional[str] = None):
        """Initialize Postgres backend.

        Args:
            database_url: PostgreSQL connection string. Defaults to DATABASE_URL env var.

        Raises:
            ValueError: If database_url not provided and DATABASE_URL env var not set.
        """
        self.database_url = database_url or os.environ.get("DATABASE_URL")
        if not self.database_url:
            raise ValueError(
                "database_url must be provided or DATABASE_URL env var must be set"
            )
        # Prisma client initialization will be done when connected
        self.prisma = None

    def load_cv_records(self) -> Dict[str, CVRecord]:
        """Load all CV records from Postgres.

        Returns:
            Dictionary of cv_id -> CVRecord
        """
        if not self.prisma:
            raise RuntimeError("Not connected to database")

        records_dict = {}

        try:
            # Query all CVRecords with their related CVEvidenceUsage
            db_records = self.prisma.cvrecord.find_many(include={"evidence": True})

            for db_record in db_records:
                # Convert evidence list
                evidence_list = [
                    CVEvidenceUsage(
                        evidence_id=e.evidence_id,
                        requirement_id=e.requirement_id,
                        content_excerpt=e.content_excerpt,
                        placement_section=e.placement_section,
                    )
                    for e in db_record.evidence
                ]

                # Convert status enum
                status = CVStatus(db_record.status)

                # Create CVRecord
                record = CVRecord(
                    cv_id=db_record.cv_id,
                    application_id=db_record.application_id,
                    version=db_record.version,
                    status=status,
                    content=db_record.content,
                    evidence_used=evidence_list,
                    created_at=db_record.created_at.isoformat() + "Z",
                    approved_by=db_record.approved_by,
                    approved_at=db_record.approved_at.isoformat() + "Z"
                    if db_record.approved_at
                    else None,
                    finalized_at=db_record.finalized_at.isoformat() + "Z"
                    if db_record.finalized_at
                    else None,
                )
                records_dict[record.cv_id] = record

        except Exception as e:
            raise RuntimeError(f"Failed to load CV records from database: {e}")

        return records_dict

    def save_cv_records(self, records: Dict[str, CVRecord]) -> None:
        """Save CV records to Postgres.

        Args:
            records: Dictionary of cv_id -> CVRecord
        """
        if not self.prisma:
            raise RuntimeError("Not connected to database")

        try:
            for record in records.values():
                # First, ensure application exists
                self.prisma.application.upsert(
                    where={"name": record.application_id},
                    data={
                        "create": {"name": record.application_id},
                        "update": {},
                    },
                )

                # Parse timestamps
                approved_at = None
                if record.approved_at:
                    approved_at_str = record.approved_at.rstrip("Z")
                    approved_at = approved_at_str

                finalized_at = None
                if record.finalized_at:
                    finalized_at_str = record.finalized_at.rstrip("Z")
                    finalized_at = finalized_at_str

                # Upsert CVRecord
                self.prisma.cvrecord.upsert(
                    where={"cv_id": record.cv_id},
                    data={
                        "create": {
                            "cv_id": record.cv_id,
                            "application_id": record.application_id,
                            "version": record.version,
                            "status": record.status.value,
                            "content": record.content,
                            "approved_by": record.approved_by,
                            "approved_at": approved_at,
                            "finalized_at": finalized_at,
                        },
                        "update": {
                            "status": record.status.value,
                            "content": record.content,
                            "approved_by": record.approved_by,
                            "approved_at": approved_at,
                            "finalized_at": finalized_at,
                        },
                    },
                )

                # Delete existing evidence and recreate
                self.prisma.cvevidenceusage.delete_many(
                    where={"cv_record_id": record.cv_id}
                )

                # Insert evidence
                for evidence in record.evidence_used:
                    self.prisma.cvevidenceusage.create(
                        data={
                            "cv_record_id": record.cv_id,
                            "evidence_id": evidence.evidence_id,
                            "requirement_id": evidence.requirement_id,
                            "content_excerpt": evidence.content_excerpt,
                            "placement_section": evidence.placement_section,
                        }
                    )

        except Exception as e:
            raise RuntimeError(f"Failed to save CV records to database: {e}")
