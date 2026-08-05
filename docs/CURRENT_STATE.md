# Current State — Job Applications MCP Server

> Last updated: 2026-08-04. Update this file when implementation status changes.

## Version

**v0.3.0** — NAS-shared data paths for multi-host sync (commit `b51d9e1`)

## Implementation Status

### Completed (all 10 implementation tasks done)

| Task | Description | Status |
|------|-------------|--------|
| 1 | Foundation — config, startup validation, persistence helpers | ✅ Done |
| 2 | Path resolver — multi-role folder support | ✅ Done |
| 3 | Tracker — stage machine, application records, follow-ups | ✅ Done |
| 4 | JD Ingestor — file/URL ingestion, structured field extraction | ✅ Done |
| 5 | Profile manager — CV seeding, LinkedIn merge, conflict detection | ✅ Done |
| 6 | Intelligence tools — match scoring, gap analysis, learning programs | ✅ Done |
| 7 | Document generation extensions — CV protection, cover letter versioning | ✅ Done |
| 8 | Export engine — PDF and DOCX generation | ✅ Done |
| 9 | pi-4 deployment — systemd units, daily tracker, NAS sync | ✅ Done |
| 10 | Integration tests and README update | ✅ Done |

### Not Yet Implemented

| Task | Description | Status |
|------|-------------|--------|
| 11 | LinkedIn job-alert discovery + Gmail API OAuth | 🔲 Backlog |

## Working Functionality

- **MCP server** running on pi-4 as `job-applications-mcp.service` (HTTP :8086, bearer auth)
- **Daily digest** via `job-applications-tracker.timer` (07:00, emails overdue follow-ups)
- **24 MCP tools** functional and tested (including `ingest_jd` with `jd_text` parameter, `save_interview_notes`, `mark_submitted`)
- **Output tracking** — all `save_*` functions record outputs in tracker `outputs` dict
- **Submitted folder** — `mark_submitted` snapshots CV/cover letter to `submitted/` subfolder
- **NAS data storage** at `/mnt/job-app-data` (NFS mount from rv-cloud.local)
- **Claude Desktop** connects via `mcp-remote` to `gs-pi-4.local:8086/mcp`
- **Claude Code** connects via HTTP (`.mcp.json` config)
- **Profile** seeded from DXC CV (10 work experiences, 4 education, 13 skills)
- **9 tracked applications** (DXC, Databricks, Gartner, Glean, Google, PwC, Salesforce, Tableau, Thoughtworks)

## Known Issues

### macOS directory permissions bug

**Issue:** Claude Code's task spooler creates directories with mode `0o600` (`drw-------`) instead of `0o700` (`drwx------`), missing the execute bit. This blocks all Bash commands because the task spooler can't create subdirectories.

**Symptoms:** `EACCES: permission denied, mkdir '/private/tmp/claude-501/.../tasks'` on every Bash command.

**Workaround:** `find /private/tmp/claude-501/ -type d -exec chmod u+rwx {} \;` after session start. Affects `/private/tmp/claude-501/` and `~/.npm/_npx/` cache directories.

**Root cause:** Likely a macOS-specific issue with directory creation modes in Claude Code's task spooler. Inferred — not confirmed by upstream.

### MCP-remote proxy failures in Claude Desktop

**Issue:** Tool calls (`update_profile`, `get_application_status`, `update_stage`) intermittently fail with "failed to call tool" errors in Claude Desktop sessions. The MCP server itself is confirmed working (direct HTTP test succeeds with session ID).

**Symptoms:** "Failed to call tool" error in Claude Desktop, no corresponding request in pi-4 service logs.

**Workaround:** Restart Claude Desktop session. The `npx mcp-remote` proxy may lose its session or have connection issues.

**Status:** Under investigation. The `mcp-remote` npm package may have session handling issues with FastMCP's streamable-http transport.

### JS-rendered job posting URLs

**Issue:** Many job sites (Meta, LinkedIn, Workday) use JavaScript rendering. URL scraping via `ingest_jd` returns only the page title (e.g., "Meta Careers", 12–14 chars) instead of the actual JD content.

**Mitigation:** The `jd_content_too_short` guard (deployed 2026-08-05) rejects URL-fetched content shorter than 50 characters with a clear error suggesting `jd_text` instead. Users can paste the JD content directly using the `jd_text` parameter, optionally keeping `jd_url` as a provenance reference.

**Status:** ✅ Guard deployed. The Meta tracker record (created before the guard) still has near-empty JD content and should be re-ingested with actual JD text.

### Duplicate Glean tracker entry

**Issue:** NAS `tracker.json` had two Glean entries (index 3 with "Role TBC" and index 8 with "Enterprise Account Executive - Singapore"). The withdrawn entry was removed on 2026-08-04.

**Status:** ✅ Fixed. NAS tracker now has 9 entries. The "Role TBC" stub entry remains — may want to update with the actual role title or remove if not needed.

## Technical Debt

| Item | Description | Priority |
|------|-------------|----------|
| `DXC/.venv` committed | A Python 3.14 venv exists inside the DXC company folder (34k+ files). Should be gitignored or removed. | Medium |
| Company folders untracked | All company folders (DXC/, Glean/, etc.) are untracked in git. They contain CVs and JDs that should be version-controlled or explicitly gitignored. | Medium |
| `tracker.json` and `profile.json` gitignored | These are runtime data and correctly gitignored, but the Mac copy can diverge from the NAS copy. No sync mechanism exists for the Mac copy. | Low (Mac is transient) |
| `weasyprint` not on pi-4 | PDF export requires weasyprint which needs Cairo system deps. Not installed on pi-4 (arm64). PDF export would fail on pi-4. | Low (PDF export typically done on Mac) |
| No automated backup of NAS data | UGOS Pro snapshots provide some protection, but there's no automated backup strategy beyond the NFS share. | Low (NAS has RAID) |
| `profile.json` on Mac is minimal | The Mac copy of `profile.json` only has `{"schema_version": "1.0"}` while the NAS copy is fully populated. They're independent copies. | Low (Mac is transient) |

## Deployment Configuration

### pi-4 (Production)

| Config | Value |
|--------|-------|
| Host | `gs-pi-4` (Tailscale: `100.119.219.90`, LAN: `192.168.10.128`) |
| SSH | `gs` (not `gslee`) |
| Service | `job-applications-mcp.service` — active (running) |
| Timer | `job-applications-tracker.timer` — enabled, fires 07:00 |
| Data dir | `/mnt/job-app-data` (NFS from `192.168.10.109`) |
| Env file | `/home/gs/Projects/Job-Applications/.env` (NAS paths, bearer token) |
| Python | `/home/gs/Projects/Job-Applications/venv/bin/python` |

### Mac (Development)

| Config | Value |
|--------|-------|
| Data dir | `~/Projects/Job-Applications` (local paths in `.env`) |
| MCP mode | stdio (local) or HTTP via `.mcp.json` (remote to pi-4) |
| Claude Desktop | `npx mcp-remote http://gs-pi-4.local:8086/mcp` with bearer auth |

## Recommended Next Steps

1. **Task 11: LinkedIn job-alert discovery** — Implement Gmail API OAuth for automated JD ingestion from LinkedIn job-alert emails. Design spec in `.kiro/specs/job-application-agent/tasks.md`.

2. **Fix `DXC/.venv`** — Remove or gitignore the committed venv inside the DXC company folder.

3. **Gitignore company folders** — Decide whether to track company artefact folders in git or explicitly gitignore them (they're currently untracked).

4. **Investigate mcp-remote stability** — Debug the intermittent tool call failures in Claude Desktop.

5. **Remove Glean "Role TBC" stub** — The remaining Glean entry at index 3 has a placeholder role title. Update with actual title or remove if no longer relevant.

6. **Sync Mac profile.json** — The Mac copy is empty while NAS is populated. Either point Mac `.env` to NAS mount or accept divergence (Mac is transient).

7. ~~**Deploy `ingest_jd` jd_text enhancement**~~ — ✅ Deployed (commit `60871ea`, pi-4 restarted 2026-08-05). The `jd_text` parameter and `jd_content_too_short` guard are live.

8. **Fix umask `0177` bug** — Claude Code sessions inherit umask 0177 (should be 0022), breaking mkdir/git/npm. Root cause is Claude Code's process environment, not shell config. Workaround: `umask 0022` at session start.