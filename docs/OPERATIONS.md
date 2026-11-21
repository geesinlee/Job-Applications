# Operations — Job Applications

## Production Credentials

The current Pi deployment loads the job digest environment from:

```text
/home/gs/Projects/Job-Applications/.env
```

This app holds no SMTP credentials (DEVOPS-243). Digests and alerts are
published through `fleet_sdk.notify` (Kafka `fleet.notifications.v1`, email
channel, local spool fallback). The fleet notification worker on pi-4 (owned by
`fleet-rationalization`) holds the SMTP settings and sends the mail.

The generic systemd unit examples use:

```text
/home/gs/.config/job-applications/env
```

Prefer converging production onto the generic path when convenient, but verify
the effective service with `systemctl --user cat <unit>` before editing secrets.

## Health Probe

`app_health.py` is the operational health check for the app. It verifies:

- required deployment environment
- artefact volume existence and writability
- Postgres TCP reachability when `JOB_APP_STORAGE_BACKEND=postgres`
- MCP HTTP `tools/list`
- Notification publish path (Kafka security config for `fleet_sdk.notify`)
- Gmail OAuth refresh for configured accounts
- LLM triage configuration when `JOB_DIGEST_TRIAGE_MODE=llm`
- job digest failure state and last-success freshness
- optional Kafka broker TCP reachability

It writes the latest snapshot to:

```text
$JOB_APP_ARTEFACTS_DIR/.job_app_health.json
```

It records the last notified failure signature in:

```text
$JOB_APP_ARTEFACTS_DIR/.job_app_health_alert_state.json
```

Notifications are state-change based, so an unchanged outage does not send a
new alert on every timer run.

## Running Checks

Local or production smoke check:

```bash
.venv/bin/python app_health.py --json
```

Production-style scheduled check:

```bash
.venv/bin/python app_health.py --notify --check-kafka
```

`notify_config` checks that the Kafka security config for the notification
publish path loads. `--check-kafka` checks the configured Kafka broker socket.
`--check-smtp-login` is accepted but ignored (SMTP moved to the worker).

## Alert Channels

Email alerts go through the same notification path as the daily digest. Because
that path can itself be the failed dependency, configure at least one
independent channel:

- `JOB_APP_HEALTH_WEBHOOK_URL` for an external HTTP alert target
- `JOB_APP_HEALTH_KAFKA_ENABLED=true` and `JOB_APP_HEALTH_KAFKA_TOPIC` for Kafka
  health events

Kafka is useful as the app-wide status rail. It should not be required for job
discovery catch-up.

## Recovery Sequence

1. Inspect health:

   ```bash
   cd ~/Projects/Job-Applications
   venv/bin/python app_health.py --json --check-kafka
   ```

2. Reauthorize Gmail OAuth if `gmail_oauth` is failing.

3. If mail stops while `notify_config` is OK, check the worker:
   `journalctl --user -u fleet-notification-worker` on pi-4 (DLQ / SMTP errors).

4. Run a dry digest check:

   ```bash
   venv/bin/python job_digest.py --dry-run
   ```

5. Run the digest once manually after Gmail OAuth and `notify_config` are healthy:

   ```bash
   venv/bin/python job_digest.py
   ```

The digest only advances `.job_digest_last_run` after successful email delivery,
so a repaired run catches up from the previous successful marker.

## LLM Job Triage

The digest can use deterministic rules or model-backed triage:

```bash
JOB_DIGEST_TRIAGE_MODE=rules
JOB_DIGEST_TRIAGE_MODE=llm
```

When `llm` is enabled, also configure the shared model provider:

```bash
LLM_PROVIDER=gemini
GEMINI_API_KEY=<provider key>
# Optional: override the digest model independently of evidence extraction.
JOB_DIGEST_LLM_MODEL=gemini-3.6-flash
JOB_DIGEST_TRIAGE_BATCH_SIZE=8
JOB_DIGEST_LLM_MAX_TOKENS=8192
```

or:

```bash
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=<provider key>
```

The model receives deduplicated LinkedIn job-alert cards plus a bounded excerpt
from the reference CV. It must return structured JSON decisions. If model triage
fails, the digest records failure state and keeps the backlog for retry.
