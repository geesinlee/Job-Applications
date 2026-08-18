"""
Abstract backend for evidence storage and retrieval.

Enables future Work RAG migration without changing consuming code.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional
from src.evidence_models import StructuredEvidence


class EvidenceBackend(ABC):
    """Abstract backend for evidence storage/retrieval."""
    
    @abstractmethod
    def save_evidence(self, evidence: StructuredEvidence) -> str:
        """Save evidence and return its ID."""
        pass
    
    @abstractmethod
    def get_evidence_by_id(self, evidence_id: str) -> Optional[StructuredEvidence]:
        """Retrieve evidence by ID."""
        pass
    
    @abstractmethod
    def get_evidence_by_cv_id(self, cv_id: str) -> list[StructuredEvidence]:
        """Retrieve all evidence extracted from a specific CV."""
        pass
    
    @abstractmethod
    def query_by_skills(self, skills: list[str]) -> list[StructuredEvidence]:
        """Find evidence containing any of the specified skills."""
        pass
    
    @abstractmethod
    def query_by_company(self, company_name: str) -> list[StructuredEvidence]:
        """Find evidence from a specific company."""
        pass
    
    @abstractmethod
    def query_by_timeframe(self, start: datetime, end: datetime) -> list[StructuredEvidence]:
        """Find evidence within a time period."""
        pass
    
    @abstractmethod
    def close(self):
        """Close any connections."""
        pass


class PostgresEvidenceBackend(EvidenceBackend):
    """Postgres implementation of EvidenceBackend."""
    
    def __init__(self, db_url: str):
        """Initialize with Postgres connection string."""
        self.db_url = db_url
        self.conn = None
        try:
            import psycopg2
            self.conn = psycopg2.connect(db_url)
        except ImportError:
            # psycopg2 not available; mock backend for testing
            pass
        except Exception as e:
            print(f"Warning: Could not connect to Postgres: {e}")
    
    def close(self):
        """Close the connection."""
        if self.conn:
            try:
                self.conn.close()
            except Exception:
                pass
    
    def save_evidence(self, evidence: StructuredEvidence) -> str:
        """Insert evidence into structured_evidence table and return ID."""
        if not self.conn:
            # Mock: return a fake ID
            import uuid
            return str(uuid.uuid4())
        
        import psycopg2.extras
        cursor = self.conn.cursor()
        try:
            query = """
                INSERT INTO structured_evidence 
                (achievement, context, impact, skills_demonstrated, job_title, company_name, 
                 time_period_start, time_period_end, source_section, source_cv_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id;
            """
            cursor.execute(query, (
                evidence.achievement,
                evidence.context,
                evidence.impact,
                psycopg2.extras.Json(evidence.skills_demonstrated),
                evidence.job_title,
                evidence.company_name,
                evidence.time_period_start,
                evidence.time_period_end,
                evidence.source_section,
                evidence.source_cv_id
            ))
            evidence_id = cursor.fetchone()[0]
            self.conn.commit()
            return evidence_id
        except Exception as e:
            print(f"Error saving evidence: {e}")
            return None
        finally:
            cursor.close()
    
    def get_evidence_by_id(self, evidence_id: str) -> Optional[StructuredEvidence]:
        """Retrieve evidence by ID."""
        if not self.conn:
            return None
        
        cursor = self.conn.cursor()
        try:
            query = "SELECT * FROM structured_evidence WHERE id = %s;"
            cursor.execute(query, (evidence_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_evidence(row, cursor.description)
        except Exception as e:
            print(f"Error getting evidence: {e}")
            return None
        finally:
            cursor.close()
    
    def get_evidence_by_cv_id(self, cv_id: str) -> list[StructuredEvidence]:
        """Retrieve all evidence from a specific CV."""
        if not self.conn:
            return []
        
        cursor = self.conn.cursor()
        try:
            query = "SELECT * FROM structured_evidence WHERE source_cv_id = %s ORDER BY time_period_start DESC;"
            cursor.execute(query, (cv_id,))
            rows = cursor.fetchall()
            return [self._row_to_evidence(row, cursor.description) for row in rows]
        except Exception as e:
            print(f"Error querying evidence by CV: {e}")
            return []
        finally:
            cursor.close()
    
    def query_by_skills(self, skills: list[str]) -> list[StructuredEvidence]:
        """Find evidence containing any of the specified skills."""
        if not self.conn:
            return []
        
        cursor = self.conn.cursor()
        try:
            # Use Postgres jsonb/array containment operator
            query = """
                SELECT * FROM structured_evidence 
                WHERE skills_demonstrated && %s
                ORDER BY time_period_start DESC;
            """
            cursor.execute(query, (skills,))
            rows = cursor.fetchall()
            return [self._row_to_evidence(row, cursor.description) for row in rows]
        except Exception as e:
            print(f"Error querying by skills: {e}")
            return []
        finally:
            cursor.close()
    
    def query_by_company(self, company_name: str) -> list[StructuredEvidence]:
        """Find evidence from a specific company."""
        if not self.conn:
            return []
        
        cursor = self.conn.cursor()
        try:
            query = "SELECT * FROM structured_evidence WHERE company_name = %s ORDER BY time_period_start DESC;"
            cursor.execute(query, (company_name,))
            rows = cursor.fetchall()
            return [self._row_to_evidence(row, cursor.description) for row in rows]
        except Exception as e:
            print(f"Error querying by company: {e}")
            return []
        finally:
            cursor.close()
    
    def query_by_timeframe(self, start: datetime, end: datetime) -> list[StructuredEvidence]:
        """Find evidence within a time period."""
        if not self.conn:
            return []
        
        cursor = self.conn.cursor()
        try:
            query = """
                SELECT * FROM structured_evidence 
                WHERE (time_period_start IS NULL OR time_period_start >= %s)
                  AND (time_period_end IS NULL OR time_period_end <= %s)
                ORDER BY time_period_start DESC;
            """
            cursor.execute(query, (start, end))
            rows = cursor.fetchall()
            return [self._row_to_evidence(row, cursor.description) for row in rows]
        except Exception as e:
            print(f"Error querying by timeframe: {e}")
            return []
        finally:
            cursor.close()
    
    def _row_to_evidence(self, row: tuple, description) -> StructuredEvidence:
        """Convert a Postgres row to StructuredEvidence."""
        col_names = [desc[0] for desc in description]
        col_dict = dict(zip(col_names, row))
        
        return StructuredEvidence(
            id=col_dict['id'],
            achievement=col_dict['achievement'],
            context=col_dict['context'],
            impact=col_dict['impact'],
            skills_demonstrated=col_dict['skills_demonstrated'] or [],
            job_title=col_dict['job_title'],
            company_name=col_dict['company_name'],
            time_period_start=col_dict['time_period_start'],
            time_period_end=col_dict['time_period_end'],
            source_section=col_dict['source_section'],
            source_cv_id=col_dict['source_cv_id']
        )
