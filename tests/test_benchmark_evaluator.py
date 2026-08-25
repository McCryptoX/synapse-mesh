import hashlib
import pytest
import shutil
from pathlib import Path
from benchmark.evaluator import ScientificBenchmarkEvaluator

EXPECTED_MANIFEST_SHA256 = "a076cff87dcf201aaeb6bf7931f1d05ea77f0da64a4a6a95a166067071ef018a"
evaluator = ScientificBenchmarkEvaluator(dataset_file="benchmark/hardened_cases.json")
ALL_CASES = evaluator.load_cases()
CASE_MAP = {c.id: c for c in ALL_CASES}
CASE_IDS = list(CASE_MAP.keys())


def test_manifest_sha256_freeze():
    """Go-Gate 1: Verifies that the Suite v2 dataset matches the pre-registered immutable SHA-256 hash."""
    manifest_bytes = Path("benchmark/hardened_cases.json").read_bytes()
    current_sha = hashlib.sha256(manifest_bytes).hexdigest()
    assert current_sha == EXPECTED_MANIFEST_SHA256, (
        f"Manifest SHA-256 changed! Expected {EXPECTED_MANIFEST_SHA256}, got {current_sha}. "
        "Benchmark dataset is frozen and must not be modified without formal re-registration."
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("case_id", CASE_IDS)
async def test_individual_benchmark_case(case_id: str):
    case = CASE_MAP[case_id]
    
    # Check runtime dependencies per individual case
    if case.family in ("Node.js", "JavaScript", "TypeScript") and not shutil.which("node"):
        pytest.skip(f"Node.js runtime executable not found for case {case_id}")
        
    if case.family == "Rust" and not (shutil.which("rustc") or shutil.which("cargo")):
        pytest.skip(f"Rust compiler toolchain not found for case {case_id}")

    res = await evaluator.evaluate_case(case)
    
    assert res.preFailPassed is True, f"Case {case.id} must fail during pre-patch repro: {res.notes}"
    assert res.signatureMatched is True, f"Case {case.id} must match error signature regex: {res.notes}"
    assert res.postPassPassed is True, f"Case {case.id} must pass after valid patch: {res.notes}"
    assert res.mutationsRejected == res.mutationsTotal, f"Case {case.id} must reject all web-fehlfix mutations: {res.notes}"
    assert res.mutationsTotal >= 3, f"Case {case.id} must define at least 3 mutations"
    assert res.fullyVerified is True, f"Case {case.id} must be fully verified: {res.notes}"
