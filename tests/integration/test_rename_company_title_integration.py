"""Integration tests for the company/title rename fix (Task 4).

Spec: .kiro/specs/rename-application-company-title (bugfix)

These tests exercise the real persistence fan-out rather than injected hooks:

- File backend: a rename persists to `tracker.json` on disk and `_nas_sync`
  is invoked via `_save_tracker`.
- Postgres backend: with `STORAGE_BACKEND='postgres'` and `_save_postgres_state`
  mocked, a rename writes the updated state through the Postgres path.
- End-to-end through the MCP wrapper `update_application` in
  job_applications_mcp_server.py: `new_company` / `new_role_title` thread
  through to the implementation and the result payload reflects the rename.

All external systems (NAS, Postgres) are mocked — no real network or DB.
The autouse conftest fixture redirects TRACKER_PATH/PROFILE_PATH/etc. into a
per-test tmp_path and forces STORAGE_BACKEND='file', so disk writes stay inside
the sandbox.

**Validates: Requirements 2.1, 2.2, 2.3, 2.4**
"""

import copy
import json

import pytest


SEED_ID = "11111111-1111-1111-1111-111111111111"
SEED_COMPANY = "Scitech"
SEED_TITLE = "Product Lead (referral, title TBC)"


def _seed_tracker():
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


@pytest.fixture
def server_module():
    import job_applications_mcp_server as server
    return server


# ===========================================================================
# File backend: rename persists to tracker.json and _nas_sync is invoked
# ===========================================================================
def test_file_backend_rename_persists_and_triggers_nas_sync(server_module, monkeypatch):
    server = server_module
    # Sanity: conftest forces file backend into the sandbox.
    assert server.STORAGE_BACKEND == "file"

    # Seed tracker.json on the sandboxed disk path.
    server.TRACKER_PATH.write_text(
        json.dumps(_seed_tracker(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # Spy on the NAS sync so we assert it fired without touching real NAS.
    calls = {"nas": 0}

    def fake_nas_sync():
        calls["nas"] += 1

    monkeypatch.setattr(server, "_nas_sync", fake_nas_sync)

    from src.tools.lifecycle import update_application

    res = update_application(
        application_id=SEED_ID,
        new_company="Scientech Consulting",
        new_role_title="Product Lead",
    )

    assert res["ok"] is True
    assert set(res["updated_fields"]) == {"company", "role_title"}
    assert res["company"] == "Scientech Consulting"
    assert res["role_title"] == "Product Lead"

    # _nas_sync fired through _save_tracker exactly once.
    assert calls["nas"] == 1

    # The change is durable on disk.
    on_disk = json.loads(server.TRACKER_PATH.read_text(encoding="utf-8"))
    rec = next(a for a in on_disk["applications"] if a["id"] == SEED_ID)
    assert rec["company"] == "Scientech Consulting"
    assert rec["role_title"] == "Product Lead"


def test_file_backend_missing_target_does_not_write_or_sync(server_module, monkeypatch):
    server = server_module
    server.TRACKER_PATH.write_text(
        json.dumps(_seed_tracker(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    before = server.TRACKER_PATH.read_text(encoding="utf-8")

    calls = {"nas": 0}
    monkeypatch.setattr(server, "_nas_sync", lambda: calls.__setitem__("nas", calls["nas"] + 1))

    from src.tools.lifecycle import update_application

    res = update_application(
        company="Nonexistent Co",
        role_title="Ghost",
        new_company="Whatever",
    )

    assert res["ok"] is False
    assert res["error"] == "application_not_found"
    # No persistence, no NAS sync on the error path.
    assert calls["nas"] == 0
    assert server.TRACKER_PATH.read_text(encoding="utf-8") == before


# ===========================================================================
# Postgres backend (mocked _save_postgres_state): rename writes updated state
# ===========================================================================
def test_postgres_backend_rename_writes_updated_state(server_module, monkeypatch):
    server = server_module

    # In-memory canonical state standing in for the job_applications DB.
    db_state = {"tracker": copy.deepcopy(_seed_tracker())}
    saved = {"count": 0}

    def fake_load_postgres_state(state_id, default):
        return copy.deepcopy(db_state.get(state_id, default))

    def fake_save_postgres_state(state_id, payload):
        saved["count"] += 1
        db_state[state_id] = copy.deepcopy(payload)

    # Flip the backend and mock both Postgres I/O ends — no real DB.
    monkeypatch.setattr(server, "STORAGE_BACKEND", "postgres")
    monkeypatch.setattr(server, "_load_postgres_state", fake_load_postgres_state)
    monkeypatch.setattr(server, "_save_postgres_state", fake_save_postgres_state)

    from src.tools.lifecycle import update_application

    res = update_application(
        application_id=SEED_ID,
        new_company="Scientech Consulting",
        new_role_title="Product Lead",
    )

    assert res["ok"] is True
    assert set(res["updated_fields"]) == {"company", "role_title"}
    assert res["backend"] == "PostgreSQL"

    # The rename was written to the Postgres canonical state.
    assert saved["count"] >= 1
    rec = next(a for a in db_state["tracker"]["applications"] if a["id"] == SEED_ID)
    assert rec["company"] == "Scientech Consulting"
    assert rec["role_title"] == "Product Lead"


def test_postgres_backend_missing_target_does_not_save(server_module, monkeypatch):
    server = server_module
    db_state = {"tracker": copy.deepcopy(_seed_tracker())}
    before = copy.deepcopy(db_state)
    saved = {"count": 0}

    monkeypatch.setattr(server, "STORAGE_BACKEND", "postgres")
    monkeypatch.setattr(
        server, "_load_postgres_state",
        lambda state_id, default: copy.deepcopy(db_state.get(state_id, default)),
    )

    def fake_save_postgres_state(state_id, payload):
        saved["count"] += 1
        db_state[state_id] = copy.deepcopy(payload)

    monkeypatch.setattr(server, "_save_postgres_state", fake_save_postgres_state)

    from src.tools.lifecycle import update_application

    res = update_application(
        company="Nonexistent Co",
        role_title="Ghost",
        new_role_title="Product Lead",
    )

    assert res["ok"] is False
    assert res["error"] == "application_not_found"
    assert saved["count"] == 0
    assert db_state == before


# ===========================================================================
# End-to-end through the MCP wrapper update_application
# ===========================================================================
def test_mcp_wrapper_threads_rename_params_and_reflects_payload(server_module):
    server = server_module
    server.TRACKER_PATH.write_text(
        json.dumps(_seed_tracker(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # Call the MCP tool wrapper exactly as a client would (positional-free).
    res = server.update_application(
        application_id=SEED_ID,
        new_company="Scientech Consulting",
        new_role_title="Product Lead",
    )

    assert res["ok"] is True
    assert set(res["updated_fields"]) == {"company", "role_title"}
    assert res["company"] == "Scientech Consulting"
    assert res["role_title"] == "Product Lead"

    on_disk = json.loads(server.TRACKER_PATH.read_text(encoding="utf-8"))
    rec = next(a for a in on_disk["applications"] if a["id"] == SEED_ID)
    assert rec["company"] == "Scientech Consulting"
    assert rec["role_title"] == "Product Lead"


def test_mcp_wrapper_lookup_rename_by_company_role(server_module):
    server = server_module
    server.TRACKER_PATH.write_text(
        json.dumps(_seed_tracker(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    res = server.update_application(
        company=SEED_COMPANY,
        role_title=SEED_TITLE,
        new_company="Scientech Consulting",
    )

    assert res["ok"] is True
    assert res["updated_fields"] == ["company"]
    assert res["company"] == "Scientech Consulting"
    # Title left intact when only company is renamed.
    assert res["role_title"] == SEED_TITLE
