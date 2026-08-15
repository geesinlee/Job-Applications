# Job Applications MCP Server — Design Spec

**Date:** 2026-06-18  
**Status:** Approved  
**Approach:** Thin Orchestrator (Approach A)

## Problem

Applying for strategic roles (e.g., Gartner SAE Large Accounts) requires deep company research, interview preparation, document tailoring, and territory/contact mapping. This work is currently manual and fragmented across tools. Existing MCP servers (AI-Assistant, AI-CRM, Contact-Cleanup, GeBiz-Awards) already hold the data and capabilities needed — but they require the user to know which tool to call, in what order, with what parameters.

## Solution

A single `job-applications` MCP server that orchestrates existing tools into a coherent workflow. It does not store data itself — every write goes to either a Markdown file (in the company folder) or AI-CRM (for structured state). It composes, it does not duplicate.

## Architecture

### Folder Structure

```
Job-Applications/
├── .mcp.json                          # Connects all MCP servers
├── job_applications_mcp_server.py     # The thin orchestrator
├── requirements.txt                   # Python deps (fastmcp, etc.)
├── Gartner/                           # Per-company folder (already exists)
│   ├── JD.md                          # Job description (extracted from PDF)
│   ├── research.md                    # Deep research output
│   ├── territory_map.md               # Contacts & accounts mapping
│   ├── pitch.md                       # Interview pitch & questions
│   ├── Gartner_Cover_Letter_Lee_Gee_Sin.md  # (already exists)
│   ├── CV LEE Gee Sin.pdf             # (already exists)
│   └── ...
├── Salesforce/                        # Future company folders
│   └── ...
└── docs/
    └── superpowers/
        └── specs/
```

### MCP Server Configuration

The `.mcp.json` connects all five MCP servers (four existing + the new orchestrator):

```json
{
  "mcpServers": {
    "job-applications": {
      "command": "python3",
      "args": ["job_applications_mcp_server.py"]
    },
    "ai-assistant": {
      "command": "python3",
      "args": ["/Users/gslee/Projects/AI-Assistant/src/ai_assistant/mcp_server.py"]
    },
    "ai-crm": {
      "command": "node",
      "args": ["/Users/gslee/Projects/AI-CRM/dist/index.js"],
      "env": { "DATABASE_URL": "postgresql://ai_crm:ai_crm_dev@localhost:5433/ai_crm" }
    },
    "contacts": {
      "command": "python3",
      "args": ["/Users/gslee/Projects/Contact-Cleanup/contacts_mcp_server.py"],
      "env": { "CONTACTS_CACHE_PATH": "/Users/gslee/Projects/Contact-Cleanup/contacts_cache.json" }
    },
    "sgdi": {
      "command": "python3",
      "args": ["/Users/gslee/Projects/Contact-Cleanup/sgdi_mcp_server.py"],
      "env": { "SGDI_CACHE_PATH": "/Users/gslee/Projects/Contact-Cleanup/sgdi_cache.json" }
    },
    "gebiz-awards": {
      "command": "python3",
      "args": ["/Users/gslee/Projects/GeBiz-Awards/mcp_server.py"]
    }
  }
}
```

All servers run locally via stdio. The orchestrator calls them through Claude Code's MCP tool invocation.

## Tools

### 1. `company_research`

Deep-research a target company covering background, management team (Singapore & HQ), annual revenue, business model, strategy, competitors, and employee/partner sentiment.

```
company_research(company: str, focus?: str) → research.md path
```

- **company**: Target employer name (e.g., "Gartner")
- **focus**: Optional area to emphasize (e.g., "AI strategy", "public sector", "competitors")
- **Orchestrates**: deep-research skill (web search + synthesis) → AI-Assistant `search_contacts` → GeBiz-Awards `ask_question` (procurement footprint)
- **Writes**: `{company}/research.md`

### 2. `create_application`

Scaffold a company folder and create the corresponding AI-CRM Account and Opportunity.

```
create_application(company: str, jd_path: str, role_title?: str) → {account_id, opportunity_id, folder_path}
```

- **company**: Target employer name
- **jd_path**: Path to the job description file (PDF or Markdown)
- **role_title**: Optional role title override (defaults to extracting from JD)
- **Orchestrates**: AI-CRM `create_account` + `create_opportunity`
- **Creates**: Company folder if it doesn't exist, extracts JD text to `JD.md`

### 3. `map_territory`

Map the user's contacts for specific named accounts. The user provides account names; the tool finds and enriches relevant contacts.

```
map_territory(company: str, accounts: list[str]) → territory_map.md path
```

- **company**: Target employer name (for the file path)
- **accounts**: Specific account names to search (e.g., ["MTI", "GovTech", "MAS"])
- **Orchestrates**: AI-Assistant `search_contacts` (per account) → Contact-Cleanup `sgdi_query` (enrich titles/departments) → GeBiz-Awards `ask_question` (procurement history per account)
- **Writes**: `{company}/territory_map.md` — contacts grouped by account with name, role, email, phone, relationship notes

### 4. `generate_cover_letter`

Generate a tailored cover letter from the JD, research, and CV.

```
generate_cover_letter(company: str, tone?: str) → cover letter path
```

- **company**: Target employer name
- **tone**: "bold" | "conservative" | "storyteller" (default: the user's established "Ground Truth" style)
- **Reads**: `{company}/JD.md` + `{company}/research.md` + CV file
- **Writes**: `{company}/Cover_Letter.md` (updates in place if one exists)

### 5. `generate_pitch`

Generate interview pitch and questions from research, territory map, and MEDDPICC gaps.

```
generate_pitch(company: str, format?: str) → pitch.md path
```

- **company**: Target employer name
- **format**: "narrative" | "bullet_points" | "star_stories" (default: "narrative")
- **Reads**: `{company}/research.md` + `{company}/territory_map.md`
- **Orchestrates**: AI-CRM `get_meddpicc_gaps` (identify information gaps for the opportunity)
- **Writes**: `{company}/pitch.md`

### 6. `tailor_cv`

Produce a JD-tailored version of the CV highlighting relevant experience.

```
tailor_cv(company: str) → tailored CV path
```

- **company**: Target employer name
- **Reads**: `{company}/JD.md` + `{company}/research.md` + base CV file
- **Writes**: `{company}/CV_tailored.md`

## Data Flow

The workflow is sequential — each step produces output the next step reads:

```
create_application → company_research → map_territory → generate_pitch
                                     ↘                 ↗
                                      generate_cover_letter
                                      tailor_cv
```

Each tool is run individually by the user through Claude Code. The user reviews output between steps. There is no automated pipeline.

### Key Principle: Single Source of Truth

| Data | Home |
|------|------|
| Company research, pitch, territory map, cover letter, CV | Company folder (Markdown files) |
| Application state (account, opportunity, stages) | AI-CRM (PostgreSQL) |
| Contact data | AI-Assistant / Contact-Cleanup (SQLite + JSON cache) |
| Procurement data | GeBiz-Awards (SQLite) |
| SGDI government directory | Contact-Cleanup SGDI cache |

The orchestrator never duplicates data. It reads from and writes to the right place.

## Implementation Notes

- **Language**: Python with FastMCP (consistent with AI-Assistant, Contact-Cleanup, GeBiz-Awards)
- **Dependencies**: `fastmcp`, `pathlib`, standard library only — no new database, no new web framework
- **Error handling**: If an upstream MCP server is unavailable, the tool should skip that enrichment and note what was skipped in the output
- **No `advance_application` tool**: Application stages are managed directly in AI-CRM when needed

## Out of Scope

- Web dashboard or UI
- Auto-applying to jobs
- Email integration or outreach automation
- Resume parsing (JD extraction from PDF is in scope)
- Caching layer (YAGNI — re-run research if you need fresh data)