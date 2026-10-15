# Job Applications Codebase Technical Diagram

```mermaid
flowchart LR
    subgraph Clients["MCP clients / operators"]
        Codex["Codex, Claude, CLI, desktop clients"]
        Owner["Owner / scheduled operator"]
    end

    subgraph Runtime["Application host"]
        MCP["job_applications_mcp_server.py<br/>FastMCP stdio or HTTP :8086"]
        Tools["src/tools/*<br/>lifecycle, profile, artefacts, discovery, state"]
        Workflow["src/workflow_tools.py<br/>src/gate10_workflow_tools.py<br/>Gate 10 CV workflow"]
        Evidence["src/evidence_service.py<br/>JD analysis, evidence matching, CV assembly"]
        Health["app_health.py<br/>health probe"]
        Digest["job_digest.py / tracker_daily.py<br/>scheduled discovery and follow-up digests"]
        ReplyCheck["application_reply_check.py<br/>Gmail reply polling"]
        Orchestration["orchestration_consumer.py<br/>Kafka worker, dry-run by default"]
    end

    subgraph Storage["Persistent state"]
        Postgres[("PostgreSQL<br/>Prisma schema")]
        Canonical[("CanonicalState<br/>tracker, profile, CV records")]
        DomainTables[("Application, history, followups,<br/>workflow, evidence usage")]
        Files["Configured artefact volume<br/>JD.md, notes, cover letters, tailored CVs"]
        RuntimeState["Digest and health state files"]
    end

    subgraph External["External / fleet systems"]
        Gmail["Gmail API<br/>OAuth via gmail_auth.py"]
        Kafka[("Kafka<br/>orchestration.action_*")]
        Notify["fleet-notify<br/>email, ntfy, osascript"]
        Gemini["Google GenAI / LangChain<br/>optional CV generation path"]
    end

    subgraph Deploy["Deployment"]
        Systemd["deploy/pi-4/*.service and *.timer"]
        Env[".env / systemd EnvironmentFile<br/>DATABASE_URL, MCP_AUTH_TOKEN, mode flags"]
    end

    Codex -->|"MCP tool calls"| MCP
    Owner -->|"runs scripts / timers"| Digest
    Owner -->|"runs scripts / timers"| Health
    Owner -->|"runs scripts / timers"| ReplyCheck

    MCP --> Tools
    MCP --> Workflow
    MCP --> Evidence
    Workflow --> Evidence
    Workflow --> Gemini

    Tools --> Canonical
    Evidence --> DomainTables
    Workflow --> DomainTables
    MCP --> Files
    Tools --> Files
    Digest --> RuntimeState
    Health --> RuntimeState

    Canonical --> Postgres
    DomainTables --> Postgres

    ReplyCheck --> Gmail
    Digest --> Notify
    Health --> Notify

    Kafka -->|"action_proposed"| Orchestration
    Orchestration -->|"owner functions"| MCP
    Orchestration -->|"action_completed"| Kafka

    Systemd --> MCP
    Systemd --> Orchestration
    Systemd --> Digest
    Systemd --> Health
    Env --> MCP
    Env --> Orchestration
    Env --> Digest
    Env --> Health
```

## Main Runtime Paths

| Path | Main responsibility |
| --- | --- |
| `job_applications_mcp_server.py` | FastMCP entrypoint, HTTP auth, tool registration, legacy owner functions. |
| `src/tools/_state.py` | Shared state helpers, stage machine, Postgres/file backend switching, path handling. |
| `src/tools/lifecycle.py` | Application listing, status, updates, stage changes, applied date handling. |
| `src/tools/profile_tools.py` | Base CV/profile reads and profile refresh helpers. |
| `src/tools/artefacts.py` | Saved artefacts and context-prep persistence helpers. |
| `src/tools/discovery.py` | Daily discovery review and ingestion helpers. |
| `src/evidence_service.py` | Evidence extraction, JD analysis, evidence ranking, CV assembly. |
| `src/evidence_backend.py` | Evidence backend interface and Postgres/in-memory implementations. |
| `src/workflow_tools.py` | Gate 10 workflow tool implementation for clarifying questions and CV revision. |
| `orchestration_consumer.py` | Kafka consumer/producer for AI-Assistant follow-up proposals. |
| `gmail_auth.py`, `application_reply_check.py` | Gmail OAuth and reply monitoring. |
| `prisma/schema.prisma` | Canonical Postgres schema. |

## Key Flows

1. MCP client calls `job_applications_mcp_server.py`.
2. Server routes lifecycle/profile/artefact calls through `src/tools/*`.
3. Canonical tracker/profile/CV payloads persist through `CanonicalState`; richer application/evidence/workflow data persists through Prisma models.
4. Artefacts remain on the configured filesystem volume.
5. Gate 10 CV workflow combines JD criteria, stored evidence, user clarifications, and optional GenAI output.
6. Kafka orchestration worker consumes proposed follow-up actions, validates through owner functions, and publishes completion events.
7. Systemd units run MCP, orchestration, digest, and health processes on pi-4.

