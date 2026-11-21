"""DEVOPS-243: fleet code comes from the fleet-sdk package, not a harness checkout."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_app_code_has_no_harness_sys_path_hack():
    for name in ("app_health.py", "kafka_security.py"):
        src = (ROOT / name).read_text()
        assert "/Users/gslee" not in src
        assert "FLEET_HARNESS_PATH" not in src
        assert "sys.path" not in src


def test_hypothesis_is_a_dev_dependency():
    reqs = (ROOT / "requirements-dev.txt").read_text().lower()
    assert "hypothesis" in reqs


def test_requirements_pin_fleet_sdk_release_not_fleet_notify():
    reqs = (ROOT / "requirements.txt").read_text()
    assert "fleet-notify" not in reqs
    assert "geesinlee/fleet-sdk@v" in reqs


def test_ci_reads_fleet_sdk_with_deploy_key_not_pat():
    ci = (ROOT / ".github/workflows/ci.yml").read_text()
    assert "ssh-private-key: ${{ secrets.FLEET_SDK_DEPLOY_KEY }}" in ci
    assert "infra-control-plane" not in ci
    assert "FLEET_INFRA_PAT" not in ci
