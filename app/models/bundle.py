from typing import Dict, Any, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


class BundleScope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    package: str
    fromVersion: Optional[str] = None
    toVersion: Optional[str] = None
    affectedVersionRange: Optional[str] = None
    runtime: str = "python"
    runtimeVersion: Optional[str] = None
    platform: str = "all"


class BundleFingerprint(BaseModel):
    model_config = ConfigDict(extra="allow")
    errorSignature: str
    regex: Optional[str] = None
    regexFlags: Optional[str] = ""
    matchStream: Optional[str] = "stderr"


class BundlePatch(BaseModel):
    model_config = ConfigDict(extra="allow")
    targetFile: str
    unifiedDiff: str
    pinnedDependencies: Dict[str, str] = Field(default_factory=dict)
    doNot: List[str] = Field(default_factory=list)


class BundleMutation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    description: Optional[str] = ""
    unifiedDiff: str


class BundleVerification(BaseModel):
    model_config = ConfigDict(extra="allow")
    scriptLanguage: str = "python"
    workspaceFiles: Dict[str, str] = Field(default_factory=dict)
    reproductionScript: str
    testSuite: str
    mutations: List[BundleMutation] = Field(default_factory=list)
    expectedPreExit: int = -1
    expectedPostExit: int = -1
    timeoutMs: int = 30000


class BundleProvenance(BaseModel):
    model_config = ConfigDict(extra="allow")
    spdxLicense: str = "NOASSERTION"
    primarySources: List[str] = Field(default_factory=list)
    verifiedAt: Optional[str] = None


class RunArtifactSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    completedAt: str
    canonicalRunArtifactSha256: str
    canonicalization: Literal["synapse-json-v1"]
    bundleSha256: str
    sourceRevisionKind: str
    sourceRevision: str
    dependencyLockSha256: str
    runnerImageDigest: str
    toolchainVersions: Dict[str, str]
    preExit: int
    postExit: int
    mutationsDeclared: int
    mutationsRejected: int


class EvidenceLifecycleRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schemaVersion: Literal["1.0.0"]
    recordType: Literal["synapse-bundle-evidence-lifecycle"]
    bundleId: str
    bundleSha256: str
    canonicalRunArtifactSha256: str
    canonicalization: Literal["synapse-json-v1"]
    state: Literal["DISPUTED", "SUPERSEDED"]
    effectiveAt: str
    reasonCode: str
    reason: str
    supersededByBundleId: Optional[str] = None
    supersededByBundleSha256: Optional[str] = None
    supersededByCanonicalRunArtifactSha256: Optional[str] = None


class EvidenceLifecycle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal[
        "UNVERIFIED",
        "VERIFIED",
        "STALE",
        "BROKEN",
        "DISPUTED",
        "SUPERSEDED",
        "UNKNOWN",
    ]
    qualified: bool
    artifactAvailable: bool
    stateSource: str
    reasonCode: str
    reason: str
    freshnessMaxAgeSeconds: int
    policyVersion: str
    freshUntil: Optional[str] = None
    record: Optional[EvidenceLifecycleRecord] = None


class EvidencePublication(BaseModel):
    model_config = ConfigDict(extra="forbid")
    qualified: bool
    runArtifactAvailable: bool
    runArtifactUrl: Optional[str] = None
    runArtifactSummary: Optional[RunArtifactSummary] = None
    recordedContractShapeSatisfied: bool
    reason: str
    lifecycle: EvidenceLifecycle


class RunArtifactRunner(BaseModel):
    model_config = ConfigDict(extra="forbid")
    imageDigest: str
    runnerVersion: str
    networkMode: str
    rootFilesystemReadOnly: bool
    nonRoot: bool
    capabilitiesDropped: bool
    noNewPrivileges: bool
    productionDataMounted: bool
    credentialsPresent: bool
    workspaceExecutable: bool
    workspaceNoSuid: bool
    workspaceNoDev: bool
    outputExecutable: bool
    pidNamespacePrivate: bool
    mountNamespacePrivate: bool
    cgroupNamespacePrivate: bool
    userNamespaceMode: str
    hostDockerSocketMounted: bool
    bindMountCount: int
    privileged: bool
    seccompMode: str
    oomKilled: bool
    workspaceSizeLimitBytes: int
    memoryLimitBytes: int
    memorySwapLimitBytes: int
    pidsLimit: int
    cpuLimit: float


class RunArtifactPreStage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    exitCode: int
    signatureMatched: bool
    exceptionClassMatched: bool
    outputSha256: str


class RunArtifactPatchStage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    strictUnifiedDiffApplied: bool
    diffSha256: str


class RunArtifactPostStage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    exitCode: int
    passed: bool
    outputSha256: str


class RunArtifactMutationStage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    diffSha256: str
    strictUnifiedDiffApplied: bool
    exitCode: int
    rejected: bool
    rejectionKind: str
    outputSha256: str


class RunArtifactStages(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pre: RunArtifactPreStage
    patch: RunArtifactPatchStage
    post: RunArtifactPostStage
    mutations: List[RunArtifactMutationStage]


class RunArtifactControlsObserved(BaseModel):
    model_config = ConfigDict(extra="forbid")
    uid: int
    gid: int
    nonRoot: bool
    capabilitiesDropped: bool
    noNewPrivileges: bool
    seccompMode: str
    rootFilesystemReadOnly: bool
    workspaceExecutable: bool
    workspaceNoSuid: bool
    workspaceNoDev: bool
    outputExecutable: bool
    onlyLoopbackInterface: bool
    networkInterfaces: List[str]
    sensitiveEnvironmentPresent: bool
    productionPathsPresent: bool
    dockerSocketPresent: bool
    workspaceSizeBytes: int
    memoryMaxBytes: int
    memorySwapMaxBytes: int
    pidsMax: int


class BundleRunArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schemaVersion: str
    artifactType: str
    contractVersion: str
    bundleId: str
    bundleSha256: str
    outcome: str
    startedAt: str
    completedAt: str
    sourceRevisionKind: str
    sourceRevision: str
    dependencyLockSha256: str
    rawReportSha256: str
    publicationValidatorImageDigest: str
    runner: RunArtifactRunner
    toolchainVersions: Dict[str, str]
    stages: RunArtifactStages
    controlsObserved: RunArtifactControlsObserved


class CompatibilityBundle(BaseModel):
    model_config = ConfigDict(extra="allow")
    schemaVersion: str = "1.0.0"
    bundleId: str
    status: Literal[
        "DRAFT",
        "CANDIDATE",
        "UNVERIFIED",
        "PROVISIONAL",
        "VERIFIED",
        "STALE",
        "BROKEN",
        "DISPUTED",
        "SUPERSEDED",
        "REVOKED",
    ] = "DRAFT"
    description: str
    tags: List[str] = Field(default_factory=list)
    scope: BundleScope
    fingerprint: BundleFingerprint
    patch: BundlePatch
    verification: BundleVerification
    provenance: BundleProvenance = Field(default_factory=BundleProvenance)
    evidencePublication: Optional[EvidencePublication] = None

    @field_validator("status", mode="before")
    @classmethod
    def normalize_status(cls, value: str) -> str:
        return value.upper() if isinstance(value, str) else value
