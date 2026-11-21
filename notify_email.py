"""Job-Applications email via the fleet notification service (DEVOPS-243).

The app holds no SMTP credentials. It publishes an ``email``-channel event to
``fleet.notifications.v1`` (Kafka acks=all, SQLite spool fallback) and the
fleet notification worker sends the mail. ``send_email`` returns True once the
event is published or spooled; delivery is the worker's job.
"""

from __future__ import annotations

from fleet_sdk.notify import (
    NotificationCategory,
    NotificationChannel,
    NotificationClient,
    emit_notification,
    get_default_client,
)

REPO = "Job-Applications"


def _client() -> NotificationClient:
    return get_default_client()


def send_email(
    subject: str,
    body: str,
    *,
    service: str,
    severity: str = "INFO",
    category: str = NotificationCategory.DIGEST.value,
    dedup_key: str = "",
) -> bool:
    receipt = emit_notification(
        title=subject,
        body=body,
        severity=severity,
        category=category,
        repo=REPO,
        service=service,
        channels=[NotificationChannel.EMAIL.value],
        dedup_key=dedup_key,
        client=_client(),
    )
    return receipt.ok
