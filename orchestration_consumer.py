#!/usr/bin/env python3
"""Supervised consumer for AI-Assistant job-application recommendations.

The worker consumes ``orchestration.action_proposed`` events and handles only
interview follow-up recommendations owned by Job-Applications. It is inert by
default: the consumer must be enabled explicitly, and its default processing
mode only logs the proposed owner action without importing or mutating the
Job-Applications state owner.

Execute mode validates the target through the existing MCP owner functions and
appends a compact, source-referenced note through ``save_interview_notes``.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


LOGGER = logging.getLogger("job_applications.orchestration")
EXPECTED_RECOMMENDATION_TYPE = "job_application_followup"
EXPECTED_ACTION_KIND = "job_application_interview_followup"
DEFAULT_TOPIC = "orchestration.action_proposed"
DEFAULT_GROUP = "job-applications-orchestration-v1"
DEFAULT_BROKER = "localhost:9092"
DEFAULT_RESULT_TOPIC = "orchestration.action_completed"

_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


def _env_flag(name: str, default: bool = False) -> bool:
    raw_value = os.environ.get(name)
    if raw_value is None or not raw_value.strip():
        return default
    value = raw_value.strip().lower()
    if value in _TRUE_VALUES:
        return True
    if value in _FALSE_VALUES:
        return False
    raise ValueError(f"{name} must be one of: true, false, 1, 0, yes, no, on, off")


@dataclass(frozen=True)
class OrchestrationConfig:
    """Runtime configuration loaded from environment variables."""

    enabled: bool = False
    execute: bool = False
    update_stage: bool = False
    result_events_enabled: bool = False
    topic: str = DEFAULT_TOPIC
    result_topic: str = DEFAULT_RESULT_TOPIC
    group: str = DEFAULT_GROUP
    broker: str = DEFAULT_BROKER

    @classmethod
    def from_env(cls) -> "OrchestrationConfig":
        return cls(
            enabled=_env_flag("JOB_APP_ORCHESTRATION_ENABLED"),
            execute=_env_flag("JOB_APP_ORCHESTRATION_EXECUTE"),
            update_stage=_env_flag("JOB_APP_ORCHESTRATION_UPDATE_STAGE"),
            result_events_enabled=_env_flag("JOB_APP_ORCHESTRATION_RESULT_EVENTS_ENABLED"),
            topic=os.environ.get("JOB_APP_ORCHESTRATION_TOPIC", DEFAULT_TOPIC),
            result_topic=os.environ.get(
                "JOB_APP_ORCHESTRATION_RESULT_TOPIC",
                DEFAULT_RESULT_TOPIC,
            ),
            group=os.environ.get("JOB_APP_ORCHESTRATION_GROUP", DEFAULT_GROUP),
            broker=os.environ.get("JOB_APP_KAFKA_BROKER", DEFAULT_BROKER),
        )


def _payload_from_event(event: Any) -> dict[str, Any] | None:
    if not isinstance(event, dict):
        return None
    payload = event.get("payload", event)
    return payload if isinstance(payload, dict) else None


def _non_empty_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _safe_reference(value: Any) -> str | None:
    """Return a reference identifier without copying evidence content."""
    if isinstance(value, (str, int, float)):
        text = str(value).strip()
        return text or None
    if not isinstance(value, dict):
        return None

    safe_parts = []
    for key in (
        "reference",
        "uri",
        "url",
        "path",
        "id",
        "key",
        "source_key",
        "external_id",
        "message_id",
        "bucket",
        "object_key",
    ):
        item = value.get(key)
        if isinstance(item, (str, int, float)) and str(item).strip():
            safe_parts.append(f"{key}={str(item).strip()}")
    return ", ".join(safe_parts) or None


def _raw_content_references(evidence: Any) -> list[str]:
    """Extract only raw-content references from evidence records."""
    if not isinstance(evidence, list):
        return []

    references: list[str] = []
    for item in evidence:
        if not isinstance(item, dict):
            continue
        candidates = [item.get("raw_content_reference")]
        source = item.get("source")
        if isinstance(source, dict):
            candidates.append(source.get("raw_content_reference"))
        for candidate in candidates:
            reference = _safe_reference(candidate)
            if reference and reference not in references:
                references.append(reference)
    return references


def _build_note(payload: dict[str, Any], action: dict[str, Any]) -> str:
    references = _raw_content_references(payload.get("evidence"))
    reference_lines = references or ["Not provided"]

    lines = [
        "AI-Assistant proposed an interview follow-up owner action.",
        "",
        f"- Recommendation ID: {_non_empty_string(payload.get('recommendation_id'))}",
        f"- Correlation ID: {_non_empty_string(action.get('correlation_id'))}",
        f"- Source message ID: {_non_empty_string(action.get('source_message_id'))}",
        "- Raw content reference(s):",
    ]
    lines.extend(f"  - {reference}" for reference in reference_lines)
    lines.extend(
        [
            f"- Source key: {_non_empty_string(payload.get('source_key')) or 'Not provided'}",
            f"- External ID: {_non_empty_string(payload.get('external_id')) or 'Not provided'}",
            "",
            "### AI-Assistant title",
            "",
            _non_empty_string(payload.get("title")) or "Not provided",
            "",
            "### AI-Assistant summary",
            "",
            _non_empty_string(payload.get("summary")) or "Not provided",
            "",
            "### Suggested next step",
            "",
            _non_empty_string(action.get("suggested_next_step")) or "Not provided",
        ]
    )
    return "\n".join(lines)


def _load_owner():
    """Import the state owner only after execute mode has been selected."""
    import job_applications_mcp_server

    return job_applications_mcp_server


def _event_correlation_id(event: Any) -> str | None:
    payload = _payload_from_event(event)
    action = payload.get("action") if isinstance(payload, dict) else None
    if isinstance(action, dict):
        correlation_id = _non_empty_string(action.get("correlation_id"))
        if correlation_id:
            return correlation_id
    if isinstance(event, dict):
        metadata = event.get("metadata")
        if isinstance(metadata, dict):
            return _non_empty_string(metadata.get("correlation_id"))
    return None


def _completion_summary(status: str) -> str:
    if status == "executed":
        return "Interview note appended in Job-Applications."
    if status == "dry_run":
        return "Interview follow-up evaluated in Job-Applications dry-run mode."
    if status == "rejected":
        return "Interview follow-up rejected by Job-Applications."
    return "Interview follow-up processing failed in Job-Applications."


def build_action_completed_event(event: Any, outcome: dict[str, Any]) -> dict[str, Any] | None:
    """Build AI-Assistant's standard completion envelope for one outcome."""
    status = _non_empty_string(outcome.get("status"))
    if status not in {"executed", "rejected", "dry_run"}:
        return None

    payload = _payload_from_event(event) or {}
    action = payload.get("action") if isinstance(payload.get("action"), dict) else {}
    correlation_id = _event_correlation_id(event)
    recommendation_id = (
        _non_empty_string(outcome.get("recommendation_id"))
        or _non_empty_string(payload.get("recommendation_id"))
    )
    if not correlation_id or not recommendation_id:
        LOGGER.error(
            "Cannot emit action completion without recommendation_id and correlation_id "
            "status=%s recommendation_id=%s correlation_id=%s",
            status,
            recommendation_id,
            correlation_id,
        )
        return None

    note_result = outcome.get("note")
    note_path = note_result.get("path") if isinstance(note_result, dict) else None
    stage_result = outcome.get("stage_update")
    stage_updated = bool(isinstance(stage_result, dict) and stage_result.get("ok"))
    completion_payload = {
        "recommendation_id": recommendation_id,
        "owner_system": "job-applications",
        "action_kind": _non_empty_string(payload.get("action_kind")) or EXPECTED_ACTION_KIND,
        "status": status,
        "application_id": (
            _non_empty_string(outcome.get("application_id"))
            or _non_empty_string(action.get("application_id"))
        ),
        "company": (
            _non_empty_string(outcome.get("company"))
            or _non_empty_string(action.get("company"))
        ),
        "role_title": (
            _non_empty_string(outcome.get("role_title"))
            or _non_empty_string(action.get("role_title"))
        ),
        "note_path": _non_empty_string(note_path) if status == "executed" else None,
        "stage_updated": stage_updated,
        "summary": _completion_summary(status),
        "error": (
            _non_empty_string(outcome.get("error"))
            or _non_empty_string(outcome.get("reason"))
            if status == "rejected"
            else None
        ),
    }
    metadata = event.get("metadata") if isinstance(event, dict) else None
    return {
        "schema_version": 1,
        "message_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "job_applications",
        "payload": completion_payload,
        "metadata": {
            "chat_id": metadata.get("chat_id") if isinstance(metadata, dict) else None,
            "correlation_id": correlation_id,
            "parent_message_id": (
                _non_empty_string(event.get("message_id"))
                if isinstance(event, dict)
                else None
            ),
        },
    }


def publish_action_completed(
    producer: Any,
    config: OrchestrationConfig,
    event: Any,
    outcome: dict[str, Any],
) -> dict[str, Any] | None:
    """Synchronously publish a deterministic owner outcome."""
    envelope = build_action_completed_event(event, outcome)
    if envelope is None:
        return None

    correlation_id = envelope["metadata"]["correlation_id"]
    delivery_errors: list[str] = []

    def on_delivery(error, message) -> None:
        if error is not None:
            delivery_errors.append(str(error))

    producer.produce(
        topic=config.result_topic,
        key=correlation_id.encode("utf-8"),
        value=json.dumps(envelope, ensure_ascii=False).encode("utf-8"),
        on_delivery=on_delivery,
    )
    undelivered = producer.flush(10.0)
    if undelivered:
        raise RuntimeError(f"result_event_delivery_timeout:{undelivered}")
    if delivery_errors:
        raise RuntimeError(f"result_event_delivery_failed:{delivery_errors[0]}")
    LOGGER.info(
        "Action completion emitted topic=%s recommendation_id=%s status=%s correlation_id=%s",
        config.result_topic,
        envelope["payload"]["recommendation_id"],
        envelope["payload"]["status"],
        correlation_id,
    )
    return envelope


def _validate_application(owner: Any, company: str, role_title: str, application_id: str | None) -> dict:
    result = owner.list_applications(company=company)
    if not isinstance(result, dict) or not isinstance(result.get("applications"), list):
        return {"ok": False, "error": "application_lookup_failed"}

    matches = [
        app
        for app in result["applications"]
        if isinstance(app, dict)
        and _non_empty_string(app.get("company"))
        and _non_empty_string(app.get("role_title"))
        and app["company"].casefold() == company.casefold()
        and app["role_title"].casefold() == role_title.casefold()
    ]
    if not matches:
        return {
            "ok": False,
            "error": "application_not_found",
            "company": company,
            "role_title": role_title,
        }
    if len(matches) > 1:
        return {
            "ok": False,
            "error": "ambiguous_application",
            "company": company,
            "role_title": role_title,
            "application_ids": [app.get("id") for app in matches],
        }

    application = matches[0]
    stored_id = _non_empty_string(application.get("id"))
    if application_id and stored_id != application_id:
        return {
            "ok": False,
            "error": "application_id_mismatch",
            "provided_application_id": application_id,
            "stored_application_id": stored_id,
        }
    return {"ok": True, "application": application}


def process_action_proposed(
    event: Any,
    config: OrchestrationConfig,
    *,
    owner: Any | None = None,
) -> dict[str, Any]:
    """Process one event value and return a JSON-serializable outcome."""
    payload = _payload_from_event(event)
    if payload is None:
        return {"ok": False, "status": "rejected", "error": "invalid_event_payload"}

    if payload.get("recommendation_type") != EXPECTED_RECOMMENDATION_TYPE:
        return {"ok": True, "status": "ignored", "reason": "unsupported_recommendation_type"}

    action = payload.get("action")
    if not isinstance(action, dict):
        return {"ok": False, "status": "rejected", "error": "invalid_action"}
    if (
        payload.get("action_kind") != EXPECTED_ACTION_KIND
        or action.get("kind") != EXPECTED_ACTION_KIND
    ):
        return {"ok": True, "status": "ignored", "reason": "unsupported_action_kind"}

    required_values = {
        "recommendation_id": payload.get("recommendation_id"),
        "company": action.get("company"),
        "role_title": action.get("role_title"),
        "correlation_id": action.get("correlation_id"),
        "source_message_id": action.get("source_message_id"),
        "title": payload.get("title"),
        "summary": payload.get("summary"),
        "suggested_next_step": action.get("suggested_next_step"),
    }
    missing = [name for name, value in required_values.items() if _non_empty_string(value) is None]
    if missing:
        return {
            "ok": False,
            "status": "rejected",
            "error": "missing_required_fields",
            "fields": missing,
        }

    recommendation_id = _non_empty_string(payload["recommendation_id"])
    company = _non_empty_string(action["company"])
    role_title = _non_empty_string(action["role_title"])
    application_id = _non_empty_string(action.get("application_id"))
    suggested_next_step = _non_empty_string(action.get("suggested_next_step")) or "Not provided"
    assert recommendation_id and company and role_title

    mode = "execute" if config.execute else "dry-run"
    LOGGER.info(
        "Proposed owner action mode=%s recommendation_id=%s application_id=%s "
        "company=%r role_title=%r suggested_next_step=%r",
        mode,
        recommendation_id,
        application_id or "not-provided",
        company,
        role_title,
        suggested_next_step,
    )

    if not config.execute:
        LOGGER.info(
            "Dry-run: no tracker, Postgres, stage, or artefact mutation was attempted "
            "for recommendation_id=%s",
            recommendation_id,
        )
        return {
            "ok": True,
            "status": "dry_run",
            "recommendation_id": recommendation_id,
            "application_id": application_id,
            "company": company,
            "role_title": role_title,
            "suggested_next_step": suggested_next_step,
        }

    owner = owner or _load_owner()
    validation = _validate_application(owner, company, role_title, application_id)
    if not validation.get("ok"):
        LOGGER.error(
            "Owner action rejected recommendation_id=%s validation=%s",
            recommendation_id,
            validation,
        )
        return {"status": "rejected", "recommendation_id": recommendation_id, **validation}

    application = validation["application"]
    stored_application_id = _non_empty_string(application.get("id"))
    note_result = owner.save_interview_notes(
        company=company,
        role_title=role_title,
        section="AI-Assistant orchestration interview follow-up",
        content=_build_note(payload, action),
    )
    if not isinstance(note_result, dict) or not note_result.get("ok"):
        LOGGER.error(
            "Owner note write failed recommendation_id=%s result=%s",
            recommendation_id,
            note_result,
        )
        return {
            "ok": False,
            "status": "failed",
            "error": "save_interview_notes_failed",
            "recommendation_id": recommendation_id,
            "owner_result": note_result,
        }

    stage_result: dict[str, Any] | None = None
    requested_stage = _non_empty_string(action.get("new_stage"))
    if config.update_stage and requested_stage:
        stage_result = owner.update_stage(
            company=company,
            role_title=role_title,
            new_stage=requested_stage,
        )
        if not isinstance(stage_result, dict) or not stage_result.get("ok"):
            LOGGER.error(
                "Stage update rejected by owner recommendation_id=%s requested_stage=%s result=%s",
                recommendation_id,
                requested_stage,
                stage_result,
            )
    elif config.update_stage:
        LOGGER.warning(
            "Stage updates are enabled, but recommendation_id=%s has no explicit action.new_stage; "
            "stage remains unchanged",
            recommendation_id,
        )

    LOGGER.info(
        "Owner action executed recommendation_id=%s application_id=%s note_path=%s stage_updated=%s",
        recommendation_id,
        stored_application_id,
        note_result.get("path"),
        bool(stage_result and stage_result.get("ok")),
    )
    return {
        "ok": True,
        "status": "executed",
        "recommendation_id": recommendation_id,
        "application_id": stored_application_id,
        "company": company,
        "role_title": role_title,
        "note": note_result,
        "stage_update": stage_result,
    }


def create_kafka_consumer(config: OrchestrationConfig):
    """Create the production Kafka consumer; imported lazily for testability."""
    try:
        from confluent_kafka import Consumer
    except ImportError as exc:
        raise RuntimeError(
            "confluent-kafka is required; install the project requirements before enabling orchestration"
        ) from exc

    return Consumer(
        {
            "bootstrap.servers": config.broker,
            "group.id": config.group,
            "client.id": "job-applications-orchestration",
            "enable.auto.commit": False,
            "auto.offset.reset": "earliest",
        }
    )


def create_kafka_producer(config: OrchestrationConfig):
    """Create the result-event producer with broker-side idempotence enabled."""
    try:
        from confluent_kafka import Producer
    except ImportError as exc:
        raise RuntimeError(
            "confluent-kafka is required; install the project requirements before enabling orchestration"
        ) from exc

    return Producer(
        {
            "bootstrap.servers": config.broker,
            "client.id": "job-applications-orchestration-results",
            "enable.idempotence": True,
            "acks": "all",
            "retries": 3,
            "retry.backoff.ms": 1000,
        }
    )


def run_consumer(
    config: OrchestrationConfig,
    *,
    consumer: Any | None = None,
    producer: Any | None = None,
    max_messages: int | None = None,
) -> dict[str, int]:
    """Consume events until interrupted (or ``max_messages`` in tests)."""
    if not config.enabled:
        LOGGER.info("Job-Applications orchestration consumer is disabled")
        return {"polled": 0, "committed": 0, "failed": 0, "result_events": 0}

    consumer = consumer or create_kafka_consumer(config)
    if config.result_events_enabled:
        producer = producer or create_kafka_producer(config)
    polled = 0
    committed = 0
    failed = 0
    result_events = 0
    consumer.subscribe([config.topic])
    LOGGER.info(
        "Orchestration consumer started topic=%s group=%s broker=%s mode=%s "
        "update_stage=%s result_events=%s result_topic=%s",
        config.topic,
        config.group,
        config.broker,
        "execute" if config.execute else "dry-run",
        config.update_stage,
        config.result_events_enabled,
        config.result_topic,
    )

    try:
        while max_messages is None or polled < max_messages:
            message = consumer.poll(1.0)
            if message is None:
                continue
            if message.error():
                failed += 1
                LOGGER.error("Kafka consumer error: %s", message.error())
                continue

            polled += 1
            try:
                raw_value = message.value()
                if isinstance(raw_value, bytes):
                    raw_value = raw_value.decode("utf-8")
                event = json.loads(raw_value) if isinstance(raw_value, str) else raw_value
                outcome = process_action_proposed(event, config)
            except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
                failed += 1
                LOGGER.exception("Rejecting malformed orchestration event")
                consumer.commit(message=message, asynchronous=False)
                committed += 1
                continue
            except Exception:
                failed += 1
                LOGGER.exception("Orchestration owner action failed; leaving Kafka offset uncommitted")
                raise

            if outcome.get("status") == "failed":
                failed += 1
                LOGGER.error("Owner action failed; leaving Kafka offset uncommitted outcome=%s", outcome)
                raise RuntimeError("orchestration_owner_action_failed")

            if config.result_events_enabled and outcome.get("status") in {
                "executed",
                "rejected",
                "dry_run",
            }:
                assert producer is not None
                try:
                    emitted = publish_action_completed(producer, config, event, outcome)
                except Exception:
                    failed += 1
                    LOGGER.exception(
                        "Action completion publish failed; leaving proposal offset uncommitted"
                    )
                    raise
                if emitted is not None:
                    result_events += 1

            consumer.commit(message=message, asynchronous=False)
            committed += 1
            if not outcome.get("ok"):
                failed += 1
                LOGGER.error("Rejected orchestration event outcome=%s", outcome)
    finally:
        consumer.close()
        LOGGER.info(
            "Orchestration consumer stopped polled=%d committed=%d failed=%d result_events=%d",
            polled,
            committed,
            failed,
            result_events,
        )

    return {
        "polled": polled,
        "committed": committed,
        "failed": failed,
        "result_events": result_events,
    }


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        config = OrchestrationConfig.from_env()
    except ValueError as exc:
        LOGGER.error("Invalid orchestration configuration: %s", exc)
        return 2

    try:
        run_consumer(config)
    except KeyboardInterrupt:
        LOGGER.info("Orchestration consumer interrupted")
    except Exception:
        LOGGER.exception("Orchestration consumer stopped unexpectedly")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
