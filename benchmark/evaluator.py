import asyncio
import json
import logging
import re
import sys
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from benchmark.schema import BenchmarkTestCase
from app.core.sandbox import SandboxRunner

logging.basicConfig(level="INFO", format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("benchmark_evaluator")


class DiagnosticEvaluationResult:
    def __init__(
        self,
        caseId: str,
        family: str,
        preFailPassed: bool,
        signatureMatched: bool,
        postPassPassed: bool,
        mutationsTotal: int,
        mutationsRejected: int,
        fullyVerified: bool,
        durationMs: float,
        notes: str
    ):
        self.caseId = caseId
        self.family = family
        self.preFailPassed = preFailPassed
        self.signatureMatched = signatureMatched
        self.postPassPassed = postPassPassed
        self.mutationsTotal = mutationsTotal
        self.mutationsRejected = mutationsRejected
        self.fullyVerified = fullyVerified
        self.durationMs = durationMs
        self.notes = notes

    def to_dict(self) -> Dict[str, Any]:
        return {
            "caseId": self.caseId,
            "family": self.family,
            "preFailPassed": self.preFailPassed,
            "signatureMatched": self.signatureMatched,
            "postPassPassed": self.postPassPassed,
            "mutationsTotal": self.mutationsTotal,
            "mutationsRejected": self.mutationsRejected,
            "fullyVerified": self.fullyVerified,
            "durationMs": self.durationMs,
            "notes": self.notes
        }


class ScientificBenchmarkEvaluator:
    """Rigorous 4-stage epistemic verification runner for benchmark datasets."""

    def __init__(self, dataset_file: str = "benchmark/pilot_dataset.json"):
        self.dataset_file = Path(dataset_file)
        self.cases: List[BenchmarkTestCase] = []

    def load_cases(self) -> List[BenchmarkTestCase]:
        if not self.dataset_file.exists():
            raise FileNotFoundError(f"Dataset file {self.dataset_file} does not exist.")
        with open(self.dataset_file, "r", encoding="utf-8") as f:
            raw = json.load(f)
            self.cases = [BenchmarkTestCase(**c) for c in raw]
        return self.cases

    async def evaluate_case(self, case: BenchmarkTestCase) -> DiagnosticEvaluationResult:
        start_time = time.perf_counter()
        
        # Stage 1: Pre-Fail & Signature Regex Match Validation (Repro MUST fail with target signature)
        if case.family in ("Node.js", "JavaScript", "TypeScript"):
            repro_res = await SandboxRunner.run_nodejs_test(case.reproductionScript)
        else:
            repro_res = await SandboxRunner.run_python_test(case.reproductionScript)
            
        pre_fail_ok = (repro_res["exitCode"] != 0)
        
        # Match error signature via regex if provided, otherwise substring
        combined_output = f"{repro_res.get('stderr', '')}\n{repro_res.get('stdout', '')}"
        if case.errorSignatureRegex:
            sig_matched = bool(re.search(case.errorSignatureRegex, combined_output))
        else:
            sig_matched = (case.errorSignature.lower() in combined_output.lower())

        # Stage 2 & 3: Post-Pass Validation (Ground Truth + Valid Patch MUST pass exit 0)
        combined_valid = f"{case.validPatch}\n\n{case.groundTruthTestSuite}"
        if case.family in ("Node.js", "JavaScript", "TypeScript"):
            post_res = await SandboxRunner.run_nodejs_test(combined_valid)
        else:
            post_res = await SandboxRunner.run_python_test(combined_valid)
            
        post_pass_ok = (post_res["exitCode"] == 0 and post_res["passed"] is True)

        # Stage 4: Multi-Mutation Sanity Check (ALL Web-Fehlfix mutations MUST fail)
        mutations = case.mutationPatches or []
        mutations_rejected = 0
        
        for mut in mutations:
            combined_mutation = f"{mut}\n\n{case.groundTruthTestSuite}"
            if case.family in ("Node.js", "JavaScript", "TypeScript"):
                mut_res = await SandboxRunner.run_nodejs_test(combined_mutation)
            else:
                mut_res = await SandboxRunner.run_python_test(combined_mutation)
            
            if mut_res["exitCode"] != 0 or mut_res["passed"] is False:
                mutations_rejected += 1

        all_mutations_killed = (len(mutations) == 0 or mutations_rejected == len(mutations))
        duration = round((time.perf_counter() - start_time) * 1000, 2)
        fully_verified = (pre_fail_ok and sig_matched and post_pass_ok and all_mutations_killed)

        notes = []
        if not pre_fail_ok:
            notes.append("Repro did not fail")
        if not sig_matched:
            notes.append("Error signature regex did not match repro output")
        if not post_pass_ok:
            notes.append(f"Valid patch failed ({post_res.get('stderr', '')[:60]})")
        if not all_mutations_killed:
            notes.append(f"Web-Fehlfix survived: {mutations_rejected}/{len(mutations)} killed")

        return DiagnosticEvaluationResult(
            caseId=case.id,
            family=case.family,
            preFailPassed=pre_fail_ok,
            signatureMatched=sig_matched,
            postPassPassed=post_pass_ok,
            mutationsTotal=len(mutations),
            mutationsRejected=mutations_rejected,
            fullyVerified=fully_verified,
            durationMs=duration,
            notes="; ".join(notes) if notes else "Hermetic Verification OK"
        )

    async def run_full_evaluation(self) -> List[DiagnosticEvaluationResult]:
        cases = self.load_cases()
        results = []
        logger.info(f"Starting rigorous 4-stage evaluation on {len(cases)} cases...")
        for c in cases:
            res = await self.evaluate_case(c)
            results.append(res)
            status_icon = "✓ PASS" if res.fullyVerified else "✗ FAIL"
            logger.info(f"[{status_icon}] {res.caseId} ({res.family}) in {res.durationMs}ms - {res.notes}")
        return results


if __name__ == "__main__":
    evaluator = ScientificBenchmarkEvaluator()
    results = asyncio.run(evaluator.run_full_evaluation())
    print("\n" + "="*85)
    print("SCIENTIFIC BENCHMARK VERIFICATION REPORT (RIGOROUS 4-STAGE EVALUATOR)")
    print("="*85)
    for r in results:
        mut_str = f"{r.mutationsRejected}/{r.mutationsTotal} Killed" if r.mutationsTotal else "N/A"
        print(f"[{'✓' if r.fullyVerified else '✗'}] {r.caseId:<35} | Pre-Fail: {r.preFailPassed} | Sig-Match: {r.signatureMatched} | Post-Pass: {r.postPassPassed} | Mutations: {mut_str:<12} | {r.durationMs}ms")
    print("="*85)
