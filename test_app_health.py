"""Tests for app_health.py."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import app_health


def test_digest_failure_state_is_unhealthy(tmp_path, monkeypatch):
    failure_path = tmp_path / ".job_digest_failure.json"
    failure_path.write_text(json.dumps({"reason": "gmail_auth_failed"}), encoding="utf-8")
    monkeypatch.setattr(app_health, "DIGEST_FAILURE_STATE_PATH", failure_path)

    result = app_health.check_digest_state()

    assert result.ok is False
    assert result.status == "unresolved_failure"
    assert result.detail == "gmail_auth_failed"


def test_digest_stale_marker_is_unhealthy(tmp_path, monkeypatch):
    marker = tmp_path / ".job_digest_last_run"
    marker.write_text("2026-08-27", encoding="utf-8")
    monkeypatch.setattr(app_health, "DIGEST_FAILURE_STATE_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(app_health, "DIGEST_LAST_RUN_PATH", marker)

    result = app_health.check_digest_state(max_age_days=1)

    assert result.ok is False
    assert result.status == "stale_last_success"


def test_gmail_oauth_reports_failed_account(monkeypatch):
    monkeypatch.setattr(app_health, "GMAIL_ACCOUNTS_CONFIG", "gmail_accounts.json")

    account = MagicMock()
    account.email = "geesin@gmail.com"
    manager = MagicMock()
    manager.accounts = {"geesin": account}
    manager.get_access_token.return_value = None

    with patch("app_health.GmailAccountManager", return_value=manager):
        result = app_health.check_gmail_oauth()

    assert result.ok is False
    assert result.status == "auth_failed"
    assert result.metadata["failed"] == [{"key": "geesin", "email": "geesin@gmail.com"}]


def test_notify_suppresses_unchanged_signature(tmp_path, monkeypatch):
    alert_state = tmp_path / ".health_alert_state.json"
    monkeypatch.setattr(app_health, "HEALTH_ALERT_STATE_PATH", alert_state)
    monkeypatch.setattr(app_health, "notify_smtp", lambda report: True)
    monkeypatch.setattr(app_health, "notify_webhook", lambda report: False)
    monkeypatch.setattr(app_health, "notify_kafka", lambda report: False)

    report = {
        "status": "unhealthy",
        "checks": [{"name": "gmail_oauth", "ok": False, "status": "auth_failed", "detail": ""}],
    }

    first = app_health.notify(report)
    second = app_health.notify(report)

    assert first["smtp"] is True
    assert second["suppressed_unchanged"] is True


def test_main_writes_health_state_and_exits_nonzero(tmp_path, monkeypatch):
    state_path = tmp_path / ".job_app_health.json"
    monkeypatch.setattr(app_health, "HEALTH_STATE_PATH", state_path)
    monkeypatch.setattr(app_health, "run_checks", lambda args: [
        app_health.CheckResult("required_env", False, "missing_required_env", "DATABASE_URL")
    ])

    result = app_health.main([])

    assert result == 1
    saved = json.loads(state_path.read_text(encoding="utf-8"))
    assert saved["status"] == "unhealthy"


def test_llm_triage_config_reports_missing_key(monkeypatch):
    monkeypatch.setenv("JOB_DIGEST_TRIAGE_MODE", "llm")
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    result = app_health.check_llm_triage_config()

    assert result.ok is False
    assert result.status == "missing_gemini_api_key"


def test_llm_triage_config_ok_for_gemini(monkeypatch):
    monkeypatch.setenv("JOB_DIGEST_TRIAGE_MODE", "llm")
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "fake")

    result = app_health.check_llm_triage_config()

    assert result.ok is True
    assert result.status == "configured"
