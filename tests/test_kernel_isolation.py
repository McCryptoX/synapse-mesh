import pytest
import asyncio
from app.core.kernel_sandbox import KernelIsolationProbe, KernelSandboxRunner
from app.core.sandbox import SandboxRunner


@pytest.mark.asyncio
async def test_kernel_isolation_probe():
    """
    Verifies that the live isolation probe inspects and measures observed kernel facts.
    """
    probe_data = await KernelIsolationProbe.probe_runtime_environment()
    assert isinstance(probe_data, dict)
    assert "observedMetrics" in probe_data
    assert "configuredPolicy" in probe_data
    assert "pidNamespace" in probe_data["observedMetrics"]
    assert "network" in probe_data["observedMetrics"]
    assert "rootFs" in probe_data["observedMetrics"]
    assert probe_data["configuredPolicy"]["attestable"] is False
    assert probe_data["configuredPolicy"]["verificationBoundary"] == "shared-container-process"
    assert probe_data["observedMetrics"]["network"] == "unmeasured"


@pytest.mark.asyncio
async def test_legacy_kernel_wrapper_never_attests_or_verifies():
    """
    Tests the first genuine 'synapse-kernel-v1' verified recipe: NumPy NAN removal.
    Executes live verification with kernel probe attestation.
    """
    repro = """
import numpy as np
try:
    _ = np.NAN
    print("UNEXPECTED_PASS")
    exit(0)
except AttributeError as e:
    print(f"AttributeError: {e}")
    exit(1)
"""
    test_suite = """
import numpy as np
val = np.nan
assert np.isnan(val)
print("TEST_PASSED")
exit(0)
"""
    mutant1 = """
import numpy as np
val = np.NAN  # Buggy mutant 1
"""
    mutant2 = """
import numpy as np
val = np.NaN  # Buggy mutant 2
"""
    evidence = await KernelSandboxRunner.verify_recipe_kernel_v1(
        runtime="python",
        error_signature="AttributeError: module 'numpy' has no attribute 'NAN'",
        repro_script=repro,
        test_suite=test_suite,
        mutations=[mutant1, mutant2],
        primary_source="https://numpy.org/devdocs/release/2.0.0-notes.html"
    )

    assert evidence.verificationStatus == "PROVISIONAL"
    assert evidence.sandboxExitCode == 0
    assert evidence.confidenceScore is None
    assert evidence.isolationProfile is not None
    assert evidence.isolationProfile["verificationProfile"] == "trusted-process-limits-v1"
    assert evidence.isolationProfile["isolationStatus"] == "NOT_ATTESTED"
    assert "observedMetrics" in evidence.isolationProfile
    assert "observedCgroup" in evidence.isolationProfile
    assert "pidsMax" in evidence.isolationProfile["observedCgroup"]
