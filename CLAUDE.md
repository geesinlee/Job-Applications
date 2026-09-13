# Caveman Protocol

You are operating under the Caveman Protocol. Follow these rules at all times to minimize token usage and maximize context transferability:

## 1. Terse Communication (Caveman Mode)
- **Be incredibly brief**: Eliminate all pleasantries, filler words, and verbose explanations.
- **Direct action**: Just state what you did, the result, and block on user input.
- **No essays**: Answer questions in bullet points or a single short paragraph.

## 2. Context Safety & Transferability
- **Maintain a clean state**: At the end of every major task or session, update a persistent artifact (like `HANDOVER.md` or `current_state.md`) in the workspace.
- **Compact Context**: Do not re-summarize entire files in chat. Persist knowledge in artifacts so fresh agent sessions can instantly resume work without reading long chat histories.
- **Token Efficiency**: Run targeted grep/view commands rather than dumping full file contents into chat context.

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

# Fleet Architecture Policy: Domain Boundaries & Zero-Infringement

You MUST adhere to strict domain boundaries and anti-infringement rules across all projects:

## 1. Domain Ownership & Exclusive Responsibility
Every project in the fleet owns an exclusive capability domain:
- **`Work-RAG`**: Vector embeddings, document ingestion/chunking, semantic & hybrid search (`pgvector`).
- **`Contact-Mgmt`**: Contact intelligence, deduplication, scoring, LinkedIn/SGDI enrichment.
- **`AI-CRM`**: Opportunity tracking, account lifecycle, MEDDPICC gap analysis, pipeline risk.
- **`GeBiz-Awards` / `GeBiz-X` / `Tenders`**: Singapore public sector tender tracking and awards ingestion.
- **`Job-Applications`**: Job pipeline tracking, application analytics, resume indexing.
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
