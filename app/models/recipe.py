from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ProblemDefinition(BaseModel):
    errorSignature: str = Field(..., description="Exact error message, exception or traceback pattern")
    runtime: str = Field(..., description="Language / Runtime (e.g. python, nodejs, rust, go)")
    packages: Dict[str, str] = Field(default_factory=dict, description="Affected package versions e.g. {'fastapi': '>=0.100.0'}")
    description: str = Field(..., description="Human and machine readable problem summary")


class SolutionDefinition(BaseModel):
    summary: str = Field(..., description="Concise explanation of the fix")
    codeDiff: Optional[str] = Field(None, description="Unified git diff representing the exact code patch")
    instructions: List[str] = Field(default_factory=list, description="Step-by-step instructions for agent or human")


class ReproductionDefinition(BaseModel):
    script: str = Field(..., description="Minimal reproducing script causing the issue")
    testSuite: str = Field(..., description="Automated test verifying that the fix resolves the issue")


class EvidenceDefinition(BaseModel):
    verificationStatus: str = Field(default="VERIFIED", description="DRAFT | SANDBOX_TESTING | VERIFIED | STALE")
    lastTestedAt: datetime = Field(default_factory=utc_now, description="Timestamp of the latest sandbox test run")
    sandboxExitCode: int = Field(default=0, description="Process exit code (0 indicates success)")
    passedTests: int = Field(default=1, description="Number of passed tests in sandbox")
    totalTests: int = Field(default=1, description="Total number of tests in suite")
    confidenceScore: float = Field(default=1.0, ge=0.0, le=1.0, description="Evidence confidence metric")
    primarySource: Optional[str] = Field(None, description="Official documentation, release notes or issue link")


class VerifiedRecipe(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_url: str = Field(default="https://synapsemesh.dev/schemas/v1/recipe.json", alias="$schema")
    context: str = Field(default="https://schema.org", alias="@context")
    type: str = Field(default="TechArticle", alias="@type")
    id: str = Field(..., description="Unique recipe identifier e.g. rec_fastapi_pydantic_v2_compat_001")
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
