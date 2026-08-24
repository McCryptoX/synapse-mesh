import asyncio
import json
import logging
import sys
import time
from pathlib import Path
from typing import List, Dict, Any, Optional
from pydantic import BaseModel

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.sandbox import SandboxRunner

logging.basicConfig(level="INFO", format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("benchmark_evaluator")


class PilotBenchmarkCase(BaseModel):
    id: str
    family: str
    name: str
    yearIntroduced: str
    breakingPackage: str
    errorSignature: str
    reproductionScript: str
    groundTruthTestSuite: str
    mutationPatch: str
    validPatch: str
    officialSource: str
    antiDowngradeEnforced: bool = True


class DiagnosticEvaluationResult(BaseModel):
    caseId: str
    family: str
    preFailPassed: bool
    postPassPassed: bool
    mutationRejected: bool
    fullyVerified: bool
    durationMs: float
    notes: str


class ScientificBenchmarkEvaluator:
    """Automated 4-stage epistemic verification runner for benchmark datasets."""

    def __init__(self, dataset_file: str = "benchmark/pilot_dataset.json"):
        self.dataset_file = Path(dataset_file)
        self.cases: List[PilotBenchmarkCase] = []

    def load_cases(self) -> List[PilotBenchmarkCase]:
        if not self.dataset_file.exists():
            raise FileNotFoundError(f"Dataset file {self.dataset_file} does not exist.")
        with open(self.dataset_file, "r", encoding="utf-8") as f:
            raw = json.load(f)
            self.cases = [PilotBenchmarkCase(**c) for c in raw]
        return self.cases

    async def evaluate_case(self, case: PilotBenchmarkCase) -> DiagnosticEvaluationResult:
        start_time = time.perf_counter()
        
        # Stage 1: Pre-Fail Validation (Repro script MUST fail)
        if case.family == "Node.js":
            repro_res = await SandboxRunner.run_nodejs_test(case.reproductionScript)
        else:
            repro_res = await SandboxRunner.run_python_test(case.reproductionScript)
            
        pre_fail_ok = (repro_res["exitCode"] != 0)
        
        # Stage 2 & 3: Post-Pass Validation (Ground Truth + Valid Patch MUST pass)
        combined_valid = f"{case.validPatch}\n\n{case.groundTruthTestSuite}"
        if case.family == "Node.js":
            post_res = await SandboxRunner.run_nodejs_test(combined_valid)
        else:
            post_res = await SandboxRunner.run_python_test(combined_valid)
            
        post_pass_ok = (post_res["exitCode"] == 0 and post_res["passed"] is True)

        # Stage 4: Mutation Check (Ground Truth + Mutation Patch MUST fail)
        combined_mutation = f"{case.mutationPatch}\n\n{case.groundTruthTestSuite}"
        if case.family == "Node.js":
            mut_res = await SandboxRunner.run_nodejs_test(combined_mutation)
        else:
            mut_res = await SandboxRunner.run_python_test(combined_mutation)
            
        mutation_rejected = (mut_res["exitCode"] != 0 or mut_res["passed"] is False)

        duration = round((time.perf_counter() - start_time) * 1000, 2)
        fully_verified = (pre_fail_ok and post_pass_ok and mutation_rejected)

        notes = []
        if not pre_fail_ok:
            notes.append("Repro did not fail")
        if not post_pass_ok:
            notes.append(f"Valid patch failed ({post_res.get('stderr', '')[:40]})")
        if not mutation_rejected:
            notes.append("Mutation patch falsely passed (tautological test)")

        return DiagnosticEvaluationResult(
            caseId=case.id,
            family=case.family,
            preFailPassed=pre_fail_ok,
            postPassPassed=post_pass_ok,
            mutationRejected=mutation_rejected,
            fullyVerified=fully_verified,
            durationMs=duration,
            notes="; ".join(notes) if notes else "Hermetic Verification OK"
        )

    async def run_full_evaluation(self) -> List[DiagnosticEvaluationResult]:
        cases = self.load_cases()
        results = []
        logger.info(f"Starting 4-stage evaluation on {len(cases)} pilot cases...")
        for c in cases:
            res = await self.evaluate_case(c)
            results.append(res)
            status_icon = "✓ PASS" if res.fullyVerified else "✗ FAIL"
            logger.info(f"[{status_icon}] {res.caseId} ({res.family}) in {res.durationMs}ms - {res.notes}")
        return results


if __name__ == "__main__":
    evaluator = ScientificBenchmarkEvaluator()
    results = asyncio.run(evaluator.run_full_evaluation())
    print("\n" + "="*80)
    print("PILOT BENCHMARK VERIFICATION REPORT (4-STAGE EPISTEMIC EVALUATOR)")
    print("="*80)
    for r in results:
        print(f"[{'✓' if r.fullyVerified else '✗'}] {r.caseId:<35} | Pre-Fail: {r.preFailPassed} | Post-Pass: {r.postPassPassed} | Mutation-Check: {r.mutationRejected} | {r.durationMs}ms")
    print("="*80)
