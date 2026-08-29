import asyncio
import importlib.util
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

from benchmark.schema import BenchmarkTestCase, DiagnosticEvaluationResult
from app.core.sandbox import SandboxRunner

logger = logging.getLogger("benchmark.evaluator")


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
        
        # Determine runtime
        if case.family == "Rust":
            runtime = "rust"
        elif case.family in ("Node.js", "JavaScript", "TypeScript"):
            runtime = "nodejs"
        else:
            runtime = "python"
        
        # 1. Pre-Fail & Signature Regex Validation (Real Reproduction Script in Workspace)
        repro_files = dict(case.workspaceFiles)
        repro_ext = Path(case.entrypoint).suffix or (".mjs" if runtime == "nodejs" else ".py")
        repro_entrypoint = f"repro{repro_ext}"
        repro_files[repro_entrypoint] = case.reproductionScript

        # Note: Repro harness runner uses python to drive compiler/runtimes if entrypoint is .py
        repro_runtime = "python" if repro_entrypoint.endswith(".py") else runtime
        repro_res = await SandboxRunner.run_workspace_test(
            files=repro_files,
            entrypoint=repro_entrypoint,
            runtime=repro_runtime,
            allow_toolchain_subprocesses=runtime in {"nodejs", "rust"},
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
            sig_matched = bool(re.search(case.errorSignatureRegex, combined_output, re.IGNORECASE))
        else:
            sig_matched = (case.errorSignature.lower() in combined_output.lower())

        # 2. Post-Pass Validation (Real Patch File + Ground Truth Test Suite in Workspace)
        valid_files = dict(case.workspaceFiles)
        valid_files[case.targetPatchFile] = case.validPatch
        valid_files[case.entrypoint] = case.groundTruthTestSuite

        post_runtime = "python" if case.entrypoint.endswith(".py") else runtime
        post_res = await SandboxRunner.run_workspace_test(
            files=valid_files,
            entrypoint=case.entrypoint,
            runtime=post_runtime,
            allow_toolchain_subprocesses=runtime in {"nodejs", "rust"},
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
                runtime=post_runtime,
                allow_toolchain_subprocesses=runtime in {"nodejs", "rust"},
            )
            if mut_res["exitCode"] != 0 or mut_res["passed"] is False:
                mutations_rejected += 1

        # Strict Red-Team Gate: Must have at least 3 mutations and ALL must be killed
        all_mutations_killed = (len(mutations) >= 3 and mutations_rejected == len(mutations))
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
        return results


if __name__ == "__main__":
    evaluator = ScientificBenchmarkEvaluator()
    results = asyncio.run(evaluator.run_full_evaluation())
    print("\n" + "="*80)
    print("SCIENTIFIC 4-STAGE BENCHMARK ORACLE RESULTS")
    print("="*80)
    for r in results:
        status = "✓ PASS" if r.fullyVerified else "✗ FAIL"
        mut_str = f"{r.mutationsRejected}/{r.mutationsTotal} Killed"
        print(f"[{status}] {r.caseId:<32} | Pre-Fail: {r.preFailPassed} | Sig-Match: {r.signatureMatched} | Post-Pass: {r.postPassPassed} | Mutations: {mut_str:<12} | {r.durationMs}ms")
    print("="*80)
