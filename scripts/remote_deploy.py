#!/usr/bin/env python3
"""Deploy only production runtime inputs over key-authenticated SSH."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REMOTE = "root@217.160.170.209"
REMOTE_DIR = "/opt/synapse-mesh/"
ROOT = Path(__file__).resolve().parent.parent


def run(command: list[str]) -> None:
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> None:
    ssh_transport = "ssh -o BatchMode=yes -o StrictHostKeyChecking=yes"
    runtime_files = [
        "./Dockerfile",
        "./docker-compose.yml",
        "./docker-entrypoint.sh",
        "./Caddyfile",
        "./deploy.sh",
        "./requirements.txt",
        "./.dockerignore",
        "./scripts/github_harvester.py",
        "./scripts/install.sh",
        "./scripts/run_disposable_verification.py",
        "./scripts/run_scheduled_verifications.py",
        "./scripts/synapse_reverify.py",
        "./scripts/run_autonomous_pipeline.py",
    ]
    runtime_directories = [
        "./app",
        "./verification",
        "./deploy/systemd",
    ]
    run([sys.executable, "-m", "pytest", "-q"])
    run(["git", "diff", "--check"])
    run(
        [
            "rsync",
            "-avz",
            "--checksum",
            "--relative",
            "--exclude=__pycache__",
            "--exclude=*.py[co]",
            "-e",
            ssh_transport,
            *runtime_files,
            f"{REMOTE}:{REMOTE_DIR}",
        ]
    )
    run(
        [
            "rsync",
            "-avz",
            "--checksum",
            "--delete",
            "--relative",
            "--exclude=__pycache__",
            "--exclude=*.py[co]",
            "-e",
            ssh_transport,
            *runtime_directories,
            f"{REMOTE}:{REMOTE_DIR}",
        ]
    )
    # Golden files, lifecycle policy, and current run artifacts are production
    # trust stores. Routine code deployment never mutates them; the daily
    # verifier owns current run pointers and separately reviewed operator
    # procedures own curated/lifecycle changes.
    run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            REMOTE,
            "cd /opt/synapse-mesh && ./deploy.sh",
        ]
    )


if __name__ == "__main__":
    main()
