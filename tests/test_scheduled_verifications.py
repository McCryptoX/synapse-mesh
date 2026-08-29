import json
from pathlib import Path

import pytest

from scripts import run_scheduled_verifications as scheduler


def test_current_registry_schedules_only_the_exact_allowlisted_target():
    assert scheduler.load_scheduled_target_ids() == [
        "httpx-0.28.1-asgi-transport"
    ]


def test_scheduler_rejects_duplicate_or_non_boolean_schedule(tmp_path: Path):
    target = {"targetId": "httpx-0.28.1-asgi-transport", "scheduled": True}
    registry = {"schemaVersion": "1.0.0", "targets": [target, target]}
    path = tmp_path / "targets.json"
    path.write_text(json.dumps(registry), encoding="utf-8")
    with pytest.raises(scheduler.ScheduleFailure):
        scheduler.load_scheduled_target_ids(path)

    registry["targets"] = [{**target, "scheduled": "yes"}]
    path.write_text(json.dumps(registry), encoding="utf-8")
    with pytest.raises(scheduler.ScheduleFailure):
        scheduler.load_scheduled_target_ids(path)


def test_scheduler_invokes_only_structured_target_arguments(monkeypatch):
    calls = []

    def fake_run(command, *, cwd, check, timeout):
        calls.append((command, cwd, check, timeout))
        return type("Result", (), {"returncode": 0})()

    monkeypatch.setattr(scheduler.subprocess, "run", fake_run)
    assert scheduler.run_scheduled_targets(["httpx-0.28.1-asgi-transport"]) == 0
    command, cwd, check, timeout = calls[0]
    assert command[-3:] == [
        "--target",
        "httpx-0.28.1-asgi-transport",
        "--publish",
    ]
    assert command[1] == str(scheduler.RUNNER_PATH)
    assert cwd == scheduler.ROOT
    assert check is False
    assert timeout == scheduler.TARGET_TIMEOUT_SECONDS


def test_systemd_job_keeps_docker_client_state_in_private_tmp():
    unit = Path("deploy/systemd/synapse-verification.service").read_text(
        encoding="utf-8"
    )

    assert "PrivateTmp=true" in unit
    assert "ProtectHome=true" in unit
    assert "Environment=DOCKER_CONFIG=/tmp/docker-config" in unit
    assert "ReadWritePaths=/opt/synapse-mesh/evidence/runs" in unit
    assert "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6" in unit
