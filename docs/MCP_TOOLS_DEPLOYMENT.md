# MCP Tools Deployment & Access Guide

## Status: ✅ OPERATIONAL

The Job Applications MCP Server is deployed and accessible in two modes:

---

## 1. **Stdio Mode** (Claude Desktop on Mac)

**When:** Active Claude Code session on your Mac
**How:** Tools are automatically available in Claude Desktop
**Tools Available:**
- Application management (new_application, get_application_status, list_applications)
- Job description analysis (analyze_jd, extract_jd_criteria)
- CV generation (generate_tailored_cv)
- Interview context capture (log_interview_context, get_interview_context)
- Opportunity tracking (list_opportunities, get_opportunity, update_opportunity_url)
- Profile management (get_profile_summary, get_base_cv, get_reference_cv)
- And 30+ additional tools for research, requirement analysis, CV versioning, etc.

**To use:** Simply reference tool names in Claude Desktop conversations
```
"List all open opportunities in interview_r2 stage"
"Get opportunity details for ID: 17ce1e4d-..."
"Update LinkedIn URL for this opportunity"
```

---

## 2. **HTTP Mode** (Always-on on pi-4)

### Server Details
- **Host:** pi-4 (gs-pi-4.tail210e4f.ts.net via Tailscale)
- **Port:** 8086
- **Protocol:** HTTP with Bearer Token authentication
- **Status:** ✅ Running (systemd service: job-applications-mcp.service)
- **Service:** `/home/gs/Projects/Job-Applications/venv/bin/python3 -m job_applications_mcp_server`

### Authentication
```bash
Authorization: Bearer <MCP_AUTH_TOKEN>
```
Token: Stored in `.env` on pi-4 (rotated 2026-08-19)

### Available Endpoints

All tools are exposed as MCP Protocol endpoints. To call a tool:

```bash
# Example: List opportunities
curl -X POST http://gs-pi-4:8086/mcp/tools \
  -H "Authorization: Bearer bAU6I6d4QtiWbsjVxEnFWapSPoBbRymSV_ngz6cGa3g" \
  -H "Content-Type: application/json" \
  -d '{
    "tool": "list_opportunities",
    "arguments": {
      "stage": "interview_r2",
      "include_closed": false
    }
  }'
```

### New Tools (Recently Added)

#### `list_opportunities`
List job opportunities with stable IDs and LinkedIn URLs.

**Parameters:**
- `stage` (string, optional): Filter by stage (e.g., "interview_r2", "applied", "offer")
- `company` (string, optional): Filter by company name (case-insensitive substring)
- `include_closed` (boolean, default: false): Include rejected/closed_won opportunities

**Returns:**
```json
{
  "total": 4,
  "opportunities": [
    {
      "id": "17ce1e4d-...",
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
        "due_date": "2026-08-25",
        "id": "abc123"
      }
    }
  ],
  "filter_applied": {
    "stage": "interview_r3",
    "company": null,
    "include_closed": false
  }
}
```

#### `get_opportunity`
Get detailed information about a specific opportunity.

**Parameters:**
- `opportunity_id` (string, required): UUID from list_opportunities

**Returns:**
- Full opportunity details
- Complete history (all stage transitions with timestamps)
- All followups with status

#### `update_opportunity_url`
Store/update the LinkedIn URL for an opportunity.

**Parameters:**
- `opportunity_id` (string, required): UUID
- `linkedin_url` (string, required): Direct LinkedIn job URL

**Returns:**
```json
{
  "success": true,
  "opportunity_id": "17ce1e4d-...",
  "linkedin_url": "https://www.linkedin.com/comm/jobs/view/4450177078/"
}
```

### URL Discovery

The tools automatically discover LinkedIn URLs by:
1. Checking tracker metadata (if previously stored via `update_opportunity_url`)
2. Searching recent digest files (within ±30 days of application date)
3. Matching by company name and role title

If a URL is found from digests, it's returned immediately. Otherwise, you can manually store it via `update_opportunity_url`.

---

## 3. Remote Access (Tailscale)

### Setup

The pi-4 server is reachable via Tailscale:

```bash
# Via Tailscale hostname
curl -X POST https://gs-pi-4.tail210e4f.ts.net:8086/mcp/tools \
  -H "Authorization: Bearer bAU6I6d4QtiWbsjVxEnFWapSPoBbRymSV_ngz6cGa3g" \
  -H "Content-Type: application/json" \
  -d '{...}'
```

**Note:** Requires Tailscale connection to the personal tailnet (100.119.219.90 - 100.111.110.67 range).

### For External AI Agents

To integrate with other AI agents (e.g., Slack bots, automation servers):
1. Ensure they have Tailscale access to gs-pi-4
2. Configure Bearer token in their MCP client config
3. Point them to: `http://gs-pi-4:8086` or `https://gs-pi-4.tail210e4f.ts.net:8086`

---

## 4. Tool Categories

### Opportunity Management (NEW)
- `list_opportunities` — List with filtering
- `get_opportunity` — Full details
- `update_opportunity_url` — Store URLs

### Application Lifecycle
- `new_application` — Create application
- `get_application_status` — Check status
- `list_applications` — List by company/stage
- `update_application_stage` — Advance in pipeline
- `get_due_followups` — Pending actions

### Job Description Analysis
- `analyze_jd` — Extract requirements
- `extract_jd_criteria` — Get explicit + inferred skills
- `extract_jd_gaps` — Identify missing evidence

### CV & Evidence
- `generate_tailored_cv` — AI-powered CV generation
- `save_tailored_cv` — Store with version tracking
- `review_cv_changes` — Analyze rewording changes
- `check_fabrication_guard_options` — Validate CV changes

### Interview Context
- `log_interview_context` — Capture interview details
- `get_interview_context` — Retrieve by application
- `list_questions` — All questions asked

### Research & Planning
- `research_company` — Company background
- `research_territory` — Market landscape
- `get_requirement_summary` — Role requirements

---

## 5. Recent Deployments

### 2026-08-20
✅ Added opportunity management tools (list, get, update URL)
✅ LinkedIn URL auto-discovery from digests
✅ Stable UUID tracking (no artificial ID generation needed)

### 2026-08-19
✅ Gmail OAuth refresh token renewed
✅ Job digest filtering improved (role blacklist, stricter matching)
✅ Email now includes clickable LinkedIn URLs

### 2026-08-18
✅ Fabrication guard options (A, B, C) for CV rewording approval
✅ PostgreSQL backend wired for Gate 10 workflow
✅ Interview context capture tools registered

---

## 6. Testing the Tools

### From Mac (Stdio)
```
# In Claude Desktop
List all opportunities in interview_r2 stage and show their LinkedIn URLs
```

### From pi-4 (HTTP)
```bash
# Test list_opportunities
ssh gs@gs-pi-4 'cd ~/Projects/Job-Applications && \
  source venv/bin/activate && \
  python3 -c "from job_applications_mcp_server import list_opportunities; \
    print(list_opportunities(stage=\"interview_r3\"))"'
```

### From Remote (Tailscale)
```bash
# Requires Tailscale connection
curl -s http://gs-pi-4:8086/tools \
  -H "Authorization: Bearer bAU6I6d4QtiWbsjVxEnFWapSPoBbRymSV_ngz6cGa3g" | jq .
```

---

## 7. Troubleshooting

### Service not running
```bash
ssh gs@gs-pi-4
systemctl --user status job-applications-mcp.service
systemctl --user restart job-applications-mcp.service
```

### Bearer token rejected
- Verify token in `.env` on pi-4
- Ensure `MCP_AUTH_TOKEN` env var is set
- Check token is up to date (rotated 2026-08-19)

### URL discovery not working
- Check `digests/` directory exists
- Verify application date_created is within search range
- Manual `update_opportunity_url` as fallback

### Database connectivity
- PostgreSQL must be running on NAS (host: rv-cloud.local:5432)
- DATABASE_URL env var must be set
- Falls back to InMemoryEvidenceBackend if DB unavailable

---

## 8. Future Enhancements

Planned additions:
- [ ] Web UI for opportunity dashboard
- [ ] Slack integration for followup reminders
- [ ] Email notifications for stage changes
- [ ] CV version comparison tool
- [ ] Interview recording transcript analysis

---

**Last Updated:** 2026-08-20  
**Service Status:** ✅ Running  
**Tools Count:** 35+  
**Deployment:** stdio (Mac) + http (pi-4)
