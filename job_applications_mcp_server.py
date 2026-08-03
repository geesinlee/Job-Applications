#!/usr/bin/env python3
"""Job Applications MCP Server — Orchestrates job application workflow.

Manages company folders, job description parsing, research templates,
territory mapping, profile management, match scoring, gap analysis,
application tracking, and document generation for job applications.

Deployment:
  - stdio  : Mac (transient, during active Claude session)
  - http   : pi-4 gs-pi-4 :8086 (always-on systemd service)

Artefact files (JD.md, CVs, research) live on the NAS share.
tracker.json and profile.json live on pi-4 local disk, rsynced to NAS
after every write.
"""

import json
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv optional; env vars may be set by systemd EnvironmentFile

try:
    from PyPDF2 import PdfReader
except ImportError:
    PdfReader = None

from mcp.server.fastmcp import FastMCP

__version__ = "0.2.0"

# ---------------------------------------------------------------------------
# Configuration — env vars with __file__-relative fallbacks
# ---------------------------------------------------------------------------

_SRC_DIR = Path(__file__).resolve().parent

BASE_DIR = Path(os.environ.get("JOB_APP_BASE_DIR", str(_SRC_DIR)))
ARTEFACTS_DIR = Path(os.environ.get("JOB_APP_ARTEFACTS_DIR", str(BASE_DIR)))
TRACKER_PATH = Path(os.environ.get("JOB_APP_TRACKER_PATH", str(BASE_DIR / "tracker.json")))
PROFILE_PATH = Path(os.environ.get("JOB_APP_PROFILE_PATH", str(BASE_DIR / "profile.json")))
BASE_CV_PATH = Path(os.environ.get(
    "JOB_APP_BASE_CV_PATH",
    str(ARTEFACTS_DIR / "DXC" / "CV LEE Gee Sin 2026 - DXC Client Partner Public Sector.md"),
))
NAS_SYNC_PATH = os.environ.get("NAS_SYNC_PATH", "")   # e.g. gs@rv-cloud.local:/share/job-app-data/
MCP_MODE = os.environ.get("MCP_MODE", "stdio")         # "stdio" | "http"
MCP_AUTH_TOKEN = os.environ.get("MCP_AUTH_TOKEN", "")

# ---------------------------------------------------------------------------
# Startup validation
# ---------------------------------------------------------------------------

def _startup_validate() -> None:
    """Verify BASE_DIR exists; initialise tracker.json and profile.json if absent.
    Exits with code 1 (writing to stderr) if BASE_DIR is missing.
    """
    if not BASE_DIR.is_dir():
        sys.stderr.write(
            f"[job-applications] ERROR: BASE_DIR not found or not a directory: {BASE_DIR}\n"
            "Set JOB_APP_BASE_DIR to a valid path.\n"
        )
        sys.exit(1)

    if not TRACKER_PATH.exists():
        TRACKER_PATH.parent.mkdir(parents=True, exist_ok=True)
        TRACKER_PATH.write_text(
            json.dumps({"schema_version": "1.0", "applications": []}, indent=2),
            encoding="utf-8",
        )

    if not PROFILE_PATH.exists():
        PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        PROFILE_PATH.write_text(
            json.dumps({"schema_version": "1.0"}, indent=2),
            encoding="utf-8",
        )

_startup_validate()

# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def _utc_now() -> str:
    """Return current UTC time as ISO-8601 string, e.g. '2026-08-02T14:30:00Z'."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_tracker() -> dict:
    """Load tracker.json, returning empty schema on any read error."""
    try:
        return json.loads(TRACKER_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"schema_version": "1.0", "applications": []}


def _save_tracker(data: dict) -> None:
    """Save tracker.json and rsync to NAS backup (fire-and-forget)."""
    TRACKER_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    _nas_sync()


def _load_profile() -> dict:
    """Load profile.json, returning empty schema on any read error."""
    try:
        return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"schema_version": "1.0"}


def _save_profile(data: dict) -> None:
    """Save profile.json and rsync to NAS backup (fire-and-forget)."""
    PROFILE_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    _nas_sync()


def _nas_sync() -> None:
    """Rsync tracker.json and profile.json to NAS backup path (non-blocking).
    Silently skips if NAS_SYNC_PATH is not configured.
    """
    if not NAS_SYNC_PATH:
        return
    try:
        subprocess.Popen(
            ["rsync", "-a", str(TRACKER_PATH), str(PROFILE_PATH), NAS_SYNC_PATH],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        pass  # rsync not installed; skip silently


# ---------------------------------------------------------------------------
# Stage machine constants
# ---------------------------------------------------------------------------

VALID_STAGES = {
    "new", "applied", "screening",
    "interview_r1", "interview_r2", "interview_r3",
    "offer", "accepted", "rejected", "withdrawn",
}
TERMINAL_STAGES = {"accepted", "rejected", "withdrawn"}
INTERVIEW_STAGES = {"interview_r1", "interview_r2", "interview_r3"}

VALID_TRANSITIONS: dict[str, set[str]] = {
    "new":          {"applied", "rejected", "withdrawn"},
    "applied":      {"screening", "rejected", "withdrawn"},
    "screening":    {"interview_r1", "rejected", "withdrawn"},
    "interview_r1": {"interview_r2", "offer", "rejected", "withdrawn"},
    "interview_r2": {"interview_r3", "offer", "rejected", "withdrawn"},
    "interview_r3": {"offer", "rejected", "withdrawn"},
    "offer":        {"accepted", "rejected", "withdrawn"},
    "accepted":     set(),
    "rejected":     set(),
    "withdrawn":    set(),
}

# ---------------------------------------------------------------------------
# Path resolver helpers
# ---------------------------------------------------------------------------

def _make_role_slug(role_title: str) -> str:
    """Convert role title to URL-safe lowercase slug.
    e.g. 'Enterprise AE – Strategic Accounts' -> 'enterprise-ae-strategic-accounts'
    """
    slug = role_title.lower()
    slug = re.sub(r"[^\w\s-]", "", slug)   # remove special chars except hyphen
    slug = re.sub(r"[\s_]+", "-", slug)    # spaces/underscores to hyphens
    slug = re.sub(r"-+", "-", slug)        # collapse multiple hyphens
    return slug.strip("-")


class AmbiguousRoleError(ValueError):
    """Raised when a company has multiple roles and none is specified."""
    def __init__(self, company: str, roles: list[str]):
        self.company = company
        self.roles = roles
        super().__init__(f"Multiple roles at {company}: {roles}")


def _resolve_company_folder(
    company: str,
    role_title: str | None = None,
    tracker: dict | None = None,
) -> Path:
    """Return the correct artefact folder for this company+role.

    Logic:
    1. If the company root has JD.md directly (legacy single-role) and either
       no role_title is given or role_title matches the tracker record → return root.
    2. If role_title is given → return ARTEFACTS_DIR/Company/role-slug/.
    3. If multiple tracker records exist for this company and role_title is None → raise.
    4. Otherwise return the company root.
    """
    company_root = ARTEFACTS_DIR / company

    # Check how many tracker records exist for this company
    if tracker is None:
        tracker = _load_tracker()
    company_apps = [
        a for a in tracker.get("applications", [])
        if a["company"].lower() == company.lower()
    ]

    # Legacy root: JD.md exists at root with no sub-folders
    root_jd = company_root / "JD.md"
    has_root_jd = root_jd.exists()

    if role_title is None:
        if len(company_apps) > 1:
            raise AmbiguousRoleError(company, [a["role_title"] for a in company_apps])
        # Single or no record — use root
        return company_root

    # role_title given — check if it matches the legacy root record
    if has_root_jd and len(company_apps) <= 1:
        return company_root  # legacy single-role, use root

    # Multi-role: use slug sub-folder
    slug = _make_role_slug(role_title)
    return company_root / slug


def _find_application(tracker: dict, company: str, role_title: str | None) -> dict | None:
    """Find an application record by company (and optionally role_title)."""
    for app in tracker.get("applications", []):
        if app["company"].lower() != company.lower():
            continue
        if role_title is None or app["role_title"].lower() == role_title.lower():
            return app
    return None


# ---------------------------------------------------------------------------
# Follow-up helpers
# ---------------------------------------------------------------------------

def _days_from_now_utc(days: int) -> str:
    """Return date N days from today in YYYY-MM-DD format (UTC)."""
    from datetime import timedelta
    return (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%d")


def _auto_create_followup(app: dict, new_stage: str) -> None:
    """Create follow-up records on stage transition (Req 11)."""
    followups = app.setdefault("followups", [])

    if new_stage == "applied":
        # send_follow_up_email — deduplicate
        already = any(
            f["action_type"] == "send_follow_up_email" and f["status"] == "pending"
            for f in followups
        )
        if not already:
            followups.append({
                "id": str(uuid.uuid4()),
                "action_type": "send_follow_up_email",
                "due_date": _days_from_now_utc(7),
                "status": "pending",
                "completed_at": None,
            })

    elif new_stage in INTERVIEW_STAGES:
        # send_thank_you_note — deduplicate
        already = any(
            f["action_type"] == "send_thank_you_note" and f["status"] == "pending"
            for f in followups
        )
        if not already:
            followups.append({
                "id": str(uuid.uuid4()),
                "action_type": "send_thank_you_note",
                "due_date": _days_from_now_utc(1),
                "status": "pending",
                "completed_at": None,
            })
        # Cancel any pending follow-up email (Req 11.7)
        _cancel_followup_emails(app)


def _cancel_followup_emails(app: dict) -> None:
    """Set pending send_follow_up_email records to cancelled."""
    for f in app.get("followups", []):
        if f["action_type"] == "send_follow_up_email" and f["status"] == "pending":
            f["status"] = "cancelled"


# ---------------------------------------------------------------------------
# MCP server instance
# ---------------------------------------------------------------------------

mcp = FastMCP("job-applications")


def _company_dir(company: str) -> Path:
    """Return the path to a company folder, creating it if needed."""
    d = ARTEFACTS_DIR / company
    d.mkdir(parents=True, exist_ok=True)
    return d


def _extract_pdf_text(pdf_path: Path) -> str:
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


def _read_file(path: Path) -> str | None:
    """Read a text file, returning None if it doesn't exist."""
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def _find_cv(company_dir: Path) -> Path | None:
    """Find the CV file in a company folder (PDF or Markdown)."""
    for pattern in ["CV*.pdf", "CV*.md", "cv*.pdf", "cv*.md", "Resume*.pdf", "Resume*.md"]:
        matches = list(company_dir.glob(pattern))
        if matches:
            return matches[0]
    # Also check for exact-name CV files
    for f in company_dir.iterdir():
        if f.is_file() and "cv" in f.name.lower() and f.suffix in (".pdf", ".md"):
            return f
    return None


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

RESEARCH_TEMPLATE = """# {company} — Company Research

> Generated: {date} | Focus: {focus}

## 1. Company Overview
- Full name, ticker, headquarters
- Founded year, CEO, leadership team
- Core business model and revenue streams
- Employee count and global footprint

## 2. Financial Performance
- Annual revenue and growth trajectory
- Key financial metrics (ARR, margins, etc.)
- Recent earnings call highlights

## 3. Strategy & Positioning
- Stated strategic priorities (from annual report / 10-K)
- Key growth initiatives and bets
- Market positioning vs. competitors
- M&A activity and partnerships

## 4. Singapore / APAC Presence
- Singapore office: location, headcount, key leaders
- APAC revenue contribution
- Key accounts in the region
- Government and public sector relationships

## 5. Management Team
- CEO, CFO, CTO, CRO and other C-suite
- Regional/APAC leadership
- Board of directors (notable names)

## 6. Competitors
- Direct competitors and market share
- Competitive advantages and moats
- Recent competitive moves

## 7. Employee & Partner Sentiment
- Glassdoor/Indeed ratings and themes
- Common employee complaints and praise
- Partner/channel feedback
- Recent layoffs or hiring freezes

## 8. Procurement Footprint (Singapore Government)
- Government contracts and tenders
- Key agency relationships

## 9. Key Insights for Interview
- What problems is this company trying to solve?
- Where does my experience align?
- What questions should I ask?

---
*Research focus: {focus}*
"""

TERRITORY_TEMPLATE = """# {company} — Territory & Contact Map

> Generated: {date}

## Account: {account}

| Name | Role | Email | Phone | Organization | Relationship | Source |
|------|------|-------|-------|--------------|---------------|--------|
| (contacts will be listed here) | | | | | | |

### Warm Paths
- (Direct relationships that can provide introductions)

### Account Intelligence
- (Key decisions, procurement history, strategic priorities)

---
"""

COVER_LETTER_TONES = {
    "bold": "Bold and direct. Lead with your strongest differentiator. Use confident, assertive language. Take a clear position on why you're the right candidate.",
    "conservative": "Professional and measured. Follow traditional cover letter conventions. Emphasize qualifications and experience systematically.",
    "storyteller": "Narrative-driven. Weave your career story into a compelling arc that connects to the role. Use the 'Ground Truth' framing if relevant.",
}

PITCH_FORMATS = {
    "narrative": "Flowing narrative with a clear arc: opening hook, key messages, closing ask. Conversational tone.",
    "bullet_points": "Structured bullet points organized by topic. Quick to scan, easy to reference during interview.",
    "star_stories": "Situation-Task-Action-Result format for each key experience. Proves claims with evidence.",
}


# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def create_application(company: str, jd_path: str, role_title: str | None = None) -> dict:
    """Create a new job application folder and parse the job description.

    Creates the company folder, extracts text from the JD (PDF or Markdown),
    and writes JD.md. Returns structured data for setting up CRM records.

    After calling this tool, use the ai-crm create_account and create_opportunity
    tools to set up CRM tracking.

    Args:
        company: Target employer name (e.g., "Gartner"). Used as the folder name.
        jd_path: Path to the job description file (PDF or Markdown).
        role_title: Optional role title override. If omitted, extracted from JD.
    """
    tracker = _load_tracker()
    try:
        # Resolve using the caller-supplied role_title only — an extracted-from-JD
        # fallback must not influence folder placement (Req 10, legacy compat).
        company_dir = _resolve_company_folder(company, role_title, tracker)
    except AmbiguousRoleError as e:
        return {"ok": False, "error": "ambiguous_role", "company": e.company, "roles": e.roles}
    company_dir.mkdir(parents=True, exist_ok=True)

    jd_source = Path(jd_path)

    # Read and parse the JD
    if not jd_source.exists():
        return {"error": f"JD file not found: {jd_path}"}

    if jd_source.suffix.lower() == ".pdf":
        jd_text = _extract_pdf_text(jd_source)
    elif jd_source.suffix.lower() in (".md", ".markdown", ".txt"):
        jd_text = jd_source.read_text(encoding="utf-8")
    else:
        return {"error": f"Unsupported JD format: {jd_source.suffix}. Use PDF or Markdown."}

    # Extract role title from first line or filename if not provided (display only)
    if not role_title:
        first_line = jd_text.strip().split("\n")[0] if jd_text else ""
        if first_line and len(first_line) < 200:
            role_title = first_line.strip("# ").strip()
        else:
            role_title = jd_source.stem.replace("_", " ").replace("-", " ")

    # Write JD.md
    jd_md = company_dir / "JD.md"
    jd_md.write_text(jd_text, encoding="utf-8")

    # Check for existing CV
    cv_file = _find_cv(company_dir)

    return {
        "company": company,
        "folder_path": str(company_dir),
        "role_title": role_title,
        "jd_path": str(jd_md),
        "jd_length": len(jd_text),
        "cv_found": cv_file is not None,
        "cv_path": str(cv_file) if cv_file else None,
        "existing_files": [f.name for f in company_dir.iterdir() if f.is_file()],
        "next_steps": [
            "1. Use the deep-research skill to research the company",
            "2. Call company_research to save research results",
            "3. Use ai-crm create_account to create the company account",
            "4. Use ai-crm create_opportunity to create the job opportunity",
        ],
    }


@mcp.tool()
def get_application_status(company: str, role_title: str | None = None) -> dict:
    """Check the status of a job application workflow.

    Returns which files exist, what's been completed, and what steps remain.

    Args:
        company: Target employer name (e.g., "Gartner").
        role_title: Optional role title, required to disambiguate companies
            with multiple tracked roles.
    """
    tracker = _load_tracker()
    try:
        company_dir = _resolve_company_folder(company, role_title, tracker)
    except AmbiguousRoleError as e:
        return {"ok": False, "error": "ambiguous_role", "company": e.company, "roles": e.roles}
    if not company_dir.exists():
        return {
            "company": company,
            "exists": False,
            "next_steps": [
                "Call create_application first to set up the company folder.",
            ],
        }

    files = {f.name: f for f in company_dir.iterdir() if f.is_file()}
    cv_file = _find_cv(company_dir)

    # Check which workflow steps are completed
    steps = {
        "job_description": "JD.md" in files,
        "research": "research.md" in files,
        "territory_map": "territory_map.md" in files,
        "cover_letter": any("cover" in f.lower() or "letter" in f.lower() for f in files),
        "pitch": "pitch.md" in files,
        "tailored_cv": "CV_tailored.md" in files,
    }

    completed = [step for step, done in steps.items() if done]
    pending = [step for step, done in steps.items() if not done]

    # Determine next recommended action
    if not steps["job_description"]:
        next_action = "create_application"
    elif not steps["research"]:
        next_action = "company_research"
    elif not steps["territory_map"]:
        next_action = "map_territory"
    elif not steps["pitch"]:
        next_action = "generate_pitch"
    elif not steps["cover_letter"]:
        next_action = "generate_cover_letter"
    elif not steps["tailored_cv"]:
        next_action = "tailor_cv"
    else:
        next_action = "All steps completed!"

    return {
        "company": company,
        "folder_path": str(company_dir),
        "exists": True,
        "steps": steps,
        "completed": completed,
        "pending": pending,
        "next_action": next_action,
        "files": list(files.keys()),
        "cv_available": cv_file is not None,
    }


@mcp.tool()
def company_research(company: str, focus: str = "general") -> dict:
    """Get a structured research template for a target company, or view existing research.

    Returns a research template with sections covering company background, financials,
    strategy, management, competitors, and interview insights. Use the deep-research
    skill to fill in each section, then save the results to research.md.

    If research.md already exists, returns its content for reference.

    Args:
        company: Target employer name (e.g., "Gartner").
        focus: Area to emphasize in research (e.g., "AI strategy", "public sector",
               "competitors"). Default: "general".
    """
    company_dir = ARTEFACTS_DIR / company
    if not company_dir.exists():
        return {"error": f"Company folder '{company}' not found. Call create_application first."}

    research_file = company_dir / "research.md"
    existing_research = _read_file(research_file)

    template = RESEARCH_TEMPLATE.format(
        company=company,
        date=datetime.now().strftime("%Y-%m-%d"),
        focus=focus,
    )

    return {
        "company": company,
        "research_file": str(research_file),
        "existing_research": existing_research is not None,
        "template": template,
        "next_steps": [
            "1. Use the deep-research skill to research the company",
            "2. Fill in each section of the template",
            "3. Use search_contacts (ai-assistant) to find your contacts at the company",
            "4. Use ask_question (gebiz-awards) for procurement data",
            "5. Save completed research to research.md",
        ] if not existing_research else [
            "Research already exists. Review and update as needed.",
        ],
    }


@mcp.tool()
def save_research(company: str, content: str, focus: str = "general") -> dict:
    """Save company research content to research.md.

    Write the completed research content (typically from the deep-research skill)
    to the company's research.md file. Adds a header with date and focus area.

    Args:
        company: Target employer name (e.g., "Gartner").
        content: The research content in Markdown format.
        focus: Research focus area. Default: "general".
    """
    company_dir = ARTEFACTS_DIR / company
    if not company_dir.exists():
        return {"error": f"Company folder '{company}' not found. Call create_application first."}

    research_file = company_dir / "research.md"
    header = f"# {company} — Company Research\n\n> Generated: {datetime.now().strftime('%Y-%m-%d')} | Focus: {focus}\n\n"
    research_file.write_text(header + content, encoding="utf-8")

    return {
        "company": company,
        "path": str(research_file),
        "content_length": len(content),
        "saved": True,
    }


@mcp.tool()
def map_territory(company: str, accounts: list[str]) -> dict:
    """Get a territory mapping template for specific accounts at a target company.

    Returns a template for mapping your contacts to the target company's key accounts.
    For each account, use the ai-assistant search_contacts tool and sgdi_query tool
    to find and enrich contacts, then save results with save_territory_map.

    Args:
        company: Target employer name (e.g., "Gartner"). Used for the file path.
        accounts: Specific account names to search for contacts
                  (e.g., ["MTI", "GovTech", "MAS"]). These are the organizations
                  where you want to find your contacts.
    """
    company_dir = ARTEFACTS_DIR / company
    if not company_dir.exists():
        return {"error": f"Company folder '{company}' not found. Call create_application first."}

    territory_file = company_dir / "territory_map.md"
    existing = _read_file(territory_file)

    # Build per-account instructions
    account_instructions = []
    for account in accounts:
        account_instructions.append({
            "account": account,
            "mcp_calls": [
                f'ai-assistant search_contacts(company="{account}")',
                f'ai-assistant get_contacts_by_org(organization="{account}")',
                f'sgdi sgdi_query(organisation="{account.lower()}")',
                f'gebiz-awards ask_question(question="What contracts does {account} have with {company}?")',
            ],
        })

    return {
        "company": company,
        "territory_file": str(territory_file),
        "existing_territory_map": existing is not None,
        "accounts": accounts,
        "account_instructions": account_instructions,
        "template": TERRITORY_TEMPLATE.format(
            company=company,
            date=datetime.now().strftime("%Y-%m-%d"),
            account=", ".join(accounts),
        ),
        "next_steps": [
            f"1. For each account ({', '.join(accounts)}), call the MCP tools listed above",
            "2. Gather contact data: name, role, email, phone, organization",
            "3. Note warm paths and account intelligence",
            "4. Call save_territory_map with the formatted content",
        ],
    }


@mcp.tool()
def save_territory_map(company: str, content: str) -> dict:
    """Save territory and contact mapping to territory_map.md.

    Formats and saves the contact data gathered from ai-assistant,
    contacts, sgdi, and gebiz-awards into a structured territory map.

    Args:
        company: Target employer name (e.g., "Gartner").
        content: The territory map content in Markdown format.
    """
    company_dir = ARTEFACTS_DIR / company
    if not company_dir.exists():
        return {"error": f"Company folder '{company}' not found. Call create_application first."}

    territory_file = company_dir / "territory_map.md"
    header = f"# {company} — Territory & Contact Map\n\n> Generated: {datetime.now().strftime('%Y-%m-%d')}\n\n"
    territory_file.write_text(header + content, encoding="utf-8")

    return {
        "company": company,
        "path": str(territory_file),
        "content_length": len(content),
        "saved": True,
    }


@mcp.tool()
def generate_cover_letter(company: str, tone: str = "storyteller") -> dict:
    """Prepare context for generating a tailored cover letter.

    Reads the JD, research, and CV files from the company folder and returns
    them organized for cover letter generation. The actual content is generated
    by Claude Code using this context.

    Args:
        company: Target employer name (e.g., "Gartner").
        tone: Writing tone: "bold", "conservative", or "storyteller" (default).
              Storyteller uses the user's established "Ground Truth" framing.
    """
    company_dir = ARTEFACTS_DIR / company
    if not company_dir.exists():
        return {"error": f"Company folder '{company}' not found. Call create_application first."}

    # Read source files
    jd_content = _read_file(company_dir / "JD.md")
    research_content = _read_file(company_dir / "research.md")
    cv_file = _find_cv(company_dir)

    cv_content = None
    if cv_file:
        if cv_file.suffix.lower() == ".pdf":
            cv_content = _extract_pdf_text(cv_file)
        else:
            cv_content = _read_file(cv_file)

    # Find existing cover letter
    existing_letter = None
    for f in company_dir.iterdir():
        if f.is_file() and ("cover" in f.name.lower() or "letter" in f.name.lower()):
            existing_letter = _read_file(f)
            break

    tone_description = COVER_LETTER_TONES.get(tone, COVER_LETTER_TONES["storyteller"])

    missing = []
    if not jd_content:
        missing.append("JD.md — call create_application first")
    if not research_content:
        missing.append("research.md — call company_research first")
    if not cv_content:
        missing.append("CV file — add a CV to the company folder")

    return {
        "company": company,
        "tone": tone,
        "tone_description": tone_description,
        "source_files": {
            "jd": {"available": jd_content is not None, "length": len(jd_content) if jd_content else 0},
            "research": {"available": research_content is not None, "length": len(research_content) if research_content else 0},
            "cv": {"available": cv_content is not None, "length": len(cv_content) if cv_content else 0},
        },
        "jd_content": jd_content,
        "research_content": research_content,
        "cv_content": cv_content,
        "existing_cover_letter": existing_letter,
        "missing_sources": missing,
        "output_path": str(company_dir / "Cover_Letter.md"),
        "instructions": (
            "Generate a cover letter using the provided context. "
            f"Use a {tone} tone. "
            "Write the cover letter in Markdown format and save to the output_path. "
            "If an existing cover letter exists, update it in place."
        ),
    }


@mcp.tool()
def save_cover_letter(company: str, content: str, tone: str = "storyteller") -> dict:
    """Save a cover letter to the company folder.

    Args:
        company: Target employer name.
        content: The cover letter content in Markdown format.
        tone: The tone used (for the file header).
    """
    company_dir = ARTEFACTS_DIR / company
    if not company_dir.exists():
        return {"error": f"Company folder '{company}' not found."}

    # Check for existing cover letter to update in place
    existing_path = None
    for f in company_dir.iterdir():
        if f.is_file() and ("cover" in f.name.lower() or "letter" in f.name.lower()):
            existing_path = f
            break

    output_path = existing_path or company_dir / "Cover_Letter.md"
    header = f"# COVER LETTER: {company.upper()}\n\n> Tone: {tone} | Generated: {datetime.now().strftime('%Y-%m-%d')}\n\n"
    output_path.write_text(header + content, encoding="utf-8")

    return {
        "company": company,
        "path": str(output_path),
        "updated_existing": existing_path is not None,
        "content_length": len(content),
        "saved": True,
    }


@mcp.tool()
def generate_pitch(company: str, format: str = "narrative") -> dict:
    """Prepare context for generating an interview pitch and questions.

    Reads research and territory map files and returns them organized for pitch
    generation. Also checks for MEDDPICC gaps via ai-crm if an opportunity exists.

    Args:
        company: Target employer name (e.g., "Gartner").
        format: Output format: "narrative", "bullet_points", or "star_stories" (default: "narrative").
    """
    company_dir = ARTEFACTS_DIR / company
    if not company_dir.exists():
        return {"error": f"Company folder '{company}' not found. Call create_application first."}

    # Read source files
    jd_content = _read_file(company_dir / "JD.md")
    research_content = _read_file(company_dir / "research.md")
    territory_content = _read_file(company_dir / "territory_map.md")
    cv_file = _find_cv(company_dir)
    cv_content = None
    if cv_file:
        cv_content = _extract_pdf_text(cv_file) if cv_file.suffix.lower() == ".pdf" else _read_file(cv_file)

    existing_pitch = _read_file(company_dir / "pitch.md")

    format_description = PITCH_FORMATS.get(format, PITCH_FORMATS["narrative"])

    missing = []
    if not research_content:
        missing.append("research.md — call company_research first")
    if not territory_content:
        missing.append("territory_map.md — call map_territory first")

    return {
        "company": company,
        "format": format,
        "format_description": format_description,
        "source_files": {
            "jd": {"available": jd_content is not None, "length": len(jd_content) if jd_content else 0},
            "research": {"available": research_content is not None, "length": len(research_content) if research_content else 0},
            "territory_map": {"available": territory_content is not None, "length": len(territory_content) if territory_content else 0},
            "cv": {"available": cv_content is not None, "length": len(cv_content) if cv_content else 0},
        },
        "jd_content": jd_content,
        "research_content": research_content,
        "territory_map_content": territory_content,
        "cv_content": cv_content,
        "existing_pitch": existing_pitch,
        "missing_sources": missing,
        "output_path": str(company_dir / "pitch.md"),
        "instructions": (
            f"Generate an interview pitch using a {format} format. "
            "Include: 1) Your key messages, 2) Questions to ask the interviewers, "
            "3) How to address potential concerns, 4) Stories/evidence from your experience. "
            "After generating, also call ai-crm get_meddpicc_gaps to identify information gaps "
            "for this opportunity. Save the pitch to the output_path."
        ),
    }


@mcp.tool()
def save_pitch(company: str, content: str, format: str = "narrative") -> dict:
    """Save an interview pitch to the company folder.

    Args:
        company: Target employer name.
        content: The pitch content in Markdown format.
        format: The format used (for the file header).
    """
    company_dir = ARTEFACTS_DIR / company
    if not company_dir.exists():
        return {"error": f"Company folder '{company}' not found."}

    pitch_file = company_dir / "pitch.md"
    header = f"# {company} — Interview Pitch\n\n> Format: {format} | Generated: {datetime.now().strftime('%Y-%m-%d')}\n\n"
    pitch_file.write_text(header + content, encoding="utf-8")

    return {
        "company": company,
        "path": str(pitch_file),
        "content_length": len(content),
        "saved": True,
    }


@mcp.tool()
def tailor_cv(company: str) -> dict:
    """Prepare context for tailoring a CV to a specific job description.

    Reads the JD, research, and base CV files and returns them organized for
    CV tailoring. The actual tailoring is done by Claude Code using this context.

    Args:
        company: Target employer name (e.g., "Gartner").
    """
    company_dir = ARTEFACTS_DIR / company
    if not company_dir.exists():
        return {"error": f"Company folder '{company}' not found. Call create_application first."}

    # Read source files
    jd_content = _read_file(company_dir / "JD.md")
    research_content = _read_file(company_dir / "research.md")
    cv_file = _find_cv(company_dir)
    cv_content = None
    if cv_file:
        cv_content = _extract_pdf_text(cv_file) if cv_file.suffix.lower() == ".pdf" else _read_file(cv_file)

    existing_tailored = _read_file(company_dir / "CV_tailored.md")

    missing = []
    if not jd_content:
        missing.append("JD.md — call create_application first")
    if not cv_content:
        missing.append("CV file — add a CV (PDF or Markdown) to the company folder")

    return {
        "company": company,
        "source_files": {
            "jd": {"available": jd_content is not None, "length": len(jd_content) if jd_content else 0},
            "research": {"available": research_content is not None, "length": len(research_content) if research_content else 0},
            "cv": {
                "available": cv_content is not None,
                "length": len(cv_content) if cv_content else 0,
                "source_file": str(cv_file) if cv_file else None,
            },
        },
        "jd_content": jd_content,
        "research_content": research_content,
        "cv_content": cv_content,
        "existing_tailored_cv": existing_tailored,
        "missing_sources": missing,
        "output_path": str(company_dir / "CV_tailored.md"),
        "instructions": (
            "Generate a tailored CV that highlights experience relevant to the job description. "
            "Keep the same structure as the original CV but: "
            "1) Reorder bullet points to lead with JD-relevant achievements, "
            "2) Emphasize skills and experiences that match key JD requirements, "
            "3) Add a tailored professional summary at the top. "
            "Do NOT fabricate experience. Only reorganize and emphasize what's already there. "
            "Save the result to the output_path."
        ),
    }


@mcp.tool()
def save_tailored_cv(company: str, content: str) -> dict:
    """Save a tailored CV to the company folder.

    Args:
        company: Target employer name.
        content: The tailored CV content in Markdown format.
    """
    company_dir = ARTEFACTS_DIR / company
    if not company_dir.exists():
        return {"error": f"Company folder '{company}' not found."}

    cv_file = company_dir / "CV_tailored.md"
    header = f"# LEE GEE SIN — Tailored CV for {company}\n\n> Generated: {datetime.now().strftime('%Y-%m-%d')}\n\n"
    cv_file.write_text(header + content, encoding="utf-8")

    return {
        "company": company,
        "path": str(cv_file),
        "content_length": len(content),
        "saved": True,
    }


if __name__ == "__main__":
    mcp.run()
