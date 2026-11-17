"""JOBS-18: deploy/pi-4 units are what pi-4 runs (venv/, .env, NAS mount)."""

from pathlib import Path

PI4 = Path(__file__).resolve().parents[2] / "deploy" / "pi-4"
SERVICES = ["job-applications-mcp", "job-applications-health", "job-applications-digest",
            "job-applications-tracker", "job-applications-orchestration"]


def _unit(name: str) -> str:
    return (PI4 / f"{name}.service").read_text()


def test_services_use_repo_venv_and_dotenv():
    for name in SERVICES:
        u = _unit(name)
        assert "%h/Projects/Job-Applications/venv/bin/python" in u, name
        assert ".venv/bin" not in u, name
        assert "EnvironmentFile=%h/Projects/Job-Applications/.env" in u, name
        assert "/home/gs" not in u, name


def test_data_services_wait_for_nas_mount():
    for name in SERVICES:
        assert "RequiresMountsFor=/mnt/job-app-data" in _unit(name), name


def test_orchestration_dropins_match_pi4_names():
    for conf in ("job-applications-orchestration-pilot.conf",
                 "job-applications-orchestration-results.conf",
                 "job-applications-orchestration-broker.conf"):
        assert (PI4 / conf).exists(), conf
    pilot = (PI4 / "job-applications-orchestration-pilot.conf").read_text()
    assert "JOB_APP_ORCHESTRATION_EXECUTE=true" in pilot
    assert "JOB_APP_ORCHESTRATION_UPDATE_STAGE=false" in pilot


def test_health_checks_kafka_against_fleet_broker():
    assert "Environment=JOB_APP_KAFKA_BROKER=rv-cloud.local:9092" in _unit("job-applications-health")
