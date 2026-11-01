"""Property-based tests for the company/title rename fix (Task 4).

Spec: .kiro/specs/rename-application-company-title (bugfix)

Covers the three correctness properties from design.md with hypothesis:

- Property 1 (Bug Condition): random rename targets -> reloaded record reflects
  the new value(s) and `updated_fields` lists them.
- Property 2 (Preservation): random non-rename payloads -> fixed output equals
  the baseline (identity fields untouched, documented payload shape).
- Property 3 (Safety): random non-matching recordRef with rename intent ->
  error and zero mutation.

Persistence is driven through injected `tracker_loader` / `tracker_saver`
hooks over an in-memory tracker (no disk, NAS, or Postgres).

**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 3.1, 3.2, 3.3, 3.4, 3.5**
"""

import copy

from hypothesis import given, settings, strategies as st

import job_applications_mcp_server as server
from src.tools.lifecycle import update_application


# Non-empty, whitespace-meaningful names. We also strip-compare to avoid
# generating a "new" value that only differs from the current one by surrounding
# behavior; the function compares with plain `!=`, so any distinct string counts.
_names = st.text(min_size=1, max_size=40).filter(lambda s: s.strip() != "")

_STABLE_STAGES = ["new", "applied", "screening"]


def _base_record(*, app_id, company, role_title, stage="new"):
    return {
        "id": app_id,
        "company": company,
        "role_title": role_title,
        "stage": stage,
        "interview_round": None,
        "date_created": "2026-01-01T00:00:00Z",
        "applied_at": None,
        "history": [{"stage": stage, "at": "2026-01-01T00:00:00Z"}],
        "followups": [],
        "metadata": {},
        "audit": [],
    }


def _make_hooks(tracker):
    store = {"saved": None, "save_count": 0}

    def loader():
        return tracker

    def saver(t):
        store["save_count"] += 1
        store["saved"] = copy.deepcopy(t)

    return loader, saver, store


def _record_by_id(container, app_id):
    for app in (container or {}).get("applications", []):
        if app.get("id") == app_id:
            return app
    return None


# ===========================================================================
# Property 1 - random rename targets persist and are reported
# ===========================================================================
@settings(max_examples=100, deadline=None)
@given(
    app_id=st.uuids().map(str),
    company=_names,
    role_title=_names,
    new_company=st.one_of(st.none(), _names),
    new_role_title=st.one_of(st.none(), _names),
)
def test_property1_rename_persists_and_reports(
    app_id, company, role_title, new_company, new_role_title
):
    # renameIntended: at least one rename field present.
    if new_company is None and new_role_title is None:
        return

    tracker = {
        "schema_version": "1.0",
        "applications": [_base_record(app_id=app_id, company=company, role_title=role_title)],
    }
    loader, saver, store = _make_hooks(tracker)

    res = update_application(
        application_id=app_id,
        new_company=new_company,
        new_role_title=new_role_title,
        tracker_loader=loader,
        tracker_saver=saver,
    )

    assert res["ok"] is True
    assert store["save_count"] == 1
    rec = _record_by_id(store["saved"], app_id)
    assert rec is not None

    # company
    if new_company is not None:
        expected_company = new_company
        changed_company = new_company != company
    else:
        expected_company = company
        changed_company = False
    assert rec["company"] == expected_company
    assert res["company"] == expected_company
    assert ("company" in res["updated_fields"]) == changed_company

    # role_title
    if new_role_title is not None:
        expected_role = new_role_title
        changed_role = new_role_title != role_title
    else:
        expected_role = role_title
        changed_role = False
    assert rec["role_title"] == expected_role
    assert res["role_title"] == expected_role
    assert ("role_title" in res["updated_fields"]) == changed_role


# ===========================================================================
# Property 2 - random non-rename payloads leave identity fields untouched
# ===========================================================================
@st.composite
def _record_and_nonrename_call(draw):
    app_id = draw(st.uuids().map(str))
    company = draw(_names)
    role_title = draw(_names)
    stage = draw(st.sampled_from(_STABLE_STAGES))
    record = _base_record(app_id=app_id, company=company, role_title=role_title, stage=stage)

    kind = draw(st.sampled_from(["stage", "linkedin", "interview", "lookup"]))
    payload = {}
    if kind == "stage":
        allowed = sorted(server._allowed_next_stages(stage))
        payload["new_stage"] = draw(st.sampled_from(allowed))
    elif kind == "linkedin":
        payload["linkedin_url"] = "https://linkedin.com/jobs/view/" + draw(
            st.integers(min_value=1, max_value=10_000_000).map(str)
        )
    elif kind == "interview":
        payload["interview_round"] = draw(_names)
    return record, payload, kind


@settings(max_examples=100, deadline=None)
@given(data=_record_and_nonrename_call())
def test_property2_nonrename_leaves_identity_untouched(data):
    record, payload, kind = data
    app_id = record["id"]
    orig_company = record["company"]
    orig_role = record["role_title"]

    tracker = {"schema_version": "1.0", "applications": [copy.deepcopy(record)]}
    loader, saver, store = _make_hooks(tracker)

    # Explicitly pass the rename params as None to prove non-rename semantics.
    res = update_application(
        application_id=app_id,
        new_company=None,
        new_role_title=None,
        tracker_loader=loader,
        tracker_saver=saver,
        **payload,
    )

    assert res["ok"] is True
    assert res["company"] == orig_company
    assert res["role_title"] == orig_role
    rec = _record_by_id(store["saved"], app_id)
    assert rec["company"] == orig_company
    assert rec["role_title"] == orig_role
    # No rename audit entries for a non-rename call.
    assert [a for a in rec["audit"] if a.get("action") == "rename"] == []
    assert "company" not in res["updated_fields"]
    assert "role_title" not in res["updated_fields"]

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


# ===========================================================================
# Property 3 - rename on a non-matching recordRef errors with zero mutation
# ===========================================================================
@settings(max_examples=100, deadline=None)
@given(
    seed_company=_names,
    seed_role=_names,
    miss_company=_names,
    new_company=st.one_of(st.none(), _names),
    new_role_title=st.one_of(st.none(), _names),
)
def test_property3_missing_target_errors_no_mutation(
    seed_company, seed_role, miss_company, new_company, new_role_title
):
    # Ensure a genuine miss: the lookup company differs from the seeded one.
    if miss_company.strip().lower() == seed_company.strip().lower():
        return
    # renameIntended.
    if new_company is None and new_role_title is None:
        return

    tracker = {
        "schema_version": "1.0",
        "applications": [
            _base_record(
                app_id="00000000-0000-0000-0000-000000000099",
                company=seed_company,
                role_title=seed_role,
            )
        ],
    }
    before = copy.deepcopy(tracker)
    loader, saver, store = _make_hooks(tracker)

    res = update_application(
        company=miss_company,
        role_title="definitely-not-a-real-role-xyz",
        new_company=new_company,
        new_role_title=new_role_title,
        tracker_loader=loader,
        tracker_saver=saver,
    )

    assert res["ok"] is False
    assert res["error"] == "application_not_found"
    assert store["save_count"] == 0
    assert tracker == before
