from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from enum import Enum


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class RecipeStatus(str, Enum):
    VERIFIED = "VERIFIED"
    STALE = "STALE"
    DISPUTED = "DISPUTED"
    DRAFT = "DRAFT"


class ProblemDefinition(BaseModel):
    errorSignature: str = Field(..., description="Exact error message, exception or traceback pattern")
    runtime: str = Field(..., description="Language / Runtime (e.g. python, nodejs, rust, go)")
    packages: Dict[str, str] = Field(default_factory=dict, description="Affected package versions e.g. {'httpx': '>=0.28.0'}")
    description: str = Field(..., description="Human and machine readable problem summary")


class SolutionDefinition(BaseModel):
    summary: str = Field(..., description="Concise explanation of the fix")
    codeDiff: Optional[str] = Field(None, description="Unified git diff representing the exact code patch")
    patchDiff: Optional[str] = Field(None, description="Unified diff alias")
    instructions: List[str] = Field(default_factory=list, description="Step-by-step instructions for agent or human")
    pinnedDependencies: Dict[str, str] = Field(default_factory=dict, description="Exact tested dependency pins e.g. {'httpx': '0.28.1'}")
    doNot: List[str] = Field(default_factory=list, description="Explicit negative recipes / web-fehlfixes that fail or cause regressions")


class ReproductionDefinition(BaseModel):
    script: str = Field(..., description="Minimal reproducing script causing the issue")
    testSuite: str = Field(..., description="Automated test verifying that the fix resolves the issue")


class EvidenceDefinition(BaseModel):
    verificationStatus: str = Field(default="VERIFIED", description="VERIFIED | STALE | DISPUTED | DRAFT")
    lastTestedAt: datetime = Field(default_factory=utc_now, description="Timestamp of the latest sandbox test run")
    sandboxExitCode: int = Field(default=0, description="Process exit code (0 indicates success)")
    passedTests: int = Field(default=1, description="Number of passed tests in sandbox")
    totalTests: int = Field(default=1, description="Total number of tests in suite")
    confidenceScore: float = Field(default=1.0, ge=0.0, le=1.0, description="Evidence confidence metric")
    preExit: int = Field(default=1, description="Expected non-zero exit code during pre-patch reproduction")
    postExit: int = Field(default=0, description="Expected zero exit code during post-patch verification")
    mutationsKilled: str = Field(default="3/3", description="Ratio of rejected web-fehlfix mutants")
    toolchainVersions: Dict[str, str] = Field(default_factory=dict, description="Exact runtime and compiler versions")
    badges: List[str] = Field(default_factory=lambda: ["VERIFIED_SANDBOX", "SOURCE_BACKED", "ZERO_PII_AUDITED"])
    primarySource: Optional[str] = Field(None, description="Official documentation, release notes or issue link")


class VerifiedRecipe(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_url: str = Field(default="https://synapsemesh.dev/schemas/v1/recipe.json", alias="$schema")
    context: str = Field(default="https://schema.org", alias="@context")
    type: str = Field(default="TechArticle", alias="@type")
    id: str = Field(..., description="Unique recipe identifier e.g. rec_httpx_028_starlette_002")
    problem: ProblemDefinition
    solution: SolutionDefinition
    reproduction: ReproductionDefinition
    evidence: EvidenceDefinition


class RecipeSearchRequest(BaseModel):
    errorSignature: str = Field(..., description="The error message, trace or keyword to query")
    runtime: Optional[str] = Field(None, description="Optional runtime filter (python, nodejs, etc.)")
    packages: Optional[Dict[str, str]] = Field(default=None, description="Optional package version constraints")
    minConfidence: float = Field(default=0.5, ge=0.0, le=1.0)
    limit: int = Field(default=5, ge=1, le=20)


class RecipeSubmitRequest(BaseModel):
    id: Optional[str] = Field(None, description="Optional custom ID, generated if omitted")
    problem: ProblemDefinition
    solution: SolutionDefinition
    reproduction: ReproductionDefinition
    primarySource: Optional[str] = None
