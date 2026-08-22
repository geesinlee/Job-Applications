# Production Storage Setup

**Last reviewed:** 2026-08-21

## Source Of Truth

- PostgreSQL on `rv-cloud` is the canonical structured store for applications, stages, history, follow-ups, profile, and CV metadata.
- `tracker.json`, `profile.json`, and `cv_records.json` are legacy migration/recovery formats only; production MCP does not read or write them.
- Application artefact files and interview notes remain on the Job Applications data volume.

## pi-4 Runtime

- Service: `job-applications-mcp.service`
- Transport: HTTP with bearer authentication on local port `8086`
- Canonical state: PostgreSQL `CanonicalState` table on the NAS
- Database user: `job-app` for the evidence/workflow PostgreSQL connection
- NAS host: `192.168.10.109`

## Recovery Policy

- Treat the verified 2026-08-21 tracker recovery as the one-time import source only; do not use the old incomplete normalized migration snapshot.
- Keep application artefacts and interview notes on the NAS filesystem, with their paths recorded in canonical Postgres state.
- Treat synthetic IDs or records not backed by an application folder/notes file as suspicious until reconciled.
- Keep temporary recovery copies in `temp-trash/` only until the restored tracker has been validated through MCP.

## Verification

```bash
python3 -m pytest -q test_mcp_server.py test_tracker_daily.py
```

For production verification, use Claude Desktop to list applications, inspect the target application status, and confirm the corresponding interview-note path. Do not use the archived migration scripts; they are retained only under `temp-trash/` for forensic review.
