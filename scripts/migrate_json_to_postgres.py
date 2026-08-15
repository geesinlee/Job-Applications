#!/usr/bin/env python3
"""
Migrate CV records from JSON to NAS Postgres database.

This script:
1. Reads cv_records.json from the local/NAS filesystem
2. Connects to NAS Postgres (via DATABASE_URL)
3. Creates Application and CVRecord entries
4. Upserts CVEvidenceUsage records
5. Validates data integrity

Usage:
  python3 migrate_json_to_postgres.py [--json-path cv_records.json] [--dry-run]

Environment:
  DATABASE_URL — Postgres connection string (e.g., postgresql://user:pass@host/db)
  Defaults to environment variable if set; override with --database-url flag.
"""

import json
import os
import sys
import argparse
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional

try:
    import psycopg2
    from psycopg2.extras import execute_values
except ImportError:
    print("ERROR: psycopg2 not installed. Run: pip install psycopg2-binary")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def load_json_records(json_path: str) -> List[Dict[str, Any]]:
    """Load CVRecord dicts from JSON file."""
    path = Path(json_path)
    if not path.exists():
        raise FileNotFoundError(f"JSON file not found: {json_path}")

    with open(path, "r") as f:
        records = json.load(f)

    logger.info(f"Loaded {len(records)} records from {json_path}")
    return records


def connect_postgres(database_url: str) -> psycopg2.extensions.connection:
    """Connect to Postgres database."""
    try:
        conn = psycopg2.connect(database_url)
        conn.autocommit = False  # Use transactions
        logger.info("Connected to Postgres")
        return conn
    except psycopg2.Error as e:
        logger.error(f"Failed to connect to Postgres: {e}")
        raise


def create_or_get_application(conn: psycopg2.extensions.connection, app_name: str) -> str:
    """Create Application if not exists, return its id."""
    cur = conn.cursor()
    try:
        # Check if exists
        cur.execute("SELECT id FROM \"Application\" WHERE name = %s", (app_name,))
        result = cur.fetchone()
        if result:
            app_id = result[0]
            logger.debug(f"Application '{app_name}' already exists (id={app_id})")
            return app_id

        # Create new
        cur.execute(
            'INSERT INTO "Application" (id, name, "createdAt", "updatedAt") '
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (f"app_{app_name}", app_name, datetime.utcnow(), datetime.utcnow())
        )
        app_id = cur.fetchone()[0]
        logger.debug(f"Created Application '{app_name}' (id={app_id})")
        return app_id
    finally:
        cur.close()


def parse_timestamp(ts_str: Optional[str]) -> Optional[datetime]:
    """Parse ISO 8601 timestamp (with Z suffix) to datetime."""
    if not ts_str:
        return None
    # Remove Z suffix and parse
    ts_str = ts_str.rstrip("Z")
    try:
        return datetime.fromisoformat(ts_str)
    except ValueError:
        logger.warning(f"Could not parse timestamp: {ts_str}")
        return None


def migrate_records(conn: psycopg2.extensions.connection, records: List[Dict[str, Any]], dry_run: bool = False):
    """Migrate CVRecord and CVEvidenceUsage records to Postgres."""
    cur = conn.cursor()
    migrated = 0
    errors = 0

    try:
        for record in records:
            try:
                # Get or create Application
                app_id = create_or_get_application(conn, record["application_id"])

                # Prepare CVRecord data
                cv_record_data = {
                    "id": f"cv_{record['cv_id']}",
                    "cvId": record["cv_id"],
                    "applicationId": app_id,
                    "version": record["version"],
                    "status": record["status"],
                    "content": record["content"],
                    "approvedBy": record.get("approved_by"),
                    "approvedAt": parse_timestamp(record.get("approved_at")),
                    "finalizedAt": parse_timestamp(record.get("finalized_at")),
                    "createdAt": parse_timestamp(record.get("created_at")) or datetime.utcnow(),
                }

                # Upsert CVRecord
                cur.execute(
                    'INSERT INTO "CVRecord" '
                    '(id, "cvId", "applicationId", version, status, content, "approvedBy", "approvedAt", "finalizedAt", "createdAt") '
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                    'ON CONFLICT ("cvId") DO UPDATE SET '
                    'version=EXCLUDED.version, status=EXCLUDED.status, content=EXCLUDED.content, '
                    '"approvedBy"=EXCLUDED."approvedBy", "approvedAt"=EXCLUDED."approvedAt", '
                    '"finalizedAt"=EXCLUDED."finalizedAt" ',
                    (
                        cv_record_data["id"],
                        cv_record_data["cvId"],
                        cv_record_data["applicationId"],
                        cv_record_data["version"],
                        cv_record_data["status"],
                        cv_record_data["content"],
                        cv_record_data["approvedBy"],
                        cv_record_data["approvedAt"],
                        cv_record_data["finalizedAt"],
                        cv_record_data["createdAt"],
                    )
                )

                # Migrate CVEvidenceUsage records
                evidence_list = record.get("evidence_used", [])
                for evidence in evidence_list:
                    cur.execute(
                        'INSERT INTO "CVEvidenceUsage" '
                        '(id, "cvRecordId", "evidenceId", "requirementId", "contentExcerpt", "placementSection") '
                        "VALUES (%s, %s, %s, %s, %s, %s) "
                        'ON CONFLICT (id) DO NOTHING',
                        (
                            f"ev_{record['cv_id']}_{evidence.get('evidence_id', 'unknown')}",
                            cv_record_data["id"],
                            evidence.get("evidence_id", ""),
                            evidence.get("requirement_id", ""),
                            evidence.get("content_excerpt", ""),
                            evidence.get("placement_section", ""),
                        )
                    )

                # Only count as migrated if no exceptions occurred
                migrated += 1
                logger.debug(f"Migrated CVRecord {record['cv_id']}")

            except psycopg2.Error as e:
                errors += 1
                logger.error(f"Error migrating record {record.get('cv_id', '?')}: {e}")
                conn.rollback()

        if not dry_run:
            conn.commit()
            logger.info(f"Successfully migrated {migrated} records (errors: {errors})")
        else:
            conn.rollback()
            logger.info(f"[DRY RUN] Would have migrated {migrated} records (errors: {errors})")

        return migrated, errors

    finally:
        cur.close()


def validate_migration(conn: psycopg2.extensions.connection, original_count: int) -> bool:
    """Validate that the correct number of records were migrated."""
    cur = conn.cursor()
    try:
        cur.execute('SELECT COUNT(*) FROM "CVRecord"')
        migrated_count = cur.fetchone()[0]

        if migrated_count >= original_count:
            logger.info(f"Validation passed: {migrated_count} records in Postgres (expected >= {original_count})")
            return True
        else:
            logger.error(f"Validation FAILED: {migrated_count} records in Postgres (expected >= {original_count})")
            return False
    finally:
        cur.close()


def main():
    parser = argparse.ArgumentParser(
        description="Migrate CV records from JSON to NAS Postgres",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Environment: DATABASE_URL must point to the target Postgres database"
    )
    parser.add_argument(
        "--json-path",
        default="cv_records.json",
        help="Path to cv_records.json (default: cv_records.json)"
    )
    parser.add_argument(
        "--database-url",
        help="Postgres connection string (overrides DATABASE_URL env var)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate migration without committing to database"
    )

    args = parser.parse_args()

    # Get database URL
    database_url = args.database_url or os.environ.get("DATABASE_URL")
    if not database_url:
        logger.error("DATABASE_URL not set. Provide via --database-url or DATABASE_URL environment variable")
        sys.exit(1)

    try:
        # Load JSON records
        records = load_json_records(args.json_path)

        # Connect to Postgres
        conn = connect_postgres(database_url)

        # Migrate records
        migrated, errors = migrate_records(conn, records, dry_run=args.dry_run)

        # Validate
        if not args.dry_run:
            success = validate_migration(conn, len(records))
            sys.exit(0 if success and errors == 0 else 1)
        else:
            sys.exit(0)

    except Exception as e:
        logger.error(f"Migration failed: {e}", exc_info=True)
        sys.exit(1)
    finally:
        if 'conn' in locals():
            conn.close()


if __name__ == "__main__":
    main()
