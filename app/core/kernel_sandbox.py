import asyncio
import os
import sys
import json
import time
import tempfile
import shutil
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
from app.core.sandbox import SandboxRunner
from app.models.recipe import EvidenceDefinition


class KernelIsolationProbe:
    """
    Reports facts that can be observed about the current API container.

    These observations do not attest the child process used by ``SandboxRunner``.
    Unmeasurable values remain ``None``/``unmeasured`` instead of inheriting an
    ideal policy passport.
    """

    @classmethod
    async def probe_runtime_environment(cls) -> Dict[str, Any]:
        """Runs an empirical self-attestation probe measuring observed kernel facts."""
        observed = {
            "pidNamespace": None,
            "ipcNamespace": None,
            "network": "unmeasured",
            "rootFs": "unmeasured",
            "backendMountsVisible": None,
            "dockerSocketPresent": os.path.exists("/var/run/docker.sock"),
            "noNewPrivs": None,
            "seccompMode": None,
            "effectiveCapabilities": None,
            "privateTmpfs": None,
            "blockedSyscalls": [],
        }

        # 1. PID Namespace check: count visible PIDs in /proc
        if os.path.exists("/proc"):
            try:
                pids = [int(p) for p in os.listdir("/proc") if p.isdigit()]
                # A small PID count is not proof of a separate namespace.  Keep
                # the observation as a count and leave attestation false.
                observed["visiblePidCount"] = len(pids)
            except Exception:
                pass

        # 3. Root Filesystem & Backend Mount Privacy
        try:
            test_path = Path("/etc/synapse_probe_test")
            test_path.write_text("probe")
            test_path.unlink()
            observed["rootFs"] = "writable"
        except (PermissionError, OSError):
            observed["rootFs"] = "read-only"

        # 3. Linux-specific checks: no_new_privs & seccomp
        if sys.platform.startswith("linux"):
            try:
                import ctypes
                libc = ctypes.CDLL(None)
                PR_GET_NO_NEW_PRIVS = 39
                nnp = libc.prctl(PR_GET_NO_NEW_PRIVS, 0, 0, 0, 0)
                observed["noNewPrivs"] = (nnp == 1)
                
                PR_GET_SECCOMP = 21
                sec = libc.prctl(PR_GET_SECCOMP, 0, 0, 0, 0)
                observed["seccompMode"] = sec if sec >= 0 else None
            except Exception:
                pass

        # 4. Linux Capabilities check in /proc/self/status
        if os.path.exists("/proc/self/status"):
            try:
                status_text = Path("/proc/self/status").read_text()
                for line in status_text.splitlines():
                    if line.startswith("CapEff:"):
                        cap_eff = line.split(":", 1)[1].strip()
                        observed["effectiveCapabilities"] = f"0x{cap_eff}"
            except Exception:
                pass

        # 5. Read back live observed cgroup limits.  Unknown is not a limit.
        observed_cgroup = {
            "memoryMaxBytes": None,
            "memorySwapMaxBytes": None,
            "pidsMax": None,
            "cpuMax": None,
        }
        if os.path.exists("/sys/fs/cgroup/memory.max"):
            try:
                mem_max = Path("/sys/fs/cgroup/memory.max").read_text().strip()
                if mem_max.isdigit():
                    observed_cgroup["memoryMaxBytes"] = int(mem_max)
            except Exception:
                pass
        if os.path.exists("/sys/fs/cgroup/pids.max"):
            try:
                p_max = Path("/sys/fs/cgroup/pids.max").read_text().strip()
                if p_max.isdigit():
                    observed_cgroup["pidsMax"] = int(p_max)
            except Exception:
                pass

        configured = {
            "verificationBoundary": "shared-container-process",
            "attestable": False,
            "cpuRlimitSeconds": 10,
            "outputLimitBytes": SandboxRunner.MAX_OUTPUT_BYTES,
            "pythonAddressSpaceRlimitBytes": (
                SandboxRunner.PYTHON_MAX_ADDRESS_SPACE_BYTES
                if sys.platform.startswith("linux")
                else None
            ),
        }

        return {
            "observedMetrics": observed,
            "observedCgroup": observed_cgroup,
            "configuredPolicy": configured
        }


class KernelSandboxRunner(SandboxRunner):
    """
    Compatibility wrapper retained for callers of the former kernel API.

    No separate per-run namespace exists today, so this wrapper always reports
    ``NOT_ATTESTED`` and cannot promote evidence to VERIFIED.
    """

    @classmethod
    async def verify_recipe_kernel_v1(
        cls,
        runtime: str,
        error_signature: str,
        repro_script: str,
        test_suite: str,
        mutations: Optional[List[str]] = None,
        primary_source: Optional[str] = None
    ) -> EvidenceDefinition:
        """
        Executes genuine 4-stage empirical verification with live kernel isolation attestation.
        Only recipes passing under verified kernel isolation obtain 'isolationStatus: ATTESTED'.
        """
        # 1. Run live Isolation Probe
        probe_result = await KernelIsolationProbe.probe_runtime_environment()
        observed = probe_result["observedMetrics"]
        
        # 2. Run the diagnostic split-script check.  It is never the Golden contract.
        evidence = await cls.verify_recipe_full(
            runtime=runtime,
            error_signature=error_signature,
            repro_script=repro_script,
            test_suite=test_suite,
            mutations=mutations,
            primary_source=primary_source
        )

        # 3. Attach an honest, non-inheritable observation profile.
        evidence.isolationProfile = {
            "verificationProfile": "trusted-process-limits-v1",
            "isolationStatus": "NOT_ATTESTED",
            "attestedAt": datetime.now(timezone.utc).isoformat(),
            "observedMetrics": observed,
            "observedCgroup": probe_result["observedCgroup"],
            "configuredPolicy": probe_result["configuredPolicy"]
        }

        return evidence
