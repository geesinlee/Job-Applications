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
