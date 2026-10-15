"""Tests for set_applied_date: strict backdating with confirm gate and audit trail."""

import json
from datetime import datetime, timedelta, timezone

import pytest


def _now():
    return datetime.now(timezone.utc)


def _fmt(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _cutoff(now):
    """12-month cutoff, same arithmetic as the implementation."""
    try:
        return now.replace(year=now.year - 1)
    except ValueError:  # Feb 29 -> non-leap target year
        return now.replace(year=now.year - 1, day=28)


def _seed_app(company="TestCo", role_title="Engineer", stage="applied",
              history=None, applied_at=None):
    from job_applications_mcp_server import _create_application_record, _save_tracker
    app = _create_application_record(company, role_title, "/tmp/jd.md")
    app["stage"] = stage
    if history is not None:
        app["history"] = history
    if applied_at is not None:
        app["applied_at"] = applied_at
    _save_tracker({"schema_version": "1.0", "applications": [app]})
    return app


class TestSetAppliedDate:
    """Strict checks: id lookup, stage gate, date bounds, confirm gate, immutability, audit."""

    def test_happy_path_sets_applied_at_and_appends_audit(self):
        app = _seed_app(stage="applied")
        date = _fmt(_now() - timedelta(days=30))
        from job_applications_mcp_server import set_applied_date, _load_tracker
        result = set_applied_date(application_id=app["id"], applied_date=date, approved_by_user=True)
        assert result["ok"] is True
        assert result["applied_at"] == date
        assert result["previous_applied_at"] is None
        assert result["forced"] is False
        stored = _load_tracker()["applications"][0]
        assert stored["applied_at"] == date
        assert len(stored["audit"]) == 1
        entry = stored["audit"][0]
        assert entry["field"] == "applied_at"
        assert entry["old"] is None
        assert entry["new"] == date

    def test_missing_application_id(self):
        from job_applications_mcp_server import set_applied_date
        result = set_applied_date(application_id="", applied_date="2026-06-01")
        assert result["ok"] is False
        assert result["error"] == "missing_application_id"

    def test_missing_applied_date(self):
        app = _seed_app(stage="applied")
        from job_applications_mcp_server import set_applied_date
        result = set_applied_date(application_id=app["id"], applied_date="")
        assert result["ok"] is False
        assert result["error"] == "missing_applied_date"

    def test_application_not_found(self):
        from job_applications_mcp_server import set_applied_date
        result = set_applied_date(
            application_id="00000000-0000-0000-0000-000000000000",
            applied_date="2026-06-01",
            approved_by_user=True,
        )
        assert result["ok"] is False
        assert result["error"] == "application_not_found"

    def test_stage_not_applied_new_record(self):
        app = _seed_app(stage="new")
        from job_applications_mcp_server import set_applied_date
        result = set_applied_date(application_id=app["id"], applied_date="2026-06-01")
        assert result["ok"] is False
        assert result["error"] == "stage_not_applied"
        assert result["current_stage"] == "new"

    def test_stage_not_applied_rejected_without_applied_history(self):
        app = _seed_app(
            stage="rejected",
            history=[{"stage": "new", "at": "2026-01-01T00:00:00Z"},
                     {"stage": "rejected", "at": "2026-02-01T00:00:00Z"}],
        )
        from job_applications_mcp_server import set_applied_date
        result = set_applied_date(application_id=app["id"], applied_date="2026-06-01")
        assert result["ok"] is False
        assert result["error"] == "stage_not_applied"

    @pytest.mark.parametrize("stage", ["applied", "screening", "interview_r1", "offer", "accepted", "closed_won"])
    def test_stage_gate_accepts_progression_stages(self, stage):
        # Reaching requires_approval proves the stage gate passed (no write either way).
        app = _seed_app(
            stage=stage,
            history=[{"stage": "applied", "at": "2026-01-01T00:00:00Z"},
                     {"stage": stage, "at": "2026-02-01T00:00:00Z"}],
        )
        from job_applications_mcp_server import set_applied_date
        result = set_applied_date(application_id=app["id"], applied_date="2026-06-01")
        assert result["ok"] is False
        assert result["error"] == "requires_approval"

    def test_stage_gate_accepts_rejected_after_applied_via_history(self):
        app = _seed_app(
            stage="rejected",
            history=[{"stage": "applied", "at": "2026-01-01T00:00:00Z"},
                     {"stage": "rejected", "at": "2026-02-01T00:00:00Z"}],
        )
        from job_applications_mcp_server import set_applied_date
        result = set_applied_date(application_id=app["id"], applied_date="2026-06-01")
        assert result["error"] == "requires_approval"

    def test_future_date_rejected(self):
        app = _seed_app(stage="applied")
        future = _fmt(_now() + timedelta(days=1))
        from job_applications_mcp_server import set_applied_date
        result = set_applied_date(application_id=app["id"], applied_date=future, approved_by_user=True)
        assert result["ok"] is False
        assert result["error"] == "future_date"

    def test_older_than_12_months_rejected(self):
        app = _seed_app(stage="applied")
        from job_applications_mcp_server import set_applied_date
        two_years_ago = _fmt(_now() - timedelta(days=730))
        result = set_applied_date(application_id=app["id"], applied_date=two_years_ago, approved_by_user=True)
        assert result["ok"] is False
        assert result["error"] == "out_of_range"

    def test_day_before_cutoff_rejected(self):
        app = _seed_app(stage="applied")
        from job_applications_mcp_server import set_applied_date
        just_outside = _fmt(_cutoff(_now()) - timedelta(days=1))
        result = set_applied_date(application_id=app["id"], applied_date=just_outside, approved_by_user=True)
        assert result["ok"] is False
        assert result["error"] == "out_of_range"

    def test_just_inside_12_month_boundary_allowed(self):
        app = _seed_app(stage="applied")
        just_inside = _fmt(_cutoff(_now()) + timedelta(minutes=1))
        from job_applications_mcp_server import set_applied_date
        result = set_applied_date(application_id=app["id"], applied_date=just_inside, approved_by_user=True)
        assert result["ok"] is True
        assert result["applied_at"] == just_inside

    @pytest.mark.parametrize("bad_date", ["not-a-date", "15/03/2026", "2026-13-01"])
    def test_malformed_date_rejected(self, bad_date):
        app = _seed_app(stage="applied")
        from job_applications_mcp_server import set_applied_date
        result = set_applied_date(application_id=app["id"], applied_date=bad_date)
        assert result["ok"] is False
        assert result["error"] == "invalid_applied_date"
        assert result["applied_date"] == bad_date

    def test_date_only_string_normalized_to_utc_midnight(self):
        app = _seed_app(stage="applied")
        date_only = (_now() - timedelta(days=30)).strftime("%Y-%m-%d")
        from job_applications_mcp_server import set_applied_date
        result = set_applied_date(application_id=app["id"], applied_date=date_only, approved_by_user=True)
        assert result["ok"] is True
        assert result["applied_at"] == date_only + "T00:00:00Z"

    def test_unconfirmed_preview_writes_nothing(self):
        app = _seed_app(stage="applied")
        date = _fmt(_now() - timedelta(days=30))
        from job_applications_mcp_server import set_applied_date, _load_tracker
        result = set_applied_date(application_id=app["id"], applied_date=date)
        assert result["ok"] is False
        assert result["error"] == "requires_approval"
        assert result["requires_review"] is True
        stored = _load_tracker()["applications"][0]
        assert stored["applied_at"] is None
        assert stored["audit"] == []

    def test_preview_contains_all_check_results(self):
        app = _seed_app(stage="applied")
        date = _fmt(_now() - timedelta(days=30))
        from job_applications_mcp_server import set_applied_date
        result = set_applied_date(application_id=app["id"], applied_date=date)
        preview = result["preview"]
        assert preview["field"] == "applied_at"
        assert preview["current_applied_at"] is None
        assert preview["new_applied_at"] == date
        assert preview["is_overwrite"] is False
        checks = preview["checks"]
        assert checks == {
            "id_found": True,
            "stage_at_or_after_applied": True,
            "date_format": True,
            "not_future": True,
            "within_12_months": True,
            "immutability": "ok",
        }
        assert result["audit_would_append"]["new"] == date

    def test_reedit_without_force_blocked(self):
        preset = "2026-05-01T00:00:00Z"
        app = _seed_app(stage="applied", applied_at=preset)
        new_date = _fmt(_now() - timedelta(days=30))
        from job_applications_mcp_server import set_applied_date, _load_tracker
        result = set_applied_date(application_id=app["id"], applied_date=new_date, approved_by_user=True)
        assert result["ok"] is False
        assert result["error"] == "already_set"
        assert result["current_applied_at"] == preset
        assert _load_tracker()["applications"][0]["applied_at"] == preset

    def test_reedit_with_force_ok(self):
        preset = "2026-05-01T00:00:00Z"
        app = _seed_app(stage="applied", applied_at=preset)
        new_date = _fmt(_now() - timedelta(days=30))
        from job_applications_mcp_server import set_applied_date, _load_tracker
        result = set_applied_date(
            application_id=app["id"], applied_date=new_date,
            approved_by_user=True, force=True,
        )
        assert result["ok"] is True
        assert result["previous_applied_at"] == preset
        assert result["forced"] is True
        stored = _load_tracker()["applications"][0]
        assert stored["applied_at"] == new_date
        assert len(stored["audit"]) == 1
        assert stored["audit"][0]["old"] == preset
        assert stored["audit"][0]["forced"] is True

    def test_reason_recorded_in_audit(self):
        app = _seed_app(stage="applied")
        date = _fmt(_now() - timedelta(days=30))
        from job_applications_mcp_server import set_applied_date, _load_tracker
        result = set_applied_date(
            application_id=app["id"], applied_date=date,
            approved_by_user=True, reason="Backdated: applied in June, tracked late",
        )
        assert result["audit_entry"]["reason"] == "Backdated: applied in June, tracked late"
        stored = _load_tracker()["applications"][0]
        assert stored["audit"][0]["reason"] == "Backdated: applied in June, tracked late"

    def test_list_applications_includes_applied_at(self):
        app = _seed_app(stage="applied")
        date = _fmt(_now() - timedelta(days=30))
        from job_applications_mcp_server import set_applied_date, list_applications
        set_applied_date(application_id=app["id"], applied_date=date, approved_by_user=True)
        result = list_applications()
        assert result["ok"] is True
        assert result["applications"][0]["applied_at"] == date


class TestAppliedDateSchema:
    """Schema 1.2: applied_at + audit defaults, idempotent normalize."""

    def test_old_record_upgraded_on_load(self):
        from job_applications_mcp_server import TRACKER_PATH, _load_tracker
        raw = {
            "schema_version": "1.0",
            "applications": [{
                "id": "legacy1", "company": "OldCo", "role_title": "Dev",
                "jd_path": "/tmp/jd.md", "stage": "applied", "interview_round": None,
                "date_created": "2026-01-01T00:00:00Z",
                "history": [{"stage": "applied", "at": "2026-01-01T00:00:00Z"}],
                "followups": [], "outputs": {}, "submitted": {},
            }],
        }
        TRACKER_PATH.write_text(json.dumps(raw), encoding="utf-8")
        tracker = _load_tracker()
        assert tracker["schema_version"] == "1.2"
        app = tracker["applications"][0]
        assert app["applied_at"] is None
        assert app["audit"] == []

    def test_normalize_idempotent(self):
        from job_applications_mcp_server import _load_tracker
        _seed_app(stage="applied")
        first = _load_tracker()
        second = _load_tracker()
        assert first == second
        assert first["applications"][0]["audit"] == []

    def test_new_records_have_defaults(self):
        from job_applications_mcp_server import _create_application_record
        from src.tools._state import create_application_record
        for record in (
            _create_application_record("TestCo", "Engineer", "/tmp/jd.md"),
            create_application_record("TestCo", "Engineer", "/tmp/jd.md"),
        ):
            assert record["applied_at"] is None
            assert record["audit"] == []