import pytest


@pytest.fixture(autouse=True)
def _isolate_job_app_paths(tmp_path, monkeypatch):
    """Force every module-level path constant to point inside tmp_path.

    job_applications_mcp_server.py computes BASE_DIR, ARTEFACTS_DIR,
    TRACKER_PATH, and PROFILE_PATH once at import time from env vars.
    Patching BASE_DIR alone does not retarget the others — each is an
    already-bound Path object, so tests that only patched BASE_DIR/
    ARTEFACTS_DIR were silently reading/writing the real project's
    tracker.json and profile.json. Patch all four here so no test can
    leak into real project state.
    """
    import job_applications_mcp_server as m
    monkeypatch.setattr(m, "BASE_DIR", tmp_path)
    monkeypatch.setattr(m, "ARTEFACTS_DIR", tmp_path)
    monkeypatch.setattr(m, "TRACKER_PATH", tmp_path / "tracker.json")
    monkeypatch.setattr(m, "PROFILE_PATH", tmp_path / "profile.json")
    monkeypatch.setattr(m, "BASE_CV_PATH", tmp_path / "__unset_base_cv__.md")
