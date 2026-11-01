"""Preservation property tests (Property 2) for the company/title rename fix.

Spec: .kiro/specs/rename-application-company-title (bugfix)

OBSERVATION-FIRST / BASELINE: These tests capture the behavior that the fix
MUST NOT change. They exercise `update_application` (src/tools/lifecycle.py)
for NON-rename calls only (no `new_company` / `new_role_title` -- those params
do not exist yet) and assert the current behavior.

EXPECTED OUTCOME: these tests PASS on the current UNFIXED code, locking in the
baseline. They must keep passing after the fix (task 3.5).

Preservation scope (design.md "Preservation Requirements"):
- `new_stage` transitions: history append, follow-up create/cancel, payload.
- `linkedin_url` sets metadata.linkedin_url + jd_source_url.
- `interview_round` updates as before.
- Pure lookup by (company, role_title) and by application_id leaves the
  record unchanged.
- Other MCP tools (list_applications, get_application_status) and the
  `update_stage` alias behave as before.

All persistence is driven through the injected `tracker_loader` /
`tracker_saver` hooks over an in-memory tracker (no disk, NAS, or Postgres).

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5**
"""

import copy

from hypothesis import given, settings, strategies as st

import job_applications_mcp_server as server
from src.tools.lifecycle import (
    get_application_status,
    list_applications,
    update_application,
)


# ---------------------------------------------------------------------------
# In-memory tracker fixtures / hooks
# ---------------------------------------------------------------------------
def _base_record(
    *,
    app_id,
    company,
    role_title,
    stage="new",
    interview_round=None,
):
    return {
        "id": app_id,
        "company": company,
        "role_title": role_title,
        "jd_path": f"{company}/JD.md",
        "stage": stage,
        "interview_round": interview_round,
        "date_created": "2026-01-01T00:00:00Z",
        "applied_at": None,
        "history": [{"stage": stage, "at": "2026-01-01T00:00:00Z"}],
        "followups": [],
        "outputs": {},
        "submitted": {},
        "metadata": {},
        "audit": [],
    }


def _seed_tracker():
    return {
        "schema_version": "1.0",
        "applications": [
            _base_record(
                app_id="aaaaaaaa-0000-0000-0000-000000000001",
                company="Scitech",
                role_title="Product Lead (referral, title TBC)",
                stage="new",
            ),
            _base_record(
                app_id="bbbbbbbb-0000-0000-0000-000000000002",
                company="Acme Corp",
                role_title="Staff Engineer",
                stage="applied",
            ),
        ],
    }


def _make_hooks(tracker):
    """Return (loader, saver, store) over a live in-memory tracker."""
    store = {"saved": None, "save_count": 0}

    def loader():
        return tracker

    def saver(t):
        store["save_count"] += 1
        store["saved"] = copy.deepcopy(t)

    return loader, saver, store


def _record_by_id(tracker, app_id):
    for app in tracker.get("applications", []):
        if app.get("id") == app_id:
            return app
    return None


# ===========================================================================
# 3.1  Stage transition preservation
# ===========================================================================
def test_stage_transition_appends_history_and_payload():
    """A valid new_stage call: stage set, history appended, payload shaped."""
    tracker = _seed_tracker()
    loader, saver, store = _make_hooks(tracker)

    res = update_application(
        company="Acme Corp",
        role_title="Staff Engineer",
        new_stage="screening",
        tracker_loader=loader,
        tracker_saver=saver,
    )

    assert res["ok"] is True
    assert res["updated_fields"] == ["stage"]
    assert res["stage"] == "screening"
    assert res["previous_stage"] == "applied"
    assert res["new_stage"] == "screening"
    assert store["save_count"] == 1

    rec = _record_by_id(tracker, "bbbbbbbb-0000-0000-0000-000000000002")
    assert rec["stage"] == "screening"
    assert rec["history"][-1]["stage"] == "screening"
    assert len(rec["history"]) == 2


def test_stage_transition_to_applied_creates_followup():
    """new_stage='applied' auto-creates a pending send_follow_up_email."""
    tracker = _seed_tracker()
    loader, saver, store = _make_hooks(tracker)

    res = update_application(
        application_id="aaaaaaaa-0000-0000-0000-000000000001",
        new_stage="applied",
        tracker_loader=loader,
        tracker_saver=saver,
    )

    assert res["ok"] is True
    assert "stage" in res["updated_fields"]

    rec = _record_by_id(tracker, "aaaaaaaa-0000-0000-0000-000000000001")
    pending = [
        f for f in rec["followups"]
        if f["action_type"] == "send_follow_up_email" and f["status"] == "pending"
    ]
    assert len(pending) == 1


def test_stage_transition_interview_cancels_followup_email():
    """Advancing into an interview stage cancels a pending follow-up email."""
    tracker = _seed_tracker()
    # Acme is 'applied'; move to 'screening' then 'interview_r1'.
    loader, saver, _ = _make_hooks(tracker)
    update_application(
        application_id="bbbbbbbb-0000-0000-0000-000000000002",
        new_stage="screening",
        tracker_loader=loader,
        tracker_saver=saver,
    )
    rec = _record_by_id(tracker, "bbbbbbbb-0000-0000-0000-000000000002")
    # Seed a pending follow-up email as if applied created it.
    rec["followups"].append({
        "id": "f1",
        "action_type": "send_follow_up_email",
        "due_date": "2026-02-01",
        "status": "pending",
        "completed_at": None,
    })

    res = update_application(
        application_id="bbbbbbbb-0000-0000-0000-000000000002",
        new_stage="interview_r1",
        tracker_loader=loader,
        tracker_saver=saver,
    )
    assert res["ok"] is True
    assert res["interview_round"] == 1

    emails = [f for f in rec["followups"] if f["action_type"] == "send_follow_up_email"]
    assert all(f["status"] == "cancelled" for f in emails)
    thanks = [f for f in rec["followups"] if f["action_type"] == "send_thank_you_note"]
    assert any(f["status"] == "pending" for f in thanks)


def test_invalid_transition_rejected_without_save():
    """An illegal stage jump returns invalid_transition and does not persist."""
    tracker = _seed_tracker()
    before = copy.deepcopy(tracker)
    loader, saver, store = _make_hooks(tracker)

    res = update_application(
        application_id="aaaaaaaa-0000-0000-0000-000000000001",  # stage 'new'
        new_stage="offer",
        tracker_loader=loader,
        tracker_saver=saver,
    )

    assert res["ok"] is False
    assert res["error"] == "invalid_transition"
    assert store["save_count"] == 0
    assert tracker == before


# ===========================================================================
# 3.2  linkedin_url / interview_round preservation
# ===========================================================================
def test_linkedin_url_sets_metadata_and_jd_source():
    tracker = _seed_tracker()
    loader, saver, store = _make_hooks(tracker)
    url = "https://linkedin.com/jobs/view/123"

    res = update_application(
        application_id="aaaaaaaa-0000-0000-0000-000000000001",
        linkedin_url=url,
        tracker_loader=loader,
        tracker_saver=saver,
    )

    assert res["ok"] is True
    assert res["updated_fields"] == ["linkedin_url"]
    assert res["linkedin_url"] == url
    assert store["save_count"] == 1

    rec = _record_by_id(tracker, "aaaaaaaa-0000-0000-0000-000000000001")
    assert rec["metadata"]["linkedin_url"] == url
    assert rec["jd_source_url"] == url


def test_interview_round_update_sets_field():
    tracker = _seed_tracker()
    loader, saver, store = _make_hooks(tracker)

    res = update_application(
        application_id="bbbbbbbb-0000-0000-0000-000000000002",
        interview_round="technical screen",
        tracker_loader=loader,
        tracker_saver=saver,
    )

    assert res["ok"] is True
    assert res["updated_fields"] == ["interview_round"]
    assert res["interview_round"] == "technical screen"

    rec = _record_by_id(tracker, "bbbbbbbb-0000-0000-0000-000000000002")
    assert rec["interview_round"] == "technical screen"


# ===========================================================================
# 3.3  Lookup-only resolution leaves the record unchanged
# ===========================================================================
def test_lookup_only_by_company_role_leaves_record_unchanged():
    """No update params supplied -> record body is unchanged (lookup only).

    A tracker_saver call may still occur (current behavior saves at the end),
    but the located record's fields must be byte-for-byte identical.
    """
    tracker = _seed_tracker()
    before = copy.deepcopy(tracker)
    loader, saver, _ = _make_hooks(tracker)

    res = update_application(
        company="Scitech",
        role_title="Product Lead (referral, title TBC)",
        tracker_loader=loader,
        tracker_saver=saver,
    )

    assert res["ok"] is True
    assert res["updated_fields"] == []
    assert res["company"] == "Scitech"
    assert res["role_title"] == "Product Lead (referral, title TBC)"
    # No record in the tracker changed.
    assert tracker == before


def test_lookup_only_by_application_id_leaves_record_unchanged():
    tracker = _seed_tracker()
    before = copy.deepcopy(tracker)
    loader, saver, _ = _make_hooks(tracker)

    res = update_application(
        application_id="bbbbbbbb-0000-0000-0000-000000000002",
        tracker_loader=loader,
        tracker_saver=saver,
    )

    assert res["ok"] is True
    assert res["updated_fields"] == []
    assert res["company"] == "Acme Corp"
    assert res["role_title"] == "Staff Engineer"
    assert tracker == before


def test_missing_identifier_returns_error_no_save():
    tracker = _seed_tracker()
    before = copy.deepcopy(tracker)
    loader, saver, store = _make_hooks(tracker)

    res = update_application(
        tracker_loader=loader,
        tracker_saver=saver,
    )

    assert res["ok"] is False
    assert res["error"] == "missing_identifier"
    assert store["save_count"] == 0
    assert tracker == before


# ===========================================================================
# 3.5  Other MCP tools + update_stage alias behave as before
# ===========================================================================
def test_list_applications_enriched_shape():
    tracker = _seed_tracker()
    loader, _, _ = _make_hooks(tracker)

    res = list_applications(tracker_loader=loader)
    assert res["ok"] is True
    assert res["count"] == 2
    companies = {a["company"] for a in res["applications"]}
    assert companies == {"Scitech", "Acme Corp"}


def test_list_applications_company_filter():
    tracker = _seed_tracker()
    loader, _, _ = _make_hooks(tracker)

    res = list_applications(company="Acme", tracker_loader=loader)
    assert res["ok"] is True
    assert res["count"] == 1
    assert res["applications"][0]["company"] == "Acme Corp"


def test_get_application_status_by_id(tmp_path):
    """Resolve by application_id. With no company folder on disk the tool
    returns its documented exists=False branch; the identity is resolved from
    the record and the tracker is left unchanged (lookup only)."""
    tracker = _seed_tracker()
    before = copy.deepcopy(tracker)
    loader, _, _ = _make_hooks(tracker)

    res = get_application_status(
        application_id="bbbbbbbb-0000-0000-0000-000000000002",
        tracker_loader=loader,
        artefacts_dir=tmp_path,
    )
    assert res["ok"] is True
    assert res["company"] == "Acme Corp"
    assert res["role_title"] == "Staff Engineer"
    assert res["exists"] is False
    # Pure lookup: the record is not mutated.
    assert tracker == before


def test_update_stage_alias_preserves_stage_behavior(monkeypatch):
    """The update_stage alias (server global hooks) still advances the stage."""
    tracker = _seed_tracker()
    loader, saver, store = _make_hooks(tracker)
    monkeypatch.setattr(server, "_load_tracker", loader)
    monkeypatch.setattr(server, "_save_tracker", saver)

    res = server.update_stage(
        application_id="bbbbbbbb-0000-0000-0000-000000000002",
        new_stage="screening",
    )

    assert res["ok"] is True
    assert res["stage"] == "screening"
    assert res["previous_stage"] == "applied"
    assert store["save_count"] == 1


# ===========================================================================
# Property-based preservation: random non-rename payloads on random records
# ===========================================================================
_STABLE_STAGES = ["new", "applied", "screening"]

_names = st.text(min_size=1, max_size=30).filter(lambda s: s.strip() != "")


@st.composite
def _record_and_nonrename_call(draw):
    """Generate one record plus a non-rename update payload for it.

    Payload kinds: stage transition (valid), linkedin_url, interview_round,
    or lookup-only. new_company / new_role_title are never referenced.
    """
    app_id = draw(st.uuids().map(str))
    company = draw(_names)
    role_title = draw(_names)
    stage = draw(st.sampled_from(_STABLE_STAGES))
    record = _base_record(
        app_id=app_id, company=company, role_title=role_title, stage=stage
    )

    kind = draw(st.sampled_from(["stage", "linkedin", "interview", "lookup"]))
    payload = {}
    if kind == "stage":
        # Pick a valid next stage for the generated starting stage.
        allowed = sorted(server._allowed_next_stages(stage))
        payload["new_stage"] = draw(st.sampled_from(allowed))
    elif kind == "linkedin":
        payload["linkedin_url"] = "https://linkedin.com/jobs/view/" + draw(
            st.integers(min_value=1, max_value=10_000_000).map(str)
        )
    elif kind == "interview":
        payload["interview_round"] = draw(_names)
    # kind == "lookup" -> empty payload (pure resolution)

    return record, payload, kind


@settings(max_examples=100, deadline=None)
@given(data=_record_and_nonrename_call())
def test_nonrename_calls_preserve_identity_fields(data):
    """For any non-rename call, company/role_title are never altered and the
    result payload matches the documented shape for that update kind."""
    record, payload, kind = data
    app_id = record["id"]
    orig_company = record["company"]
    orig_role = record["role_title"]

    tracker = {"schema_version": "1.0", "applications": [copy.deepcopy(record)]}
    loader, saver, store = _make_hooks(tracker)

    res = update_application(
        application_id=app_id,
        tracker_loader=loader,
        tracker_saver=saver,
        **payload,
    )

    assert res["ok"] is True
    # Identity fields are never touched by a non-rename call.
    assert res["company"] == orig_company
    assert res["role_title"] == orig_role
    rec = _record_by_id(tracker, app_id)
    assert rec["company"] == orig_company
    assert rec["role_title"] == orig_role

    if kind == "stage":
        assert "stage" in res["updated_fields"]
        assert res["stage"] == payload["new_stage"]
    elif kind == "linkedin":
        assert res["updated_fields"] == ["linkedin_url"]
        assert rec["metadata"]["linkedin_url"] == payload["linkedin_url"]
    elif kind == "interview":
        assert res["updated_fields"] == ["interview_round"]
        assert rec["interview_round"] == payload["interview_round"]
    else:  # lookup
        assert res["updated_fields"] == []
