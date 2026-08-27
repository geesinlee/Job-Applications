import json
import logging

import pytest

from orchestration_consumer import (
    DEFAULT_BROKER,
    DEFAULT_GROUP,
    DEFAULT_RESULT_TOPIC,
    DEFAULT_TOPIC,
    OrchestrationConfig,
    process_action_proposed,
    run_consumer,
)


def _event(**overrides):
    payload = {
        "recommendation_id": "rec-123",
        "recommendation_type": "job_application_followup",
        "action_kind": "job_application_interview_followup",
        "action": {
            "kind": "job_application_interview_followup",
            "application_id": "app-123",
            "company": "Example Corp",
            "role_title": "Enterprise Account Executive",
            "source_message_id": "msg-456",
            "correlation_id": "corr-789",
            "suggested_next_step": "Send a concise thank-you note.",
        },
        "title": "Interview follow-up recommended",
        "summary": "The interview concluded and a prompt follow-up is appropriate.",
        "score": 0.91,
        "confidence": 0.95,
        "source_key": "gmail:work",
        "external_id": "gmail-message-456",
        "evidence": [
            {
                "raw_content_reference": "communication://messages/msg-456/raw",
                "raw_content": "THIS FULL RAW MESSAGE MUST NOT BE COPIED",
            },
            {
                "source": {
                    "raw_content_reference": {
                        "uri": "communication://messages/msg-457/raw",
                        "content": "NOR THIS CONTENT",
                    }
                }
            },
        ],
    }
    for key, value in overrides.items():
        if key.startswith("action__"):
            payload["action"][key.removeprefix("action__")] = value
        else:
            payload[key] = value
    return {
        "schema_version": 1,
        "message_id": "proposal-message-123",
        "timestamp": "2026-08-26T12:00:00+00:00",
        "source": "ai_assistant",
        "payload": payload,
        "metadata": {
            "chat_id": 42,
            "correlation_id": "corr-789",
            "parent_message_id": "communication-message-123",
        },
    }


def _seed_application(monkeypatch, *, stage="screening"):
    import job_applications_mcp_server as owner

    monkeypatch.setattr(owner, "STORAGE_BACKEND", "file")
    application = owner._create_application_record(
        "Example Corp",
        "Enterprise Account Executive",
        "/tmp/example-jd.md",
    )
    application["id"] = "app-123"
    application["stage"] = stage
    application["history"] = [{"stage": stage, "at": "2026-08-25T00:00:00Z"}]
    owner._save_tracker({"schema_version": "1.1", "applications": [application]})
    return owner


def test_config_defaults_are_disabled_and_supervised(monkeypatch):
    for name in (
        "JOB_APP_ORCHESTRATION_ENABLED",
        "JOB_APP_ORCHESTRATION_EXECUTE",
        "JOB_APP_ORCHESTRATION_UPDATE_STAGE",
        "JOB_APP_ORCHESTRATION_RESULT_EVENTS_ENABLED",
        "JOB_APP_ORCHESTRATION_TOPIC",
        "JOB_APP_ORCHESTRATION_RESULT_TOPIC",
        "JOB_APP_ORCHESTRATION_GROUP",
        "JOB_APP_KAFKA_BROKER",
    ):
        monkeypatch.delenv(name, raising=False)

    config = OrchestrationConfig.from_env()

    assert config.enabled is False
    assert config.execute is False
    assert config.update_stage is False
    assert config.result_events_enabled is False
    assert config.topic == DEFAULT_TOPIC
    assert config.result_topic == DEFAULT_RESULT_TOPIC
    assert config.group == DEFAULT_GROUP
    assert config.broker == DEFAULT_BROKER


def test_invalid_boolean_configuration_is_rejected(monkeypatch):
    monkeypatch.setenv("JOB_APP_ORCHESTRATION_EXECUTE", "sometimes")

    with pytest.raises(ValueError, match="JOB_APP_ORCHESTRATION_EXECUTE"):
        OrchestrationConfig.from_env()


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("recommendation_type", "calendar_followup", "unsupported_recommendation_type"),
        ("action_kind", "job_application_other", "unsupported_action_kind"),
        ("action__kind", "job_application_other", "unsupported_action_kind"),
    ],
)
def test_only_supported_recommendation_and_both_action_kinds_are_processed(field, value, reason):
    result = process_action_proposed(
        _event(**{field: value}),
        OrchestrationConfig(enabled=True),
    )

    assert result == {"ok": True, "status": "ignored", "reason": reason}


def test_dry_run_logs_owner_action_without_loading_or_calling_owner(caplog):
    class OwnerMustNotBeCalled:
        def __getattr__(self, name):
            raise AssertionError(f"dry-run tried to access owner function {name}")

    caplog.set_level(logging.INFO, logger="job_applications.orchestration")
    result = process_action_proposed(
        _event(),
        OrchestrationConfig(enabled=True, execute=False),
        owner=OwnerMustNotBeCalled(),
    )

    assert result["status"] == "dry_run"
    assert result["suggested_next_step"] == "Send a concise thank-you note."
    assert "Proposed owner action mode=dry-run" in caplog.text
    assert "no tracker, Postgres, stage, or artefact mutation was attempted" in caplog.text


def test_missing_trace_or_summary_fields_are_rejected():
    event = _event(summary="")

    result = process_action_proposed(event, OrchestrationConfig(enabled=True))

    assert result["ok"] is False
    assert result["status"] == "rejected"
    assert result["error"] == "missing_required_fields"
    assert result["fields"] == ["summary"]


def test_execute_mode_validates_and_saves_source_referenced_note(tmp_path, monkeypatch):
    owner = _seed_application(monkeypatch)

    result = process_action_proposed(
        _event(),
        OrchestrationConfig(enabled=True, execute=True),
        owner=owner,
    )

    assert result["ok"] is True
    assert result["status"] == "executed"
    assert result["application_id"] == "app-123"
    notes_path = tmp_path / "Example Corp" / "enterprise-account-executive" / "interview_notes.md"
    note = notes_path.read_text(encoding="utf-8")
    assert "Recommendation ID: rec-123" in note
    assert "Correlation ID: corr-789" in note
    assert "Source message ID: msg-456" in note
    assert "communication://messages/msg-456/raw" in note
    assert "uri=communication://messages/msg-457/raw" in note
    assert "Interview follow-up recommended" in note
    assert "The interview concluded and a prompt follow-up is appropriate." in note
    assert "THIS FULL RAW MESSAGE MUST NOT BE COPIED" not in note
    assert "NOR THIS CONTENT" not in note

    application = owner._load_tracker()["applications"][0]
    assert application["stage"] == "screening"
    assert application["outputs"]["interview_notes"][0]["section"] == (
        "AI-Assistant orchestration interview follow-up"
    )


def test_execute_mode_rejects_mismatched_application_id_without_writing(tmp_path, monkeypatch):
    owner = _seed_application(monkeypatch)

    result = process_action_proposed(
        _event(action__application_id="wrong-app"),
        OrchestrationConfig(enabled=True, execute=True),
        owner=owner,
    )

    assert result["ok"] is False
    assert result["status"] == "rejected"
    assert result["error"] == "application_id_mismatch"
    assert not list(tmp_path.rglob("interview_notes.md"))


def test_stage_change_requires_flag_and_explicit_stage(monkeypatch):
    owner = _seed_application(monkeypatch)
    event = _event(action__new_stage="interview_r1")

    disabled_result = process_action_proposed(
        event,
        OrchestrationConfig(enabled=True, execute=True, update_stage=False),
        owner=owner,
    )
    assert disabled_result["stage_update"] is None
    assert owner._load_tracker()["applications"][0]["stage"] == "screening"

    enabled_result = process_action_proposed(
        event,
        OrchestrationConfig(enabled=True, execute=True, update_stage=True),
        owner=owner,
    )
    assert enabled_result["stage_update"]["ok"] is True
    assert owner._load_tracker()["applications"][0]["stage"] == "interview_r1"


class _FakeMessage:
    def __init__(self, value, error=None):
        self._value = value
        self._error = error

    def value(self):
        return self._value

    def error(self):
        return self._error


class _FakeConsumer:
    def __init__(self, messages):
        self.messages = list(messages)
        self.subscriptions = []
        self.commits = []
        self.closed = False

    def subscribe(self, topics):
        self.subscriptions.append(topics)

    def poll(self, timeout):
        return self.messages.pop(0) if self.messages else None

    def commit(self, *, message, asynchronous):
        self.commits.append((message, asynchronous))

    def close(self):
        self.closed = True


class _FakeProducer:
    def __init__(self, *, flush_result=0, delivery_error=None):
        self.messages = []
        self.flush_result = flush_result
        self.delivery_error = delivery_error
        self.flush_timeouts = []

    def produce(self, **message):
        self.messages.append(message)
        callback = message.get("on_delivery")
        if callback is not None:
            callback(self.delivery_error, object())

    def flush(self, timeout):
        self.flush_timeouts.append(timeout)
        return self.flush_result


def test_fake_kafka_input_is_processed_and_committed_in_dry_run():
    message = _FakeMessage(json.dumps(_event()).encode("utf-8"))
    consumer = _FakeConsumer([message])
    config = OrchestrationConfig(enabled=True, execute=False, topic="pilot-topic")

    summary = run_consumer(config, consumer=consumer, max_messages=1)

    assert summary == {"polled": 1, "committed": 1, "failed": 0, "result_events": 0}
    assert consumer.subscriptions == [["pilot-topic"]]
    assert consumer.commits == [(message, False)]
    assert consumer.closed is True


def test_fake_malformed_kafka_input_is_rejected_and_committed():
    message = _FakeMessage(b"{not-json")
    consumer = _FakeConsumer([message])

    summary = run_consumer(
        OrchestrationConfig(enabled=True),
        consumer=consumer,
        max_messages=1,
    )

    assert summary == {"polled": 1, "committed": 1, "failed": 1, "result_events": 0}
    assert consumer.commits == [(message, False)]
    assert consumer.closed is True


def test_owner_failure_stops_consumer_without_committing(monkeypatch):
    message = _FakeMessage(json.dumps(_event()).encode("utf-8"))
    consumer = _FakeConsumer([message])
    producer = _FakeProducer()

    monkeypatch.setattr(
        "orchestration_consumer.process_action_proposed",
        lambda event, config: {"ok": False, "status": "failed", "error": "owner_down"},
    )

    with pytest.raises(RuntimeError, match="orchestration_owner_action_failed"):
        run_consumer(
            OrchestrationConfig(
                enabled=True,
                execute=True,
                result_events_enabled=True,
            ),
            consumer=consumer,
            producer=producer,
            max_messages=1,
        )

    assert consumer.commits == []
    assert consumer.closed is True
    assert producer.messages == []


def test_dry_run_emits_completion_with_original_correlation_id():
    message = _FakeMessage(json.dumps(_event()).encode("utf-8"))
    consumer = _FakeConsumer([message])
    producer = _FakeProducer()

    summary = run_consumer(
        OrchestrationConfig(
            enabled=True,
            execute=False,
            result_events_enabled=True,
            result_topic="completion-topic",
        ),
        consumer=consumer,
        producer=producer,
        max_messages=1,
    )

    assert summary == {"polled": 1, "committed": 1, "failed": 0, "result_events": 1}
    assert len(producer.messages) == 1
    produced = producer.messages[0]
    envelope = json.loads(produced["value"])
    assert produced["topic"] == "completion-topic"
    assert produced["key"] == b"corr-789"
    assert envelope["source"] == "job_applications"
    assert envelope["metadata"] == {
        "chat_id": 42,
        "correlation_id": "corr-789",
        "parent_message_id": "proposal-message-123",
    }
    assert envelope["payload"] == {
        "recommendation_id": "rec-123",
        "owner_system": "job-applications",
        "action_kind": "job_application_interview_followup",
        "status": "dry_run",
        "application_id": "app-123",
        "company": "Example Corp",
        "role_title": "Enterprise Account Executive",
        "note_path": None,
        "stage_updated": False,
        "summary": "Interview follow-up evaluated in Job-Applications dry-run mode.",
        "error": None,
    }
    assert consumer.commits == [(message, False)]


@pytest.mark.parametrize(
    ("outcome", "expected_status", "expected_note_path", "expected_error"),
    [
        (
            {
                "ok": True,
                "status": "executed",
                "recommendation_id": "rec-123",
                "application_id": "app-123",
                "company": "Example Corp",
                "role_title": "Enterprise Account Executive",
                "note": {"ok": True, "path": "/pilot/interview_notes.md"},
                "stage_update": None,
            },
            "executed",
            "/pilot/interview_notes.md",
            None,
        ),
        (
            {
                "ok": False,
                "status": "rejected",
                "recommendation_id": "rec-123",
                "error": "application_id_mismatch",
            },
            "rejected",
            None,
            "application_id_mismatch",
        ),
    ],
)
def test_executed_and_rejected_outcomes_emit_completion(
    monkeypatch,
    outcome,
    expected_status,
    expected_note_path,
    expected_error,
):
    message = _FakeMessage(json.dumps(_event()).encode("utf-8"))
    consumer = _FakeConsumer([message])
    producer = _FakeProducer()
    monkeypatch.setattr(
        "orchestration_consumer.process_action_proposed",
        lambda event, config: outcome,
    )

    summary = run_consumer(
        OrchestrationConfig(enabled=True, result_events_enabled=True),
        consumer=consumer,
        producer=producer,
        max_messages=1,
    )

    envelope = json.loads(producer.messages[0]["value"])
    assert summary["result_events"] == 1
    assert envelope["payload"]["status"] == expected_status
    assert envelope["payload"]["note_path"] == expected_note_path
    assert envelope["payload"]["stage_updated"] is False
    assert envelope["payload"]["error"] == expected_error
    assert envelope["metadata"]["correlation_id"] == "corr-789"


def test_ignored_outcome_does_not_emit_completion():
    message = _FakeMessage(
        json.dumps(_event(recommendation_type="calendar_followup")).encode("utf-8")
    )
    consumer = _FakeConsumer([message])
    producer = _FakeProducer()

    summary = run_consumer(
        OrchestrationConfig(enabled=True, result_events_enabled=True),
        consumer=consumer,
        producer=producer,
        max_messages=1,
    )

    assert summary["committed"] == 1
    assert summary["result_events"] == 0
    assert producer.messages == []


def test_result_delivery_failure_leaves_proposal_uncommitted():
    message = _FakeMessage(json.dumps(_event()).encode("utf-8"))
    consumer = _FakeConsumer([message])
    producer = _FakeProducer(delivery_error="broker unavailable")

    with pytest.raises(RuntimeError, match="result_event_delivery_failed"):
        run_consumer(
            OrchestrationConfig(enabled=True, result_events_enabled=True),
            consumer=consumer,
            producer=producer,
            max_messages=1,
        )

    assert consumer.commits == []
    assert consumer.closed is True
