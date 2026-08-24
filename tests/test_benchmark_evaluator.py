import pytest
import shutil
from benchmark.evaluator import ScientificBenchmarkEvaluator


@pytest.mark.asyncio
async def test_pilot_benchmark_cases():
    evaluator = ScientificBenchmarkEvaluator(dataset_file="benchmark/pilot_dataset.json")
    results = await evaluator.run_full_evaluation()
    
    assert len(results) == 5, "Must evaluate all 5 pilot cases"
    node_available = shutil.which("node") is not None

    for r in results:
        if r.family == "Node.js" and not node_available:
            continue
        assert r.preFailPassed is True, f"Case {r.caseId} must fail during pre-patch repro"
        assert r.postPassPassed is True, f"Case {r.caseId} must pass after valid patch"
        assert r.mutationRejected is True, f"Case {r.caseId} must reject mutated patch"
        assert r.fullyVerified is True, f"Case {r.caseId} must be fully verified"
