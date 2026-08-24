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
    """Rigorous 4-stage epistemic verification runner executing real multi-file workspaces in isolated directories."""

    def __init__(self, dataset_file: str = "benchmark/hardened_cases.json"):
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
        runtime = "nodejs" if case.family in ("Node.js", "JavaScript", "TypeScript") else "python"
        
        # 1. Pre-Fail & Signature Regex Validation (Real Reproduction Script in Workspace)
        repro_files = dict(case.workspaceFiles)
        repro_ext = Path(case.entrypoint).suffix or (".mjs" if runtime == "nodejs" else ".py")
        repro_entrypoint = f"repro{repro_ext}"
        repro_files[repro_entrypoint] = case.reproductionScript

        repro_res = await SandboxRunner.run_workspace_test(
            files=repro_files,
            entrypoint=repro_entrypoint,
            runtime=runtime
        )
        
        if repro_res.get("unverified"):
            return DiagnosticEvaluationResult(
                caseId=case.id,
                family=case.family,
                preFailPassed=False,
                signatureMatched=False,
                postPassPassed=False,
                mutationsTotal=len(case.mutationPatches),
                mutationsRejected=0,
                fullyVerified=False,
                durationMs=0.0,
                notes=f"UNVERIFIED: {repro_res.get('stderr')}"
            )

        pre_fail_ok = (repro_res["exitCode"] != 0)
        combined_output = f"{repro_res.get('stderr', '')}\n{repro_res.get('stdout', '')}"
        
        if case.errorSignatureRegex:
            sig_matched = bool(re.search(case.errorSignatureRegex, combined_output))
        else:
            sig_matched = (case.errorSignature.lower() in combined_output.lower())

        # 2. Post-Pass Validation (Real Patch File + Ground Truth Test Suite in Workspace)
        valid_files = dict(case.workspaceFiles)
        valid_files[case.targetPatchFile] = case.validPatch
        valid_files[case.entrypoint] = case.groundTruthTestSuite

        post_res = await SandboxRunner.run_workspace_test(
            files=valid_files,
            entrypoint=case.entrypoint,
            runtime=runtime
        )
        
        post_pass_ok = (post_res["exitCode"] == 0 and post_res["passed"] is True)

        # 3. Multi-Mutation Sanity Check (Each Web-Fehlfix written to target file MUST fail test suite)
        mutations = case.mutationPatches or []
        mutations_rejected = 0
        
        for mut in mutations:
            mut_files = dict(case.workspaceFiles)
            mut_files[case.targetPatchFile] = mut
            mut_files[case.entrypoint] = case.groundTruthTestSuite
            
            mut_res = await SandboxRunner.run_workspace_test(
                files=mut_files,
                entrypoint=case.entrypoint,
                runtime=runtime
            )
            if mut_res["exitCode"] != 0 or mut_res["passed"] is False:
                mutations_rejected += 1

        all_mutations_killed = (len(mutations) == 0 or mutations_rejected == len(mutations))
        duration = round((time.perf_counter() - start_time) * 1000, 2)
        fully_verified = (pre_fail_ok and sig_matched and post_pass_ok and all_mutations_killed)

        notes = []
        if not pre_fail_ok:
            notes.append("Repro did not fail")
        if not sig_matched:
            notes.append(f"Signature mismatch (stderr: {repro_res.get('stderr', '')[:80]})")
        if not post_pass_ok:
            notes.append(f"Valid patch failed ({post_res.get('stderr', '')[:80]})")
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
    evaluator = ScientificBenchmarkEvaluator("benchmark/hardened_cases.json")
    results = asyncio.run(evaluator.run_full_evaluation())
    print("\n" + "="*95)
    print("SCIENTIFIC BENCHMARK VERIFICATION REPORT (GENUINE FILE-WORKSPACE EVALUATOR)")
    print("="*95)
    for r in results:
        mut_str = f"{r.mutationsRejected}/{r.mutationsTotal} Killed" if r.mutationsTotal else "N/A"
        print(f"[{'✓' if r.fullyVerified else '✗'}] {r.caseId:<32} | Pre-Fail: {r.preFailPassed} | Sig-Match: {r.signatureMatched} | Post-Pass: {r.postPassPassed} | Mutations: {mut_str:<12} | {r.durationMs}ms")
    print("="*95)
