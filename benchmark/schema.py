from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Any
from datetime import datetime


class BenchmarkTestCase(BaseModel):
    id: str = Field(..., description="Unique case identifier e.g. case_py312_cgi_001")
    title: str = Field(..., description="Short descriptive title of the breaking change")
    runtime: str = Field(..., description="Language / Environment (python, nodejs, rust, etc.)")
    packages: Dict[str, str] = Field(default_factory=dict, description="Locked dependency versions")
    errorSignature: str = Field(..., description="The exact error signature presented to the agent")
    problemDescription: str = Field(..., description="Context and minimal problem statement")
    reproScript: str = Field(..., description="Script proving the issue fails before fix")
    groundTruthTestSuite: str = Field(..., description="Automated unit test asserting whether fix actually works")
    difficulty: str = Field(default="medium", description="easy | medium | hard | expert")


class AgentExecutionTelemetry(BaseModel):
    group: str = Field(..., description="GroupA_Baseline | GroupB_WebDocs | GroupC_SynapseMesh")
    caseId: str
    solved: bool
    firstTrySolved: bool
    attemptsCount: int
    promptTokens: int
    completionTokens: int
    totalTokens: int
    wallClockSeconds: float
    toolCallsCount: int
    usedSynapseRecipe: bool = False
    hallucinatedPatchesCount: int = 0
    rawAgentOutput: Optional[str] = None
    errorMessage: Optional[str] = None


class BenchmarkReport(BaseModel):
    benchmarkVersion: str = "1.0.0"
    modelEvaluated: str = "Gemini-2.0-Flash"
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    totalCases: int
    summaryGroupA: Dict[str, Any]
    summaryGroupB: Dict[str, Any]
    summaryGroupC: Dict[str, Any]
    telemetry: List[AgentExecutionTelemetry] = []
