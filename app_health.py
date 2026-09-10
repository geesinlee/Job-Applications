#!/usr/bin/env python3
"""Operational health probe for the Job Applications app.

The probe is intentionally standalone so systemd can run it even when the MCP
process, digest job, or orchestration worker is unhealthy. It writes a durable
JSON snapshot, exits non-zero on unhealthy state, and can notify on state
changes through SMTP, a webhook, or Kafka.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from fleet_notify import send_email
from fleet_notify.config import load_smtp_config
from gmail_auth import GmailAccountManager


_SRC_DIR = Path(__file__).resolve().parent
_DEFAULT_DATA_DIR = _SRC_DIR / "data"

BASE_DIR = Path(os.environ.get("JOB_APP_BASE_DIR", str(_DEFAULT_DATA_DIR)))
ARTEFACTS_DIR = Path(os.environ.get("JOB_APP_ARTEFACTS_DIR", str(BASE_DIR)))
HEALTH_STATE_PATH = Path(os.environ.get(
    "JOB_APP_HEALTH_STATE_PATH",
    str(ARTEFACTS_DIR / ".job_app_health.json"),
))
HEALTH_ALERT_STATE_PATH = Path(os.environ.get(
    "JOB_APP_HEALTH_ALERT_STATE_PATH",
    str(ARTEFACTS_DIR / ".job_app_health_alert_state.json"),
))
DIGEST_LAST_RUN_PATH = Path(os.environ.get(
    "JOB_DIGEST_LAST_RUN_PATH",
    str(ARTEFACTS_DIR / ".job_digest_last_run"),
))
DIGEST_FAILURE_STATE_PATH = Path(os.environ.get(
    "JOB_DIGEST_FAILURE_STATE_PATH",
    str(ARTEFACTS_DIR / ".job_digest_failure.json"),
))
GMAIL_ACCOUNTS_CONFIG = os.environ.get("GMAIL_ACCOUNTS_CONFIG", "")

DEFAULT_DIGEST_MAX_AGE_DAYS = int(os.environ.get("JOB_APP_HEALTH_DIGEST_MAX_AGE_DAYS", "2"))
DEFAULT_HTTP_TIMEOUT_SECONDS = float(os.environ.get("JOB_APP_HEALTH_HTTP_TIMEOUT_SECONDS", "8"))
DEFAULT_SOCKET_TIMEOUT_SECONDS = float(os.environ.get("JOB_APP_HEALTH_SOCKET_TIMEOUT_SECONDS", "5"))

SMTP_CONFIG = load_smtp_config()


@dataclass
class CheckResult:
    name: str
    ok: bool
    status: str
    detail: str = ""
    metadata: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        data = {
            "name": self.name,
            "ok": self.ok,
            "status": self.status,
            "detail": self.detail,
        }
        if self.metadata:
            data["metadata"] = self.metadata
        return data


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    path.chmod(0o600)


def _redact_url(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return "<configured>"
    return f"{parsed.scheme}://{parsed.hostname or parsed.netloc}:{parsed.port or ''}/{parsed.path.lstrip('/')}".rstrip(":")


def check_required_env() -> CheckResult:
    required = ["JOB_APP_STORAGE_BACKEND", "JOB_APP_BASE_DIR", "JOB_APP_ARTEFACTS_DIR"]
    if os.environ.get("JOB_APP_STORAGE_BACKEND", "file").lower() == "postgres":
        required.append("DATABASE_URL")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        return CheckResult(
            "required_env",
            False,
            "missing_required_env",
            ", ".join(missing),
        )
    return CheckResult("required_env", True, "ok")


def check_artifact_paths() -> CheckResult:
    missing = []
    for path in (BASE_DIR, ARTEFACTS_DIR):
        if not path.exists():
            missing.append(str(path))
    if missing:
        return CheckResult("artifact_paths", False, "missing_paths", ", ".join(missing))
    if not os.access(ARTEFACTS_DIR, os.W_OK):
        return CheckResult("artifact_paths", False, "not_writable", str(ARTEFACTS_DIR))
    return CheckResult("artifact_paths", True, "ok", metadata={"artefacts_dir": str(ARTEFACTS_DIR)})


def check_postgres_socket(timeout: float = DEFAULT_SOCKET_TIMEOUT_SECONDS) -> CheckResult:
    database_url = os.environ.get("DATABASE_URL", "")
    if os.environ.get("JOB_APP_STORAGE_BACKEND", "file").lower() != "postgres":
        return CheckResult("postgres", True, "skipped_file_backend")
    if not database_url:
        return CheckResult("postgres", False, "missing_database_url")

    parsed = urlparse(database_url)
    host = parsed.hostname
    port = parsed.port or 5432
    if not host:
        return CheckResult("postgres", False, "invalid_database_url")
    try:
        with socket.create_connection((host, port), timeout=timeout):
            pass
    except OSError as exc:
        return CheckResult("postgres", False, "connect_failed", str(exc), {"target": f"{host}:{port}"})
    return CheckResult("postgres", True, "tcp_ok", metadata={"target": f"{host}:{port}"})


def check_mcp_http(timeout: float = DEFAULT_HTTP_TIMEOUT_SECONDS) -> CheckResult:
    mcp_url = os.environ.get("JOB_APP_MCP_URL", "http://127.0.0.1:8086/mcp")
    token = os.environ.get("MCP_AUTH_TOKEN", "")
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    try:
        response = requests.post(mcp_url, headers=headers, json=payload, timeout=timeout)
    except Exception as exc:
        return CheckResult("mcp_http", False, "request_failed", str(exc), {"url": _redact_url(mcp_url)})

    if response.status_code in {401, 403}:
        return CheckResult(
            "mcp_http",
            False,
            "auth_failed",
            f"HTTP {response.status_code}",
            {"url": _redact_url(mcp_url)},
        )
    if response.status_code >= 500:
        return CheckResult(
            "mcp_http",
            False,
            "server_error",
            f"HTTP {response.status_code}",
            {"url": _redact_url(mcp_url)},
        )
    if response.status_code >= 400:
        return CheckResult(
            "mcp_http",
            True,
            "endpoint_reachable",
            f"HTTP {response.status_code}",
            {"url": _redact_url(mcp_url)},
        )

    data = response.json()
    if "result" not in data:
        return CheckResult("mcp_http", False, "invalid_response", metadata={"url": _redact_url(mcp_url)})
    return CheckResult("mcp_http", True, "ok", metadata={"url": _redact_url(mcp_url)})


def check_smtp_config() -> CheckResult:
    if not SMTP_CONFIG.is_configured:
        return CheckResult("smtp_config", False, "not_configured")
    return CheckResult(
        "smtp_config",
        True,
        "configured",
        metadata={"host": SMTP_CONFIG.host, "port": SMTP_CONFIG.port, "user": SMTP_CONFIG.user},
    )


def check_smtp_login(timeout: float = DEFAULT_SOCKET_TIMEOUT_SECONDS) -> CheckResult:
    if not SMTP_CONFIG.is_configured:
        return CheckResult("smtp_login", False, "not_configured")
    try:
        import smtplib

        with smtplib.SMTP(SMTP_CONFIG.host, SMTP_CONFIG.port, timeout=timeout) as server:
            server.starttls()
            server.login(SMTP_CONFIG.user, SMTP_CONFIG.password)
    except Exception as exc:
        return CheckResult("smtp_login", False, "login_failed", str(exc))
    return CheckResult("smtp_login", True, "ok")


def check_gmail_oauth() -> CheckResult:
    if not GMAIL_ACCOUNTS_CONFIG:
        return CheckResult("gmail_oauth", False, "missing_gmail_accounts_config")
    mgr = GmailAccountManager(GMAIL_ACCOUNTS_CONFIG)
    if not mgr.accounts:
        return CheckResult("gmail_oauth", False, "no_accounts")

    failed = []
    checked = []
    for account_key, account in mgr.accounts.items():
        checked.append({"key": account_key, "email": account.email})
        if not mgr.get_access_token(account_key):
            failed.append({"key": account_key, "email": account.email})
    if failed:
        return CheckResult("gmail_oauth", False, "auth_failed", metadata={"failed": failed, "checked": checked})
    return CheckResult("gmail_oauth", True, "ok", metadata={"checked": checked})


def check_digest_state(max_age_days: int = DEFAULT_DIGEST_MAX_AGE_DAYS) -> CheckResult:
    failure = _read_json(DIGEST_FAILURE_STATE_PATH)
    if failure:
        return CheckResult(
            "job_digest",
            False,
            "unresolved_failure",
            failure.get("reason", ""),
            {"failure": failure},
        )
    if not DIGEST_LAST_RUN_PATH.exists():
        return CheckResult("job_digest", False, "missing_last_success_marker")
    try:
        last_run = date.fromisoformat(DIGEST_LAST_RUN_PATH.read_text(encoding="utf-8").strip())
    except Exception as exc:
        return CheckResult("job_digest", False, "invalid_last_success_marker", str(exc))
    age_days = (date.today() - last_run).days
    if age_days > max_age_days:
        return CheckResult(
            "job_digest",
            False,
            "stale_last_success",
            f"last successful digest was {age_days} day(s) ago",
            {"last_run": last_run.isoformat(), "max_age_days": max_age_days},
        )
    return CheckResult("job_digest", True, "ok", metadata={"last_run": last_run.isoformat(), "age_days": age_days})


def check_kafka(timeout: float = DEFAULT_SOCKET_TIMEOUT_SECONDS) -> CheckResult:
    broker = os.environ.get("JOB_APP_KAFKA_BROKER", "")
    if not broker:
        return CheckResult("kafka", True, "not_configured")
    host, _, port_text = broker.partition(":")
    port = int(port_text or "9092")
    try:
        with socket.create_connection((host, port), timeout=timeout):
            pass
    except OSError as exc:
        return CheckResult("kafka", False, "connect_failed", str(exc), {"broker": broker})
    return CheckResult("kafka", True, "tcp_ok", metadata={"broker": broker})


def check_llm_triage_config() -> CheckResult:
    mode = os.environ.get("JOB_DIGEST_TRIAGE_MODE", "rules").lower()
    if mode != "llm":
        return CheckResult("llm_triage", True, "not_enabled")

    provider = os.environ.get("LLM_PROVIDER", "mock").lower()
    if provider == "gemini":
        if not os.environ.get("GEMINI_API_KEY"):
            return CheckResult("llm_triage", False, "missing_gemini_api_key")
        return CheckResult("llm_triage", True, "configured", metadata={"provider": provider})
    if provider == "anthropic":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return CheckResult("llm_triage", False, "missing_anthropic_api_key")
        return CheckResult("llm_triage", True, "configured", metadata={"provider": provider})
    return CheckResult("llm_triage", False, "unsupported_or_mock_provider", provider)


def run_checks(args: argparse.Namespace) -> list[CheckResult]:
    checks = [
        check_required_env(),
        check_artifact_paths(),
        check_postgres_socket(),
        check_mcp_http(),
        check_smtp_config(),
        check_gmail_oauth(),
        check_digest_state(args.digest_max_age_days),
        check_llm_triage_config(),
    ]
    if args.check_smtp_login:
        checks.append(check_smtp_login())
    if args.check_kafka:
        checks.append(check_kafka())
    return checks


def build_report(checks: list[CheckResult]) -> dict[str, Any]:
    unhealthy = [check for check in checks if not check.ok]
    status = "healthy" if not unhealthy else "unhealthy"
    return {
        "schema_version": 1,
        "checked_at": _now_iso(),
        "status": status,
        "ok": not unhealthy,
        "checks": [check.as_dict() for check in checks],
    }


def _state_signature(report: dict[str, Any]) -> str:
    failures = [
        {"name": check["name"], "status": check["status"], "detail": check.get("detail", "")}
        for check in report.get("checks", [])
        if not check.get("ok")
    ]
    return json.dumps(failures, sort_keys=True)


def _format_alert(report: dict[str, Any]) -> tuple[str, str]:
    unhealthy = [check for check in report["checks"] if not check["ok"]]
    subject = f"Job Applications Health — {report['status']} ({len(unhealthy)} failing)"
    lines = [
        f"Job Applications health is {report['status']}.",
        f"Checked at: {report['checked_at']}",
        "",
    ]
    for check in unhealthy:
        lines.append(f"- {check['name']}: {check['status']}")
        if check.get("detail"):
            lines.append(f"  Detail: {check['detail']}")
    if not unhealthy:
        lines.append("All checks are healthy.")
    lines.append("")
    lines.append(f"Health state: {HEALTH_STATE_PATH}")
    return subject, "\n".join(lines)


def _should_notify(report: dict[str, Any], force: bool = False) -> bool:
    if force:
        return True
    signature = _state_signature(report)
    previous = _read_json(HEALTH_ALERT_STATE_PATH) or {}
    return signature != previous.get("signature")


def _record_notification_state(report: dict[str, Any]) -> None:
    _write_json(HEALTH_ALERT_STATE_PATH, {
        "signature": _state_signature(report),
        "recorded_at": _now_iso(),
        "status": report["status"],
    })


def notify_smtp(report: dict[str, Any]) -> bool:
    subject, body = _format_alert(report)
    return send_email(subject, body, config=SMTP_CONFIG)


def notify_webhook(report: dict[str, Any]) -> bool:
    webhook_url = os.environ.get("JOB_APP_HEALTH_WEBHOOK_URL", "")
    if not webhook_url:
        return False
    try:
        response = requests.post(webhook_url, json=report, timeout=DEFAULT_HTTP_TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.RequestException:
        return False
    return True


def notify_kafka(report: dict[str, Any]) -> bool:
    if os.environ.get("JOB_APP_HEALTH_KAFKA_ENABLED", "false").lower() != "true":
        return False
    broker = os.environ.get("JOB_APP_KAFKA_BROKER", "")
    topic = os.environ.get("JOB_APP_HEALTH_KAFKA_TOPIC", "job_applications.health")
    if not broker:
        return False
    try:
        from confluent_kafka import Producer
    except ImportError:
        return False

    delivered: list[str] = []

    def on_delivery(err, msg):
        if err:
            delivered.append(str(err))

    producer = Producer({
        "bootstrap.servers": broker,
        "client.id": "job-applications-health",
        "enable.idempotence": True,
        "acks": "all",
        "retries": 3,
        "retry.backoff.ms": 1000,
    })
    producer.produce(
        topic=topic,
        key="job-applications-health",
        value=json.dumps(report, sort_keys=True),
        callback=on_delivery,
    )
    undelivered = producer.flush(10.0)
    return undelivered == 0 and not delivered


def notify(report: dict[str, Any], *, force: bool = False) -> dict[str, bool]:
    if not _should_notify(report, force=force):
        return {"smtp": False, "webhook": False, "kafka": False, "suppressed_unchanged": True}
    results = {
        "smtp": notify_smtp(report),
        "webhook": notify_webhook(report),
        "kafka": notify_kafka(report),
        "suppressed_unchanged": False,
    }
    _record_notification_state(report)
    return results


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check Job Applications operational health")
    parser.add_argument("--digest-max-age-days", type=int, default=DEFAULT_DIGEST_MAX_AGE_DAYS)
    parser.add_argument("--check-smtp-login", action="store_true", help="Attempt SMTP STARTTLS login without sending email")
    parser.add_argument("--check-kafka", action="store_true", help="Check Kafka broker TCP connectivity")
    parser.add_argument("--notify", action="store_true", help="Notify on health-state changes")
    parser.add_argument("--force-notify", action="store_true", help="Notify even if the health-state signature is unchanged")
    parser.add_argument("--json", action="store_true", help="Print full JSON report")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    report = build_report(run_checks(args))
    _write_json(HEALTH_STATE_PATH, report)

    notification_results = None
    if args.notify or args.force_notify:
        notification_results = notify(report, force=args.force_notify)
        report["notification"] = notification_results
        _write_json(HEALTH_STATE_PATH, report)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Job Applications health: {report['status']}")
        for check in report["checks"]:
            prefix = "OK" if check["ok"] else "FAIL"
            print(f"{prefix} {check['name']}: {check['status']}")
        if notification_results is not None:
            print(f"Notification: {notification_results}")

    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
