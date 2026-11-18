"""Env-driven Kafka client security settings (FCP-47).

Imports ``harness.kafka_security`` when the fleet harness is available (via
``FLEET_HARNESS_PATH`` or ``~/Projects/fleet-rationalization``) and falls back
to the identical local contract when running standalone.

Fail-closed: once ``KAFKA_SECURITY_PROTOCOL=SASL_SSL`` is requested, any
missing or unsafe setting raises ``KafkaSecurityConfigError`` instead of
silently falling back to PLAINTEXT.
"""

from __future__ import annotations

import os
import stat
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Mapping, Optional

_FLEET_HARNESS_PATH = os.path.expanduser(
    os.environ.get("FLEET_HARNESS_PATH", "~/Projects/fleet-rationalization")
)
if os.path.isdir(_FLEET_HARNESS_PATH) and _FLEET_HARNESS_PATH not in sys.path:
    sys.path.append(_FLEET_HARNESS_PATH)

try:
    from harness.kafka_security import (  # type: ignore[import-not-found]
        DEFAULT_SASL_BOOTSTRAP,
        SUPPORTED_MECHANISMS,
        SUPPORTED_PROTOCOLS,
        KafkaSecurity,
        KafkaSecurityConfigError,
        kafka_security,
    )
except ImportError:
    DEFAULT_SASL_BOOTSTRAP = "rv-cloud.tail210e4f.ts.net:9094"
    SUPPORTED_PROTOCOLS = ("PLAINTEXT", "SASL_SSL")
    SUPPORTED_MECHANISMS = ("SCRAM-SHA-512", "SCRAM-SHA-256")

    class KafkaSecurityConfigError(RuntimeError):
        """Kafka security env is incomplete or unsafe; the client must not connect."""

    @dataclass(frozen=True)
    class KafkaSecurity:
        protocol: str = "PLAINTEXT"
        mechanism: str = ""
        username: str = ""
        password: str = field(default="", repr=False)
        ca_file: str = ""
        sasl_bootstrap: tuple = ()

        @property
        def secure(self) -> bool:
            return self.protocol == "SASL_SSL"

        def __repr__(self) -> str:
            pw = "***" if self.password else ""
            return (
                f"KafkaSecurity(protocol={self.protocol!r}, mechanism={self.mechanism!r}, "
                f"username={self.username!r}, password={pw!r}, ca_file={self.ca_file!r})"
            )

        __str__ = __repr__

        def bootstrap_servers(self, plaintext_candidates: Iterable[str]) -> List[str]:
            """Broker list to dial: caller's list for PLAINTEXT, TLS listener for SASL_SSL."""
            if not self.secure:
                return [b for b in plaintext_candidates if b]
            return list(self.sasl_bootstrap)

        def confluent(self) -> dict:
            """Extra keys to merge into a confluent_kafka Producer/Consumer conf."""
            if not self.secure:
                return {}
            return {
                "security.protocol": "SASL_SSL",
                "sasl.mechanism": self.mechanism,
                "sasl.username": self.username,
                "sasl.password": self.password,
                "ssl.ca.location": self.ca_file,
                "ssl.endpoint.identification.algorithm": "https",
            }

        def kafka_python(self) -> dict:
            """Extra kwargs for kafka-python clients."""
            if not self.secure:
                return {}
            return {
                "security_protocol": "SASL_SSL",
                "sasl_mechanism": self.mechanism,
                "sasl_plain_username": self.username,
                "sasl_plain_password": self.password,
                "ssl_cafile": self.ca_file,
                "ssl_check_hostname": True,
            }

    def _read_password_file(path: str) -> str:
        p = Path(path)
        if not p.is_file():
            raise KafkaSecurityConfigError(f"KAFKA_SASL_PASSWORD_FILE not found: {path}")
        mode = stat.S_IMODE(p.stat().st_mode)
        if mode & (stat.S_IRWXG | stat.S_IRWXO):
            raise KafkaSecurityConfigError(
                f"KAFKA_SASL_PASSWORD_FILE {path} is group/world accessible ({oct(mode)}); chmod 0600 it"
            )
        value = p.read_text().strip()
        if not value:
            raise KafkaSecurityConfigError(f"KAFKA_SASL_PASSWORD_FILE {path} is empty")
        return value

    def kafka_security(env: Optional[Mapping[str, str]] = None) -> KafkaSecurity:
        """Build Kafka security settings from ``env`` (defaults to os.environ)."""
        env = os.environ if env is None else env
        protocol = (env.get("KAFKA_SECURITY_PROTOCOL") or "PLAINTEXT").strip().upper()
        if protocol not in SUPPORTED_PROTOCOLS:
            raise KafkaSecurityConfigError(
                f"KAFKA_SECURITY_PROTOCOL={protocol!r} unsupported; use one of {SUPPORTED_PROTOCOLS}"
            )
        if protocol == "PLAINTEXT":
            return KafkaSecurity()

        mechanism = (env.get("KAFKA_SASL_MECHANISM") or "SCRAM-SHA-512").strip().upper()
        if mechanism not in SUPPORTED_MECHANISMS:
            raise KafkaSecurityConfigError(
                f"KAFKA_SASL_MECHANISM={mechanism!r} unsupported; use one of {SUPPORTED_MECHANISMS}"
            )

        username = (env.get("KAFKA_SASL_USERNAME") or "").strip()
        if not username:
            raise KafkaSecurityConfigError("SASL_SSL requires KAFKA_SASL_USERNAME")

        pw_file = (env.get("KAFKA_SASL_PASSWORD_FILE") or "").strip()
        password = _read_password_file(pw_file) if pw_file else (env.get("KAFKA_SASL_PASSWORD") or "")
        if not password:
            raise KafkaSecurityConfigError(
                "SASL_SSL requires KAFKA_SASL_PASSWORD_FILE (0600) or KAFKA_SASL_PASSWORD"
            )

        ca_file = (env.get("KAFKA_SSL_CA_FILE") or "").strip()
        if not ca_file:
            raise KafkaSecurityConfigError("SASL_SSL requires KAFKA_SSL_CA_FILE (fleet Kafka CA)")
        if not Path(ca_file).is_file():
            raise KafkaSecurityConfigError(f"KAFKA_SSL_CA_FILE not found: {ca_file}")

        raw = env.get("KAFKA_SASL_BOOTSTRAP_SERVERS") or DEFAULT_SASL_BOOTSTRAP
        bootstrap = tuple(b.strip() for b in raw.split(",") if b.strip())

        return KafkaSecurity(
            protocol="SASL_SSL",
            mechanism=mechanism,
            username=username,
            password=password,
            ca_file=ca_file,
            sasl_bootstrap=bootstrap,
        )
