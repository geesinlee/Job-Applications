"""Bug condition exploration test (Property 1) for company/title rename.

Spec: .kiro/specs/rename-application-company-title (bugfix)

CRITICAL: These tests encode the EXPECTED (post-fix) behavior and are
EXPECTED TO FAIL on the current unfixed code. The failure confirms the bug:
`update_application` has no write path for the company / role_title fields,
so a rename cannot be persisted.

Bug Condition (from design.md):
    isBugCondition(X) = recordExists(recordRef)
                        AND (newCompany != NULL OR newRoleTitle != NULL)
                        AND renameIntended(X)

We drive `update_application` with an in-memory tracker via the injected
`tracker_loader` / `tracker_saver` hooks (no disk, no NAS/Postgres).

**Validates: Requirements 1.1, 1.2, 1.3, 2.1, 2.2, 2.3**
"""

import copy

import pytest
from hypothesis import given, settings, strategies as st

from src.tools.lifecycle import update_application


SEED_COMPANY = "Scitech"
SEED_TITLE = "Product Lead (referral, title TBC)"
SEED_ID = "11111111-1111-1111-1111-111111111111"


def _seed_tracker():
    """A single existing record matching the design's concrete failing case."""
    return {
        "schema_version": "1.0",
        "applications": [
            {
                "id": SEED_ID,
                "company": SEED_COMPANY,
                "role_title": SEED_TITLE,
                "stage": "new",
                "interview_round": None,
                "history": [{"stage": "new", "at": "2026-01-01T00:00:00Z"}],
                "followups": [],
                "metadata": {},
                "audit": [],
            }
        ],
    }


def _make_hooks(tracker):
    """Return (loader, saver, store) wired to an in-memory tracker.

    `store["saved"]` holds the last-persisted tracker so the test can
    "reload" the record exactly as a backing store would.
    """
    store = {"saved": None, "save_count": 0}

    def loader():
        # Hand out the live tracker (same object the function mutates).
        return tracker

    def saver(t):
        store["save_count"] += 1
        store["saved"] = copy.deepcopy(t)

    return loader, saver, store


def _reload_record(store, tracker, *, by_id=None, company=None):
    """Read the record back from the persisted snapshot (or live tracker)."""
    source = store["saved"] if store["saved"] is not None else tracker
    for app in source.get("applications", []):
        if by_id is not None and app.get("id") == by_id:
            return app
        if company is not None and app.get("company", "").lower() == company.lower():
            return app
    return None


# ---------------------------------------------------------------------------
# Case 1: Company rename by (company, role_title) lookup
# ---------------------------------------------------------------------------
def test_company_rename_by_lookup_persists():
    """Rename company via lookup keys -> stored company must become the new value.

    EXPECTED TO FAIL on unfixed code: there is no `new_company` parameter and
    no write-back, so the stored company stays 'Scitech'.
    """
    tracker = _seed_tracker()
    loader, saver, store = _make_hooks(tracker)

    res = update_application(
        company=SEED_COMPANY,
        role_title=SEED_TITLE,
        new_company="Scientech Consulting",
        tracker_loader=loader,
        tracker_saver=saver,
    )

    assert res.get("ok") is True
    assert "company" in res.get("updated_fields", [])
    assert res.get("company") == "Scientech Consulting"

    record = _reload_record(store, tracker, company="Scientech Consulting")
    assert record is not None, "record not found under new company name after reload"
    assert record["company"] == "Scientech Consulting"


# ---------------------------------------------------------------------------
# Case 2: Title rename by lookup
# ---------------------------------------------------------------------------
def test_title_rename_by_lookup_persists():
    """Rename role_title via lookup keys -> stored title must become the new value.

    EXPECTED TO FAIL on unfixed code: no `new_role_title` parameter / write-back.
    """
    tracker = _seed_tracker()
    loader, saver, store = _make_hooks(tracker)

    res = update_application(
        company=SEED_COMPANY,
        role_title=SEED_TITLE,
        new_role_title="Product Lead",
        tracker_loader=loader,
        tracker_saver=saver,
    )

    assert res.get("ok") is True
    assert "role_title" in res.get("updated_fields", [])
    assert res.get("role_title") == "Product Lead"

    record = _reload_record(store, tracker, by_id=SEED_ID)
    assert record is not None
    assert record["role_title"] == "Product Lead"


# ---------------------------------------------------------------------------
# Case 3: Rename by application_id (id branch discards rename intent)
# ---------------------------------------------------------------------------
def test_rename_by_application_id_persists_both():
    """Rename both fields by application_id -> both must be written atomically.

    EXPECTED TO FAIL on unfixed code: the `application_id` branch reassigns
    company/role_title from the stored record, discarding any rename intent.
    """
    tracker = _seed_tracker()
    loader, saver, store = _make_hooks(tracker)

    res = update_application(
        application_id=SEED_ID,
        new_company="Scientech Consulting",
        new_role_title="Product Lead",
        tracker_loader=loader,
        tracker_saver=saver,
    )

    assert res.get("ok") is True
    assert "company" in res.get("updated_fields", [])
    assert "role_title" in res.get("updated_fields", [])
    assert res.get("company") == "Scientech Consulting"
    assert res.get("role_title") == "Product Lead"

    record = _reload_record(store, tracker, by_id=SEED_ID)
    assert record is not None
    assert record["company"] == "Scientech Consulting"
    assert record["role_title"] == "Product Lead"


# ---------------------------------------------------------------------------
# Case 4 (edge, Property 3): rename on a non-existent target -> error, no mutation
# ---------------------------------------------------------------------------
def test_rename_missing_target_returns_not_found_no_mutation():
    """Rename on a non-existent (company, role_title) -> application_not_found, no save.

    This case already behaves correctly on unfixed code (lookup fails), so it
    documents the safe-no-mutation boundary for Property 3.
    """
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

    assert res.get("ok") is False
    assert res.get("error") == "application_not_found"
    assert store["save_count"] == 0, "tracker_saver must not be called on missing target"
    assert tracker == before, "no record may be mutated on a missing-target rename"


# ---------------------------------------------------------------------------
# Scoped property-based test: any requested rename on the seeded record must
# be reflected on reload. Scoped to valid non-empty new values.
# **Validates: Requirements 2.1, 2.2, 2.3**
# ---------------------------------------------------------------------------
_names = st.text(min_size=1, max_size=40).filter(lambda s: s.strip() != "")


@settings(max_examples=50, deadline=None)
@given(
    new_company=st.one_of(st.none(), _names),
    new_role_title=st.one_of(st.none(), _names),
)
def test_rename_property_persists(new_company, new_role_title):
    """For any requested rename (at least one field), the reloaded record and
    `updated_fields` must reflect the new value(s).

    EXPECTED TO FAIL on unfixed code — surfaces counterexamples proving the
    toolset has no write path for the name fields.
    """
    # Bug condition requires renameIntended: at least one new value present.
    if new_company is None and new_role_title is None:
        return

    tracker = _seed_tracker()
    loader, saver, store = _make_hooks(tracker)

    res = update_application(
        application_id=SEED_ID,
        new_company=new_company,
        new_role_title=new_role_title,
        tracker_loader=loader,
        tracker_saver=saver,
    )

    assert res.get("ok") is True
    record = _reload_record(store, tracker, by_id=SEED_ID)
    assert record is not None

    if new_company is not None:
        assert "company" in res.get("updated_fields", [])
        assert record["company"] == new_company
    if new_role_title is not None:
        assert "role_title" in res.get("updated_fields", [])
        assert record["role_title"] == new_role_title
