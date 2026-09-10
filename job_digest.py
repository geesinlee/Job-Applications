#!/usr/bin/env python3
"""Job Applications — daily LinkedIn job discovery digest.

Standalone script (stdlib + requests, like tracker_daily.py). It can run from
a scheduler such as a systemd timer.

Pipeline:
  1. Authenticate with Gmail API via OAuth2 (GmailAccountManager)
  2. Query Gmail for LinkedIn job-alert emails since last run
  3. Parse job listings from each email (parse_linkedin_email)
  4. De-duplicate against tracker.json (URL exact + company+title fuzzy)
  5. Require both AI-company relevance and enterprise-sales role relevance
  6. Write daily Markdown digest to $JOB_APP_ARTEFACTS_DIR/digests/YYYY-MM-DD.md
  7. Send summary email via SMTP (fleet-notify)
  8. Move processed LinkedIn emails to Trash via Gmail API
  9. Update last-run timestamp
"""

from __future__ import annotations

import argparse
import base64
import fcntl
import json
import logging
import os
import re
import sys
import time
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv optional; env vars may be set by systemd

from gmail_auth import GmailAccountManager
from email_parser import JobCard, parse_linkedin_email
from email_parser import _extract_job_id

from fleet_notify import send_email
from fleet_notify.config import load_smtp_config

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_SRC_DIR = Path(__file__).resolve().parent
_DEFAULT_DATA_DIR = _SRC_DIR / "data"

BASE_DIR = Path(os.environ.get("JOB_APP_BASE_DIR", str(_DEFAULT_DATA_DIR)))
ARTEFACTS_DIR = Path(os.environ.get("JOB_APP_ARTEFACTS_DIR", str(BASE_DIR)))
TRACKER_PATH = Path(os.environ.get("JOB_APP_TRACKER_PATH", str(BASE_DIR / "tracker.json")))
PROFILE_PATH = Path(os.environ.get("JOB_APP_PROFILE_PATH", str(BASE_DIR / "profile.json")))
REFERENCE_CV_PATH = Path(os.environ.get(
    "JOB_APP_REFERENCE_CV_PATH",
    str(ARTEFACTS_DIR / "base_cv" / "Reference_CV.md"),
))

GMAIL_ACCOUNTS_CONFIG = os.environ.get("GMAIL_ACCOUNTS_CONFIG", "")

# SMTP config via fleet-notify — auto-loaded from SMTP_* env vars.
# SMTP and Gmail API accounts are configured independently through environment
# variables and the ignored gmail_accounts.json runtime file.
_SMTP_CONFIG = load_smtp_config()

DIGEST_DIR = ARTEFACTS_DIR / "digests"
LAST_RUN_FILE = ARTEFACTS_DIR / ".job_digest_last_run"
RUN_LOCK_PATH = ARTEFACTS_DIR / ".job_digest.lock"
FAILURE_STATE_PATH = ARTEFACTS_DIR / ".job_digest_failure.json"
LOG_PATH = Path(os.environ.get("JOB_DIGEST_LOG_PATH", str(_SRC_DIR / "job_digest.log")))

GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"
GMAIL_LIST_PAGE_SIZE = int(os.environ.get("JOB_DIGEST_GMAIL_PAGE_SIZE", "100"))
TRIAGE_MODE = os.environ.get("JOB_DIGEST_TRIAGE_MODE", "rules").lower()
TRIAGE_BATCH_SIZE = int(os.environ.get("JOB_DIGEST_TRIAGE_BATCH_SIZE", "8"))
TRIAGE_MIN_SCORE = int(os.environ.get("JOB_DIGEST_TRIAGE_MIN_SCORE", "70"))
TRIAGE_CV_CONTEXT_CHARS = int(os.environ.get("JOB_DIGEST_TRIAGE_CV_CONTEXT_CHARS", "6000"))
TRIAGE_LLM_MODEL = os.environ.get("JOB_DIGEST_LLM_MODEL", "").strip() or None
TRIAGE_LLM_MAX_TOKENS = int(os.environ.get("JOB_DIGEST_LLM_MAX_TOKENS", "8192"))

# Levenshtein distance threshold for fuzzy title matching (company is exact match)
LEV_THRESHOLD = 3

# Pre-filter senior-title keywords (case-insensitive)
SENIOR_KEYWORDS = {
    "senior", "director", "vp", "vice president", "partner", "head",
    "lead", "principal", "chief", "cto", "ceo", "cfo", "cro", "cso",
    "vp-", "svp", "evp", "avp", "distinguished", "staff",
}

def _env_keywords(name: str, default: str) -> set[str]:
    """Return normalized comma-separated keywords from an environment variable."""
    return {value.strip().lower() for value in os.getenv(name, default).split(",") if value.strip()}


# Location preferences are tenant configuration, not repository defaults.
LOCATION_KEYWORDS = _env_keywords("JOB_DIGEST_LOCATION_KEYWORDS", "remote,hybrid")

# Role type blacklist — exclude academic, education, training roles
ROLE_BLACKLIST = {
    "lecturer", "professor", "instructor", "tutor", "trainer", "teacher",
    "academic", "education", "teaching", "training", "course", "faculty",
    "researcher", "research scientist", "postdoc", "phd", "scholarship",
}

# Known AI-core and AI-adjacent companies. The environment variable replaces
# this default set so each deployment can maintain its own target-account list.
_DEFAULT_AI_TARGET_COMPANIES = (
    "openai,anthropic,palantir,palantir technologies,mistral,mistral ai,"
    "cohere,scale ai,hugging face,perplexity,xai,google deepmind,deepmind,"
    "stability ai,databricks,snowflake,confluent,cerebras,cerebras systems,"
    "groq,together ai,anyscale,pinecone,weaviate,weights & biases,wandb"
)
AI_TARGET_COMPANIES = _env_keywords(
    "JOB_DIGEST_AI_TARGET_COMPANIES",
    _DEFAULT_AI_TARGET_COMPANIES,
)

# For companies outside the configured target list, the short LinkedIn snippet
# must describe an AI product/business or an adjacent data/AI platform. A bare
# mention of "AI" is intentionally insufficient.
AI_BUSINESS_PATTERNS = (
    r"\b(?:ai|artificial intelligence|generative ai|machine learning|"
    r"foundation models?|large language models?|llms?)\b.{0,60}"
    r"\b(?:company|platform|products?|solutions?|software|infrastructure|"
    r"technology|services?|models?)\b",
    r"\b(?:company|platform|products?|solutions?|software|infrastructure|"
    r"technology|services?|models?)\b.{0,60}"
    r"\b(?:ai|artificial intelligence|generative ai|machine learning|"
    r"foundation models?|large language models?|llms?)\b",
    r"\b(?:data (?:and )?ai|data intelligence|lakehouse|data cloud|"
    r"cloud data platform|data streaming platform|streaming data platform|"
    r"vector database|mlops|model serving|gpu cloud)\b",
)

# Direct enterprise sellers and sales/GTM/revenue leaders are in scope.
ENTERPRISE_SALES_ROLE_PATTERNS = (
    r"\benterprise\b.{0,40}\b(?:account executive|account director|"
    r"sales executive|sales director|sales manager|sales|seller)\b",
    r"\b(?:account executive|account director|sales executive|sales director|"
    r"sales manager|seller)\b.{0,40}\benterprise\b",
    r"\b(?:strategic|global|major|named|key)\s+(?:accounts?|account executive|"
    r"account director|sales)\b",
    r"\b(?:account executive|account director)\b.{0,40}"
    r"\b(?:strategic|global|major|named|key)\b",
)

SALES_LEADERSHIP_ROLE_PATTERNS = (
    r"\b(?:chief revenue officer|cro)\b",
    r"\b(?:vp|svp|evp|vice president|head|director)\b.{0,50}"
    r"\b(?:sales|revenue|go[ -]to[ -]market|gtm)\b",
    r"\b(?:sales|revenue|go[ -]to[ -]market|gtm)\b.{0,50}"
    r"\b(?:vp|svp|evp|vice president|head|director|lead|leader)\b",
    r"\b(?:regional|area|country|national|enterprise|strategic)\s+sales\s+"
    r"(?:manager|lead|leader)\b",
)

# Sales-adjacent roles are useful but do not match the requested search.
SALES_ROLE_EXCLUSION_PATTERNS = (
    r"\b(?:sales|solutions?|pre[ -]sales)\s+"
    r"(?:engineer(?:ing)?|architect(?:ure)?|consult(?:ant|ing))\b",
    r"\b(?:sales|revenue|commercial)\s+(?:operations|ops|enablement|training|"
    r"compensation)\b",
    r"\b(?:business|sales) development representative\b",
    r"\b(?:sdr|bdr)\b",
    r"\bcustomer success\b",
)

logger = logging.getLogger("job_digest")


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _log(message: str) -> None:
    """Append a timestamped message to the digest log file."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"[{timestamp}] {message}"
    try:
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass  # best-effort logging
    logger.info(message)


# ---------------------------------------------------------------------------
# Tracker loading
# ---------------------------------------------------------------------------

def load_tracker(path: Path) -> dict:
    """Load tracker.json; return empty schema on any read error.

    Conservative: if tracker is unreadable, treat all jobs as "new" rather
    than silently skipping them.
    """
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        _log(f"WARNING: tracker.json read failure at {path}, treating all jobs as new")
        return {"schema_version": "1.0", "applications": []}


# ---------------------------------------------------------------------------
# De-duplication
# ---------------------------------------------------------------------------

def _levenshtein(s1: str, s2: str) -> int:
    """Compute Levenshtein edit distance between two strings."""
    if len(s1) < len(s2):
        return _levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]


def deduplicate_jobs(jobs: list[JobCard], tracker: dict) -> dict:
    """De-duplicate parsed jobs against tracker records.

    Returns {"new": [...], "already_tracked": [...]}.
    A job is "already tracked" if:
      - Its URL exactly matches a tracker record's jd_source_url, or
      - Its URL exactly matches any URL found in the tracker applications, or
      - Its company exactly matches (case-insensitive) AND its title is within
        Levenshtein distance <= LEV_THRESHOLD of a tracker record's role_title.
    """
    tracked_urls: set[str] = set()
    tracked_combos: list[tuple[str, str]] = []  # (company_lower, title_lower)

    for app in tracker.get("applications", []):
        # Collect known URLs from tracker records
        for url_field in ("jd_source_url", "jd_path"):
            url_val = app.get(url_field)
            if url_val and url_val.startswith("http"):
                tracked_urls.add(url_val)
        # Also check outputs for any saved URLs
        for output_entries in (app.get("outputs", {}) or {}).values():
            if isinstance(output_entries, list):
                for entry in output_entries:
                    if isinstance(entry, dict):
                        url_val = entry.get("url") or entry.get("jd_source_url")
                        if url_val:
                            tracked_urls.add(url_val)
        # Fuzzy combo
        company = (app.get("company") or "").lower().strip()
        title = (app.get("role_title") or "").lower().strip()
        if company and title:
            tracked_combos.append((company, title))

    new_jobs: list[JobCard] = []
    already_tracked: list[JobCard] = []

    for job in jobs:
        # URL exact match
        if job.url in tracked_urls:
            already_tracked.append(job)
            continue

        # Fuzzy company+title match
        job_company = job.company.lower().strip()
        job_title = job.title.lower().strip()
        is_dup = False
        for tc, tt in tracked_combos:
            if job_company == tc and _levenshtein(job_title, tt) <= LEV_THRESHOLD:
                is_dup = True
                break
        if is_dup:
            already_tracked.append(job)
            continue

        new_jobs.append(job)

    return {"new": new_jobs, "already_tracked": already_tracked}


def deduplicate_across_job_alerts(jobs: list[JobCard]) -> list[JobCard]:
    """Remove duplicate LinkedIn jobs from repeated alert emails.

    LinkedIn tracking parameters can make the same job appear under many URLs.
    The numeric job ID is the stable identity when present.
    """
    by_key: dict[str, JobCard] = {}

    for job in jobs:
        job_id = _extract_job_id(job.url)
        key = job_id if job_id else job.url
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = job
            continue

        if len(job.snippet or "") > len(existing.snippet or ""):
            by_key[key] = job
        elif len(job.snippet or "") == len(existing.snippet or ""):
            if job.company != "Unknown" and existing.company == "Unknown":
                by_key[key] = job
            elif len(job.company) > len(existing.company) and job.company not in job.title:
                by_key[key] = job

    return list(by_key.values())


# ---------------------------------------------------------------------------
# Discovery configuration and relevance pre-filter
# ---------------------------------------------------------------------------

def load_prefilter_keywords(reference_cv_path: Path) -> dict:
    """Load discovery configuration and profile keywords.

    Returns senior_titles, locations, skills, industries, and
    ai_target_companies. The profile-derived values remain available as
    context, but only the AI-company and enterprise-sales gates determine
    whether a job is surfaced.
    Falls back to basic keyword-only pre-filter if the file is missing.
    """
    result: dict[str, set[str]] = {
        "senior_titles": set(SENIOR_KEYWORDS),
        "locations": set(LOCATION_KEYWORDS),
        "skills": set(),
        "industries": set(),
        "ai_target_companies": set(AI_TARGET_COMPANIES),
    }

    if not reference_cv_path.exists():
        _log(f"WARNING: Reference_CV.md not found at {reference_cv_path}, using basic keywords only")
        return result

    try:
        text = reference_cv_path.read_text(encoding="utf-8").lower()
    except Exception:
        _log(f"WARNING: Failed to read Reference_CV.md at {reference_cv_path}")
        return result

    # Extract skills from Technical Skills section
    # The CV format is: - **Category:** item, item, item
    # Colon may be inside or outside the bold markers
    skills_match = re.search(
        r"##\s*technical skills\s*\n(.+?)(?:\n---|\n##|\Z)", text, re.DOTALL | re.IGNORECASE,
    )
    if skills_match:
        for line in skills_match.group(1).split("\n"):
            # Match: - **Category:** items  OR  - **Category** items
            skill_line = re.match(r"^\s*[-*]\s*\*\*(.+?)\*\*:?\s*(.*)", line.strip())
            if skill_line:
                items_str = skill_line.group(2).strip()
                if not items_str:
                    continue
                items = items_str.split(",")
                for item in items:
                    clean = re.sub(r"\(.+?\)", "", item).strip()
                    if clean and len(clean) > 1:
                        result["skills"].add(clean)
                        # Also add individual words for broader matching
                        for word in clean.split():
                            if len(word) > 3:
                                result["skills"].add(word)

    # Extract industries/verticals from Professional Summary and Core Competencies
    industry_keywords = _env_keywords(
        "JOB_DIGEST_INDUSTRY_KEYWORDS",
        "software,technology,cloud,cybersecurity,automation,ai,data,consulting,"
        "finance,healthcare,retail,manufacturing,education,government",
    )
    for kw in industry_keywords:
        if kw in text:
            result["industries"].add(kw)

    # Optional tenant-supplied account terms can participate in matching.
    for keyword in _env_keywords("JOB_DIGEST_ACCOUNT_KEYWORDS", ""):
        if keyword in text:
            result["industries"].add(keyword)

    return result


def _normalize_company(value: str) -> str:
    """Normalize a company name for conservative alias matching."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", value.lower())).strip()


def _matches_target_company(company: str, target_companies: set[str]) -> bool:
    """Return True when company matches a configured target-company alias."""
    normalized = _normalize_company(company)
    if not normalized:
        return False

    for target in target_companies:
        alias = _normalize_company(target)
        if not alias:
            continue
        if (
            normalized == alias
            or normalized.startswith(f"{alias} ")
            or normalized.endswith(f" {alias}")
        ):
            return True
    return False


def _is_ai_relevant_company(job: JobCard, target_companies: set[str]) -> bool:
    """Identify a known target account or product evidence in the job card."""
    if _matches_target_company(job.company, target_companies):
        return True

    # Company names that explicitly contain a standalone "AI" are strong
    # enough; snippets/titles need product or platform context.
    if re.search(r"(?:^|[^a-z0-9])ai(?:$|[^a-z0-9])", job.company.lower()):
        return True

    # A role explicitly assigned to an AI/ML sales segment is also direct
    # product evidence; the independent role gate still has to pass.
    if re.search(
        r"\b(?:ai|artificial intelligence|generative ai|machine learning|ai/ml)\b",
        job.title.lower(),
    ):
        return True

    product_text = f"{job.title} {job.snippet or ''}".lower()
    return any(re.search(pattern, product_text) for pattern in AI_BUSINESS_PATTERNS)


def _is_enterprise_sales_role(title: str) -> bool:
    """Return True for enterprise sellers or sales/GTM/revenue leaders."""
    normalized = re.sub(r"\s+", " ", title.lower()).strip()
    if any(re.search(pattern, normalized) for pattern in SALES_ROLE_EXCLUSION_PATTERNS):
        return False
    return any(
        re.search(pattern, normalized)
        for pattern in ENTERPRISE_SALES_ROLE_PATTERNS + SALES_LEADERSHIP_ROLE_PATTERNS
    )


def prefilter_jobs(jobs: list[JobCard], keywords: dict) -> dict:
    """Apply strict AI-company and enterprise-sales relevance gates.

    A job passes the pre-filter if:
      - NOT in the role blacklist (academic, education, lecturer, etc.)
      - AND the company is a configured AI/AI-adjacent target OR the card
        contains evidence that it delivers an AI/AI-adjacent product
      - AND the title describes enterprise sales or sales/GTM/revenue leadership

    Returns surfaced and below_threshold lists plus URL-keyed rejection_reasons.
    """
    target_companies = keywords.get("ai_target_companies", AI_TARGET_COMPANIES)

    surfaced: list[JobCard] = []
    below_threshold: list[JobCard] = []
    rejection_reasons: dict[str, str] = {}

    for job in jobs:
        title_lower = job.title.lower()

        # Reject blacklisted role types immediately
        if any(blacklist_kw in title_lower for blacklist_kw in ROLE_BLACKLIST):
            below_threshold.append(job)
            rejection_reasons[job.url] = "Role type is excluded from the search"
            continue

        has_ai_company_fit = _is_ai_relevant_company(job, set(target_companies))
        has_sales_role_fit = _is_enterprise_sales_role(job.title)

        if has_ai_company_fit and has_sales_role_fit:
            surfaced.append(job)
        else:
            below_threshold.append(job)
            missing = []
            if not has_ai_company_fit:
                missing.append("company is not identified as AI-core, AI-product, or AI-adjacent")
            if not has_sales_role_fit:
                missing.append("role is not enterprise sales or sales leadership")
            reason = "; ".join(missing)
            rejection_reasons[job.url] = reason[:1].upper() + reason[1:]

    return {
        "surfaced": surfaced,
        "below_threshold": below_threshold,
        "rejection_reasons": rejection_reasons,
        "policy": "ai_company_and_enterprise_sales",
    }


def _read_candidate_context(reference_cv_path: Path) -> str:
    """Read a bounded reference CV excerpt for LLM triage."""
    try:
        text = reference_cv_path.read_text(encoding="utf-8")
    except OSError:
        return ""
    return text[:TRIAGE_CV_CONTEXT_CHARS]


def _extract_json_array(text: str) -> list[dict]:
    """Extract a JSON array from an LLM response."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end < start:
        raise ValueError("llm_response_missing_json_array")
    data = json.loads(text[start : end + 1])
    if not isinstance(data, list):
        raise ValueError("llm_response_not_array")
    return [item for item in data if isinstance(item, dict)]


def _build_triage_prompt(jobs: list[JobCard], candidate_context: str) -> str:
    """Build an evidence-constrained LLM triage prompt."""
    job_payload = [
        {
            "url": job.url,
            "title": job.title,
            "company": job.company,
            "location": job.location,
            "snippet": job.snippet,
        }
        for job in jobs
    ]
    return f"""
You are triaging LinkedIn job-alert cards for a candidate.

Candidate profile/resume excerpt:
{candidate_context or "(No resume excerpt available.)"}

Target opportunity:
- The company must have AI as a core business, sell AI products, or sell adjacent data/AI infrastructure products.
- The role must be enterprise sales, strategic account sales, field sales leadership, GTM leadership, revenue leadership, or a similarly senior commercial leadership role.
- Prefer opportunities aligned to the candidate's enterprise technology, public sector, cloud/data/AI, partner, and regional leadership background.
- Reject academic, instructor, sales engineering, solution consulting, customer success, SDR/BDR, pure marketing, product, engineering, and operations roles unless the title is clearly a senior sales/GTM/revenue leadership role.
- If the card is too ambiguous, reject it rather than guessing.

Return ONLY a JSON array. One object per job, preserving each URL exactly:
[
  {{
    "url": "same URL from input",
    "surface": true,
    "score": 0-100,
    "company_fit": "ai_core|ai_product|ai_adjacent|unclear|no",
    "role_fit": "enterprise_sales|sales_leadership|gtm_revenue_leadership|adjacent|no",
    "candidate_fit": "strong|moderate|weak|unclear",
    "reason": "short evidence-based explanation"
  }}
]

Jobs:
{json.dumps(job_payload, ensure_ascii=False, indent=2)}
""".strip()


def triage_jobs_with_llm(
    jobs: list[JobCard],
    candidate_context: str,
    *,
    provider=None,
    batch_size: int = TRIAGE_BATCH_SIZE,
    min_score: int = TRIAGE_MIN_SCORE,
) -> dict:
    """Use the configured LLM provider to classify discovery candidates."""
    if not jobs:
        return {"surfaced": [], "below_threshold": [], "rejection_reasons": {}, "policy": "llm_resume_triage"}

    if provider is None:
        from src.llm_provider import get_llm_provider

        provider = get_llm_provider()

    decisions: dict[str, dict] = {}
    for start in range(0, len(jobs), batch_size):
        batch = jobs[start : start + batch_size]
        prompt = _build_triage_prompt(batch, candidate_context)
        response = provider.generate_text(
            prompt,
            model=TRIAGE_LLM_MODEL,
            max_tokens=TRIAGE_LLM_MAX_TOKENS,
        )
        for item in _extract_json_array(response):
            url = str(item.get("url", ""))
            if url:
                decisions[url] = item

    surfaced: list[JobCard] = []
    below_threshold: list[JobCard] = []
    rejection_reasons: dict[str, str] = {}

    for job in jobs:
        decision = decisions.get(job.url)
        if not decision:
            below_threshold.append(job)
            rejection_reasons[job.url] = "LLM triage did not return a decision for this job"
            continue

        score = int(decision.get("score") or 0)
        reason = str(decision.get("reason") or "No reason supplied").strip()
        surface = bool(decision.get("surface")) and score >= min_score

        if surface:
            surfaced.append(job)
        else:
            below_threshold.append(job)
            rejection_reasons[job.url] = f"LLM triage rejected: {reason}"

    return {
        "surfaced": surfaced,
        "below_threshold": below_threshold,
        "rejection_reasons": rejection_reasons,
        "policy": "llm_resume_triage",
        "llm_decisions": decisions,
    }


def triage_jobs(jobs: list[JobCard], keywords: dict, reference_cv_path: Path) -> dict:
    """Triage jobs with LLM when enabled, otherwise use deterministic rules."""
    if TRIAGE_MODE == "llm":
        try:
            return triage_jobs_with_llm(jobs, _read_candidate_context(reference_cv_path))
        except Exception as exc:
            _log(f"ERROR: LLM triage failed: {exc}")
            if os.environ.get("JOB_DIGEST_TRIAGE_FAIL_OPEN", "false").lower() == "true":
                _log("WARNING: Falling back to rules because JOB_DIGEST_TRIAGE_FAIL_OPEN=true")
                return prefilter_jobs(jobs, keywords)
            raise
    return prefilter_jobs(jobs, keywords)


# ---------------------------------------------------------------------------
# Digest Markdown
# ---------------------------------------------------------------------------

def write_digest_markdown(
    digest_dir: Path,
    date_str: str,
    surfaced: list[JobCard],
    below_threshold: list[JobCard],
    stats: dict,
    rejection_reasons: dict[str, str] | None = None,
) -> Path:
    """Write the daily Markdown digest file and return its path."""
    digest_dir.mkdir(parents=True, exist_ok=True)
    filepath = digest_dir / f"{date_str}.md"

    lines = [f"# Job Discoveries — {date_str}", ""]

    # Surfaced section
    lines.append("## Surfaced for Review")
    lines.append("")
    if surfaced:
        for job in surfaced:
            lines.append(f"### {job.company} — {job.title}")
            lines.append(f"- **Location:** {job.location or 'N/A'}")
            lines.append(f"- **URL:** {job.url}")
            lines.append(f"- **Snippet:** {job.snippet or 'N/A'}")
            lines.append(f"- **Category:** surfaced")
            lines.append("")
            lines.append("---")
            lines.append("")
    else:
        lines.append("*(No jobs surfaced today)*")
        lines.append("")

    # Stats line
    lines.append(
        f"*({stats.get('processed', 0)} jobs processed, "
        f"{stats.get('surfaced', 0)} surfaced, "
        f"{stats.get('below_threshold', 0)} below threshold, "
        f"{stats.get('already_tracked', 0)} already tracked)*"
    )
    lines.append("")
    lines.append("---")
    lines.append("")

    # Below threshold section
    lines.append("## Below Threshold")
    lines.append("")
    if below_threshold:
        rejection_reasons = rejection_reasons or {}
        for job in below_threshold:
            lines.append(f"### {job.company} — {job.title}")
            lines.append(f"- **Location:** {job.location or 'N/A'}")
            lines.append(f"- **URL:** {job.url}")
            lines.append(f"- **Snippet:** {job.snippet or 'N/A'}")
            reason = rejection_reasons.get(job.url, "Below pre-filter threshold")
            lines.append(f"- **Reason:** {reason}")
            lines.append("")
    else:
        lines.append("*(No jobs below threshold)*")
        lines.append("")

    filepath.write_text("\n".join(lines), encoding="utf-8")
    return filepath


# ---------------------------------------------------------------------------
# Gmail API
# ---------------------------------------------------------------------------

def _extract_html_body(msg_data: dict) -> str | None:
    """Extract HTML from a Gmail message payload (base64 decode, handle multipart)."""
    payload = msg_data.get("payload", {})
    mime_type = payload.get("mimeType", "")

    # Helper: decode a base64 data payload
    def _decode_data(data: str) -> str:
        # Gmail uses URL-safe base64 without padding
        padded = data + "=" * (4 - len(data) % 4) if len(data) % 4 else data
        return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")

    # If multipart, recurse to find HTML part
    if mime_type.startswith("multipart/"):
        parts = payload.get("parts", [])
        for part in parts:
            if part.get("mimeType", "") == "text/html":
                data = part.get("body", {}).get("data")
                if data:
                    return _decode_data(data)
        # Fallback: search nested parts
        for part in parts:
            if part.get("mimeType", "").startswith("multipart/"):
                # Recurse into nested multipart
                nested = _extract_html_body({"payload": part})
                if nested:
                    return nested
        # Last resort: try text/plain
        for part in parts:
            if part.get("mimeType", "") == "text/plain":
                data = part.get("body", {}).get("data")
                if data:
                    return _decode_data(data)
        return None

    # Single-part HTML
    if mime_type == "text/html":
        data = payload.get("body", {}).get("data")
        if data:
            return _decode_data(data)

    # Single-part plain text (fallback)
    if mime_type == "text/plain":
        data = payload.get("body", {}).get("data")
        if data:
            return _decode_data(data)

    return None


def _get_email_date(msg_data: dict) -> str:
    """Extract date from Gmail message headers, return ISO-8601 date string."""
    headers = msg_data.get("payload", {}).get("headers", [])
    for header in headers:
        if header.get("name", "").lower() == "date":
            date_str = header.get("value", "")
            try:
                # Parse RFC 2822 date
                from email.utils import parsedate_to_datetime
                dt = parsedate_to_datetime(date_str)
                return dt.strftime("%Y-%m-%d")
            except Exception:
                pass
            # Fallback: try to extract YYYY-MM-DD
            m = re.search(r"(\d{4}-\d{2}-\d{2})", date_str)
            if m:
                return m.group(1)
    return date.today().isoformat()


def query_linkedin_emails(
    mgr: GmailAccountManager,
    account: str,
    after_date: str,
) -> list[dict]:
    """Query Gmail API for LinkedIn job-alert emails since after_date.

    Returns a list of {id, date, html} dicts.
    """
    token = mgr.get_access_token(account)
    if not token:
        _log(f"ERROR: Failed to get access token for account '{account}'")
        return []

    headers = {"Authorization": f"Bearer {token}"}

    # Search for LinkedIn job alert emails (two sender addresses):
    #   jobalerts-noreply = digest-format daily/weekly alerts
    #   jobs-noreply = individual job recommendations
    query = f"(from:jobalerts-noreply@linkedin.com OR from:jobs-noreply@linkedin.com) after:{after_date}"
    messages: list[dict] = []
    page_token: str | None = None

    while True:
        list_url = (
            f"{GMAIL_API_BASE}/messages?q={requests.utils.quote(query)}"
            f"&maxResults={GMAIL_LIST_PAGE_SIZE}"
        )
        if page_token:
            list_url += f"&pageToken={page_token}"

        try:
            resp = requests.get(list_url, headers=headers, timeout=15)
            if resp.status_code == 429:
                _log("WARNING: Gmail API rate limit hit, waiting 5s before retry")
                time.sleep(5)
                continue
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            _log(f"ERROR: Gmail list query failed: {e}")
            return []

        page_messages = data.get("messages", [])
        messages.extend(page_messages)
        _log(f"Fetched Gmail list page for '{account}': {len(page_messages)} messages (total: {len(messages)})")

        page_token = data.get("nextPageToken")
        if not page_token:
            break

    if not messages:
        return []

    # Fetch each message
    results: list[dict] = []
    for msg_summary in messages:
        msg_id = msg_summary["id"]
        try:
            msg_url = f"{GMAIL_API_BASE}/messages/{msg_id}?format=full"
            msg_resp = requests.get(msg_url, headers=headers, timeout=15)
            msg_resp.raise_for_status()
            msg_data = msg_resp.json()

            html = _extract_html_body(msg_data)
            email_date = _get_email_date(msg_data)

            results.append({
                "id": msg_id,
                "date": email_date,
                "html": html,
            })
        except requests.RequestException as e:
            _log(f"WARNING: Failed to fetch email {msg_id}: {e}")
            continue
        except Exception as e:
            _log(f"WARNING: Failed to process email {msg_id}: {e}")
            continue

    return results


def trash_emails(
    mgr: GmailAccountManager,
    account: str,
    message_ids: list[str],
) -> int:
    """Move emails to Trash via Gmail API. Returns count of successfully trashed."""
    token = mgr.get_access_token(account)
    if not token:
        _log("ERROR: Failed to get access token for trash operation")
        return 0

    headers = {"Authorization": f"Bearer {token}"}
    trashed = 0

    for msg_id in message_ids:
        try:
            url = f"{GMAIL_API_BASE}/messages/{msg_id}/trash"
            resp = requests.post(url, headers=headers, timeout=10)
            resp.raise_for_status()
            trashed += 1
        except requests.RequestException as e:
            _log(f"WARNING: Failed to trash email {msg_id}: {e}")
            continue

    return trashed


# ---------------------------------------------------------------------------
# Email notification
# ---------------------------------------------------------------------------

def _format_digest_email(
    surfaced: list[JobCard],
    stats: dict,
    date_str: str,
    recovery_note: str = "",
) -> tuple[str, str]:
    """Format email subject and body for the digest notification.

    Includes full URLs for each opportunity so user can click directly to apply.
    """
    surfaced_count = len(surfaced)
    subject = f"Job Discoveries — {date_str}: {surfaced_count} new roles"

    lines = [f"Job Discoveries for {date_str}", ""]

    if recovery_note:
        lines.append(recovery_note.rstrip())
        lines.append("")

    if surfaced:
        lines.append("🔥 Top Matches:")
        lines.append("")
        for i, job in enumerate(surfaced, 1):
            lines.append(f"{i}. {job.company} — {job.title}")
            lines.append(f"   Location: {job.location or 'N/A'}")
            if job.snippet:
                lines.append(f"   {job.snippet[:100]}...")
            lines.append(f"   URL: {job.url}")
            lines.append("")
    else:
        lines.append("(No relevant roles found today)")
        lines.append("")

    lines.append(
        f"📊 Stats: {stats.get('processed', 0)} processed, "
        f"{surfaced_count} surfaced, "
        f"{stats.get('below_threshold', 0)} below threshold, "
        f"{stats.get('already_tracked', 0)} already tracked"
    )
    lines.append("")
    lines.append(f'Full digest with all opportunities: review_daily_discoveries("{date_str}")')

    return subject, "\n".join(lines)


def _send_digest_email(subject: str, body: str) -> bool:
    """Send the digest via SMTP (fleet-notify). Returns True on success."""
    return send_email(subject, body, config=_SMTP_CONFIG)


def _send_alert_email(subject: str, body: str) -> bool:
    """Send an alert email (e.g. auth failure) via SMTP. Returns True on success."""
    return send_email(subject, body, config=_SMTP_CONFIG)


# ---------------------------------------------------------------------------
# Failure state
# ---------------------------------------------------------------------------

def _read_failure_state() -> dict | None:
    """Read the last unresolved digest failure state, if present."""
    if not FAILURE_STATE_PATH.exists():
        return None
    try:
        data = json.loads(FAILURE_STATE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _write_failure_state(reason: str, detail: str, date_str: str) -> None:
    """Persist a failure that must be visible after credentials recover."""
    previous = _read_failure_state() or {}
    first_failed_at = previous.get("first_failed_at") or datetime.now(timezone.utc).isoformat()
    state = {
        "ok": False,
        "first_failed_at": first_failed_at,
        "last_failed_at": datetime.now(timezone.utc).isoformat(),
        "run_date": date_str,
        "reason": reason,
        "detail": detail,
        "failure_count": int(previous.get("failure_count", 0)) + 1,
    }
    try:
        FAILURE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        FAILURE_STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    except OSError as e:
        _log(f"WARNING: Failed to write digest failure state: {e}")


def _clear_failure_state() -> None:
    """Clear the persisted failure state after a successful digest delivery."""
    try:
        FAILURE_STATE_PATH.unlink(missing_ok=True)
    except OSError as e:
        _log(f"WARNING: Failed to clear digest failure state: {e}")


def _format_recovery_note(failure_state: dict | None, after_date: str) -> str:
    """Return a concise recovery note for the next delivered digest."""
    if not failure_state:
        return ""

    first_failed_at = failure_state.get("first_failed_at", "unknown")
    last_failed_at = failure_state.get("last_failed_at", "unknown")
    failure_count = failure_state.get("failure_count", 1)
    reason = failure_state.get("reason", "unknown")
    detail = failure_state.get("detail", "")

    lines = [
        "Recovery note:",
        f"- Previous digest runs failed {failure_count} time(s).",
        f"- First failure: {first_failed_at}",
        f"- Last failure: {last_failed_at}",
        f"- Reason: {reason}",
    ]
    if detail:
        lines.append(f"- Detail: {detail}")
    lines.append(f"- This run caught up from the last successful marker: {after_date}")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Last-run timestamp
# ---------------------------------------------------------------------------

def _read_last_run() -> str | None:
    """Read the last-run timestamp file. Returns ISO date string or None."""
    if not LAST_RUN_FILE.exists():
        return None
    try:
        return LAST_RUN_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        return None


def _write_last_run(date_str: str) -> None:
    """Write the last-run timestamp file."""
    try:
        LAST_RUN_FILE.parent.mkdir(parents=True, exist_ok=True)
        LAST_RUN_FILE.write_text(date_str, encoding="utf-8")
    except OSError as e:
        _log(f"WARNING: Failed to write last-run timestamp: {e}")


def _acquire_run_lock(path: Path):
    """Acquire a non-blocking process lock; return its open handle or None."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None

    handle.seek(0)
    handle.truncate()
    handle.write(
        f"pid={os.getpid()} started_at="
        f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}\n"
    )
    handle.flush()
    return handle


def _release_run_lock(handle) -> None:
    """Release and close a handle returned by _acquire_run_lock."""
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def _run_pipeline(args: argparse.Namespace, today: str) -> int:
    """Run the pipeline after the caller has established single-run ownership."""
    _log(f"=== Job digest starting for {today} {'(DRY RUN)' if args.dry_run else ''} ===")

    # Check if digest already sent today (prevent duplicate emails from multiple timer runs)
    last_run = _read_last_run()
    if last_run == today and not args.dry_run:
        _log(f"INFO: Digest already processed for {today} — skipping to prevent duplicates")
        return 0

    # 1. Authenticate with Gmail API
    if not GMAIL_ACCOUNTS_CONFIG:
        _log("ERROR: GMAIL_ACCOUNTS_CONFIG env var not set")
        _write_failure_state(
            "gmail_config_missing",
            "GMAIL_ACCOUNTS_CONFIG env var is not set",
            today,
        )
        _send_alert_email(
            "Job Digest Auth Failure",
            f"Job digest failed: GMAIL_ACCOUNTS_CONFIG not set on {today}",
        )
        return 1

    mgr = GmailAccountManager(GMAIL_ACCOUNTS_CONFIG)
    if not mgr.accounts:
        _log("ERROR: No email accounts configured")
        _write_failure_state(
            "gmail_accounts_missing",
            "No Gmail accounts are configured or credentials could not be loaded",
            today,
        )
        _send_alert_email(
            "Job Digest Auth Failure",
            f"Job digest failed: No email accounts configured on {today}",
        )
        return 1

    # Authenticate all configured accounts; skip any that fail
    authenticated_accounts: list[str] = []
    for account_key in mgr.accounts:
        token = mgr.get_access_token(account_key)
        if token:
            authenticated_accounts.append(account_key)
            _log(f"Authenticated account: {account_key} ({mgr.accounts[account_key].email})")
        else:
            _log(f"WARNING: Skipping account '{account_key}' — auth failed")

    if not authenticated_accounts:
        _log("ERROR: No email accounts could be authenticated")
        _write_failure_state(
            "gmail_auth_failed",
            "Could not authenticate any configured Gmail account",
            today,
        )
        _send_alert_email(
            "Job Digest Auth Failure",
            f"Job digest failed: Could not authenticate any account on {today}",
        )
        return 1

    # 2. Determine query window
    last_run = _read_last_run()
    if last_run:
        after_date = last_run
    else:
        after_date = (date.today() - timedelta(days=30)).isoformat()
    _log(f"Querying LinkedIn emails after {after_date}")

    # 3. Query all authenticated accounts for LinkedIn job-alert emails
    all_emails: list[dict] = []
    seen_ids: set[tuple[str, str]] = set()
    for account_key in authenticated_accounts:
        account_emails = query_linkedin_emails(mgr, account_key, after_date)
        _log(f"Account '{account_key}': found {len(account_emails)} LinkedIn emails")
        for email_info in account_emails:
            seen_key = (account_key, email_info["id"])
            if seen_key not in seen_ids:
                email_info = dict(email_info)
                email_info["account_key"] = account_key
                all_emails.append(email_info)
                seen_ids.add(seen_key)
    emails = all_emails
    _log(f"Total unique LinkedIn emails across {len(authenticated_accounts)} account(s): {len(emails)}")

    if args.dry_run:
        print(f"DRY RUN: Gmail API access OK. Found {len(emails)} emails since {after_date}.")
        print("No digest written, no email sent, no emails trashed.")
        return 0

    if not emails:
        # No emails found: write empty digest, no email, no trash
        stats = {"processed": 0, "surfaced": 0, "below_threshold": 0, "already_tracked": 0}
        write_digest_markdown(DIGEST_DIR, today, [], [], stats)
        failure_state = _read_failure_state()
        if failure_state:
            recovery_note = _format_recovery_note(failure_state, after_date)
            sent = _send_alert_email(
                f"Job Digest Recovered — {today}",
                recovery_note + "No LinkedIn job-alert emails were waiting.",
            )
            _log(f"Recovery notification sent: {sent}")
            if sent:
                _clear_failure_state()
            else:
                _write_failure_state(
                    "digest_delivery_failed",
                    "Gmail access recovered, but the recovery notification email could not be sent",
                    today,
                )
                return 1
        _write_last_run(today)
        _log(f"Job digest complete (no emails): {stats}")
        return 0

    # 4. Parse job listings from each email
    all_jobs: list[JobCard] = []
    email_ids_by_account: dict[str, list[str]] = {}  # only IDs of emails that produced jobs
    skipped_ids: list[str] = []  # emails that didn't yield any jobs
    for email_info in emails:
        try:
            jobs = parse_linkedin_email(
                html=email_info.get("html"),
                source_email_id=email_info["id"],
                source_date=email_info.get("date", today),
            )
            if jobs:
                all_jobs.extend(jobs)
                account_key = email_info.get("account_key", "")
                email_ids_by_account.setdefault(account_key, []).append(email_info["id"])
            else:
                skipped_ids.append(email_info["id"])
                _log(f"INFO: Email {email_info['id']} yielded 0 jobs (kept in inbox)")
        except Exception as e:
            _log(f"WARNING: Failed to parse email {email_info.get('id', '?')}: {e}")
            continue

    parsed_email_count = sum(len(ids) for ids in email_ids_by_account.values())
    _log(f"Parsed {len(all_jobs)} total job cards from {parsed_email_count} emails")
    unique_alert_jobs = deduplicate_across_job_alerts(all_jobs)
    _log(f"Cross-alert dedup: {len(unique_alert_jobs)} unique jobs ({len(all_jobs) - len(unique_alert_jobs)} duplicates removed)")

    # 5. De-duplicate against tracker.json
    tracker = load_tracker(TRACKER_PATH)
    dedup_result = deduplicate_jobs(unique_alert_jobs, tracker)
    new_jobs = dedup_result["new"]
    already_tracked = dedup_result["already_tracked"]
    _log(f"Dedup: {len(new_jobs)} new, {len(already_tracked)} already tracked")

    # 6. Apply configured triage policy
    keywords = load_prefilter_keywords(REFERENCE_CV_PATH)
    try:
        filter_result = triage_jobs(new_jobs, keywords, REFERENCE_CV_PATH)
    except Exception as exc:
        _write_failure_state(
            "job_triage_failed",
            f"Job triage failed before digest delivery: {exc}",
            today,
        )
        _send_alert_email(
            "Job Digest Triage Failure",
            f"Job digest failed during triage on {today}: {exc}",
        )
        return 1
    surfaced = filter_result["surfaced"]
    below_threshold = filter_result["below_threshold"]
    _log(f"Triage ({filter_result.get('policy', 'unknown')}): {len(surfaced)} surfaced, {len(below_threshold)} below threshold")

    # 7. Write digest
    stats = {
        "processed": len(unique_alert_jobs),
        "surfaced": len(surfaced),
        "below_threshold": len(below_threshold),
        "already_tracked": len(already_tracked),
    }
    digest_path = write_digest_markdown(
        DIGEST_DIR,
        today,
        surfaced,
        below_threshold,
        stats,
        rejection_reasons=filter_result["rejection_reasons"],
    )
    _log(f"Digest written to {digest_path}")

    # 8. Send summary email
    failure_state = _read_failure_state()
    recovery_note = _format_recovery_note(failure_state, after_date)
    subject, body = _format_digest_email(surfaced, stats, today, recovery_note=recovery_note)
    sent = _send_digest_email(subject, body)
    _log(f"Email sent: {sent}")
    if not sent:
        _write_failure_state(
            "digest_delivery_failed",
            "Digest was written but SMTP delivery failed; source emails were kept for retry",
            today,
        )
        _log("ERROR: Digest delivery failed; keeping emails and last-run marker unchanged for catch-up")
        return 1

    # 9. Move processed LinkedIn emails to Trash (across all accounts)
    total_trashed = 0
    for account_key in authenticated_accounts:
        # Only trash emails belonging to this account
        account_email_ids = email_ids_by_account.get(account_key, [])
        trashed = trash_emails(mgr, account_key, account_email_ids)
        _log(f"Account '{account_key}': trashed {trashed} emails")
        total_trashed += trashed
    _log(f"Trashed {total_trashed} total emails across {len(authenticated_accounts)} account(s)")

    # 10. Update last-run timestamp
    _write_last_run(today)
    if failure_state:
        _clear_failure_state()

    _log(f"=== Job digest complete: {stats} ===")
    return 0


def main() -> int:
    """Run the daily job discovery digest pipeline."""
    parser = argparse.ArgumentParser(description="Daily LinkedIn job discovery digest")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Authenticate and query Gmail but do not write digest, send email, or trash emails",
    )
    args = parser.parse_args()
    today = date.today().isoformat()

    # Dry runs are read-only and do not contend with the scheduled production
    # run. Every mutating run holds this lock until all delivery and cleanup
    # work is complete, closing the race left by the end-of-run daily marker.
    if args.dry_run:
        return _run_pipeline(args, today)

    try:
        lock_handle = _acquire_run_lock(RUN_LOCK_PATH)
    except OSError as e:
        _log(f"ERROR: Could not acquire digest run lock at {RUN_LOCK_PATH}: {e}")
        return 1

    if lock_handle is None:
        _log("INFO: Another job digest process is already running — skipping duplicate invocation")
        return 0

    try:
        return _run_pipeline(args, today)
    finally:
        _release_run_lock(lock_handle)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    sys.exit(main())
