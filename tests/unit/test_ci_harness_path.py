"""JOBS-17: app_health finds the fleet harness without a Mac-only path."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_app_health_has_no_hardcoded_mac_path():
    src = (ROOT / "app_health.py").read_text()
    assert "/Users/gslee" not in src
    assert "FLEET_HARNESS_PATH" in src


def test_hypothesis_is_a_dev_dependency():
    reqs = (ROOT / "requirements-dev.txt").read_text().lower()
    assert "hypothesis" in reqs


def test_ci_checks_out_harness_and_points_tests_at_it():
    ci = (ROOT / ".github/workflows/ci.yml").read_text()
    assert "geesinlee/infra-control-plane" in ci
    assert "FLEET_HARNESS_PATH" in ci


def test_ci_reads_harness_with_deploy_key_not_pat():
    ci = (ROOT / ".github/workflows/ci.yml").read_text()
    assert "ssh-key: ${{ secrets.FLEET_INFRA_DEPLOY_KEY }}" in ci
    assert "FLEET_INFRA_PAT" not in ci
