import os
import tempfile
from pathlib import Path

import pytest


_SESSION_TEMP_DIR = None
_ORIGINAL_JOB_APP_ENV = {}


def pytest_configure(config):
    """Isolate module-scope server imports that happen during collection."""
    global _SESSION_TEMP_DIR
    config.addinivalue_line("markers", "integration: tests requiring integration resources")
    config.addinivalue_line("markers", "tracker: tracker persistence tests")
    _SESSION_TEMP_DIR = tempfile.TemporaryDirectory(prefix="job-applications-pytest-")
    base_dir = Path(_SESSION_TEMP_DIR.name)
    test_environment = {
        "JOB_APP_STORAGE_BACKEND": "file",
        "JOB_APP_BASE_DIR": str(base_dir),
        "JOB_APP_ARTEFACTS_DIR": str(base_dir),
        "JOB_APP_TRACKER_PATH": str(base_dir / "tracker.json"),
        "JOB_APP_PROFILE_PATH": str(base_dir / "profile.json"),
        "JOB_APP_CV_RECORDS_PATH": str(base_dir / "cv_records.json"),
        "LLM_PROVIDER": "mock",
    }
    for name, value in test_environment.items():
        _ORIGINAL_JOB_APP_ENV[name] = os.environ.get(name)
        os.environ[name] = value


def pytest_unconfigure(config):
    for name, original_value in _ORIGINAL_JOB_APP_ENV.items():
        if original_value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = original_value
    if _SESSION_TEMP_DIR is not None:
        _SESSION_TEMP_DIR.cleanup()


@pytest.fixture(autouse=True)
def _isolate_job_app_paths(tmp_path, monkeypatch):
    """Force every module-level path constant to point inside tmp_path.

    job_applications_mcp_server.py computes BASE_DIR, ARTEFACTS_DIR,
    TRACKER_PATH, PROFILE_PATH, and CV_RECORDS_PATH once at import time from
    env vars.
    Patching BASE_DIR alone does not retarget the others — each is an
    already-bound Path object, so tests that only patched BASE_DIR/
    ARTEFACTS_DIR were silently reading/writing the real project's
    tracker.json and profile.json. Patch all five here so no test can
    leak into real project state.

    If job_applications_mcp_server cannot be imported (e.g. missing
    optional deps like beautifulsoup4), skip the fixture silently so
    that unrelated test modules still work.
    """
    # Set the environment before the first import. The module runs startup
    # validation at import time, so patching its constants afterwards is too
    # late when a developer's .env points at an unavailable production mount.
    monkeypatch.setenv("JOB_APP_STORAGE_BACKEND", "file")
    monkeypatch.setenv("JOB_APP_BASE_DIR", str(tmp_path))
    monkeypatch.setenv("JOB_APP_ARTEFACTS_DIR", str(tmp_path))
    monkeypatch.setenv("JOB_APP_TRACKER_PATH", str(tmp_path / "tracker.json"))
    monkeypatch.setenv("JOB_APP_PROFILE_PATH", str(tmp_path / "profile.json"))
    monkeypatch.setenv("JOB_APP_CV_RECORDS_PATH", str(tmp_path / "cv_records.json"))
    monkeypatch.setenv("LLM_PROVIDER", "mock")

    try:
        import job_applications_mcp_server as m
    except ImportError:
        return
    monkeypatch.setattr(m, "BASE_DIR", tmp_path)
    monkeypatch.setattr(m, "ARTEFACTS_DIR", tmp_path)
    monkeypatch.setattr(m, "TRACKER_PATH", tmp_path / "tracker.json")
    monkeypatch.setattr(m, "PROFILE_PATH", tmp_path / "profile.json")
    monkeypatch.setattr(m, "CV_RECORDS_PATH", tmp_path / "cv_records.json")
    monkeypatch.setattr(m, "BASE_CV_PATH", tmp_path / "__unset_base_cv__.md")
    monkeypatch.setattr(m, "STORAGE_BACKEND", "file")
    monkeypatch.setattr(m, "_cv_service_instance", None)
