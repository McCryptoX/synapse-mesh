#!/usr/bin/env python3
"""Refresh exact allowlisted verification artifacts without an LLM."""

from __future__ import annotations

import fcntl
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
TARGETS_PATH = ROOT / "verification" / "targets.json"
RUNNER_PATH = ROOT / "scripts" / "run_disposable_verification.py"
LOCK_PATH = Path("/tmp/synapse_scheduled_verifications.lock")
TARGET_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,119}$")
MAX_TARGETS = 32
TARGET_TIMEOUT_SECONDS = 45 * 60


class ScheduleFailure(RuntimeError):
    pass


def load_scheduled_target_ids(path: Path = TARGETS_PATH) -> list[str]:
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScheduleFailure("target registry is unavailable or malformed") from exc
    targets = data.get("targets") if isinstance(data, dict) else None
    if data.get("schemaVersion") != "1.0.0" or not isinstance(targets, list):
        raise ScheduleFailure("target registry schema is unsupported")
    if len(targets) > MAX_TARGETS:
        raise ScheduleFailure("target registry exceeds the scheduling bound")

    scheduled: list[str] = []
    seen: set[str] = set()
    for target in targets:
        if not isinstance(target, dict):
            raise ScheduleFailure("target registry entry is malformed")
        target_id = target.get("targetId")
        if not isinstance(target_id, str) or TARGET_ID_RE.fullmatch(target_id) is None:
            raise ScheduleFailure("target identifier is invalid")
        if target_id in seen:
            raise ScheduleFailure("target identifier is duplicated")
        seen.add(target_id)
        scheduled_flag = target.get("scheduled", False)
        if not isinstance(scheduled_flag, bool):
            raise ScheduleFailure("scheduled flag must be boolean")
        if scheduled_flag:
            scheduled.append(target_id)
    return scheduled


def run_scheduled_targets(target_ids: list[str]) -> int:
    failures = 0
    for target_id in target_ids:
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    str(RUNNER_PATH),
                    "--target",
                    target_id,
                    "--publish",
                ],
                cwd=ROOT,
                check=False,
                timeout=TARGET_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.SubprocessError):
            failures += 1
            print(f"target={target_id} result=INFRASTRUCTURE_FAILURE", file=sys.stderr)
            continue
        if result.returncode == 0:
            print(f"target={target_id} result=PASSED")
        else:
            failures += 1
            print(f"target={target_id} result=FAILED", file=sys.stderr)
    return 1 if failures else 0


def main() -> int:
    try:
        target_ids = load_scheduled_target_ids()
        LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOCK_PATH.open("w", encoding="utf-8") as lock_file:
            try:
                fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                print("scheduled_verification=already_running")
                return 0
            return run_scheduled_targets(target_ids)
    except ScheduleFailure as exc:
        print(f"scheduled_verification_failed={exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
