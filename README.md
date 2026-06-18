# Job Applications MCP Server

Thin orchestrator MCP server for managing the job application workflow. Provides folder structure, templates, PDF parsing, and file I/O while Claude Code orchestrates calls to other MCP servers (AI-Assistant, AI-CRM, Contact-Cleanup, GeBiz-Awards).

## Tools

| Tool | Description |
|------|-------------|
| `create_application` | Create company folder, parse JD (PDF/Markdown), set up tracking |
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

Use `get_application_status` at any point to check progress.

## Company Folder Structure

```
Job-Applications/
├── Gartner/                           # Per-company folder
│   ├── JD.md                          # Job description (extracted from PDF)
│   ├── research.md                    # Deep research output
│   ├── territory_map.md               # Contacts & accounts mapping
│   ├── pitch.md                       # Interview pitch & questions
│   ├── Cover_Letter.md                # Tailored cover letter
│   ├── CV_tailored.md                 # JD-tailored CV
│   ├── Gartner Strategic Account Executive - Large Accounts.pdf  # Original JD
│   └── CV LEE Gee Sin.pdf            # Original CV
├── Salesforce/                        # Future company folders
└── ...
```

## Dependencies

- fastmcp
- PyPDF2

## Setup

```bash
pip install -r requirements.txt
```

## Running

```bash
python3 job_applications_mcp_server.py
```

The server runs on stdio (for Claude Code integration). See `.mcp.json` for the full MCP server configuration including AI-Assistant, AI-CRM, Contact-Cleanup, and GeBiz-Awards.

## Testing

```bash
python3 -m pytest test_mcp_server.py -v
```