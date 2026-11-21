"""Env-driven Kafka client security settings (FCP-47).

Single home is ``fleet_sdk.kafka.security`` (DEVOPS-243); this module
re-exports it so existing ``from kafka_security import ...`` imports keep
working. Fail-closed: once ``KAFKA_SECURITY_PROTOCOL=SASL_SSL`` is requested,
any missing or unsafe setting raises ``KafkaSecurityConfigError``.
"""

from fleet_sdk.kafka.security import (  # noqa: F401
    DEFAULT_SASL_BOOTSTRAP,
    SUPPORTED_MECHANISMS,
    SUPPORTED_PROTOCOLS,
    KafkaSecurity,
    KafkaSecurityConfigError,
    kafka_security,
)

__all__ = [
    "DEFAULT_SASL_BOOTSTRAP",
    "SUPPORTED_MECHANISMS",
    "SUPPORTED_PROTOCOLS",
    "KafkaSecurity",
    "KafkaSecurityConfigError",
    "kafka_security",
]
