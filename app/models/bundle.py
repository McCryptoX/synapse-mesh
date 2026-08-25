from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field


class BundleScope(BaseModel):
    package: str
    fromVersion: Optional[str] = None
    toVersion: Optional[str] = None
    runtime: str = "python"
    runtimeVersion: Optional[str] = None
    platform: str = "all"


class BundleFingerprint(BaseModel):
    errorSignature: str
    regex: Optional[str] = None
    regexFlags: Optional[str] = ""
    matchStream: Optional[str] = "stderr"


class BundlePatch(BaseModel):
    targetFile: str
    unifiedDiff: str
    pinnedDependencies: Dict[str, str] = Field(default_factory=dict)
    doNot: List[str] = Field(default_factory=list)


class BundleMutation(BaseModel):
    id: str
    description: Optional[str] = ""
    unifiedDiff: str


class BundleVerification(BaseModel):
    scriptLanguage: str = "python"
    workspaceFiles: Dict[str, str] = Field(default_factory=dict)
    reproductionScript: str
    testSuite: str
    mutations: List[BundleMutation] = Field(default_factory=list)
    expectedPreExit: int = 1
    expectedPostExit: int = 0
    timeoutMs: int = 30000


class BundleProvenance(BaseModel):
    spdxLicense: str = "MIT"
    primarySources: List[str] = Field(default_factory=list)
    verifiedAt: Optional[str] = None


class CompatibilityBundle(BaseModel):
    schemaVersion: str = "1.0.0"
    bundleId: str
    status: str = "VERIFIED"
    description: str
    tags: List[str] = Field(default_factory=list)
    scope: BundleScope
    fingerprint: BundleFingerprint
    patch: BundlePatch
    verification: BundleVerification
    provenance: BundleProvenance = Field(default_factory=BundleProvenance)
