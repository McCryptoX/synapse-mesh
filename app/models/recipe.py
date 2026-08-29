from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator
from typing import Optional, Dict, Any, List
from datetime import datetime
from enum import Enum
from urllib.parse import urlsplit


VERIFIED_EVIDENCE_CONTRACT = "bundle-4-stage-v1"


def _bounded_string_map(value: Dict[str, str], *, max_items: int = 64) -> Dict[str, str]:
    if len(value) > max_items:
        raise ValueError("too many mapping entries")
    if any(
        not isinstance(key, str)
        or not isinstance(item, str)
        or len(key) > 128
        or len(item) > 512
        for key, item in value.items()
    ):
        raise ValueError("mapping keys or values exceed the accepted bounds")
    return value


def _bounded_string_list(value: List[str], *, max_items: int = 32) -> List[str]:
    if len(value) > max_items or any(not isinstance(item, str) or len(item) > 2000 for item in value):
        raise ValueError("list entries exceed the accepted bounds")
    return value


class RecipeStatus(str, Enum):
    VERIFIED = "VERIFIED"
    STALE = "STALE"
    DISPUTED = "DISPUTED"
    DRAFT = "DRAFT"


class ProblemDefinition(BaseModel):
    errorSignature: str = Field(..., min_length=3, max_length=4000, description="Exact error message, exception or traceback pattern")
    runtime: str = Field(..., min_length=2, max_length=32, description="Language / Runtime (e.g. python, nodejs, rust, go)")
    packages: Dict[str, str] = Field(default_factory=dict, description="Affected package versions e.g. {'httpx': '>=0.28.0'}")
    description: str = Field(..., min_length=3, max_length=12000, description="Human and machine readable problem summary")

    @field_validator("packages")
    @classmethod
    def validate_packages(cls, value: Dict[str, str]) -> Dict[str, str]:
        return _bounded_string_map(value)


class SolutionDefinition(BaseModel):
    summary: str = Field(..., min_length=1, max_length=12000, description="Concise explanation of the fix")
    codeDiff: Optional[str] = Field(None, max_length=100000, description="Unified git diff representing the exact code patch")
    patchDiff: Optional[str] = Field(None, max_length=100000, description="Unified diff alias")
    instructions: List[str] = Field(default_factory=list, description="Step-by-step instructions for agent or human")
    pinnedDependencies: Dict[str, str] = Field(default_factory=dict, description="Exact tested dependency pins e.g. {'httpx': '0.28.1'}")
    doNot: List[str] = Field(default_factory=list, description="Explicit known-bad fixes that fail or cause regressions")

    @field_validator("instructions", "doNot")
    @classmethod
    def validate_text_lists(cls, value: List[str]) -> List[str]:
        return _bounded_string_list(value)

    @field_validator("pinnedDependencies")
    @classmethod
    def validate_pins(cls, value: Dict[str, str]) -> Dict[str, str]:
        return _bounded_string_map(value)


class ReproductionDefinition(BaseModel):
    script: str = Field(..., max_length=100000, description="Minimal reproducing script causing the issue")
    testSuite: str = Field(..., max_length=100000, description="Automated test verifying that the fix resolves the issue")


class EvidenceDefinition(BaseModel):
    verificationStatus: str = Field(default="DRAFT", description="VERIFIED | PROVISIONAL | STALE | DISPUTED | DRAFT")
    evidenceContract: Optional[str] = Field(
        default=None,
        description=f"Explicit verification contract. VERIFIED records require {VERIFIED_EVIDENCE_CONTRACT}.",
    )
    verificationNote: Optional[str] = Field(default=None, max_length=12000, description="Human-readable reason for the current evidence tier")
    lastTestedAt: Optional[datetime] = Field(default=None, description="Timestamp of the latest completed verification run")
    sandboxExitCode: int = Field(default=-1, description="Last process exit code; -1 means no completed run")
    passedTests: int = Field(default=0, ge=0, description="Number of observed passing tests")
    totalTests: int = Field(default=0, ge=0, description="Number of observed tests")
    confidenceScore: Optional[float] = Field(
        default=None,
        description="Deprecated compatibility field; always returned as null and never used as evidence",
    )
    preExit: int = Field(default=-1, description="Observed pre-patch exit code; -1 means not run")
    postExit: int = Field(default=-1, description="Observed post-patch exit code; -1 means not run")
    mutationsKilled: str = Field(default="0/0", description="Ratio of observed rejected mutants")
    toolchainVersions: Dict[str, str] = Field(default_factory=dict, description="Exact runtime and compiler versions")
    badges: List[str] = Field(default_factory=list)
    isolationProfile: Dict[str, Any] = Field(
        default_factory=dict,
        description="Observed isolation profile, empty when no isolation attestation exists",
    )
    primarySource: Optional[str] = Field(None, max_length=2048, description="Official documentation, release notes or issue link")

    @field_validator("toolchainVersions")
    @classmethod
    def validate_toolchain(cls, value: Dict[str, str]) -> Dict[str, str]:
        return _bounded_string_map(value)

    @field_validator("badges")
    @classmethod
    def validate_badges(cls, value: List[str]) -> List[str]:
        return _bounded_string_list(value, max_items=64)

    @field_validator("confidenceScore", mode="before")
    @classmethod
    def discard_uncalibrated_confidence(cls, _value):
        """Do not expose historical heuristic values as probabilities."""
        return None

    @model_validator(mode="after")
    def verified_requires_complete_contract(self):
        """Make an incomplete VERIFIED object impossible to construct."""
        if self.verificationStatus != "VERIFIED":
            return self
        if self.evidenceContract != VERIFIED_EVIDENCE_CONTRACT:
            raise ValueError("VERIFIED evidence requires the four-stage evidence contract")
        if self.preExit in (-1, 0) or self.postExit != 0:
            raise ValueError("VERIFIED evidence requires an observed failing pre-run and passing post-run")
        try:
            killed_text, total_text = self.mutationsKilled.split("/", 1)
            killed, total = int(killed_text), int(total_text)
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValueError("VERIFIED evidence requires a valid mutation result") from exc
        if total < 2 or killed != total:
            raise ValueError("VERIFIED evidence requires at least two rejected mutants")
        return self


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
    model_config = ConfigDict(extra="forbid")
    errorSignature: str = Field(..., min_length=3, max_length=4000, description="The error message, trace or keyword to query")
    runtime: Optional[str] = Field(None, min_length=2, max_length=32, description="Optional runtime filter (python, nodejs, etc.)")
    packages: Optional[Dict[str, str]] = Field(default=None, description="Optional package version constraints")
    minConfidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Deprecated compatibility input; accepted but ignored",
    )
    limit: int = Field(default=5, ge=1, le=20)

    @field_validator("packages")
    @classmethod
    def validate_search_packages(cls, value: Optional[Dict[str, str]]) -> Optional[Dict[str, str]]:
        return _bounded_string_map(value) if value is not None else None


class RecipeSubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Optional[str] = Field(None, max_length=128, description="Optional custom ID, generated if omitted")
    problem: ProblemDefinition
    solution: SolutionDefinition
    reproduction: ReproductionDefinition
    primarySource: Optional[str] = None

    @field_validator("primarySource")
    @classmethod
    def validate_primary_source(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if len(value) > 2048:
            raise ValueError("primarySource is too long")
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("primarySource must be an absolute HTTP(S) URL")
        return value
