import pytest
import shutil
from benchmark.evaluator import ScientificBenchmarkEvaluator


@pytest.mark.asyncio
async def test_hardened_benchmark_cases():
    evaluator = ScientificBenchmarkEvaluator(dataset_file="benchmark/hardened_cases.json")
    cases = evaluator.load_cases()
    assert len(cases) == 15, f"Must evaluate all 15 hardened cases across 5 ecosystems, found {len(cases)}"
    
    node_available = shutil.which("node") is not None
    cargo_available = shutil.which("cargo") is not None or shutil.which("rustc") is not None

    for c in cases:
        if c.family in ("Node.js", "JavaScript", "TypeScript") and not node_available:
            continue
        if c.family == "Rust" and not cargo_available:
            continue
        res = await evaluator.evaluate_case(c)
        assert res.preFailPassed is True, f"Case {c.id} must fail during pre-patch repro"
        assert res.signatureMatched is True, f"Case {c.id} must match error signature regex: {res.notes}"
        assert res.postPassPassed is True, f"Case {c.id} must pass after valid patch: {res.notes}"
        assert res.mutationsRejected == res.mutationsTotal, f"Case {c.id} must reject all web-fehlfix mutations: {res.notes}"
        assert res.mutationsTotal >= 3, f"Case {c.id} must define at least 3 mutations"
        assert res.fullyVerified is True, f"Case {c.id} must be fully verified: {res.notes}"
