"""notify_email routes Job-Applications email through fleet_sdk.notify (DEVOPS-243)."""

from __future__ import annotations

import pytest

import notify_email
from fleet_sdk.notify import DeliveryReceipt, DeliveryStatus, NotificationClient


def _client(tmp_path, ok: bool, sink: list):
    def transport(topic, key, value):
        sink.append((topic, key, value))
        return (True, "broker", "") if ok else (False, "", "down")

    return NotificationClient(
        brokers=["b:9094"], spool_path=tmp_path / "spool.db", transport_override=transport
    )


def test_publishes_email_channel_event(tmp_path, monkeypatch):
    sink: list = []
    monkeypatch.setattr(notify_email, "_client", lambda: _client(tmp_path, True, sink))
    assert notify_email.send_email("Daily digest", "body text", service="job_digest") is True
    assert len(sink) == 1
    payload = sink[0][2].decode()
    assert '"email"' in payload and "Job-Applications" in payload and "job_digest" in payload


def test_spooled_when_kafka_down_still_counts_as_sent(tmp_path, monkeypatch):
    # Spool guarantees later delivery, so the caller must not retry or mark failure.
    monkeypatch.setattr(notify_email, "_client", lambda: _client(tmp_path, False, []))
    assert notify_email.send_email("s", "b", service="tracker_daily") is True


@pytest.mark.parametrize(
    "status,expected",
    [
        (DeliveryStatus.PUBLISHED_KAFKA, True),
        (DeliveryStatus.SPOOL_BUFFERED, True),
        (DeliveryStatus.SUPPRESSED_DEDUP, True),
        (DeliveryStatus.FAILED, False),
    ],
)
def test_result_follows_receipt_ok(monkeypatch, status, expected):
    monkeypatch.setattr(
        notify_email,
        "emit_notification",
        lambda **kw: DeliveryReceipt(notification_id="n", status=status),
    )
    assert notify_email.send_email("s", "b", service="x") is expected


def test_no_smtp_in_app_code():
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parent
    pattern = re.compile(r"\bsmtplib\b|fleet_notify|SMTP_CONFIG")
    offenders = [
        p.name
        for p in (root / n for n in ("app_health.py", "job_digest.py", "tracker_daily.py", "notify_email.py"))
        if pattern.search(p.read_text())
    ]
    assert offenders == []
