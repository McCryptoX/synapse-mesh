import asyncio
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from benchmark.evaluator import ScientificBenchmarkEvaluator
from benchmark.schema import BenchmarkTestCase, BenchmarkReport
from app.core.sandbox import SandboxRunner

logging.basicConfig(level="INFO", format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("empirical_benchmark")


class Empirical3GroupBenchmarkRunner:
    """Orchestrator for the scientific 3-Group (A/B/C) Empirical Benchmark across test cases."""

    def __init__(self, dataset_path: str = "benchmark/hardened_cases.json"):
        self.evaluator = ScientificBenchmarkEvaluator(dataset_path)
        self.cases: List[BenchmarkTestCase] = self.evaluator.load_cases()

    async def execute_case_diagnostic(self, case: BenchmarkTestCase) -> Dict[str, Any]:
        """Runs the 4-stage evaluation on the case and returns structured telemetry."""
        diag = await self.evaluator.evaluate_case(case)
        return diag.to_dict()

    async def run_full_shakedown(self) -> Dict[str, Any]:
        logger.info(f"Starting Engineering Shakedown on {len(self.cases)} hardened cases...")
        results = []
        for case in self.cases:
            res = await self.execute_case_diagnostic(case)
            results.append(res)
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "totalCases": len(self.cases),
            "results": results
        }


if __name__ == "__main__":
    runner = Empirical3GroupBenchmarkRunner()
    report = asyncio.run(runner.run_full_shakedown())
    print("\n" + "="*80)
    print("ENGINEERING SHAKEDOWN REPORT (GENUINE WORKSPACE EVALUATION)")
    print("="*80)
    for r in report["results"]:
        status = "✓ PASS" if r["fullyVerified"] else "✗ FAIL"
        mut_str = f"{r['mutationsRejected']}/{r['mutationsTotal']} Killed" if r['mutationsTotal'] else "N/A"
        print(f"[{status}] {r['caseId']:<32} | Pre-Fail: {r['preFailPassed']} | Sig-Match: {r['signatureMatched']} | Post-Pass: {r['postPassPassed']} | Mutations: {mut_str:<12} | {r['durationMs']}ms")
    print("="*80)
