"""FCP-47: tests for env-driven Kafka SASL/SCRAM-SHA-512 over TLS (fail-closed)."""

from __future__ import annotations

import os
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from kafka_security import KafkaSecurityConfigError, kafka_security


def _sasl_env(tmp_path: Path, **overrides: str) -> dict[str, str]:
    pw_file = tmp_path / ".kafka-job_applications-password"
    pw_file.write_text("test-secret-pw\n", encoding="utf-8")
    os.chmod(pw_file, 0o600)

    ca_file = tmp_path / "ca.crt"
    ca_file.write_text("-----BEGIN CERTIFICATE-----\nFAKE\n-----END CERTIFICATE-----\n", encoding="utf-8")

    env = {
        "KAFKA_SECURITY_PROTOCOL": "SASL_SSL",
        "KAFKA_SASL_MECHANISM": "SCRAM-SHA-512",
        "KAFKA_SASL_USERNAME": "job_applications",
        "KAFKA_SASL_PASSWORD_FILE": str(pw_file),
        "KAFKA_SSL_CA_FILE": str(ca_file),
        "KAFKA_SASL_BOOTSTRAP_SERVERS": "rv-cloud.tail210e4f.ts.net:9094",
    }
    env.update(overrides)
    return env


def test_plaintext_default_is_non_secure():
    sec = kafka_security({})
    assert sec.secure is False
    assert sec.confluent() == {}
    assert sec.bootstrap_servers(["rv-cloud.local:9092"]) == ["rv-cloud.local:9092"]


def test_sasl_ssl_valid_config_and_no_password_leak(tmp_path: Path):
    env = _sasl_env(tmp_path)
    sec = kafka_security(env)

    assert sec.secure is True
    assert sec.bootstrap_servers(["rv-cloud.local:9092"]) == ["rv-cloud.tail210e4f.ts.net:9094"]
    conf = sec.confluent()
    assert conf["security.protocol"] == "SASL_SSL"
    assert conf["sasl.mechanism"] == "SCRAM-SHA-512"
    assert conf["sasl.username"] == "job_applications"
    assert conf["sasl.password"] == "test-secret-pw"
    assert conf["ssl.ca.location"] == env["KAFKA_SSL_CA_FILE"]
    assert conf["ssl.endpoint.identification.algorithm"] == "https"
    assert "test-secret-pw" not in repr(sec)
    assert "test-secret-pw" not in str(sec)


@pytest.mark.parametrize(
    "missing_key",
    ["KAFKA_SASL_USERNAME", "KAFKA_SASL_PASSWORD_FILE", "KAFKA_SSL_CA_FILE"],
)
def test_sasl_ssl_incomplete_env_fails_closed(tmp_path: Path, missing_key: str):
    env = _sasl_env(tmp_path)
    env.pop(missing_key)
    with pytest.raises(KafkaSecurityConfigError):
        kafka_security(env)


def test_sasl_ssl_rejects_world_readable_password_file(tmp_path: Path):
    env = _sasl_env(tmp_path)
    os.chmod(env["KAFKA_SASL_PASSWORD_FILE"], 0o644)
    with pytest.raises(KafkaSecurityConfigError, match="0600"):
        kafka_security(env)


def test_orchestration_consumer_and_producer_use_sasl_ssl_and_fail_closed(
    monkeypatch, tmp_path: Path
):
    import orchestration_consumer as oc

    env = _sasl_env(tmp_path)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("JOB_APP_ORCHESTRATION_ENABLED", "true")
    monkeypatch.delenv("JOB_APP_KAFKA_BROKER", raising=False)

    config = oc.OrchestrationConfig.from_env()
    assert config.broker == "rv-cloud.tail210e4f.ts.net:9094"

    captured_consumer = {}
    captured_producer = {}
    fake_ck = types.SimpleNamespace(
        Consumer=lambda c: captured_consumer.update(c) or MagicMock(),
        Producer=lambda c: captured_producer.update(c) or MagicMock(),
    )
    monkeypatch.setitem(sys.modules, "confluent_kafka", fake_ck)

    oc.create_kafka_consumer(config)
    oc.create_kafka_producer(config)

    assert captured_consumer["bootstrap.servers"] == "rv-cloud.tail210e4f.ts.net:9094"
    assert captured_consumer["security.protocol"] == "SASL_SSL"
    assert captured_consumer["sasl.username"] == "job_applications"
    assert captured_producer["bootstrap.servers"] == "rv-cloud.tail210e4f.ts.net:9094"
    assert captured_producer["security.protocol"] == "SASL_SSL"

    # Fail closed on incomplete SASL_SSL config: no PLAINTEXT fallback
    monkeypatch.delenv("KAFKA_SSL_CA_FILE")
    with pytest.raises(KafkaSecurityConfigError):
        oc.OrchestrationConfig.from_env()
    with pytest.raises(KafkaSecurityConfigError):
        oc.create_kafka_consumer(config)
    with pytest.raises(KafkaSecurityConfigError):
        oc.create_kafka_producer(config)
    assert oc.main() == 2


def test_app_health_kafka_uses_sasl_ssl_and_fails_closed(monkeypatch, tmp_path: Path):
    import app_health

    env = _sasl_env(tmp_path)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("JOB_APP_KAFKA_BROKER", "rv-cloud.local:9092")
    monkeypatch.setenv("JOB_APP_HEALTH_KAFKA_ENABLED", "true")

    seen_addrs = []

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(
        app_health.socket,
        "create_connection",
        lambda addr, timeout=None: seen_addrs.append(addr) or _Conn(),
    )
    res = app_health.check_kafka()
    assert res.ok is True
    assert seen_addrs == [("rv-cloud.tail210e4f.ts.net", 9094)]

    captured_producer = {}
    fake_producer = MagicMock()
    fake_producer.flush.return_value = 0

    def _make_producer(conf):
        captured_producer.update(conf)
        return fake_producer

    monkeypatch.setitem(sys.modules, "confluent_kafka", types.SimpleNamespace(Producer=_make_producer))
    assert app_health.notify_kafka({"status": "healthy"}) is True
    assert captured_producer["bootstrap.servers"] == "rv-cloud.tail210e4f.ts.net:9094"
    assert captured_producer["security.protocol"] == "SASL_SSL"
    assert captured_producer["sasl.username"] == "job_applications"

    # Fail closed when SASL_SSL is incomplete
    monkeypatch.delenv("KAFKA_SASL_PASSWORD_FILE")
    bad_check = app_health.check_kafka()
    assert bad_check.ok is False
    assert bad_check.status == "invalid_security_config"
    with pytest.raises(KafkaSecurityConfigError):
        app_health.notify_kafka({"status": "healthy"})
