"""Shared state, configuration, and helper functions for Job-Applications.

This module is the single source of truth for tracker I/O, profile I/O, path
resolution, stage machine logic, and utility helpers. Both the monolith
(`job_applications_mcp_server`) and the modular tool files (`src/tools/`)
import from here — breaking the circular dependency.

Naming convention: public names (no underscore prefix) are the canonical API.
The monolith re-exports them with underscore prefix for backwards compatibility.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

try:
    from PyPDF2 import PdfReader
except ImportError:
    PdfReader = None

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    requests = None
    BeautifulSoup = None

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration — env vars with __file__-relative fallbacks
# ---------------------------------------------------------------------------

_SRC_DIR = Path(__file__).resolve().parent.parent.parent  # src/tools/_state.py -> project root
_DEFAULT_DATA_DIR = _SRC_DIR / "data"


def detect_base_dir() -> Path:
    env_dir = os.environ.get("JOB_APP_BASE_DIR")
    if env_dir:
        return Path(env_dir)
    linux_nas = Path("/mnt/job-app-data")
    if linux_nas.exists() and linux_nas.is_dir():
        return linux_nas
    mac_nas = Path("/Volumes/job-app-data")
    if mac_nas.exists() and mac_nas.is_dir():
        return mac_nas
    return _DEFAULT_DATA_DIR


BASE_DIR = detect_base_dir()
ARTEFACTS_DIR = Path(os.environ.get("JOB_APP_ARTEFACTS_DIR", str(BASE_DIR)))
TRACKER_PATH = Path(os.environ.get("JOB_APP_TRACKER_PATH", str(BASE_DIR / "tracker.json")))
PROFILE_PATH = Path(os.environ.get("JOB_APP_PROFILE_PATH", str(BASE_DIR / "profile.json")))
CV_RECORDS_PATH = Path(os.environ.get("JOB_APP_CV_RECORDS_PATH", str(BASE_DIR / "cv_records.json")))
BASE_CV_PATH = Path(os.environ.get(
    "JOB_APP_BASE_CV_PATH",
    str(_DEFAULT_DATA_DIR / "base_cv" / "Reference_CV.md"),
))
NAS_SYNC_PATH = os.environ.get("NAS_SYNC_PATH", "")
STORAGE_BACKEND = os.environ.get("JOB_APP_STORAGE_BACKEND", "file").lower()
TRACKER_SCHEMA_VERSION = "1.2"

# ---------------------------------------------------------------------------
# Exception classes
# ---------------------------------------------------------------------------


class AmbiguousRoleError(ValueError):
    """Raised when a company has multiple roles and none is specified."""

    def __init__(self, company: str, roles: list[str]):
        self.company = company
        self.roles = roles
        super().__init__(f"Multiple roles at {company}: {roles}")


# ---------------------------------------------------------------------------
# Stage machine constants
# ---------------------------------------------------------------------------

VALID_STAGES = {
    "new", "ready_for_submission", "applied", "screening",
    "offer", "accepted", "rejected", "withdrawn",
}
TERMINAL_STAGES = {"accepted", "rejected", "withdrawn"}
INTERVIEW_STAGE_RE = re.compile(r"^interview_r([1-9]\d*)$")

# Static map retained for compatibility with existing tests/docs.
VALID_TRANSITIONS: dict[str, set[str]] = {
    "new": {"ready_for_submission", "applied", "rejected", "withdrawn"},
    "ready_for_submission": {"applied", "rejected", "withdrawn"},
    "applied": {"screening", "rejected", "withdrawn"},
    "screening": {"interview_r1", "rejected", "withdrawn"},
    "offer": {"accepted", "rejected", "withdrawn"},
    "accepted": set(),
    "rejected": set(),
    "withdrawn": set(),
}


def is_interview_stage(stage: str) -> bool:
    return INTERVIEW_STAGE_RE.fullmatch(stage) is not None


def interview_round(stage: str) -> int | None:
    match = INTERVIEW_STAGE_RE.fullmatch(stage)
    if match is None:
        return None
    return int(match.group(1))


def is_valid_stage(stage: str) -> bool:
    return stage in VALID_STAGES or is_interview_stage(stage)


def allowed_next_stages(stage: str) -> set[str]:
    if stage == "new":
        return {"ready_for_submission", "applied", "rejected", "withdrawn"}
    if stage == "ready_for_submission":
        return {"applied", "rejected", "withdrawn"}
    if stage == "applied":
        return {"screening", "rejected", "withdrawn"}
    if stage == "screening":
        return {"interview_r1", "rejected", "withdrawn"}
    if is_interview_stage(stage):
        round_num = interview_round(stage)
        assert round_num is not None
        return {f"interview_r{round_num + 1}", "offer", "rejected", "withdrawn"}
    if stage == "offer":
        return {"accepted", "rejected", "withdrawn"}
    return set()


def can_advance_to_stage(current_stage: str, new_stage: str) -> bool:
    allowed_next = allowed_next_stages(current_stage)
    if new_stage in allowed_next:
        return True
    if is_interview_stage(current_stage) and is_interview_stage(new_stage):
        current_round = interview_round(current_stage)
        new_round = interview_round(new_stage)
        return current_round is not None and new_round is not None and new_round > current_round
    return False


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------


def utc_now() -> str:
    """Return current UTC time as ISO-8601 string, e.g. '2026-08-02T14:30:00Z'."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def days_from_now_utc(days: int) -> str:
    """Return date N days from today in YYYY-MM-DD format (UTC)."""
    return (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Postgres helpers
# ---------------------------------------------------------------------------


def run_postgres(operation):
    """Run one Prisma async operation from synchronous tools."""
    try:
        from prisma import Prisma
    except ImportError as exc:
        raise RuntimeError("postgres_client_unavailable") from exc

    async def wrapped():
        db = Prisma()
        await db.connect()
        try:
            return await operation(db)
        finally:
            await db.disconnect()

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(lambda: asyncio.run(wrapped())).result()
    return asyncio.run(wrapped())


def load_postgres_state(state_id: str, default: dict) -> dict:
    """Read canonical JSON state; never fall back to a stale JSON copy."""
    async def operation(db):
        rows = await db.query_raw(
            'SELECT "payload" FROM "CanonicalState" WHERE "id" = $1',
            state_id,
        )
        return rows[0]["payload"] if rows else None

    payload = run_postgres(operation)
    if payload is None:
        raise RuntimeError(f"canonical_state_missing:{state_id}")
    if not isinstance(payload, dict):
        raise RuntimeError(f"canonical_state_invalid:{state_id}")
    return payload


def save_postgres_state(state_id: str, payload: dict) -> None:
    """Atomically replace one canonical state payload in Postgres."""
    async def operation(db):
        await db.execute_raw(
            """
            INSERT INTO "CanonicalState" ("id", "payload", "createdAt", "updatedAt")
            VALUES ($1, $2::jsonb, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT ("id") DO UPDATE SET
              "payload" = EXCLUDED."payload",
              "updatedAt" = CURRENT_TIMESTAMP
            """,
            state_id,
            json.dumps(payload, ensure_ascii=False),
        )

    run_postgres(operation)


# ---------------------------------------------------------------------------
# NAS sync
# ---------------------------------------------------------------------------


def nas_sync() -> None:
    """Rsync legacy JSON state to optional backup storage (non-blocking)."""
    if not NAS_SYNC_PATH:
        return
    try:
        subprocess.Popen(
            ["rsync", "-a", str(TRACKER_PATH), str(PROFILE_PATH), str(CV_RECORDS_PATH), NAS_SYNC_PATH],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        pass


# ---------------------------------------------------------------------------
# Tracker I/O
# ---------------------------------------------------------------------------


def normalize_tracker(data: dict) -> dict:
    """Upgrade tracker records in place while preserving the public shape."""
    if not isinstance(data, dict):
        return {"schema_version": TRACKER_SCHEMA_VERSION, "applications": []}

    normalized = data
    applications = normalized.setdefault("applications", [])
    if not isinstance(applications, list):
        applications = []
        normalized["applications"] = applications

    for app in applications:
        if not isinstance(app, dict):
            continue
        stage = app.get("stage")
        app["interview_round"] = interview_round(stage) if isinstance(stage, str) else None
        app.setdefault("applied_at", None)
        if not isinstance(app.get("audit"), list):
            app["audit"] = []
        history = app.get("history", [])
        if isinstance(history, list):
            for entry in history:
                if not isinstance(entry, dict):
                    continue
                history_stage = entry.get("stage")
                round_num = interview_round(history_stage) if isinstance(history_stage, str) else None
                if round_num is None:
                    entry.pop("interview_round", None)
                else:
                    entry["interview_round"] = round_num

    normalized["schema_version"] = TRACKER_SCHEMA_VERSION
    return normalized


def load_tracker() -> dict:
    """Load canonical tracker state, using Postgres in production."""
    if STORAGE_BACKEND == "postgres":
        tracker = load_postgres_state("tracker", {"schema_version": TRACKER_SCHEMA_VERSION, "applications": []})
        normalized = normalize_tracker(tracker)
        if normalized != tracker:
            save_postgres_state("tracker", normalized)
        return normalized
    try:
        tracker = json.loads(TRACKER_PATH.read_text(encoding="utf-8"))
        normalized = normalize_tracker(tracker)
        if normalized != tracker:
            save_tracker(normalized)
        return normalized
    except Exception:
        return {"schema_version": TRACKER_SCHEMA_VERSION, "applications": []}


def save_tracker(data: dict) -> None:
    """Save canonical tracker state, using Postgres in production."""
    data = normalize_tracker(data)
    if STORAGE_BACKEND == "postgres":
        save_postgres_state("tracker", data)
        return
    TRACKER_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    nas_sync()


# ---------------------------------------------------------------------------
# Profile I/O
# ---------------------------------------------------------------------------


def load_profile() -> dict:
    """Load canonical profile state, using Postgres in production."""
    if STORAGE_BACKEND == "postgres":
        return load_postgres_state("profile", {"schema_version": "1.0"})
    try:
        return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"schema_version": "1.0"}


def save_profile(data: dict) -> None:
    """Save canonical profile state, using Postgres in production."""
    if STORAGE_BACKEND == "postgres":
        save_postgres_state("profile", data)
        return
    PROFILE_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    nas_sync()


# ---------------------------------------------------------------------------
# Path resolver helpers
# ---------------------------------------------------------------------------


def make_role_slug(role_title: str) -> str:
    """Convert role title to URL-safe lowercase slug."""
    slug = role_title.lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")


def relativize_path(path: Path | str) -> str:
    """Convert an absolute path to a relative path against ARTEFACTS_DIR."""
    p = Path(path)
    if not p.is_absolute():
        return str(p)
    try:
        return str(p.relative_to(ARTEFACTS_DIR))
    except ValueError:
        return str(p)


def absolutize_path(path_str: str, company: str) -> str:
    """Convert a relative path back to an absolute path against ARTEFACTS_DIR."""
    p = Path(path_str)
    if not p.is_absolute():
        return str(ARTEFACTS_DIR / p)

    # Legacy absolute path detected. Try to salvage it.
    parts = p.parts
    try:
        lower_parts = [part.lower() for part in parts]
        idx = lower_parts.index(company.lower())
        rel_parts = parts[idx:]
        return str(ARTEFACTS_DIR.joinpath(*rel_parts))
    except ValueError:
        return path_str


def resolve_company_folder(
    company: str,
    role_title: str | None = None,
    tracker: dict | None = None,
) -> Path:
    """Return the correct artefact folder for this company+role."""
    company_root = (ARTEFACTS_DIR / company).resolve()
    if not company_root.is_relative_to(ARTEFACTS_DIR.resolve()):
        raise ValueError(f"Path traversal detected in company: {company}")

    if tracker is None:
        tracker = load_tracker()
    company_apps = [
        a for a in tracker.get("applications", [])
        if a["company"].lower() == company.lower()
    ]

    root_jd = company_root / "JD.md"
    has_root_jd = root_jd.exists()

    if role_title is None:
        if len(company_apps) > 1:
            raise AmbiguousRoleError(company, [a["role_title"] for a in company_apps])
        return company_root

    if has_root_jd and len(company_apps) <= 1:
        return company_root

    slug = make_role_slug(role_title)
    return company_root / slug


def find_application(tracker: dict, company: str, role_title: str | None) -> dict | None:
    """Find an application record by company (and optionally role_title)."""
    for app in tracker.get("applications", []):
        if app["company"].lower() != company.lower():
            continue
        if role_title is None or app["role_title"].lower() == role_title.lower():
            return app
    return None


def create_application_record(company: str, role_title: str, jd_path: str) -> dict:
    """Build a new tracker application record in the 'new' stage."""
    now = utc_now()
    return {
        "id": str(uuid.uuid4()),
        "company": company,
        "role_title": role_title,
        "jd_path": jd_path,
        "stage": "new",
        "interview_round": None,
        "date_created": now,
        "applied_at": None,
        "history": [{"stage": "new", "at": now}],
        "followups": [],
        "outputs": {},
        "submitted": {},
        "audit": [],
    }


def record_output(tracker: dict, company: str, role_title: str | None,
                  output_type: str, entry: dict) -> None:
    """Append an output entry to the tracker record for the given application."""
    app = find_application(tracker, company, role_title)
    if app is not None:
        if "path" in entry:
            entry["path"] = relativize_path(entry["path"])
        app.setdefault("outputs", {}).setdefault(output_type, []).append(entry)


# ---------------------------------------------------------------------------
# Follow-up helpers
# ---------------------------------------------------------------------------


def auto_create_followup(app: dict, new_stage: str) -> None:
    """Create follow-up records on stage transition."""
    followups = app.setdefault("followups", [])

    if new_stage == "applied":
        already = any(
            f["action_type"] == "send_follow_up_email" and f["status"] == "pending"
            for f in followups
        )
        if not already:
            followups.append({
                "id": str(uuid.uuid4()),
                "action_type": "send_follow_up_email",
                "due_date": days_from_now_utc(7),
                "status": "pending",
                "completed_at": None,
            })

    elif is_interview_stage(new_stage):
        already = any(
            f["action_type"] == "send_thank_you_note" and f["status"] == "pending"
            for f in followups
        )
        if not already:
            followups.append({
                "id": str(uuid.uuid4()),
                "action_type": "send_thank_you_note",
                "due_date": days_from_now_utc(1),
                "status": "pending",
                "completed_at": None,
            })
        cancel_followup_emails(app)


def cancel_followup_emails(app: dict) -> None:
    """Set pending send_follow_up_email records to cancelled."""
    for f in app.get("followups", []):
        if f["action_type"] == "send_follow_up_email" and f["status"] == "pending":
            f["status"] = "cancelled"


# ---------------------------------------------------------------------------
# File helpers
# ---------------------------------------------------------------------------


def company_dir(company: str) -> Path:
    """Return the path to a company folder, creating it if needed."""
    d = (ARTEFACTS_DIR / company).resolve()
    if not d.is_relative_to(ARTEFACTS_DIR.resolve()):
        raise ValueError(f"Path traversal detected in company: {company}")
    d.mkdir(parents=True, exist_ok=True)
    return d


def extract_pdf_text(pdf_path: Path) -> str:
    """Extract text from a PDF file."""
    if PdfReader is None:
        return "[ERROR: PyPDF2 not installed. Install with: pip install PyPDF2]"
    reader = PdfReader(str(pdf_path))
    pages = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            pages.append(text)
    return "\n\n".join(pages)


def read_file(path: Path) -> str | None:
    """Read a text file, returning None if it doesn't exist."""
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def find_cv(company_dir: Path) -> Path | None:
    """Find the CV file in a company folder (PDF or Markdown)."""
    for pattern in ["CV*.pdf", "CV*.md", "cv*.pdf", "cv*.md", "Resume*.pdf", "Resume*.md"]:
        matches = list(company_dir.glob(pattern))
        if matches:
            return matches[0]
    for f in company_dir.iterdir():
        if f.is_file() and "cv" in f.name.lower() and f.suffix in (".pdf", ".md"):
            return f
    return None


def ingest_jd_url(url: str) -> str:
    """Fetch a job description page and return its visible text."""
    if requests is None or BeautifulSoup is None:
        raise RuntimeError("requests and beautifulsoup4 are required for URL ingestion")
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    return soup.get_text(separator="\n", strip=True)


# ---------------------------------------------------------------------------
# JD resolution
# ---------------------------------------------------------------------------


def resolve_jd_content(application_id: str, jd_path: str | None = None) -> str | None:
    """Resolve JD content from application_id or jd_path.

    Searches multiple mount points to find the JD file.
    """
    if jd_path:
        p = Path(jd_path)
        # Try multiple mount points
        for base in [ARTEFACTS_DIR, BASE_DIR, _SRC_DIR / "data"]:
            candidate = base / p if not p.is_absolute() else p
            if candidate.exists():
                if candidate.suffix.lower() == ".pdf":
                    return extract_pdf_text(candidate)
                return candidate.read_text(encoding="utf-8")
        # Try home directory
        home_jd = Path.home() / "Personal" / "Jobs" / p
        if home_jd.exists():
            if home_jd.suffix.lower() == ".pdf":
                return extract_pdf_text(home_jd)
            return home_jd.read_text(encoding="utf-8")
        return None

    # Resolve by application_id
    tracker = load_tracker()
    for app in tracker.get("applications", []):
        if app.get("id") == application_id:
            app_jd = app.get("jd_path")
            if app_jd:
                return resolve_jd_content(application_id, app_jd)
    return None


def find_opportunity_url(company: str, role_title: str | None = None, date_created: datetime | None = None) -> str | None:
    """Search digest files for a LinkedIn URL matching the company/role."""
    digest_dir = ARTEFACTS_DIR / "digests"
    if not digest_dir.exists():
        return None

    url_pattern = re.compile(r"https?://(?:www\.)?linkedin\.com/[^\s)]+")
    company_lower = company.lower() if company else ""

    try:
        if date_created:
            # Check the digest closest to the creation date
            candidates = sorted(digest_dir.glob("*.md"), reverse=True)
            for digest_file in candidates:
                fname = digest_file.stem
                try:
                    file_date = datetime.fromisoformat(fname)
                except (ValueError, TypeError):
                    continue
                if file_date > date_created + timedelta(days=1):
                    continue
                if file_date < date_created - timedelta(days=30):
                    break

                try:
                    content = digest_file.read_text(encoding="utf-8")
                    lines = content.split("\n")
                    for i, line in enumerate(lines):
                        if company_lower in line.lower():
                            search_range = lines[max(0, i): min(len(lines), i + 10)]
                            for search_line in search_range:
                                url_match = url_pattern.search(search_line)
                                if url_match:
                                    return url_match.group(1)
                except (OSError, UnicodeDecodeError):
                    continue
        else:
            # No date — search all digests, newest first
            for digest_file in sorted(digest_dir.glob("*.md"), reverse=True):
                try:
                    content = digest_file.read_text(encoding="utf-8")
                    lines = content.split("\n")
                    for i, line in enumerate(lines):
                        if company_lower in line.lower():
                            search_range = lines[max(0, i): min(len(lines), i + 10)]
                            for search_line in search_range:
                                url_match = url_pattern.search(search_line)
                                if url_match:
                                    return url_match.group(1)
                except (OSError, UnicodeDecodeError):
                    continue
    except Exception:
        return None

    return None


# ---------------------------------------------------------------------------
# Profile merge helpers
# ---------------------------------------------------------------------------

_MONTH_ABBR = {
    "jan": "01", "feb": "02", "mar": "03", "apr": "04",
    "may": "05", "jun": "06", "jul": "07", "aug": "08",
    "sep": "09", "oct": "10", "nov": "11", "dec": "12",
}


def normalise_profile_date(token: str) -> str | None:
    """Normalise a date token (e.g. 'Jan 2023' or '2023-01') to 'YYYY-MM'."""
    token = token.strip()
    m = re.match(r"^(\w{3})\s+(\d{4})$", token, re.IGNORECASE)
    if m:
        month = _MONTH_ABBR.get(m.group(1).lower())
        if month:
            return f"{m.group(2)}-{month}"
    m = re.match(r"^(\d{4})-(\d{2})$", token)
    if m:
        return token
    return None


def parse_ym(token: str) -> tuple | None:
    m = re.match(r"^(\d{4})-(\d{2})", token)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None


def compute_years_of_experience(work_exp: list) -> int:
    """Calculate total years of experience from work history entries."""
    if not work_exp:
        return 0
    total_months = 0
    for entry in work_exp:
        start = parse_ym(entry.get("start_date", ""))
        end = parse_ym(entry.get("end_date", "")) if entry.get("end_date") else None
        if not start:
            continue
        if end:
            months = (end[0] - start[0]) * 12 + (end[1] - start[1])
        else:
            now = datetime.now(timezone.utc)
            months = (now.year - start[0]) * 12 + (now.month - start[1])
        total_months += max(0, months)
    return total_months // 12


def top_n_skills(work_exp: list, skills: list, n: int = 5) -> list:
    """Return the top N most frequently mentioned skills across work history."""
    skill_counts: dict[str, int] = {}
    for entry in work_exp:
        for skill in entry.get("skills", []):
            skill_lower = skill.lower()
            skill_counts[skill_lower] = skill_counts.get(skill_lower, 0) + 1
    for skill in (skills or []):
        skill_lower = skill.lower() if isinstance(skill, str) else str(skill).lower()
        skill_counts[skill_lower] = skill_counts.get(skill_lower, 0) + 1
    sorted_skills = sorted(skill_counts.items(), key=lambda x: x[1], reverse=True)
    return [s[0] for s in sorted_skills[:n]]


def merge_profile_section(existing: list, incoming: list, source: str, key_fields: tuple) -> tuple:
    """Merge a section of profile data, deduplicating by key_fields."""
    existing_map = {}
    for entry in existing:
        key = tuple(entry.get(f, "") for f in key_fields)
        existing_map[key] = entry

    added = []
    for entry in incoming:
        key = tuple(entry.get(f, "") for f in key_fields)
        if key not in existing_map:
            entry_copy = dict(entry)
            entry_copy["source"] = source
            existing_map[key] = entry_copy
            added.append(entry_copy)

    merged = list(existing_map.values())
    return merged, added


def merge_profile(existing: dict, incoming: dict, source: str) -> dict:
    """Merge an incoming profile into an existing one."""
    merged = dict(existing)
    conflicts = []

    for section in ("work_experience", "education", "certifications"):
        existing_list = merged.get(section, [])
        incoming_list = incoming.get(section, [])
        key_fields = {
            "work_experience": ("company", "title", "start_date"),
            "education": ("institution", "degree", "field"),
            "certifications": ("name", "issuer"),
        }.get(section, ("name",))

        merged_list, added = merge_profile_section(existing_list, incoming_list, source, key_fields)
        merged[section] = merged_list
        if added:
            conflicts.extend([f"Added {section}: {a.get('company', a.get('name', ''))}" for a in added])

    existing_skills = [s.lower() if isinstance(s, str) else str(s).lower() for s in merged.get("skills", [])]
    new_skills = []
    for skill in incoming.get("skills", []):
        skill_lower = skill.lower() if isinstance(skill, str) else str(skill).lower()
        if skill_lower not in existing_skills:
            new_skills.append(skill)
    merged["skills"] = merged.get("skills", []) + new_skills

    for field in ("headline", "current_role", "location", "summary"):
        if not merged.get(field) and incoming.get(field):
            merged[field] = incoming[field]

    merged["conflicts"] = conflicts
    merged["last_updated"] = {"source": source, "at": utc_now()}

    return merged


def seed_profile_from_cv(cv_path: Path) -> dict:
    """Seed a profile dict from a CV markdown file using heuristic extraction."""
    if not cv_path.exists():
        return {"work_experience": [], "education": [], "skills": [], "certifications": []}

    text = cv_path.read_text(encoding="utf-8")
    lines = text.split("\n")

    profile: dict[str, Any] = {
        "work_experience": [],
        "education": [],
        "skills": [],
        "certifications": [],
    }

    # Extract skills from Skills section
    in_skills = False
    for line in lines:
        stripped = line.strip()
        if re.match(r"^#+\s*skills", stripped, re.IGNORECASE):
            in_skills = True
            continue
        if re.match(r"^#+\s*", stripped) and in_skills:
            in_skills = False
            continue
        if in_skills and stripped.startswith(("-", "•", "*")):
            skill = stripped.lstrip("-•* ").strip()
            if skill:
                profile["skills"].append(skill)

    return profile


def parse_linkedin_export(text: str) -> dict:
    """Parse a LinkedIn profile export text into a structured dict."""
    profile: dict[str, Any] = {
        "work_experience": [],
        "education": [],
        "skills": [],
        "certifications": [],
        "headline": "",
        "current_role": "",
    }

    def section_body(name):
        pattern = re.compile(rf"^#+\s*{re.escape(name)}", re.IGNORECASE | re.MULTILINE)
        match = pattern.search(text)
        if not match:
            return []
        start = match.end()
        next_header = re.search(r"^#+\s", text[start:], re.MULTILINE)
        end = start + next_header.start() if next_header else len(text)
        return text[start:end].strip().split("\n")

    def blocks(body_lines):
        entries = []
        current = {}
        for line in body_lines:
            stripped = line.strip()
            if not stripped:
                if current:
                    entries.append(current)
                    current = {}
                continue
            if stripped.startswith(("-", "•", "*")):
                skill = stripped.lstrip("-•* ").strip()
                if skill:
                    profile["skills"].append(skill)
                continue
            if current and stripped.startswith(("-", "•", "*")):
                continue
            if "|" in stripped:
                parts = [p.strip() for p in stripped.split("|")]
                if len(parts) >= 2:
                    current.setdefault("company", parts[0])
                    current.setdefault("title", parts[1])
            else:
                current.setdefault("title", stripped)
        if current:
            entries.append(current)
        return entries

    # This is a simplified parser; the monolith has a more complete one
    # that handles LinkedIn's specific format more thoroughly.
    # For Phase 2, we keep the monolith's full parser and only extract
    # the helpers that are clearly self-contained.

    return profile