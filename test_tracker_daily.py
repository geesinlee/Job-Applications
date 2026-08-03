import pytest

import tracker_daily as td


def _followup(action_type, due_date, status="pending"):
    return {
        "id": "f1", "action_type": action_type, "due_date": due_date,
        "status": status, "completed_at": None,
    }


def _application(company, role_title, stage, followups=None):
    return {
        "id": "a1", "company": company, "role_title": role_title, "stage": stage,
        "followups": followups or [],
    }


class TestFlagOverdueFollowups:
    def test_flags_pending_past_due_as_overdue(self):
        tracker = {"applications": [
            _application("Acme", "AE", "applied", [_followup("send_follow_up_email", "2026-07-01")]),
        ]}
        flagged = td._flag_overdue_followups(tracker, "2026-08-03")
        assert flagged == 1
        assert tracker["applications"][0]["followups"][0]["status"] == "overdue"

    def test_leaves_future_due_date_pending(self):
        tracker = {"applications": [
            _application("Acme", "AE", "applied", [_followup("send_follow_up_email", "2026-09-01")]),
        ]}
        flagged = td._flag_overdue_followups(tracker, "2026-08-03")
        assert flagged == 0
        assert tracker["applications"][0]["followups"][0]["status"] == "pending"

    def test_leaves_non_pending_status_untouched(self):
        tracker = {"applications": [
            _application("Acme", "AE", "applied", [_followup("send_follow_up_email", "2026-07-01", status="cancelled")]),
        ]}
        flagged = td._flag_overdue_followups(tracker, "2026-08-03")
        assert flagged == 0
        assert tracker["applications"][0]["followups"][0]["status"] == "cancelled"


class TestCompileDigest:
    def test_active_excludes_terminal_stages(self):
        tracker = {"applications": [
            _application("Acme", "AE", "applied"),
            _application("Globex", "SE", "rejected"),
        ]}
        digest = td._compile_digest(tracker, "2026-08-03")
        assert digest["active_count"] == 1
        assert "applied" in digest["active_by_stage"]
        assert "rejected" not in digest["active_by_stage"]

    def test_overdue_followups_sorted_by_due_date(self):
        tracker = {"applications": [
            _application("Acme", "AE", "applied", [
                _followup("send_follow_up_email", "2026-08-01", status="overdue"),
            ]),
            _application("Globex", "SE", "applied", [
                _followup("send_follow_up_email", "2026-07-15", status="overdue"),
            ]),
        ]}
        digest = td._compile_digest(tracker, "2026-08-03")
        dates = [f["due_date"] for f in digest["overdue_followups"]]
        assert dates == sorted(dates)
        assert len(digest["overdue_followups"]) == 2

    def test_due_soon_within_seven_days(self):
        tracker = {"applications": [
            _application("Acme", "AE", "applied", [
                _followup("send_thank_you_note", "2026-08-05"),
            ]),
            _application("Globex", "SE", "applied", [
                _followup("send_follow_up_email", "2026-09-01"),
            ]),
        ]}
        digest = td._compile_digest(tracker, "2026-08-03")
        due_soon_types = [f["action_type"] for f in digest["due_soon"]]
        assert due_soon_types == ["send_thank_you_note"]


class TestFormatDigestEmail:
    def test_subject_line_format(self):
        overdue_entry = {"company": "Acme", "role_title": "AE", "action_type": "send_follow_up_email", "due_date": "2026-07-01"}
        digest = {"active_count": 3, "overdue_followups": [overdue_entry, overdue_entry],
                   "active_by_stage": {}, "due_soon": []}
        subject, _ = td._format_digest_email(digest, "2026-08-03")
        assert subject == "Job Applications Daily — 2026-08-03 | 3 active, 2 overdue"

    def test_body_contains_sections(self):
        digest = {
            "active_count": 1,
            "active_by_stage": {"applied": [{"company": "Acme", "role_title": "AE"}]},
            "overdue_followups": [{"company": "Acme", "role_title": "AE", "action_type": "send_follow_up_email", "due_date": "2026-07-01"}],
            "due_soon": [{"company": "Globex", "role_title": "SE", "action_type": "send_thank_you_note", "due_date": "2026-08-05"}],
        }
        _, body = td._format_digest_email(digest, "2026-08-03")
        assert "ACTIVE APPLICATIONS (1)" in body
        assert "Acme (AE)" in body
        assert "OVERDUE FOLLOW-UPS (1)" in body
        assert "DUE IN NEXT 7 DAYS (1)" in body
        assert "Globex (SE)" in body

    def test_body_shows_none_placeholders_when_empty(self):
        digest = {"active_count": 0, "active_by_stage": {}, "overdue_followups": [], "due_soon": []}
        _, body = td._format_digest_email(digest, "2026-08-03")
        assert body.count("(none)") == 3


class TestSendDigestEmail:
    def test_returns_false_when_not_configured(self, monkeypatch):
        monkeypatch.setattr(td, "DIGEST_EMAIL", "")
        monkeypatch.setattr(td, "GMAIL_APP_PASSWORD", "")
        assert td._send_digest_email("subject", "body") is False

    def test_sends_via_smtp_when_configured(self, monkeypatch):
        monkeypatch.setattr(td, "DIGEST_EMAIL", "user@gmail.com")
        monkeypatch.setattr(td, "GMAIL_APP_PASSWORD", "app-password")

        sent_messages = []

        class FakeSMTP:
            def __init__(self, host, port, timeout=None):
                self.host, self.port = host, port

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def starttls(self):
                pass

            def login(self, user, password):
                assert user == "user@gmail.com"
                assert password == "app-password"

            def send_message(self, msg):
                sent_messages.append(msg)

        monkeypatch.setattr(td.smtplib, "SMTP", FakeSMTP)
        result = td._send_digest_email("subject", "body")
        assert result is True
        assert len(sent_messages) == 1
        assert sent_messages[0]["Subject"] == "subject"

    def test_returns_false_on_smtp_exception(self, monkeypatch):
        monkeypatch.setattr(td, "DIGEST_EMAIL", "user@gmail.com")
        monkeypatch.setattr(td, "GMAIL_APP_PASSWORD", "app-password")

        class RaisingSMTP:
            def __init__(self, *a, **k):
                raise OSError("connection refused")

        monkeypatch.setattr(td.smtplib, "SMTP", RaisingSMTP)
        assert td._send_digest_email("subject", "body") is False


class TestSyncToNas:
    def test_returns_false_when_unset(self, monkeypatch):
        monkeypatch.setattr(td, "NAS_SYNC_PATH", "")
        assert td._sync_to_nas() is False

    def test_constructs_rsync_command(self, monkeypatch, tmp_path):
        monkeypatch.setattr(td, "NAS_SYNC_PATH", "gs@rv-cloud.local:/share/job-app-data/")
        monkeypatch.setattr(td, "TRACKER_PATH", tmp_path / "tracker.json")
        monkeypatch.setattr(td, "PROFILE_PATH", tmp_path / "profile.json")

        captured = {}

        class FakeResult:
            returncode = 0

        def fake_run(cmd, check, capture_output, timeout):
            captured["cmd"] = cmd
            return FakeResult()

        monkeypatch.setattr(td.subprocess, "run", fake_run)
        result = td._sync_to_nas()
        assert result is True
        assert captured["cmd"] == [
            "rsync", "-a", str(tmp_path / "tracker.json"), str(tmp_path / "profile.json"),
            "gs@rv-cloud.local:/share/job-app-data/",
        ]

    def test_returns_false_on_nonzero_returncode(self, monkeypatch, tmp_path):
        monkeypatch.setattr(td, "NAS_SYNC_PATH", "gs@rv-cloud.local:/share/job-app-data/")

        class FakeResult:
            returncode = 1

        monkeypatch.setattr(td.subprocess, "run", lambda *a, **k: FakeResult())
        assert td._sync_to_nas() is False

    def test_returns_false_on_exception(self, monkeypatch):
        monkeypatch.setattr(td, "NAS_SYNC_PATH", "gs@rv-cloud.local:/share/job-app-data/")

        def raising_run(*a, **k):
            raise OSError("rsync not found")

        monkeypatch.setattr(td.subprocess, "run", raising_run)
        assert td._sync_to_nas() is False


class TestLoadSaveTracker:
    def test_load_missing_file_returns_empty_schema(self, tmp_path):
        assert td._load_tracker(tmp_path / "nope.json") == {"applications": []}

    def test_save_then_load_round_trips(self, tmp_path):
        path = tmp_path / "tracker.json"
        data = {"applications": [_application("Acme", "AE", "applied")]}
        td._save_tracker(path, data)
        assert td._load_tracker(path) == data
