from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from app.config import settings
from app.models.discovery import AgentManifest, McpManifest
from app.models.recipe import VERIFIED_EVIDENCE_CONTRACT


router = APIRouter()
SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"


@router.get("/.well-known/mcp.json", tags=["Discovery"], response_model=McpManifest)
@router.head("/.well-known/mcp.json", tags=["Discovery"], include_in_schema=False)
async def get_mcp_manifest():
    """Return the MCP discovery manifest."""
    return McpManifest()


@router.get("/.well-known/agent-card.json", tags=["Discovery"], response_model=AgentManifest)
@router.head("/.well-known/agent-card.json", tags=["Discovery"], include_in_schema=False)
@router.get("/.well-known/agent.json", tags=["Discovery"], response_model=AgentManifest)
@router.head("/.well-known/agent.json", tags=["Discovery"], include_in_schema=False)
async def get_agent_manifest():
    """Return discovery metadata; this is not an A2A task gateway."""
    return AgentManifest()


@router.get("/install.sh", tags=["Agent Tooling"], response_class=PlainTextResponse)
@router.head("/install.sh", tags=["Agent Tooling"], include_in_schema=False)
async def get_install_script():
    """Return the optional local CLI installer."""
    install_file = SCRIPTS_DIR / "install.sh"
    if install_file.exists():
        return PlainTextResponse(
            install_file.read_text(encoding="utf-8"),
            media_type="text/x-shellscript",
        )
    return PlainTextResponse(
        "#!/usr/bin/env bash\necho 'Installer not found'\nexit 1\n",
        status_code=404,
    )


LLMS_TXT_CONTENT = """# Synapse-Mesh

> Fail-closed compatibility evidence for software agents over MCP and REST.

Synapse-Mesh publishes curated compatibility bundle records with exact version
scope, unified diffs, negative examples, provenance, and a declared four-stage
verification contract. A record becomes `VERIFIED` only when a separate valid
run artifact is bound to its exact bytes and toolchain. Otherwise it remains an
explicitly unverified candidate. No record is a production warranty.

## Implemented interfaces

- [MCP endpoint](__CANONICAL_MCP_ENDPOINT__): `find_solution` and storage-only `submit_solution`.
- [MCP manifest](https://synapsemesh.dev/.well-known/mcp.json).
- [REST/OpenAPI](https://docs.synapsemesh.dev).
- [Curated bundle API](https://synapsemesh.dev/api/v1/bundles): authoritative current runtime statuses.
- Qualified bundle records expose a validated run at their `evidencePublication.runArtifactUrl`.
- [Verification boundary](https://synapsemesh.dev/verification).
- [Frozen fixture evaluation](https://synapsemesh.dev/benchmark).
- [Full agent context](https://synapsemesh.dev/llms-full.txt).

The agent-card routes provide discovery metadata only; no A2A task gateway is
implemented. Public and crawled submissions are sanitised and retained as
unexecuted `DRAFT` records. Server-side hostile-code verification is disabled.
Use local re-verification only for code you have chosen to trust.
""".replace("__CANONICAL_MCP_ENDPOINT__", settings.canonical_mcp_url)


LLMS_FULL_TXT_CONTENT = """# Synapse-Mesh: Technical Reference for Software Agents

## Trust model

Synapse-Mesh is a narrow compatibility evidence registry. It returns a scoped
record or an explicit miss; it does not claim universal correctness.

`VERIFIED` requires a run artifact bound to the exact bundle bytes and exact
toolchain, recording the `__VERIFICATION_PROFILE__` contract on the real declared
package, compiler, or engine:

1. the unpatched workspace fails with the declared exception class/signature;
2. a strict unified diff applies to that workspace;
3. the patched workspace passes in the selected runtime;
4. at least two independent mutant diffs fail the same suite.

Missing evidence, ambiguous versions, substitute mocks, or unknown runtime state
fail closed. The API bundle list is the authoritative current status surface;
curated location alone does not imply `VERIFIED`. A qualified bundle exposes
its validated artifact at `/api/v1/bundles/{bundleId}/evidence`.

## MCP

Endpoint: `POST __CANONICAL_MCP_ENDPOINT__`

### `find_solution`

Required input: `errorSignature`. Optional inputs: `runtime` and a package-to-
version map. Results include evidence scope and actionability:

- `VERIFIED_MATCH`: a valid exact-run artifact exists and the supplied package version equals the observed release; still reproduce before applying.
- `UNVERIFIED_MATCH`: no exact-version run evidence applies, including when the target version is missing, ambiguous, or different; reproduce every stage before considering it.
- `VERSION_MISMATCH`: the supplied version is outside the record's declared scope; do not apply.
- `NO_VERIFIED_MATCH`: no curated record passed the deterministic match gates; do not apply.

### `submit_solution`

Accepts a technical problem, proposed diff, reproduction, test suite, and optional
HTTP(S) source. It sanitises and stores the input as an unexecuted `DRAFT`.
Submission does not verify, promote, or execute code.

## Execution boundary

The trusted-fixture worker accepts only exact repository-owned allowlist entries
and runs in a separately built, pinned container with no network, no bind mounts,
a read-only root, private temporary filesystems, a non-root identity, dropped
capabilities, seccomp, and explicit CPU, memory, PID, output, and time limits.
The resulting artifact is admitted only after a separate application-image gate
validates it against the exact curated bundle bytes. This is not a general
hostile-code service: public and crawled submissions remain storage-only drafts,
and authenticated server verification routes remain disabled.

The local CLI executes trusted bundle code with the invoking user's process
permissions. Inspect the bundle first and run it in a disposable environment.

## Autonomous maintenance

One elected hourly worker fetches allowlisted release metadata, normalises and
synthesises candidate drafts without an LLM, and writes only to
`bundles/drafts/`. Remote snippets are not executed. The worker does not edit
application source, deploy itself, or promote files into `bundles/golden/`.

Separately, a daily host timer starts the disposable exact verifier for the
pre-approved repository-owned target allowlist. It publishes an evidence
artifact only after every evidence stage and the independent application gate
pass. It is not triggered through the public API or the Ops page.

## Evaluation

`Suite v2-runtime-9` is the frozen primary-runtime fixture corpus. Its numeric
result is currently withheld because the latest production-runtime revalidation
did not satisfy every required case. This is not live-registry coverage or an
A/B model result.

## Privacy

The service is configured not to persist client IP addresses, raw User-Agent
strings, or query text. Minimal telemetry contains a coarse client class, event
category, and timestamp and is purged after 30 days on startup. Do not submit
personal data, credentials, or proprietary source code.

## Resources

- https://synapsemesh.dev/api/v1/bundles
- https://synapsemesh.dev/api/v1/bundles/{bundleId}/evidence
- https://synapsemesh.dev/.well-known/mcp.json
- https://synapsemesh.dev/openapi.json
- https://synapsemesh.dev/verification
- https://synapsemesh.dev/benchmark
- https://synapsemesh.dev/legal
- https://synapsemesh.dev/privacy
""".replace("__CANONICAL_MCP_ENDPOINT__", settings.canonical_mcp_url).replace(
    "__VERIFICATION_PROFILE__", VERIFIED_EVIDENCE_CONTRACT
)


@router.get("/llms.txt", tags=["Discovery"], response_class=PlainTextResponse)
@router.head("/llms.txt", tags=["Discovery"], include_in_schema=False)
@router.get("/.well-known/llms.txt", tags=["Discovery"], response_class=PlainTextResponse)
@router.head("/.well-known/llms.txt", tags=["Discovery"], include_in_schema=False)
async def get_llms_txt():
    """Return concise machine-readable discovery context."""
    return PlainTextResponse(LLMS_TXT_CONTENT, media_type="text/markdown; charset=utf-8")


@router.get("/llms-full.txt", tags=["Discovery"], response_class=PlainTextResponse)
@router.head("/llms-full.txt", tags=["Discovery"], include_in_schema=False)
async def get_llms_full_txt():
    """Return full machine-readable trust and interface context."""
    return PlainTextResponse(LLMS_FULL_TXT_CONTENT, media_type="text/markdown; charset=utf-8")
