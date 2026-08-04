# Decisions — Job Applications MCP Server

Documented architectural and implementation decisions. Inferred decisions are marked as such.

## Architecture Decisions

### ADR-1: Single-file server architecture

**Decision:** All MCP tools live in one Python file (`job_applications_mcp_server.py`).

**Rationale:** The project started as a thin orchestrator and grew organically. The single-file approach keeps all tool implementations visible in one place, which is valuable when Claude needs to understand the full API surface. It also simplifies deployment — one file to rsync to pi-4.

**Alternatives considered:** Package with multiple modules (e.g., `server/`, `tracker/`, `profile/`). Rejected because the conftest.py path-isolation fixture monkeypatches module-level constants, which would need rewriting for a package.

**Inferred:** No. Stated in design doc §4.

---

### ADR-2: JSON files instead of a database

**Decision:** `tracker.json` and `profile.json` as the sole persistent stores.

**Rationale:** The data is small (10–20 applications at most) and read-write patterns are simple. JSON files are human-readable, git-friendly, and require no database runtime on pi-4. The daily digest script can read them with stdlib only.

**Alternatives considered:** SQLite (would add a dependency but enable queries), PostgreSQL on NAS (overkill for this scale, adds operational complexity).

**Inferred:** No. Stated in requirements doc Req 9.1 and design doc §4.3.

---

### ADR-3: Context-prep pattern (not in-server LLM calls)

**Decision:** Intelligence tools (`score_match`, `analyse_gaps`, `generate_learning_program`, `tailor_cv`, `generate_cover_letter`, `generate_pitch`) return context dicts rather than calling an LLM directly. Claude performs the reasoning and calls back with `save_*` tools.

**Rationale:** FastMCP servers should not embed LLM API keys or make model calls. The context-prep pattern keeps the server stateless and lets the AI client (Claude) choose the model and reasoning approach. It also makes the tools testable without mocking an LLM.

**Alternatives considered:** Embedding Gemini/OpenAI calls in the server (would require API keys in `.env`, make testing harder, and couple the server to a specific model).

**Inferred:** No. Stated in design doc §4.

---

### ADR-4: pi-4 as always-on host, NAS for artefact storage

**Decision:** The MCP server runs on pi-4 (aarch64, 1844 MB RAM) as a systemd service. Artefact files (CVs, research, exports) live on the NAS via NFS mount. Tracker and profile JSON live on the NAS directly (not rsynced).

**Rationale:** pi-4 has enough RAM for FastMCP + python-docx but not weasyprint (Cairo dependencies on arm64). The NAS provides persistent storage accessible from both pi-4 and Mac. The v0.3.0 migration (commit `b51d9e1`) moved all data to the NAS NFS share, eliminating the rsync backup pattern.

**Alternatives considered:** pi-3 (armv7l 32-bit, 921 MB — insufficient), Mac (no always-on service per fleet policy), NAS Docker container (adds operational complexity for a single Python process).

**Inferred:** No. Stated in design doc §3 and README deployment section. The v0.3.0 migration to NAS-direct is confirmed by git history and current `.env` configuration.

---

### ADR-5: NAS-direct storage (no rsync backup for tracker/profile)

**Decision:** `JOB_APP_BASE_DIR` points to the NFS mount (`/mnt/job-app-data`). `NAS_SYNC_PATH` is empty/disabled. Data is written directly to the NAS.

**Rationale:** v0.3.0 (commit `b51d9e1`) migrated from pi-4-local + rsync backup to NAS-direct. This eliminates the sync lag and rsync failure modes. The NAS has RAID and UGOS Pro snapshots for data protection.

**Alternatives considered:** pi-4-local storage with rsync backup (previous approach — had sync failures and stale data).

**Inferred:** No. Confirmed by git commit message, `.env` configuration, and README documentation.

---

### ADR-6: FastMCP >=2.0,<3 (not ~=0.1)

**Decision:** Use `fastmcp>=2.0,<3` instead of the originally specified `fastmcp~=0.1`.

**Rationale:** The original Kiro design doc specified `fastmcp~=0.1`, but by implementation time FastMCP 2.x was released with breaking API changes. The fleet-wide AGENTS.md requires `>=2.0,<3`. The server uses FastMCP 2.x APIs (`@mcp.tool()`, streamable-http transport).

**Inferred:** No. Confirmed by `requirements.txt` and the fleet-wide pin in the parent AGENTS.md.

---

### ADR-7: Streamable-HTTP transport (not SSE)

**Decision:** The server uses FastMCP's streamable-http transport for HTTP mode.

**Rationale:** FastMCP 2.x deprecated SSE in favor of streamable-http. Claude Desktop connects via `npx mcp-remote` which supports this transport. The server requires the `Accept: application/json, text/event-stream` header and a session ID for stateful requests.

**Inferred:** Yes. The code uses FastMCP 2.x defaults; the transport choice is not explicitly documented but is observable in the server logs and MCP handshake behavior.

---

## Implementation Decisions

### IMP-1: Fabrication protection for CV tailoring

**Decision:** `save_tailored_cv` rejects edits that alter quantified achievements. Two regex patterns protect text: `\d+\s*[%$SGD€£]` (currency/percentage) and `ARR|quota|deal|target` (keywords). Protected segments from the base CV must appear verbatim in the tailored CV.

**Rationale:** Job application documents must never fabricate or inflate achievements. This is a hard constraint from requirements doc Req 6.5.

**Inferred:** No. Stated in requirements doc Req 4.5, 6.5 and implemented in `_protected_lines()`.

---

### IMP-2: Cover letter versioning

**Decision:** When saving a new `Cover_Letter.md`, the existing file is renamed to `Cover_Letter_v{N}.md` where N is the count of existing versioned backups plus one.

**Rationale:** Prevents accidental data loss. Users may iterate on cover letters multiple times for the same company.

**Inferred:** No. Stated in requirements doc Req 7.5.

---

### IMP-3: LinkedIn source always wins conflicts

**Decision:** When merging profile data from LinkedIn and CV sources, LinkedIn values take precedence. CV values are preserved in a `conflicts[]` array with source markers.

**Rationale:** LinkedIn is considered the canonical source of truth for professional history. The CV may be outdated or tailored for a specific role.

**Inferred:** No. Stated in requirements doc Req 2.6, 2.7.

---

### IMP-4: Match score weights

**Decision:** 40% required skills, 25% years of experience, 15% seniority alignment, 10% industry/domain alignment, 10% preferred skills.

**Rationale:** Required skills are weighted highest because they represent hard requirements in job postings. Years of experience is second because it's a common filter. Seniority and industry alignment are softer signals. Preferred skills are lowest because they're nice-to-haves.

**Inferred:** Yes. The weights are implemented in the code (`MATCH_SCORE_WEIGHTS`) but the rationale for each weight is not documented.

---

### IMP-5: Follow-up deduplication and auto-cancellation

**Decision:** `send_follow_up_email` follow-ups are created on `applied` stage (due +7 days) and `send_thank_you_note` on interview stages (due +1 day). Duplicate creation is silently suppressed. When an application reaches `interview_r1+`, pending `send_follow_up_email` records are set to `cancelled`.

**Rationale:** Prevents duplicate reminder emails and ensures follow-up emails are cancelled once the candidate is already in interviews.

**Inferred:** No. Stated in requirements doc Req 11.

---

### IMP-6: Multi-role folder support with legacy compatibility

**Decision:** When a company has multiple roles, artefacts are stored in role-slug subfolders (`{Company}/{role-slug}/JD.md`). Legacy single-role folders (`{Company}/JD.md`) continue to work without migration.

**Rationale:** The system must support applying to multiple roles at the same company (e.g., two Salesforce roles). Forcing migration of existing folders would break working applications.

**Inferred:** No. Stated in requirements doc Req 10 and design doc §4.4.

---

### IMP-7: Error response pattern

**Decision:** All MCP tools return `{"ok": True/False, ...}` dicts. Errors include a short `error` code string (e.g., `jd_not_found`, `ambiguous_role`) and never raise exceptions to the FastMCP layer.

**Rationale:** Consistent error handling makes it easy for Claude to check `ok` and branch on error codes. Raising exceptions would produce unstructured error messages.

**Inferred:** No. Stated in design doc §Error Handling.