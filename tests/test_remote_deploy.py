from scripts import remote_deploy


def test_routine_deploy_preserves_production_trust_stores(monkeypatch):
    calls: list[list[str]] = []

    def record(command, *, cwd, check):
        assert cwd == remote_deploy.ROOT
        assert check is True
        calls.append(command)

    monkeypatch.setattr(remote_deploy.subprocess, "run", record)

    remote_deploy.main()

    assert len(calls) == 5
    tests, diff_check, file_sync, directory_sync, remote_deploy_call = calls
    assert tests[:3] == [remote_deploy.sys.executable, "-m", "pytest"]
    assert tests[-1] == "-q"
    assert diff_check == ["git", "diff", "--check"]
    general_sync = file_sync + directory_sync
    assert file_sync[0] == directory_sync[0] == "rsync"
    assert "--checksum" in file_sync
    assert "--checksum" in directory_sync
    assert "--delete" not in file_sync
    assert "--delete" in directory_sync
    assert "./app" in directory_sync
    assert "./scripts/install.sh" in file_sync
    assert "./bundles/golden" not in general_sync
    assert "./evidence/runs" not in general_sync
    assert "./evidence/lifecycle" not in general_sync
    assert remote_deploy_call[-1] == "cd /opt/synapse-mesh && ./deploy.sh"


def test_lifecycle_policy_is_present_in_image_and_read_only_at_runtime():
    dockerfile = (remote_deploy.ROOT / "Dockerfile").read_text(encoding="utf-8")
    compose = (remote_deploy.ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    deploy_script = (remote_deploy.ROOT / "deploy.sh").read_text(encoding="utf-8")

    assert "COPY evidence/lifecycle ./evidence/lifecycle" in dockerfile
    assert "./evidence/lifecycle:/app/evidence/lifecycle:ro" in compose
    assert "install -d -m 0755 evidence/runs evidence/lifecycle" in deploy_script
    assert "[ -L evidence/runs ] || [ -L evidence/lifecycle ]" in deploy_script
    assert "SYNAPSE_ALLOW_EMPTY_DATABASE" in deploy_script
    assert "PRAGMA quick_check" in deploy_script
    assert "https://synapsemesh.dev" in deploy_script


def test_public_installer_is_packaged_in_production_image():
    dockerfile = (remote_deploy.ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "scripts/install.sh ./scripts/" in dockerfile
