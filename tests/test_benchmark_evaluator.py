import pytest
import shutil
from benchmark.evaluator import ScientificBenchmarkEvaluator


@pytest.mark.asyncio
async def test_hardened_benchmark_cases():
    evaluator = ScientificBenchmarkEvaluator(dataset_file="benchmark/hardened_cases.json")
    cases = evaluator.load_cases()
    assert len(cases) >= 3, "Must evaluate at least 3 hardened cases"
    
    node_available = shutil.which("node") is not None

    for c in cases:
        if c.family == "Node.js" and not node_available:
            continue
        res = await evaluator.evaluate_case(c)
        assert res.preFailPassed is True, f"Case {c.id} must fail during pre-patch repro"
        assert res.signatureMatched is True, f"Case {c.id} must match error signature regex"
        assert res.postPassPassed is True, f"Case {c.id} must pass after valid patch"
        assert res.mutationsRejected == res.mutationsTotal, f"Case {c.id} must reject all web-fehlfix mutations"
        assert res.fullyVerified is True, f"Case {c.id} must be fully verified"
