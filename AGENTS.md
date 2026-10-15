# Caveman Protocol

You are operating under the Caveman Protocol. Follow these rules at all times to minimize token usage and maximize context transferability:

## 1. Terse Communication (Caveman Mode)
- **Be incredibly brief**: Eliminate all pleasantries, filler words, and verbose explanations.
- **Direct action**: Just state what you did, the result, and block on user input.
- **No essays**: Answer questions in bullet points or a single short paragraph.

## 2. Context Safety & Transferability
- **Maintain a clean state**: At the end of every major task or session, update a persistent artifact (like `HANDOVER.md` or `current_state.md`) in the workspace.
- **Compact Context**: Do not re-summarize entire files in chat. Persist knowledge in artifacts so fresh agent sessions can instantly resume work without reading long chat histories.
- **Token Efficiency**: Run targeted grep/view commands rather than dumping full file contents into chat context. Never view files > 100 lines entirely; use targeted line ranges or AST slices.

# Fleet Token Economy & DevEx Guardrails

To prevent rapid token exhaustion (e.g. 100k+ tokens in a session):
1. **Targeted Read Limits**:
   - NEVER `cat` or read files > 100 lines into context. Use `grep`, `head`, `tail`, or AST slice inspection.
   - Do NOT run directory-wide searches or dump large logs to chat context.
2. **Local Offload First**:
   - For code review, compliance audits, or AST checks, execute locally via the Universal Harness (0 cloud tokens):
     ```bash
     python3 -m harness.cli review --diff <diff_file>
     python3 -m harness.cli compliance --repo <repo_name>
     ```
3. **Session Compaction & Handover**:
   - Always persist progress, decisions, and open tickets in `HANDOVER.md`.
   - When a task is complete, write handover state and prompt user to start fresh session.
4. **Accountability Loop & Circuit Breaker (Anti-Workaround)**:
   - **Max 3 Bounded Retries**: Never repeat an identical failing command/patch (`STAGNATION`) or oscillate between states (`OSCILLATION`).
   - **Zero Unproductive Workarounds**: NEVER bypass failures via `@pytest.mark.skip`, `except: pass`, vacuous `assert True`, `--no-verify`, or mocking another repo's domain.
   - **Break & Explain**: When blocked, trip the circuit breaker immediately, explain the exact root cause/situation, and present concrete unblock options to the user:
     ```bash
     python3 -m harness.cli loop --task-type code_patch --prompt "<task>" --max-retries 3
     ```
5. **Multi-Agent & Sub-Agent DAG Orchestration**:
   - Coordinate complex tasks across topological waves (`ArchAdvisor` -> `CodePatcher` -> parallel `CodeReviewer` + `ComplianceSentinel`) passing only scoped AST slices (`harness.cli slice`), never full chat transcripts:
     ```bash
     python3 -m harness.cli orchestrate --goal "<complex task>" --files <file1,file2>
     ```

# Fleet Security Policy: Zero Plaintext Secret Exposure & JIT Governance

You MUST follow these strict security rules at all times across all projects:

## 1. Zero Plaintext Secret "Blurt" Rule
- **NEVER print, blurt, write to markdown, log, or display raw passwords, auth tokens, database credentials, or private keys in chat, logs, or commit diffs.**
- Always mask or redact credentials in output: e.g. `postgres://user:***@host:port/db` or `[REDACTED_TOKEN]`.
- In application code, reference secrets exclusively via environment variables (`os.getenv(...)`) or parameter files (`.env`).
- Never commit `.env` files or credentials to git version control.

## 2. Just-In-Time (JIT) Secret Broker MCP Usage
- When an agent requires database or API credentials to perform an automated task:
  1. **Do NOT** ask the user to type passwords in chat.
  2. Call the MCP tool: `request_secret_access(resource_id, requester, reason, duration_minutes)`.
  3. The superuser will receive an instant approval notification.
  4. Once approved, call `get_secret(ticket_id)` to receive an ephemeral, time-limited leased credential in-memory.
  5. Never persist the returned secret value to disk or commit history.

## 3. Zero Hardcoded LAN IP Policy
- Never hardcode intranet/LAN IP addresses (`192.168.10.*`).
- Use Tailscale MagicDNS (`*.ts.net`) or canonical service endpoints (`rv-cloud.local`).

# Fleet Device & Database Identity Matrix (Zero-Guessing Rule)

Never guess SSH usernames, database ports, or role names. Query `python3 -m harness.cli facts --query "<target>"` or use this canonical matrix:

## 1. Device SSH & OS User IDs
| Device | Canonical Hostname / Tailscale | OS / SSH User ID | Access Method & Rules |
| :--- | :--- | :--- | :--- |
| **pi-4** | `gs-pi-4.local` / `gs-pi-4.tail210e4f.ts.net` | **`gs`** (NEVER `gslee` or `root`) | Key-based SSH: `ssh gs@gs-pi-4.tail210e4f.ts.net` (no password prompt) |
| **pi-3** | `gs-pi-3.local` / `gs-pi-3.tail210e4f.ts.net` | **`gs`** (NEVER `gslee` or `root`) | Key-based SSH: `ssh gs@gs-pi-3.tail210e4f.ts.net` (no password prompt) |
| **NAS** | `rv-cloud.local` / `rv-cloud.tail210e4f.ts.net` | **`admin` (SSH is NOLOGIN)** | Do NOT SSH to NAS. Use published ports (`:5432`, `:5433`, `:8080`, `:9092`) or UGOS GUI |
| **Mac** | `gslee-mac` (`localhost`) | **`gslee`** | Local dev workstation only. Do NOT SSH to Mac |

## 2. Database Roles, Ports & JIT Secret Broker Resource IDs
Never ask the user for database passwords. Lease passwords dynamically via `secret-broker` MCP (`request_secret_access` -> `get_secret`), which returns both the connection metadata and ephemeral password:
| Domain / Service | Host:Port | Database (Schema) | App DML User (`resource_id`) | DDL Migrator User (`resource_id`) |
| :--- | :--- | :--- | :--- | :--- |
| **Work-RAG / SaaS** | `rv-cloud.local:5433` | `ai-assistant-db` (`wka_core`) | `work_rag_app` (`postgres.work_rag.app`) | `work_rag_migrator` (`postgres.work_rag.migrator`) |
| **AI-CRM** | `rv-cloud.local:5433` | `crm` | `crm_app` (`postgres.crm.app`) | `ai_crm_migrator` (`postgres.crm.migrator`) |
| **ITSM-Agent** | `rv-cloud.local:5433` | `itsm` | `itsm_app` (`postgres.itsm.app`) | `itsm_migrator` (`postgres.itsm.migrator`) |
| **Aegis** | `rv-cloud.local:5433` | `aegis` | `aegis_app` (`postgres.aegis.app`) | `aegis_migrator` (`postgres.aegis.migrator`) |
| **Contact-Mgmt** | `rv-cloud.local:5433` | `contacts` | `contact_app` (`postgres.contact_mgmt.app`) | — |
| **Job-Applications** | `rv-cloud.local:5432` | `job_applications` | `job-app` (`postgres.job_applications.app`) | — |
| **GeBiz-Tracking** | `rv-cloud.local:5432` | `gebiz_tracking` | `gebiz_user` | — |
| **NAS Superuser** | `rv-cloud.local:5433` | `postgres` | `postgres` (`postgres.superuser`) | `postgres` (`postgres.superuser`) |

# Fleet Architecture Policy: Domain Boundaries & Zero-Infringement

You MUST adhere to strict domain boundaries and anti-infringement rules across all projects:

## 1. Domain Ownership & Exclusive Responsibility
Every project in the fleet owns an exclusive capability domain:
- **`Work-RAG`**: Vector embeddings, document ingestion/chunking, semantic & hybrid search (`pgvector`).
- **`Contact-Mgmt`**: Contact intelligence, deduplication, scoring, LinkedIn/SGDI enrichment.
- **`AI-CRM`**: Opportunity tracking, account lifecycle, MEDDPICC gap analysis, pipeline risk.
- **`GeBiz-Awards` / `GeBiz-X` / `Tenders`**: Singapore public sector tender tracking and awards ingestion.
- **`Job-Applications`**: Job pipeline tracking, application analytics, resume indexing.
- **`DevEx-Intel`**: Developer experience, engineering effectiveness, token telemetry & ROI analytics.
- **`fleet-rationalization`**: Infrastructure health, JIT Secret Broker, Kafka event bus, A2A mesh discovery.

## 2. Strict Anti-Infringement & Zero-Mock Rule
- **NEVER** write code, mock services, or create database schemas for capabilities owned by another repository.
- If your project needs vector similarity, contact resolution, or CRM updates:
  - **PROHIBITED**: Reimplementing local vector distance math, building private scraping pipelines, or creating duplicate lookup tables.
  - **MANDATORY**: Consume the canonical capability via the fleet MCP tool or A2A mesh client.

## 3. Mandatory Service Discovery & Delegation Protocol
When an agent cannot fulfill a requirement due to a missing dependency or endpoint:
1. **Discover**: Query the Fleet Capability Catalog to identify the authoritative owner:
   ```bash
   python3 /Users/gslee/Projects/fleet-rationalization/scripts/fleet_capability_catalog.py query "<feature or tool needed>"
   ```
2. **If MCP Tool Exists**: Use the canonical MCP server over Tailscale HTTPS.
3. **If Feature Is Missing in Owning Project**:
   - **DO NOT** attempt to build it in your current workspace.
   - Dispatch a formal feature request using the cross-agent delegation tool:
     ```bash
     python3 /Users/gslee/Projects/fleet-rationalization/scripts/cross_agent_delegate.py \
       --from-repo "<current_repo>" \
       --to-repo "<owning_repo>" \
       --type "feature_request" \
       --title "<short title>" \
       --description "<detailed requirements>"
     ```
   - Record state in `HANDOVER.md` as `BLOCKED_ON_DELEGATION: [TICKET_ID]`.
   - Exit cleanly and notify the user that implementation is blocked pending the owning agent's delivery.
