# MCP Tools — Quick Reference

## ✅ Status: Operational

**Service:** job-applications-mcp on pi-4 (port 8086)  
**Availability:** 24/7 (systemd service)  
**Authentication:** Bearer token  
**Tools:** 35+ available

---

## Accessing Tools

### Option 1: Claude Desktop (Stdio)
Automatic in active Claude Code sessions on Mac. Just ask naturally:
```
"List all opportunities in interview stage"
"Get details for opportunity 17ce1e4d-..."
"Update LinkedIn URL for this job"
```

### Option 2: Remote Access (HTTP)
Via pi-4 on port 8086 with bearer token auth:
```bash
curl -X POST http://gs-pi-4:8086/mcp/tools \
  -H "Authorization: Bearer <TOKEN>" \
  -d '{"tool": "list_opportunities", "arguments": {...}}'
```

---

## Top Tools

### Opportunity Management (NEW)

**`list_opportunities`**
- List with filtering (stage, company)
- Returns: id, company, role_title, stage, linkedin_url, days_elapsed
```
Stage filters: new, applied, screening, interview_r1, interview_r2, interview_r3, offer, rejected, closed_won
```

**`get_opportunity`**
- Full details + history + followups

**`update_opportunity_url`**
- Store LinkedIn URL for an opportunity

### Application Management

**`new_application`** — Create job application  
**`get_application_status`** — Current stage  
**`list_applications`** — Filter by company/stage  
**`update_application_stage`** — Advance in pipeline  
**`get_due_followups`** — Pending actions  

### CV & Interview

**`generate_tailored_cv`** — AI-powered CV generation  
**`log_interview_context`** — Capture interview details  
**`review_cv_changes`** — Analyze CV rewording  
**`check_fabrication_guard_options`** — Validate changes  

### Analysis & Research

**`analyze_jd`** — Extract JD requirements  
**`extract_jd_criteria`** — Skills + criteria  
**`research_company`** — Company background  
**`get_requirement_summary`** — Role requirements  

---

## Quick Examples

### List Interview R2 Opportunities
```
In Claude Desktop:
"Show me all opportunities in interview_r2 stage with their LinkedIn URLs"

Returns: 1 opportunity (IBM/Confluent Strategic Account Executive)
```

### Get Specific Opportunity
```
In Claude Desktop:
"Get full details for opportunity ibm-confluent-001"

Returns: All history, followups, URL, etc.
```

### Update URL
```
In Claude Desktop:
"Store the LinkedIn URL https://linkedin.com/jobs/view/4450177078/ for opportunity 17ce1e4d-..."

Returns: Success confirmation
```

---

## Data Structure

### Opportunity Object
```json
{
  "id": "17ce1e4d-b024-4d7a-88c7-a3fbd7c0e4c5",
  "company": "Thoughtworks",
  "role_title": "Client Partner - Singapore",
  "stage": "interview_r3",
  "date_created": "2026-08-04T02:00:00Z",
  "last_updated": "2026-08-09T02:00:00Z",
  "days_elapsed": 16,
  "linkedin_url": "https://www.linkedin.com/comm/jobs/view/4446107214/...",
  "jd_path": "Thoughtworks/client-partner-sg.md",
  "next_followup": {
    "action": "send_follow_up_email",
    "due_date": "2026-08-25"
  }
}
```

---

## Service Commands

### Check Status
```bash
ssh gs@gs-pi-4 'systemctl --user status job-applications-mcp.service'
```

### Restart Service
```bash
ssh gs@gs-pi-4 'systemctl --user restart job-applications-mcp.service'
```

### View Logs
```bash
ssh gs@gs-pi-4 'journalctl --user -u job-applications-mcp.service -n 50 -f'
```

---

## Token & Config

**Token Location:** `/home/gs/Projects/Job-Applications/.env` (pi-4)  
**Config File:** `job_applications_mcp_server.py`  
**Data Files:**
- `tracker.json` — All opportunities
- `cv_records.json` — CV versions
- `profile.json` — User profile

---

## Recent Updates

- ✅ 2026-08-20: Added opportunity management tools
- ✅ 2026-08-19: Gmail OAuth renewed, digest improved
- ✅ 2026-08-18: Fabrication guard options, PostgreSQL backend

---

## Next Steps

1. **For Claude Desktop:** Just use the tools naturally in conversations
2. **For External Agents:** Connect to http://gs-pi-4:8086 with bearer auth
3. **For URL Management:** Use `update_opportunity_url` to store LinkedIn links

---

**All tools are ready for use! 🚀**
