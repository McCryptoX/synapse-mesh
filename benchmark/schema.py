from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class BenchmarkTestCase(BaseModel):
    id: str = Field(..., description="Unique case identifier e.g. P2_HTTPX_0_28_STARLETTE")
    family: str = Field(..., description="Python | Node.js | Rust | Docker | SQL")
    name: str = Field(..., description="Human readable title of breaking change")
    yearIntroduced: str = Field(..., description="Year the breaking change landed (2024-2026)")
    breakingPackage: str = Field(..., description="Affected package version constraint e.g. httpx>=0.28.0")
    errorSignature: str = Field(..., description="Representative error message")
    errorSignatureRegex: Optional[str] = Field(None, description="Regex pattern matching target error in stderr")
    targetPatchFile: str = Field(default="module.py", description="Relative filename where patch is applied")
    entrypoint: str = Field(default="test_runner.py", description="Test suite entrypoint file")
    workspaceFiles: Dict[str, str] = Field(default_factory=dict, description="Initial workspace fixtures/configs")
    reproductionScript: str = Field(..., description="Script reliably reproducing target breaking error")
    groundTruthTestSuite: str = Field(..., description="Hermetic test validating that the patch cleanly fixes the bug")
    validPatch: str = Field(..., description="The canonical, forward-compatible fix")
    mutationPatches: List[str] = Field(default_factory=list, description="Top web/hallucinated bad fixes that MUST fail")
    officialSource: str = Field(..., description="Official changelog or migration guide URL")
    antiDowngradeEnforced: bool = Field(default=True, description="Strictly rejects package downgrades")
    executionMode: str = Field(default="compiler_runtime", description="compiler_runtime | static_semantic_oracle | toolchain_syntax_oracle")
    benchmarkTier: str = Field(default="primary_runtime_core", description="primary_runtime_core | supplemental_oracle")


class DiagnosticEvaluationResult(BaseModel):
    caseId: str
    family: str
    preFailPassed: bool
    signatureMatched: bool
    postPassPassed: bool
    mutationsTotal: int
    mutationsRejected: int
    fullyVerified: bool
    durationMs: float
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


class AgentExecutionTelemetry(BaseModel):
    group: str = Field(..., description="Group_A_Baseline | Group_B_WebSearch | Group_C_SynapseMesh")
    caseId: str
    passed: bool
    firstTry: bool
    tokensUsed: int
    durationSec: float
    toolCallsCount: int
    appliedPatchDiff: Optional[str] = None
    errorMessage: Optional[str] = None


class BenchmarkReport(BaseModel):
    timestamp: datetime = Field(default_factory=utc_now)
    totalCases: int
    modelEvaluated: str = Field(default="Independent Benchmark Harness")
    summaryGroupA: Dict[str, Any]
    summaryGroupB: Dict[str, Any]
    summaryGroupC: Dict[str, Any]
    telemetry: List[AgentExecutionTelemetry] = Field(default_factory=list)
