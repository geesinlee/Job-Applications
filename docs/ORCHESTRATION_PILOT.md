# AI-Assistant Orchestration Pilot

## Purpose

`orchestration_consumer.py` is the Job-Applications owner-side consumer for
AI-Assistant `orchestration.action_proposed` events. It consumes only events
whose payload has both of these exact classifications:

- `recommendation_type == "job_application_followup"`
- `action_kind == action.kind == "job_application_interview_followup"`

All other recommendation and action kinds are acknowledged and ignored. The
worker does not read or write the AI-Assistant database.

## Safety Modes

The worker has two independent opt-ins:

1. `JOB_APP_ORCHESTRATION_ENABLED=true` starts Kafka consumption.
2. `JOB_APP_ORCHESTRATION_EXECUTE=true` allows owner-side mutation.

With execution disabled, the worker logs the application, recommendation ID,
and suggested owner action. It does not import the MCP owner module, so it does
not read or mutate tracker state, Postgres, or artefact files.

Execute mode uses existing owner functions only:

1. `list_applications(company=...)` validates an exact company and role-title
   match, plus `application_id` when the event provides one.
2. `save_interview_notes(...)` appends a section named
   `AI-Assistant orchestration interview follow-up`.
3. The note contains recommendation/correlation/source-message IDs,
   `raw_content_reference` values extracted from evidence, the AI-Assistant
   title and summary, and the suggested next step. It never copies evidence
   raw-content fields.

Postgres remains the canonical structured-state backend in production. Notes
remain owner-managed artefacts on the configured tenant data volume.

## Stage Updates

Stage updates are off by default and are not inferred from an interview
follow-up. A stage can change only when all of the following are true:

- `JOB_APP_ORCHESTRATION_EXECUTE=true`
- `JOB_APP_ORCHESTRATION_UPDATE_STAGE=true`
- the event contains an explicit non-empty `action.new_stage`

The current pilot payload does not require `action.new_stage`, so enabling the
flag alone does not change a stage. When present, the worker calls the existing
`update_stage(company, role_title, new_stage)` owner function. Invalid or
terminal-stage transitions remain blocked by the normal stage machine.

## Kafka Delivery

The consumer uses group `job-applications-orchestration-v1` by default, with
automatic commits disabled. It commits offsets synchronously after ignored,
dry-run, executed, or deterministically rejected events. A failed owner note
write or unexpected owner exception stops the worker with that offset left
uncommitted; systemd restarts it for replay. Malformed JSON is logged,
rejected, and committed so it cannot hold the partition indefinitely.

When `JOB_APP_ORCHESTRATION_RESULT_EVENTS_ENABLED=true`, deterministic
`dry_run`, `rejected`, and `executed` outcomes are published to
`orchestration.action_completed` before the proposal offset is committed. The
event uses the original correlation ID as both its Kafka key and
`metadata.correlation_id`; the proposal message ID becomes
`metadata.parent_message_id`. Its payload identifies Job-Applications as the
owner and includes the recommendation, action and application identifiers,
the note path when executed, whether an explicit stage update succeeded, a
compact outcome summary, and a rejection error when applicable.

The producer flushes synchronously. If completion delivery fails, the proposal
offset remains uncommitted. If the owner write itself fails, no completion
event is emitted and the proposal likewise remains uncommitted. Ignored events
do not produce completion events.

## Systemd user-service deployment

Install the updated Python dependencies and systemd unit:

```bash
cd "$HOME/Projects/Job-Applications"
.venv/bin/pip install -r requirements.txt
cp deploy/pi-4/job-applications-orchestration.service ~/.config/systemd/user/
mkdir -p ~/.config/systemd/user/job-applications-orchestration.service.d
cp deploy/pi-4/job-applications-orchestration-dry-run.conf \
  ~/.config/systemd/user/job-applications-orchestration.service.d/10-dry-run.conf
cp deploy/pi-4/job-applications-orchestration-results.conf \
  ~/.config/systemd/user/job-applications-orchestration.service.d/20-result-events.conf
systemctl --user daemon-reload
```

Add the pilot settings to the deployment environment file. Start in supervised dry-run mode:

```dotenv
JOB_APP_ORCHESTRATION_ENABLED=true
JOB_APP_ORCHESTRATION_EXECUTE=false
JOB_APP_ORCHESTRATION_UPDATE_STAGE=false
JOB_APP_ORCHESTRATION_TOPIC=orchestration.action_proposed
JOB_APP_ORCHESTRATION_GROUP=job-applications-orchestration-v1
JOB_APP_ORCHESTRATION_RESULT_EVENTS_ENABLED=true
JOB_APP_ORCHESTRATION_RESULT_TOPIC=orchestration.action_completed
JOB_APP_KAFKA_BROKER=kafka.example.internal:9092
```

Enable and inspect the worker:

```bash
systemctl --user enable --now job-applications-orchestration.service
systemctl --user status job-applications-orchestration.service
journalctl --user -u job-applications-orchestration.service -f
```

Confirm that logs show only the intended recommendation/action kinds and the
expected company, role, application ID, and next step. After supervision,
remove or edit the dry-run systemd drop-in, enable note writes, and restart:

```bash
rm ~/.config/systemd/user/job-applications-orchestration.service.d/10-dry-run.conf
sed -i 's/JOB_APP_ORCHESTRATION_EXECUTE=false/JOB_APP_ORCHESTRATION_EXECUTE=true/' .env
systemctl --user daemon-reload
systemctl --user restart job-applications-orchestration.service
```

Keep `JOB_APP_ORCHESTRATION_UPDATE_STAGE=false` unless AI-Assistant begins
emitting an explicit reviewed `action.new_stage` contract.

To stop the pilot without affecting the MCP server:

```bash
systemctl --user disable --now job-applications-orchestration.service
```

## Tests

The focused tests use isolated file-backend tracker state and fake Kafka
messages/consumers; no broker or production state is required:

```bash
python3 -m pytest -q test_orchestration_consumer.py
```
