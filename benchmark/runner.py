import asyncio
import json
import time
from pathlib import Path
from typing import List, Dict, Any
from benchmark.schema import BenchmarkTestCase, AgentExecutionTelemetry, BenchmarkReport
from app.core.sandbox import SandboxRunner


class EmpiricalBenchmarkHarness:
    """Automated evaluation harness for the 3-Group (A/B/C) Empirical Benchmark."""

    def __init__(self, dataset_path: str = "benchmark/dataset.json"):
        self.dataset_path = Path(dataset_path)
        self.cases: List[BenchmarkTestCase] = []

    def load_dataset(self) -> List[BenchmarkTestCase]:
        if not self.dataset_path.exists():
            return []
        with open(self.dataset_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
            self.cases = [BenchmarkTestCase(**c) for c in raw]
        return self.cases

    async def evaluate_patch(self, case: BenchmarkTestCase, patch_code: str) -> Dict[str, Any]:
        """Executes patch against ground truth test suite in isolated sandbox."""
        combined_test = f"{patch_code}\n\n{case.groundTruthTestSuite}"
        result = await SandboxRunner.run_python_test(combined_test)
        return {
            "passed": result["passed"],
            "exitCode": result["exitCode"],
            "durationMs": result["durationMs"],
            "stderr": result["stderr"]
        }

    def generate_markdown_report(self, report: BenchmarkReport) -> str:
        """Generates a neutral, unbiased Markdown table comparing Group A, B, and C."""
        md = []
        md.append(f"# Empirical Benchmark Report: Scientific 3-Group Evaluation")
        md.append(f"- **Evaluated Model:** {report.modelEvaluated}")
        md.append(f"- **Total Test Cases:** {report.totalCases}")
        md.append(f"- **Date:** {report.timestamp.isoformat()}\n")
        md.append("| Metric | Group A (Baseline) | Group B (Live Web Docs) | Group C (Synapse-Mesh) |")
        md.append("|---|---|---|---|")
        
        a = report.summaryGroupA
        b = report.summaryGroupB
        c = report.summaryGroupC
        
        md.append(f"| First-Try Solve Rate | {a.get('firstTryRate', 'N/A')}% | {b.get('firstTryRate', 'N/A')}% | {c.get('firstTryRate', 'N/A')}% |")
        md.append(f"| Total Solve Rate | {a.get('totalSolveRate', 'N/A')}% | {b.get('totalSolveRate', 'N/A')}% | {c.get('totalSolveRate', 'N/A')}% |")
        md.append(f"| Avg. Tokens / Case | {a.get('avgTokens', 'N/A')} | {b.get('avgTokens', 'N/A')} | {c.get('avgTokens', 'N/A')} |")
        md.append(f"| Avg. Time / Case (s) | {a.get('avgSeconds', 'N/A')}s | {b.get('avgSeconds', 'N/A')}s | {c.get('avgSeconds', 'N/A')}s |")
        md.append(f"| Avg. Tool Calls | {a.get('avgToolCalls', 0)} | {b.get('avgToolCalls', 0)} | {c.get('avgToolCalls', 0)} |")
        md.append(f"| Hallucinated Patches | {a.get('failedAttempts', 0)} | {b.get('failedAttempts', 0)} | {c.get('failedAttempts', 0)} |")
        
        return "\n".join(md)
