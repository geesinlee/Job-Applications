"""Unit tests for the company/title rename fix.

Spec: .kiro/specs/rename-application-company-title (bugfix), Task 4.

These are example-based unit tests complementing the property-based coverage
in test_rename_company_title_bug.py and test_rename_company_title_preservation.py.
They exercise the concrete rename cases called out in design.md "Unit Tests":

- Rename company only / title only / both — by lookup keys and by application_id.
- No-op rename (new value equals current) does not spuriously mark fields or
  corrupt history / audit.
- Rename on a missing target returns `application_not_found` with no save.
- Mixed call: `new_stage` + rename in one call applies both and persists once.

Persistence is driven through injected `tracker_loader` / `tracker_saver`
hooks over an in-memory tracker (no disk, NAS, or Postgres).

**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 3.1**
"""

import copy

from src.tools.lifecycle import update_application


SEED_ID = "11111111-1111-1111-1111-111111111111"
SEED_COMPANY = "Scitech"
SEED_TITLE = "Product Lead (referral, title TBC)"


def _seed_tracker(stage="new"):
    return {
        "schema_version": "1.0",
        "applications": [
            {
                "id": SEED_ID,
                "company": SEED_COMPANY,
                "role_title": SEED_TITLE,
                "stage": stage,
                "interview_round": None,
                "history": [{"stage": stage, "at": "2026-01-01T00:00:00Z"}],
                "followups": [],
                "metadata": {},
                "audit": [],
            }
        ],
    }


def _make_hooks(tracker):
    store = {"saved": None, "save_count": 0}

    def loader():
        return tracker

    def saver(t):
        store["save_count"] += 1
        store["saved"] = copy.deepcopy(t)

    return loader, saver, store


def _reload(store, *, by_id=SEED_ID):
    for app in (store["saved"] or {}).get("applications", []):
        if app.get("id") == by_id:
            return app
    return None


# ---------------------------------------------------------------------------
# Rename company only
# ---------------------------------------------------------------------------
def test_rename_company_only_by_lookup():
    tracker = _seed_tracker()
    loader, saver, store = _make_hooks(tracker)

    res = update_application(
        company=SEED_COMPANY,
        role_title=SEED_TITLE,
        new_company="Scientech Consulting",
        tracker_loader=loader,
        tracker_saver=saver,
    )

    assert res["ok"] is True
    assert res["updated_fields"] == ["company"]
    assert res["company"] == "Scientech Consulting"
    assert res["role_title"] == SEED_TITLE
    assert store["save_count"] == 1
    assert _reload(store)["company"] == "Scientech Consulting"


def test_rename_company_only_by_application_id():
    tracker = _seed_tracker()
    loader, saver, store = _make_hooks(tracker)

    res = update_application(
        application_id=SEED_ID,
        new_company="Scientech Consulting",
        tracker_loader=loader,
        tracker_saver=saver,
    )

    assert res["ok"] is True
    assert res["updated_fields"] == ["company"]
    assert res["company"] == "Scientech Consulting"
    # id branch must not have clobbered the rename with the stored value.
    assert _reload(store)["company"] == "Scientech Consulting"
    assert _reload(store)["role_title"] == SEED_TITLE


# ---------------------------------------------------------------------------
# Rename title only
# ---------------------------------------------------------------------------
def test_rename_title_only_by_lookup():
    tracker = _seed_tracker()
    loader, saver, store = _make_hooks(tracker)

    res = update_application(
        company=SEED_COMPANY,
        role_title=SEED_TITLE,
        new_role_title="Product Lead",
        tracker_loader=loader,
        tracker_saver=saver,
    )

    assert res["ok"] is True
    assert res["updated_fields"] == ["role_title"]
    assert res["role_title"] == "Product Lead"
    assert res["company"] == SEED_COMPANY
    assert _reload(store)["role_title"] == "Product Lead"


def test_rename_title_only_by_application_id():
    tracker = _seed_tracker()
    loader, saver, store = _make_hooks(tracker)

    res = update_application(
        application_id=SEED_ID,
        new_role_title="Product Lead",
        tracker_loader=loader,
        tracker_saver=saver,
    )

    assert res["ok"] is True
    assert res["updated_fields"] == ["role_title"]
    assert res["role_title"] == "Product Lead"
    assert _reload(store)["role_title"] == "Product Lead"


# ---------------------------------------------------------------------------
# Rename both
# ---------------------------------------------------------------------------
def test_rename_both_by_lookup():
    tracker = _seed_tracker()
    loader, saver, store = _make_hooks(tracker)

    res = update_application(
        company=SEED_COMPANY,
        role_title=SEED_TITLE,
        new_company="Scientech Consulting",
        new_role_title="Product Lead",
        tracker_loader=loader,
        tracker_saver=saver,
    )

    assert res["ok"] is True
    assert set(res["updated_fields"]) == {"company", "role_title"}
    assert res["company"] == "Scientech Consulting"
    assert res["role_title"] == "Product Lead"
    assert store["save_count"] == 1
    rec = _reload(store)
    assert rec["company"] == "Scientech Consulting"
    assert rec["role_title"] == "Product Lead"


def test_rename_both_by_application_id():
    tracker = _seed_tracker()
    loader, saver, store = _make_hooks(tracker)

    res = update_application(
        application_id=SEED_ID,
        new_company="Scientech Consulting",
        new_role_title="Product Lead",
        tracker_loader=loader,
        tracker_saver=saver,
    )

    assert res["ok"] is True
    assert set(res["updated_fields"]) == {"company", "role_title"}
    rec = _reload(store)
    assert rec["company"] == "Scientech Consulting"
    assert rec["role_title"] == "Product Lead"
    # Exactly one audit entry per changed field.
    actions = [a for a in rec["audit"] if a.get("action") == "rename"]
    assert {a["field"] for a in actions} == {"company", "role_title"}


# ---------------------------------------------------------------------------
# No-op rename: new value equals current value
# ---------------------------------------------------------------------------
def test_noop_rename_company_equals_current_does_not_mark_or_audit():
    tracker = _seed_tracker()
    before = copy.deepcopy(tracker)
    loader, saver, store = _make_hooks(tracker)

    res = update_application(
        application_id=SEED_ID,
        new_company=SEED_COMPANY,  # identical to stored value
        tracker_loader=loader,
        tracker_saver=saver,
    )

    assert res["ok"] is True
    # No spurious field marking.
    assert "company" not in res["updated_fields"]
    assert res["updated_fields"] == []
    rec = _reload(store)
    # History and audit uncorrupted (no rename audit appended).
    assert rec["history"] == before["applications"][0]["history"]
    assert [a for a in rec["audit"] if a.get("action") == "rename"] == []


def test_noop_rename_both_equal_current_no_changes():
    tracker = _seed_tracker()
    loader, saver, store = _make_hooks(tracker)

    res = update_application(
        application_id=SEED_ID,
        new_company=SEED_COMPANY,
        new_role_title=SEED_TITLE,
        tracker_loader=loader,
        tracker_saver=saver,
    )

    assert res["ok"] is True
    assert res["updated_fields"] == []
    rec = _reload(store)
    assert [a for a in rec["audit"] if a.get("action") == "rename"] == []


# ---------------------------------------------------------------------------
# Missing target: error, no save
# ---------------------------------------------------------------------------
def test_rename_missing_company_returns_not_found_no_save():
    tracker = _seed_tracker()
    before = copy.deepcopy(tracker)
    loader, saver, store = _make_hooks(tracker)

    res = update_application(
        company="Does Not Exist Inc",
        role_title="Ghost Role",
        new_company="Whatever",
        tracker_loader=loader,
        tracker_saver=saver,
    )

    assert res["ok"] is False
    assert res["error"] == "application_not_found"
    assert store["save_count"] == 0
    assert tracker == before


def test_rename_missing_role_title_at_known_company_returns_not_found():
    """A known company but a role_title that does not match any record."""
    tracker = _seed_tracker()
    before = copy.deepcopy(tracker)
    loader, saver, store = _make_hooks(tracker)

    res = update_application(
        company=SEED_COMPANY,
        role_title="No Such Role Here",
        new_role_title="Product Lead",
        tracker_loader=loader,
        tracker_saver=saver,
    )

    assert res["ok"] is False
    assert res["error"] == "application_not_found"
    assert store["save_count"] == 0
    assert tracker == before


# ---------------------------------------------------------------------------
# Mixed call: new_stage + rename applies both, persists once
# ---------------------------------------------------------------------------
def test_mixed_stage_and_rename_applies_both_and_saves_once():
    tracker = _seed_tracker(stage="new")
    loader, saver, store = _make_hooks(tracker)

    res = update_application(
        application_id=SEED_ID,
        new_stage="applied",
        new_company="Scientech Consulting",
        new_role_title="Product Lead",
        tracker_loader=loader,
        tracker_saver=saver,
    )

    assert res["ok"] is True
    assert set(res["updated_fields"]) == {"stage", "company", "role_title"}
    assert res["stage"] == "applied"
    assert res["previous_stage"] == "new"
    assert res["company"] == "Scientech Consulting"
    assert res["role_title"] == "Product Lead"
    # Persisted exactly once for the combined change.
    assert store["save_count"] == 1

    rec = _reload(store)
    assert rec["stage"] == "applied"
    assert rec["history"][-1]["stage"] == "applied"
    assert rec["company"] == "Scientech Consulting"
    assert rec["role_title"] == "Product Lead"
