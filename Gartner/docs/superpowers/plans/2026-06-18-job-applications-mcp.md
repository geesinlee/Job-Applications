# Job Applications MCP Server — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a thin orchestrator MCP server (Python/FastMCP) that manages the job application workflow — folder structure, templates, PDF parsing, and file I/O — while Claude Code orchestrates the calls to other MCP servers (AI-Assistant, AI-CRM, Contact-Cleanup, GeBiz-Awards).

**Architecture:** A single `job_applications_mcp_server.py` file using FastMCP (matching the pattern in GeBiz-Awards and Contact-Cleanup). The server provides 6 tools + 1 status tool. Each tool handles file I/O and templates; Claude Code handles content generation and orchestration of other MCP servers via their respective tools.

**Tech Stack:** Python 3, FastMCP, PyPDF2 (PDF parsing), pathlib, standard library only.

---

## Key Design Decision: Orchestration Boundary

The MCP server cannot call other MCP servers — that's Claude Code's job. Each tool's description tells Claude Code what other MCP calls to make before or after calling this tool. The pattern is:

1. Claude Code calls the job-applications tool to set up structure or read context
2. The tool returns structured data + next-step instructions
3. Claude Code calls other MCP servers (ai-assistant, ai-crm, etc.) as needed
4. Claude Code calls the job-applications tool again to save results

This keeps the orchestrator thin and the MCP server self-contained.

---

### Task 1: Project Setup

**Files:**
- Create: `job_applications_mcp_server.py`
- Create: `requirements.txt`
- Create: `.mcp.json`

- [ ] **Step 1: Create requirements.txt**

```txt
fastmcp>=0.1.0
PyPDF2>=3.0.0
```

- [ ] **Step 2: Create the MCP server skeleton**

Create `job_applications_mcp_server.py`:

```python
#!/usr/bin/env python3
"""Job Applications MCP Server — Orchestrates job application workflow.

Manages company folders, job description parsing, research templates,
territory mapping, and document generation for job applications.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

try:
    from PyPDF2 import PdfReader
except ImportError:
    PdfReader = None

mcp = FastMCP("job-applications")

# Base directory: the Job-Applications folder containing company subfolders
BASE_DIR = Path(__file__).resolve().parent


def _company_dir(company: str) -> Path:
    """Return the path to a company folder, creating it if needed."""
    d = BASE_DIR / company
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


# ... tools defined below ...
```

- [ ] **Step 3: Create .mcp.json**

Create `.mcp.json` in the `Job-Applications/` root (one level above `Gartner/`):

```json
{
  "mcpServers": {
    "job-applications": {
      "command": "python3",
      "args": ["job_applications_mcp_server.py"],
      "cwd": "/Users/gslee/Projects/Job-Applications"
    },
    "ai-assistant": {
      "command": "python3",
      "args": ["/Users/gslee/Projects/AI-Assistant/src/ai_assistant/mcp_server.py"]
    },
    "ai-crm": {
      "command": "node",
      "args": ["/Users/gslee/Projects/AI-CRM/dist/index.js"],
      "env": {
        "DATABASE_URL": "postgresql://ai_crm:ai_crm_dev@localhost:5433/ai_crm"
      }
    },
    "contacts": {
      "command": "python3",
      "args": ["/Users/gslee/Projects/Contact-Cleanup/contacts_mcp_server.py"],
      "env": {
        "CONTACTS_CACHE_PATH": "/Users/gslee/Projects/Contact-Cleanup/contacts_cache.json"
      }
    },
    "sgdi": {
      "command": "python3",
      "args": ["/Users/gslee/Projects/Contact-Cleanup/sgdi_mcp_server.py"],
      "env": {
        "SGDI_CACHE_PATH": "/Users/gslee/Projects/Contact-Cleanup/sgdi_cache.json"
      }
    },
    "gebiz-awards": {
      "command": "python3",
      "args": ["/Users/gslee/Projects/GeBiz-Awards/mcp_server.py"]
    }
  }
}
```

- [ ] **Step 4: Install dependencies**

Run: `pip install fastmcp PyPDF2`

- [ ] **Step 5: Test the server starts**

Run: `python3 job_applications_mcp_server.py` — it should start without errors (it will listen on stdio and exit when no input is received, which is expected).

- [ ] **Step 6: Commit**

```bash
cd /Users/gslee/Projects/Job-Applications
git init
git add job_applications_mcp_server.py requirements.txt .mcp.json
git commit -m "feat: job applications MCP server skeleton with project setup"
```

---

### Task 2: `create_application` Tool

**Files:**
- Modify: `job_applications_mcp_server.py`

- [ ] **Step 1: Add the `create_application` tool**

Add this tool function to `job_applications_mcp_server.py`:

```python
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
    company_dir = _company_dir(company)
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

    # Extract role title from first line or filename if not provided
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
```

- [ ] **Step 2: Test with the existing Gartner JD**

Run a quick test: Start the server, call `create_application` with company="Gartner" and jd_path pointing to the existing JD PDF. Verify that:
- The Gartner folder is not recreated (it already exists)
- JD.md is created with extracted text
- The return value includes role_title and next_steps

- [ ] **Step 3: Commit**

```bash
git add job_applications_mcp_server.py
git commit -m "feat: add create_application tool with JD parsing"
```

---

### Task 3: `get_application_status` Tool

**Files:**
- Modify: `job_applications_mcp_server.py`

- [ ] **Step 1: Add the `get_application_status` tool**

```python
@mcp.tool()
def get_application_status(company: str) -> dict:
    """Check the status of a job application workflow.

    Returns which files exist, what's been completed, and what steps remain.

    Args:
        company: Target employer name (e.g., "Gartner").
    """
    company_dir = BASE_DIR / company
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
```

- [ ] **Step 2: Test with the existing Gartner folder**

Call `get_application_status("Gartner")` and verify it correctly identifies the existing cover letter and CV, and shows research, territory_map, pitch, etc. as pending.

- [ ] **Step 3: Commit**

```bash
git add job_applications_mcp_server.py
git commit -m "feat: add get_application_status tool"
```

---

### Task 4: `company_research` Tool

**Files:**
- Modify: `job_applications_mcp_server.py`

- [ ] **Step 1: Add the research template function**

Add this helper and tool:

```python
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
    company_dir = BASE_DIR / company
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
    company_dir = BASE_DIR / company
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
```

- [ ] **Step 2: Test the research template**

Call `company_research("Gartner", focus="AI strategy and public sector")` and verify the template has all 9 sections. Also test `save_research` with sample content.

- [ ] **Step 3: Commit**

```bash
git add job_applications_mcp_server.py
git commit -m "feat: add company_research and save_research tools"
```

---

### Task 5: `map_territory` Tool

**Files:**
- Modify: `job_applications_mcp_server.py`

- [ ] **Step 1: Add the `map_territory` and `save_territory_map` tools**

```python
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
    company_dir = BASE_DIR / company
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
    company_dir = BASE_DIR / company
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
```

- [ ] **Step 2: Test with Gartner accounts**

Call `map_territory("Gartner", accounts=["MTI", "GovTech", "MAS"])` and verify it returns the correct MCP call instructions for each account.

- [ ] **Step 3: Commit**

```bash
git add job_applications_mcp_server.py
git commit -m "feat: add map_territory and save_territory_map tools"
```

---

### Task 6: `generate_cover_letter` Tool

**Files:**
- Modify: `job_applications_mcp_server.py`

- [ ] **Step 1: Add the `generate_cover_letter` tool**

```python
COVER_LETTER_TONES = {
    "bold": "Bold and direct. Lead with your strongest differentiator. Use confident, assertive language. Take a clear position on why you're the right candidate.",
    "conservative": "Professional and measured. Follow traditional cover letter conventions. Emphasize qualifications and experience systematically.",
    "storyteller": "Narrative-driven. Weave your career story into a compelling arc that connects to the role. Use the 'Ground Truth' framing if relevant.",
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
    company_dir = BASE_DIR / company
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
    company_dir = BASE_DIR / company
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
```

- [ ] **Step 2: Test with Gartner**

Call `generate_cover_letter("Gartner", tone="storyteller")` and verify it reads the existing JD, cover letter, and CV. Check that missing_sources correctly identifies research.md as missing.

- [ ] **Step 3: Commit**

```bash
git add job_applications_mcp_server.py
git commit -m "feat: add generate_cover_letter and save_cover_letter tools"
```

---

### Task 7: `generate_pitch` Tool

**Files:**
- Modify: `job_applications_mcp_server.py`

- [ ] **Step 1: Add the `generate_pitch` tool**

```python
PITCH_FORMATS = {
    "narrative": "Flowing narrative with a clear arc: opening hook, key messages, closing ask. Conversational tone.",
    "bullet_points": "Structured bullet points organized by topic. Quick to scan, easy to reference during interview.",
    "star_stories": "Situation-Task-Action-Result format for each key experience. Proves claims with evidence.",
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
    company_dir = BASE_DIR / company
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
    company_dir = BASE_DIR / company
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
```

- [ ] **Step 2: Test**

Call `generate_pitch("Gartner", format="narrative")` and verify it correctly reads available source files and reports missing ones.

- [ ] **Step 3: Commit**

```bash
git add job_applications_mcp_server.py
git commit -m "feat: add generate_pitch and save_pitch tools"
```

---

### Task 8: `tailor_cv` Tool

**Files:**
- Modify: `job_applications_mcp_server.py`

- [ ] **Step 1: Add the `tailor_cv` tool**

```python
@mcp.tool()
def tailor_cv(company: str) -> dict:
    """Prepare context for tailoring a CV to a specific job description.

    Reads the JD, research, and base CV files and returns them organized for
    CV tailoring. The actual tailoring is done by Claude Code using this context.

    Args:
        company: Target employer name (e.g., "Gartner").
    """
    company_dir = BASE_DIR / company
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
    company_dir = BASE_DIR / company
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
```

- [ ] **Step 2: Add the main entry point**

At the bottom of `job_applications_mcp_server.py`, add:

```python
if __name__ == "__main__":
    mcp.run()
```

- [ ] **Step 3: Test the full server**

Start the server: `python3 job_applications_mcp_server.py`
Verify it starts without errors.

- [ ] **Step 4: Commit**

```bash
git add job_applications_mcp_server.py
git commit -m "feat: add tailor_cv and save_tailored_cv tools, complete all 8 tools"
```

---

### Task 9: End-to-End Integration Test

**Files:**
- Create: `test_mcp_server.py`

- [ ] **Step 1: Write integration tests**

Create `test_mcp_server.py`:

```python
"""Integration tests for the job-applications MCP server.

Tests the full workflow: create_application → company_research → map_territory →
generate_cover_letter → generate_pitch → tailor_cv.
"""

import json
import tempfile
from pathlib import Path

from job_applications_mcp_server import (
    create_application,
    get_application_status,
    company_research,
    save_research,
    map_territory,
    save_territory_map,
    generate_cover_letter,
    save_cover_letter,
    generate_pitch,
    save_pitch,
    tailor_cv,
    save_tailored_cv,
    BASE_DIR,
)


class TestCreateApplication:
    def test_create_with_markdown_jd(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        jd_file = tmp_path / "test_jd.md"
        jd_file.write_text("# Senior Developer\nWe need a developer...")
        result = create_application("TestCo", str(jd_file))
        assert result["company"] == "TestCo"
        assert result["role_title"] == "Senior Developer"
        assert result["jd_length"] > 0
        assert (tmp_path / "TestCo" / "JD.md").exists()

    def test_create_existing_folder(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        company_dir = tmp_path / "ExistingCo"
        company_dir.mkdir()
        (company_dir / "existing.txt").write_text("data")
        jd_file = tmp_path / "jd.md"
        jd_file.write_text("# Role")
        result = create_application("ExistingCo", str(jd_file))
        assert result["company"] == "ExistingCo"
        assert "existing.txt" in result["existing_files"]


class TestGetApplicationStatus:
    def test_status_nonexistent_company(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        result = get_application_status("NonexistentCo")
        assert result["exists"] is False

    def test_status_with_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        company_dir = tmp_path / "TestCo"
        company_dir.mkdir()
        (company_dir / "JD.md").write_text("# JD")
        (company_dir / "research.md").write_text("# Research")
        result = get_application_status("TestCo")
        assert result["exists"] is True
        assert result["steps"]["job_description"] is True
        assert result["steps"]["research"] is True
        assert result["steps"]["territory_map"] is False


class TestCompanyResearch:
    def test_research_template(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        company_dir = tmp_path / "TestCo"
        company_dir.mkdir()
        result = company_research("TestCo", focus="AI strategy")
        assert result["company"] == "TestCo"
        assert "AI strategy" in result["template"]
        assert len(result["next_steps"]) > 0

    def test_save_research(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        company_dir = tmp_path / "TestCo"
        company_dir.mkdir()
        result = save_research("TestCo", "# Test Research\n\nSome content.", focus="AI")
        assert result["saved"] is True
        assert (company_dir / "research.md").exists()


class TestMapTerritory:
    def test_territory_template(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        company_dir = tmp_path / "TestCo"
        company_dir.mkdir()
        result = map_territory("TestCo", accounts=["MTI", "GovTech"])
        assert result["company"] == "TestCo"
        assert len(result["account_instructions"]) == 2
        assert any("MTI" in instr["account"] for instr in result["account_instructions"])

    def test_save_territory_map(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        company_dir = tmp_path / "TestCo"
        company_dir.mkdir()
        result = save_territory_map("TestCo", "# Territory Map\n\nMTI contacts...")
        assert result["saved"] is True
        assert (company_dir / "territory_map.md").exists()


class TestGenerateCoverLetter:
    def test_cover_letter_context(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        company_dir = tmp_path / "TestCo"
        company_dir.mkdir()
        (company_dir / "JD.md").write_text("# Senior Developer\nJob desc...")
        (company_dir / "research.md").write_text("# Research\nCompany info...")
        result = generate_cover_letter("TestCo", tone="storyteller")
        assert result["company"] == "TestCo"
        assert result["source_files"]["jd"]["available"] is True
        assert result["source_files"]["research"]["available"] is True

    def test_save_cover_letter(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        company_dir = tmp_path / "TestCo"
        company_dir.mkdir()
        result = save_cover_letter("TestCo", "Dear Hiring Team,\n\nI am writing...")
        assert result["saved"] is True


class TestGeneratePitch:
    def test_pitch_context(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        company_dir = tmp_path / "TestCo"
        company_dir.mkdir()
        (company_dir / "research.md").write_text("# Research")
        (company_dir / "territory_map.md").write_text("# Territory")
        result = generate_pitch("TestCo", format="bullet_points")
        assert result["format"] == "bullet_points"

    def test_save_pitch(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        company_dir = tmp_path / "TestCo"
        company_dir.mkdir()
        result = save_pitch("TestCo", "# Pitch\n\nKey messages...")
        assert result["saved"] is True


class TestTailorCv:
    def test_cv_context(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        company_dir = tmp_path / "TestCo"
        company_dir.mkdir()
        (company_dir / "JD.md").write_text("# Developer\nRequirements...")
        (company_dir / "CV_Lee_Gee_Sin.pdf").write_text("dummy pdf")
        result = tailor_cv("TestCo")
        assert result["source_files"]["jd"]["available"] is True

    def test_save_tailored_cv(self, tmp_path, monkeypatch):
        monkeypatch.setattr("job_applications_mcp_server.BASE_DIR", tmp_path)
        company_dir = tmp_path / "TestCo"
        company_dir.mkdir()
        result = save_tailored_cv("TestCo", "# Tailored CV\n\nExperience...")
        assert result["saved"] is True
        assert (company_dir / "CV_tailored.md").exists()
```

- [ ] **Step 2: Run the tests**

Run: `cd /Users/gslee/Projects/Job-Applications && python3 -m pytest test_mcp_server.py -v`

Expected: All tests pass.

- [ ] **Step 3: Fix any test failures**

If tests fail, debug and fix the issues. Common problems:
- Import paths (the module needs to be importable)
- monkeypatch not correctly patching BASE_DIR (need to patch in the module namespace)

- [ ] **Step 4: Commit**

```bash
git add test_mcp_server.py
git commit -m "test: add integration tests for all 8 MCP tools"
```

---

### Task 10: Real-World Validation with Gartner

**Files:**
- No new files — validation against existing Gartner data

- [ ] **Step 1: Test `create_application` with real Gartner JD**

In Claude Code, call `create_application` with the existing Gartner JD PDF. Verify JD text extraction works and the folder structure is preserved.

- [ ] **Step 2: Test `get_application_status` with Gartner**

Verify it correctly identifies the existing cover letter and CV files.

- [ ] **Step 3: Test `company_research` template**

Call `company_research("Gartner", focus="AI strategy and public sector")`. Verify the template includes all 9 sections and the focus area.

- [ ] **Step 4: Test `map_territory` with MTI, GovTech, MAS**

Call `map_territory("Gartner", accounts=["MTI", "GovTech", "MAS"])`. Verify the MCP call instructions are correct and reference the right tools.

- [ ] **Step 5: Test `generate_cover_letter` with existing Gartner data**

Call `generate_cover_letter("Gartner", tone="storyteller")`. Verify it reads the existing JD, cover letter, and CV.

- [ ] **Step 6: Commit any fixes**

```bash
git add -A
git commit -m "fix: adjustments from real-world Gartner validation"
```

---

### Task 11: Final Cleanup and Documentation

**Files:**
- Modify: `job_applications_mcp_server.py` (if needed)
- Create: `README.md`

- [ ] **Step 1: Add docstring and version to the server**

Add at the top of the file (after imports):

```python
__version__ = "0.1.0"
```

- [ ] **Step 2: Create README.md**

```markdown
# Job Applications MCP Server

Thin orchestrator MCP server for managing the job application workflow.

## Tools

| Tool | Description |
|------|-------------|
| `create_application` | Create company folder, parse JD, set up CRM tracking |
| `get_application_status` | Check which workflow steps are completed |
| `company_research` | Get research template for a target company |
| `save_research` | Save completed research to research.md |
| `map_territory` | Get territory mapping template for specific accounts |
| `save_territory_map` | Save contact/territory mapping to territory_map.md |
| `generate_cover_letter` | Prepare context for cover letter generation |
| `save_cover_letter` | Save cover letter to company folder |
| `generate_pitch` | Prepare context for interview pitch generation |
| `save_pitch` | Save interview pitch to company folder |
| `tailor_cv` | Prepare context for CV tailoring |
| `save_tailored_cv` | Save tailored CV to company folder |

## Workflow

1. `create_application` → Set up company folder and parse JD
2. `company_research` → Research template, then `save_research`
3. `map_territory` → Territory template, then `save_territory_map`
4. `generate_pitch` → Pitch context, then `save_pitch`
5. `generate_cover_letter` → Cover letter context, then `save_cover_letter`
6. `tailor_cv` → CV context, then `save_tailored_cv`

## Dependencies

- fastmcp
- PyPDF2

## Setup

```bash
pip install -r requirements.txt
```

Run with: `python3 job_applications_mcp_server.py`
```

- [ ] **Step 3: Final commit**

```bash
git add README.md job_applications_mcp_server.py
git commit -m "docs: add README and version number"
```