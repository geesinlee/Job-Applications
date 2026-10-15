# Fleet Identity, Devices & Architecture Fast Reference

Follow these canonical facts across all fleet projects to prevent trial-and-error looping and connection failures:

## 1. Device User IDs & SSH Access Matrix
- **Mac** (`gslee-mac`): OS user `gslee`. Dev workstation only. Zero always-on services.
- **Raspberry Pi 4** (`gs-pi-4.local` / `100.119.219.90`): SSH user is **`gs`** (CRITICAL: user is `gs`, NEVER `gslee`). Host for heavy services (Work-RAG MCP :8087, JIT Secret Broker :8089, GeBiz MCP :8085, FinVault :8088, Ollama :11434).
- **Raspberry Pi 3** (`gs-pi-3.local` / `100.111.110.67`): SSH user is **`gs`** (CRITICAL: user is `gs`, NEVER `gslee`). Host for GeBiz feed timers + Contact-Mgmt MCP (:8001, :8002, :8003).
- **NAS** (`rv-cloud.local` / `rv-cloud.tail210e4f.ts.net`): Admin SSH is **`nologin`**. Do not attempt SSH login as admin. State spine (PostgreSQL, Kafka :9092, AI-CRM container :8080).

## 2. Canonical Database Roles & Ports Matrix
All database credentials must be leased via JIT Secret Broker (`request_secret_access`). The broker returns `username`, `endpoint`, and `connection_template` with the leased secret:
- **Port 5433** (`rv-cloud.local:5433` — container `ai-assistant-db`):
  - **Work-RAG / Work-RAG-SaaS**: DB `ai-assistant-db` | schema `wka_core` | App DML: `work_rag_app` | Migrator DDL: `work_rag_migrator` | JIT: `postgres.work_rag.app`
  - **AI-CRM**: DB `crm` | App DML: `crm_app` | Migrator DDL: `ai_crm_migrator` | JIT: `postgres.crm.app`
  - **ITSM**: DB `itsm` | App DML: `itsm_app` | Migrator DDL: `itsm_migrator` | JIT: `postgres.itsm.app`
  - **Aegis**: DB `aegis` | App DML: `aegis_app` | Migrator DDL: `aegis_migrator` | JIT: `postgres.aegis.app`
  - **Superuser**: DB `postgres` | User: `postgres` | JIT: `postgres.superuser`
- **Port 5432** (`rv-cloud.local:5432` LAN-only):
  - **Job-Applications**: DB `job_applications` | Role: `job-app` | JIT: `postgres.job_applications.app`
  - **GeBiz-Awards**: DB `gebiz_tracking` | Role: `gebiz_user` (LAN-only for Pi-3 sync)

## 3. Instant Zero-Token Fact Queries (Anti-Looping)
Do NOT read large markdown files, run blind directory greps, or try random SSH/curl commands to discover facts. Use the Universal Harness or MCP:
```bash
# Query any device, DB, service, or CI/CD fact in 0 cloud tokens:
python3 -m harness.cli facts --query "<search term>"

# Query specific topic:
python3 -m harness.cli facts --topic [devices|databases|services|cicd]
```
Or via Secret Broker MCP: call `query_fleet_facts(query="...")`.
