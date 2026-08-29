from fastapi import APIRouter, Request, Response, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError
import asyncio
import json
import logging
import uuid
import re
from typing import Dict, Any, List, Optional

from app.models.recipe import (
    VERIFIED_EVIDENCE_CONTRACT,
    RecipeSearchRequest,
    RecipeSubmitRequest,
    ProblemDefinition,
    SolutionDefinition,
    ReproductionDefinition
)
from app.api.recipes import (
    get_recipe_by_id,
    list_recipes,
    recipe_matches_requested_evidence_versions,
    search_recipes,
    store_recipe_draft,
)
from app.database import get_db_connection
from app.core.telemetry_categories import (
    summarize_action,
    summarize_source,
    summarize_user_agent as _summarize_user_agent,
)
from app.config import settings

logger = logging.getLogger("synapse_mesh.mcp")
router = APIRouter(tags=["Model Context Protocol (MCP)"])

# Active SSE sessions: sessionId -> asyncio.Queue
sse_sessions: Dict[str, asyncio.Queue] = {}
sse_session_locks: Dict[str, asyncio.Lock] = {}
MAX_SSE_SESSIONS = 32  # Production uses one uvicorn worker for process-local SSE state.
MAX_SSE_SESSION_SECONDS = 15 * 60
MAX_MCP_CONCURRENT_POSTS = 32  # Per worker.
_mcp_post_slots = asyncio.Semaphore(MAX_MCP_CONCURRENT_POSTS)
MODERN_MCP_VERSION = settings.mcp_protocol_version
LEGACY_MCP_VERSION = "2024-11-05"

MCP_TOOLS = [
    {
        "name": "find_solution",
        "description": (
            "Search curated compatibility records. VERIFIED_MATCH requires a valid run-bound artifact and an exact supplied package version equal to the observed release; "
            "missing, ambiguous, differently versioned, or artifact-free matches are UNVERIFIED_MATCH and must be fully reproduced; "
            "an unknown query returns NO_VERIFIED_MATCH."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "errorSignature": {
                    "type": "string",
                    "description": "The exact error message, exception type, or traceback snippet"
                },
                "runtime": {
                    "type": "string",
                    "description": "Optional runtime or language (e.g. 'python', 'nodejs', 'rust', 'docker')"
                },
                "packages": {
                    "type": "object",
                    "description": "Optional key-value pairs of packages and version strings e.g. {'fastapi': '>=0.100.0'}"
                }
            },
            "required": ["errorSignature"]
        }
    },
    {
        "name": "submit_solution",
        "description": "Stores a sanitized problem, proposed fix, and test suite as an unexecuted DRAFT for the controlled verification pipeline.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "runtime": { "type": "string", "description": "Language or runtime e.g. 'python'" },
                "errorSignature": { "type": "string", "description": "The exact error signature resolved" },
                "description": { "type": "string", "description": "Description of why the error occurs" },
                "summary": { "type": "string", "description": "Summary of the solution fix" },
                "codeDiff": { "type": "string", "description": "Unified git diff of the patch" },
                "reproScript": { "type": "string", "description": "Minimal script triggering the error" },
                "testSuite": { "type": "string", "description": "Test code asserting the fix works" },
                "primarySource": { "type": "string", "description": "Official docs / release notes link" }
            },
            "required": ["runtime", "errorSignature", "description", "summary", "reproScript", "testSuite"]
        }
    }
]


def summarize_user_agent(ua: str) -> str:
    """Coarse client class only. Never persist a raw User-Agent string (can identify a device)."""
    return _summarize_user_agent(ua)


async def log_agent_access(source_type: str, action: str, query: str, request: Request):
    db = None
    try:
        ua_summary = summarize_user_agent(request.headers.get("user-agent", ""))
        db = await get_db_connection()
        # query_snippet left empty: error text can contain emails/paths/IPs; we do not persist it.
        await db.execute(
            "INSERT INTO access_logs (source_type, action, query_snippet, user_agent_summary) VALUES (?, ?, ?, ?)",
            (summarize_source(source_type), summarize_action(action), "", ua_summary)
        )
        await db.commit()
    except Exception as exc:
        # Exception messages can contain client-derived values or local paths.
        logger.warning("Agent access log write failed (%s)", type(exc).__name__)
    finally:
        if db:
            await db.close()


async def _dispatch_mcp_request_inner(body: Dict[str, Any], request: Request) -> Dict[str, Any]:
    msg_id = body.get("id")
    method = body.get("method") or request.headers.get("mcp-method")
    params = body.get("params", {})

    if not method:
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32600, "message": "Missing method"}}

    # 1. Server Discovery (MCP Modern Stateless Probe - Spec 2026-07-28 / OpenAI Agents SDK)
    if method == "server/discover":
        await log_agent_access("mcp_call", "server_discover", "", request)
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "resultType": "complete",
                "supportedVersions": [MODERN_MCP_VERSION],
                "capabilities": {
                    "tools": {"listChanged": False},
                    "resources": {"subscribe": False, "listChanged": False},
                    "prompts": {"listChanged": False},
                },
                "instructions": (
                    "Retrieve a scoped VERIFIED_MATCH, a fail-closed UNVERIFIED_MATCH candidate, "
                    "or an explicit NO_VERIFIED_MATCH. Public submissions are stored as unexecuted drafts."
                ),
                "ttlMs": 300000,
                "cacheScope": "public",
                "_meta": {
                    "io.modelcontextprotocol/serverInfo": {
                        "name": "synapse-mesh",
                        "version": settings.app_version
                    }
                },
            },
        }

    # 2. Initialize (Legacy/Stateful MCP Handshake)
    elif method == "initialize":
        await log_agent_access("mcp_call", "initialize", "", request)
        requested_proto = params.get("protocolVersion")
        client_proto = requested_proto if requested_proto == LEGACY_MCP_VERSION else LEGACY_MCP_VERSION
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": client_proto,
                "capabilities": {
                    "tools": {"listChanged": False},
                    "resources": {"subscribe": False, "listChanged": False},
                    "prompts": {"listChanged": False},
                    "logging": {}
                },
                "serverInfo": {
                    "name": "synapse-mesh",
                    "version": settings.app_version
                },
                "instructions": (
                    "Synapse-Mesh returns run-artifact-qualified evidence, explicitly unverified curated candidates, "
                    "or an honest miss. Reproduce every result in the target project."
                )
            }
        }

    # 2. Initialized Notification
    elif method == "notifications/initialized":
        return {"jsonrpc": "2.0", "result": {}}

    # 3. Ping
    elif method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}

    # 4. Tools List
    elif method == "tools/list":
        await log_agent_access("mcp_call", "tools_list", "", request)
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "tools": MCP_TOOLS
            }
        }

    # 5. Tools Call
    elif method == "tools/call":
        tool_name = params.get("name") or request.headers.get("mcp-name")
        arguments = params.get("arguments", {})

        if tool_name == "find_solution":
            from app.core.sanitizer import ZeroPiiSanitizer
            raw_error_sig = arguments.get("errorSignature", "")
            error_sig = ZeroPiiSanitizer.sanitize_text(raw_error_sig)
            await log_agent_access("mcp_call", "find_solution", error_sig, request)
            runtime_filter = arguments.get("runtime")

            # 1. Search curated compatibility bundles. A candidate remains
            # useful to an agent even when no run-bound artifact qualifies it
            # as VERIFIED, but the result tier and actionability must say so.
            from app.api.bundles import load_all_published_bundles
            from app.api.recipes import KNOWN_PACKAGES, PACKAGE_ALIASES, STOPWORDS
            from app.core.signature_matcher import SignatureMatcher
            from app.core.version_matcher import VersionMatcher
            
            clean_query = error_sig.lower()
            raw_tokens = [w.strip(".:(),'\"`") for w in clean_query.split()]
            
            query_packages = {t for t in raw_tokens if t in KNOWN_PACKAGES}
            for t in raw_tokens:
                if t in PACKAGE_ALIASES:
                    query_packages.add(PACKAGE_ALIASES[t])
            
            req_packages_dict = arguments.get("packages") if isinstance(arguments.get("packages"), dict) else {}
            if req_packages_dict:
                query_packages.update(req_packages_dict.keys())

            scored_bundles = []
            for b in load_all_published_bundles():
                publication = b.get("evidencePublication") or {}
                artifact_summary = publication.get("runArtifactSummary")
                if not isinstance(artifact_summary, dict):
                    artifact_summary = {}
                if publication.get("recordedContractShapeSatisfied") is not True:
                    continue
                artifact_available = publication.get("runArtifactAvailable") is True
                lifecycle = publication.get("lifecycle")
                if not isinstance(lifecycle, dict):
                    lifecycle = {}
                lifecycle_status = lifecycle.get("status") or "UNVERIFIED"
                bundle_evidence_qualified = (
                    b.get("status") == "VERIFIED"
                    and publication.get("qualified") is True
                    and lifecycle_status == "VERIFIED"
                    and lifecycle.get("qualified") is True
                )
                if runtime_filter and b.get("scope", {}).get("runtime", "").lower() != runtime_filter.lower():
                    continue
                fp = b.get("fingerprint", {})
                regex_pat = fp.get("regex", "")
                sig_text = fp.get("errorSignature", "")
                variants = fp.get("variants", [])
                scope = b.get("scope", {})
                pkg = scope.get("package", "").lower()
                aff_versions = scope.get("affectedVersionRange")
                if not aff_versions:
                    continue

                # Package filter rule: if query has explicit package, bundle MUST match package!
                if query_packages and pkg not in query_packages:
                    continue

                # Structural Semantic Matcher Gate (Multi-Variant Aware)
                is_matched, match_conf = SignatureMatcher.compute_match(error_sig, sig_text, regex_pat, variants=variants)
                if not is_matched or match_conf < 0.70:
                    continue

                # 3-State Epistemological Version Gate (MATCH / MISMATCH / UNKNOWN)
                env_status, version_constraint_matched = VersionMatcher.evaluate_environment(
                    pkg, req_packages_dict, aff_versions
                )
                normalized_requested_packages = {
                    str(name).lower(): version
                    for name, version in req_packages_dict.items()
                }
                requested_package_version = normalized_requested_packages.get(pkg)
                observed_toolchains = artifact_summary.get("toolchainVersions")
                if not isinstance(observed_toolchains, dict):
                    observed_toolchains = {}
                observed_package_version = observed_toolchains.get(pkg)
                exact_observed_version_matched = (
                    VersionMatcher.matches_exact_observed_version(
                        requested_package_version,
                        observed_package_version,
                    )
                    if requested_package_version is not None
                    else None
                )
                evidence_qualified = (
                    bundle_evidence_qualified
                    and requested_package_version is not None
                    and exact_observed_version_matched is True
                )
                if artifact_available and not bundle_evidence_qualified:
                    evidence_gap_tier = f"RUN_BOUND_EVIDENCE_{lifecycle_status}"
                    evidence_gap_reason = (
                        f"A run artifact exists, but its current lifecycle state is "
                        f"{lifecycle_status}: {lifecycle.get('reason') or 'it is not current evidence.'} "
                        "Reproduce every stage before considering the patch."
                    )
                    evidence_gap_explanation = (
                        "Historic run data remains inspectable, but lifecycle policy "
                        f"currently classifies it as {lifecycle_status}."
                    )
                elif bundle_evidence_qualified and requested_package_version is None:
                    evidence_gap_tier = "RUN_BOUND_EVIDENCE_TARGET_VERSION_UNKNOWN"
                    evidence_gap_reason = (
                        f"A valid run artifact exists for {pkg} {observed_package_version}, "
                        "but no target package version was supplied. Reproduce every stage "
                        "for the target version before considering the patch."
                    )
                    evidence_gap_explanation = (
                        "A valid exact-run artifact is published for one concrete package "
                        "version, but applicability is unknown because the target version "
                        "was not supplied."
                    )
                elif bundle_evidence_qualified:
                    evidence_gap_tier = "RUN_BOUND_EVIDENCE_OTHER_VERSION"
                    evidence_gap_reason = (
                        f"A valid run artifact exists for {pkg} {observed_package_version}, "
                        "but the supplied version is not that exact observed release. "
                        "Reproduce every stage for the target version before considering "
                        "the patch."
                    )
                    evidence_gap_explanation = (
                        "A valid exact-run artifact is published for a different concrete "
                        "package version; it is evidence for that observed run, not for "
                        "the supplied version."
                    )
                else:
                    evidence_gap_tier = "CURATED_UNVERIFIED_CANDIDATE"
                    evidence_gap_reason = (
                        "The query matches a curated candidate, but no valid run-bound "
                        "artifact exists for these exact bundle bytes. Reproduce every "
                        "stage before considering the patch."
                    )
                    evidence_gap_explanation = (
                        "The curated record declares pre-fail, unified diff, post-pass, "
                        "and mutant checks, but no valid exact-run artifact is published."
                    )

                prov = b.get("provenance", {})
                primary_src = prov.get("primarySources", ["https://synapsemesh.dev/benchmark"])[0] if prov.get("primarySources") else prov.get("primarySource", "https://synapsemesh.dev/benchmark")
                relative_artifact_url = publication.get("runArtifactUrl")
                run_artifact_url = (
                    f"https://synapsemesh.dev{relative_artifact_url}"
                    if artifact_available
                    and isinstance(relative_artifact_url, str)
                    and relative_artifact_url.startswith("/api/v1/bundles/")
                    else None
                )

                if env_status == "MISMATCH":
                    req_pkg_ver = requested_package_version
                    scored_bundles.append((match_conf, {
                        "status": "VERSION_MISMATCH",
                        "actionability": "DO_NOT_APPLY",
                        "actionabilityReason": f"Specified {pkg} version ({req_pkg_ver}) is outside the bundle's recorded affected range ({aff_versions}).",
                        "signatureSimilarity": match_conf,
                        "environmentStatus": "MISMATCH",
                        "versionConstraintMatched": False,
                        "evidenceContractSatisfied": evidence_qualified,
                        "bundleEvidenceQualified": bundle_evidence_qualified,
                        "runArtifactAvailable": artifact_available,
                        "evidenceLifecycleStatus": lifecycle_status,
                        "exactObservedVersionMatched": exact_observed_version_matched,
                        "observedPackageVersion": observed_package_version,
                        "runArtifactUrl": run_artifact_url,
                        "package": pkg,
                        "requestedVersion": req_pkg_ver,
                        "recipeAffectedVersions": aff_versions,
                        "recipeId": b.get("bundleId"),
                        "errorSignature": fp.get("errorSignature"),
                        "suggestion": f"The error signature matches a curated compatibility candidate for {pkg} {aff_versions}, but your specified version ({req_pkg_ver}) lies outside the declared affected range.",
                        "canonicalUrl": f"https://synapsemesh.dev/api/v1/bundles/{b.get('bundleId')}"
                    }))
                else:
                    raw_iso_data = b.get("isolationProfile", {})
                    iso_data = (
                        dict(raw_iso_data)
                        if isinstance(raw_iso_data, dict)
                        else {}
                    )
                    if not evidence_qualified:
                        iso_data.pop("verificationProfile", None)
                    v_profile = VERIFIED_EVIDENCE_CONTRACT if evidence_qualified else None
                    iso_status = iso_data.get("isolationStatus", "NOT_ATTESTED")
                    verification = b.get("verification", {})
                    mutation_count = len(verification.get("mutations") or [])
                    observed_mutations = artifact_summary.get("mutationsRejected")
                    observed_mutation_total = artifact_summary.get("mutationsDeclared")
                    observed_mutations_killed = (
                        f"{observed_mutations}/{observed_mutation_total}"
                        if artifact_available
                        and isinstance(observed_mutations, int)
                        and isinstance(observed_mutation_total, int)
                        else None
                    )

                    result_status = "VERIFIED_MATCH" if evidence_qualified else "UNVERIFIED_MATCH"
                    lifecycle_blocks_patch = lifecycle_status in {
                        "STALE",
                        "BROKEN",
                        "DISPUTED",
                        "SUPERSEDED",
                        "UNKNOWN",
                    }
                    lifecycle_record = lifecycle.get("record")
                    if not isinstance(lifecycle_record, dict):
                        lifecycle_record = {}
                    superseded_by_bundle_id = lifecycle_record.get(
                        "supersededByBundleId"
                    )

                    if evidence_qualified:
                        actionability = "REPRODUCE_BEFORE_APPLY"
                        actionability_reason = (
                            "The query matches evidence bound to a validated current "
                            "run artifact for the exact supplied package version; "
                            "reproduce it in the target project before applying."
                        )
                    elif lifecycle_status == "STALE":
                        actionability = "REVERIFY_BEFORE_CONSIDERING"
                        actionability_reason = (
                            "The historic run artifact is outside the current freshness "
                            "window. Re-verify the four-stage contract before considering "
                            "the patch."
                        )
                    elif (
                        lifecycle_status == "SUPERSEDED"
                        and isinstance(superseded_by_bundle_id, str)
                        and superseded_by_bundle_id
                    ):
                        actionability = "USE_SUPERSEDING_RECORD"
                        actionability_reason = (
                            "This historic evidence has been superseded. Resolve and "
                            f"evaluate {superseded_by_bundle_id} instead."
                        )
                    elif lifecycle_status in {
                        "BROKEN",
                        "DISPUTED",
                        "SUPERSEDED",
                        "UNKNOWN",
                    }:
                        actionability = "DO_NOT_APPLY"
                        actionability_reason = (
                            "The evidence lifecycle does not currently permit applying "
                            f"this patch ({lifecycle_status})."
                        )
                    else:
                        actionability = "REPRODUCE_BEFORE_CONSIDERING"
                        actionability_reason = evidence_gap_reason

                    payload = {
                        "status": result_status,
                        "actionability": actionability,
                        "actionabilityReason": actionability_reason,
                        "signatureSimilarity": match_conf,
                        "environmentStatus": env_status,
                        "versionConstraintMatched": version_constraint_matched,
                        "evidenceContractSatisfied": evidence_qualified,
                        "bundleEvidenceQualified": bundle_evidence_qualified,
                        "runArtifactAvailable": artifact_available,
                        "evidenceLifecycleStatus": lifecycle_status,
                        "exactObservedVersionMatched": exact_observed_version_matched,
                        "observedPackageVersion": observed_package_version,
                        "observedMutationsKilled": observed_mutations_killed,
                        "runArtifactUrl": run_artifact_url,
                        "evidenceTier": (
                            "VERIFIED_REAL_RUNTIME"
                            if evidence_qualified
                            else evidence_gap_tier
                        ),
                        "isolationStatus": iso_status,
                        "isolationProfile": iso_data if iso_data else None,
                        "recipeId": b.get("bundleId"),
                        "runtime": b.get("scope", {}).get("runtime"),
                        "package": b.get("scope", {}).get("package"),
                        "affectedVersions": aff_versions,
                        "errorSignature": fp.get("errorSignature"),
                        "minimalFix": b.get("description"),
                        "pinnedDependencies": b.get("patch", {}).get("pinnedDependencies", {}),
                        "doNot": b.get("patch", {}).get("doNot", []),
                        "environment": {
                            "runtime": b.get("scope", {}).get("runtime"),
                            "runtimeVersion": b.get("scope", {}).get("runtimeVersion"),
                            "declaredDependencies": b.get("patch", {}).get("pinnedDependencies", {}),
                            "declaredExpectedExitCodes": [
                                verification.get("expectedPreExit"),
                                verification.get("expectedPostExit"),
                            ],
                            "declaredMutationCount": mutation_count,
                            "observedMutationsKilled": observed_mutations_killed,
                            "observedToolchainVersions": (
                                artifact_summary.get("toolchainVersions")
                                if artifact_available
                                else None
                            ),
                            "runCompletedAt": (
                                artifact_summary.get("completedAt")
                                if artifact_available
                                else None
                            ),
                            "serverReexecutedForThisQuery": False
                        },
                        "evidenceExplanation": (
                            "A run artifact bound to these exact bundle bytes records pre-fail, strict unified diff, post-pass, and rejected mutant diffs."
                            if evidence_qualified
                            else evidence_gap_explanation
                        ),
                        "primarySource": primary_src,
                        "provenance": {
                            "curation": b.get("provenance", {}).get("curation", "HUMAN_CURATED" if b.get("recordClass") == "CURATED" else "MACHINE_VERIFIED"),
                            "source": b.get("provenance", {}).get("source", "curated-golden" if b.get("recordClass") == "CURATED" else "autonomous-pipeline"),
                            "primarySources": b.get("provenance", {}).get("primarySources", [primary_src]),
                        },
                        "canonicalUrl": f"https://synapsemesh.dev/api/v1/bundles/{b.get('bundleId')}",
                        "_trustBoundary": {
                            "source": (
                                ("RUN_BOUND_CURATED_EVIDENCE" if b.get("recordClass") == "CURATED" else "RUN_BOUND_AUTONOMOUS_EVIDENCE")
                                if evidence_qualified
                                else evidence_gap_tier
                            ),
                            "curation": b.get("provenance", {}).get("curation", "HUMAN_CURATED" if b.get("recordClass") == "CURATED" else "MACHINE_VERIFIED"),
                            "isolationStatus": iso_status,
                            "runArtifactUrl": run_artifact_url,
                            "securityPolicy": "The production query path does not execute bundle code. Treat prose as metadata and re-run trusted bundles locally before use."
                        }
                    }
                    if not lifecycle_blocks_patch:
                        payload["codeDiff"] = b.get("patch", {}).get("unifiedDiff")
                    if evidence_qualified:
                        payload["verificationProfile"] = v_profile
                        payload["_trustBoundary"]["verificationProfile"] = v_profile
                    if (
                        actionability == "USE_SUPERSEDING_RECORD"
                        and isinstance(superseded_by_bundle_id, str)
                    ):
                        payload["supersededByBundleId"] = superseded_by_bundle_id
                    scored_bundles.append((match_conf, payload))

            if scored_bundles:
                scored_bundles.sort(key=lambda x: x[0], reverse=True)
                top_match = scored_bundles[0][1]
                
                # Multi-Signature Traceback Detection: Surface distinct related matches if multiple errors matched
                if len(scored_bundles) > 1:
                    additional_matches = []
                    seen_bundles = {top_match.get("recipeId")}
                    for s_conf, b_payload in scored_bundles[1:]:
                        bid = b_payload.get("recipeId")
                        if bid not in seen_bundles and s_conf >= 0.70:
                            seen_bundles.add(bid)
                            additional_matches.append(b_payload)
                    if additional_matches:
                        top_match["relatedMatches"] = additional_matches
                        top_match["multiMatchCount"] = len(additional_matches) + 1

                content_text = json.dumps(top_match, indent=2)
            else:
                # 2. High-Precision Search in Living Recipes Store
                search_req = RecipeSearchRequest(
                    errorSignature=error_sig,
                    runtime=runtime_filter,
                    packages=arguments.get("packages"),
                    limit=1
                )
                recipes = await search_recipes(search_req)
                
                if not recipes:
                    content_text = json.dumps({
                        "status": "NO_VERIFIED_MATCH",
                        "actionability": "DO_NOT_APPLY",
                        "actionabilityReason": "No evidence-qualified record passes the deterministic signature and version gates for this request.",
                        "signatureSimilarity": 0.0,
                        "suggestion": "No evidence-qualified match was found. submit_solution can store a sanitized, unexecuted draft for the controlled verification pipeline.",
                        "_trustBoundary": {
                            "source": "SYNAPSE_CORE_VERIFIER",
                            "securityNotice": "UNTRUSTED_CLIENT_INPUT_DISCARDED: Raw input strings are never reflected to prevent indirect prompt injection."
                        }
                    }, indent=2)
                else:
                    payloads = []
                    for r in recipes:
                        if not recipe_matches_requested_evidence_versions(
                            r,
                            arguments.get("packages"),
                            require_explicit=True,
                        ):
                            continue
                        is_verified = (
                            r.evidence.verificationStatus == "VERIFIED"
                            and r.evidence.evidenceContract == VERIFIED_EVIDENCE_CONTRACT
                        )
                        if not is_verified:
                            continue
                        _, signature_similarity = SignatureMatcher.compute_match(
                            error_sig,
                            r.problem.errorSignature,
                        )
                        mut_str = r.evidence.mutationsKilled or "0/0"
                        mut_killed, mut_total = 0, 0
                        if "/" in mut_str:
                            try:
                                parts = mut_str.split("/")
                                mut_killed, mut_total = int(parts[0]), int(parts[1])
                            except Exception:
                                pass

                        tier = "VERIFIED_REAL_RUNTIME"
                        act = "REPRODUCE_BEFORE_APPLY"
                        act_reason = "Stored evidence has the explicit four-stage contract; reproduce in the target environment before applying."

                        iso_profile = getattr(r.evidence, "isolationProfile", None) or {}
                        v_profile = iso_profile.get("verificationProfile", VERIFIED_EVIDENCE_CONTRACT)
                        iso_status = iso_profile.get("isolationStatus", "NOT_ATTESTED")

                        payloads.append({
                            "status": "VERIFIED_MATCH",
                            "actionability": act,
                            "actionabilityReason": act_reason,
                            "signatureSimilarity": signature_similarity,
                            "evidenceContractSatisfied": True,
                            "evidenceTier": tier,
                            "verificationProfile": v_profile,
                            "isolationStatus": iso_status,
                            "isolationProfile": iso_profile if iso_profile else None,
                            "recipeId": r.id,
                            "runtime": r.problem.runtime,
                            "errorSignature": r.problem.errorSignature,
                            "minimalFix": r.solution.summary,
                            "codeDiff": r.solution.codeDiff or r.solution.patchDiff,
                            "pinnedDependencies": r.solution.pinnedDependencies or r.problem.packages,
                            "doNot": r.solution.doNot or ["Do not apply unverified global monkeypatches"],
                            "environment": {
                                "runtime": r.problem.runtime,
                                "recordedExitCodes": [r.evidence.preExit, r.evidence.postExit],
                                "mutationsKilled": mut_str
                            },
                            "evidenceExplanation": f"Stored contract evidence records pre-exit {r.evidence.preExit}, post-exit {r.evidence.postExit}, and mutants {mut_str}.",
                            "primarySource": r.evidence.primarySource,
                            "canonicalUrl": f"https://synapsemesh.dev/recipes/{r.id}",
                            "_trustBoundary": {
                                "source": "STORED_CONTRACT_EVIDENCE",
                                "verificationProfile": v_profile,
                                "isolationStatus": iso_status,
                                "securityPolicy": "The query path does not execute code. Reproduce locally in the target environment before use."
                            }
                        })
                    content_text = json.dumps(payloads[0] if payloads else {
                        "status": "NO_VERIFIED_MATCH",
                        "actionability": "DO_NOT_APPLY",
                        "signatureSimilarity": 0.0,
                    }, indent=2)

            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": [{"type": "text", "text": content_text}],
                    "isError": False
                }
            }

        elif tool_name == "submit_solution":
            error_sig = arguments.get("errorSignature", "")
            await log_agent_access("mcp_call", "submit_solution", error_sig, request)

            submit_req = RecipeSubmitRequest(
                problem=ProblemDefinition(
                    errorSignature=error_sig,
                    runtime=arguments.get("runtime", "unknown"),
                    description=arguments.get("description", "")
                ),
                solution=SolutionDefinition(
                    summary=arguments.get("summary", ""),
                    codeDiff=arguments.get("codeDiff"),
                    instructions=[]
                ),
                reproduction=ReproductionDefinition(
                    script=arguments.get("reproScript", ""),
                    testSuite=arguments.get("testSuite", "")
                ),
                primarySource=arguments.get("primarySource")
            )
            # Public MCP ingestion is deliberately storage-only. The submitted
            # reproduction and test suite are never executed in the API process.
            created = await store_recipe_draft(submit_req)
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                f"Stored recipe '{created.id}' as an unexecuted "
                                f"{created.evidence.verificationStatus} candidate. "
                                f"Link: https://synapsemesh.dev/recipes/{created.id}. "
                                "No submitted code was run during ingestion. A separate, "
                                "controlled verifier must produce evidence before promotion."
                            )
                        }
                    ],
                    "isError": False
                }
            }

        else:
            return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"Tool '{tool_name}' not found"}}

    # 6. Resources List
    elif method == "resources/list":
        recipes = await list_recipes(response=Response(), limit=20, status="VERIFIED")
        resources = [
            {
                "uri": f"synapse://recipes/{r.id}",
                "name": f"Recipe: {r.id}",
                "description": r.problem.errorSignature,
                "mimeType": "application/json"
            }
            for r in recipes
        ]
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {"resources": resources}
        }

    else:
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"Method '{method}' not found"}}


async def dispatch_mcp_request(body: Any, request: Request) -> Dict[str, Any]:
    """Processes an incoming MCP JSON-RPC 2.0 request payload with structured error guarantees."""
    if not isinstance(body, dict):
        return {
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": -32600, "message": "JSON-RPC request must be an object"},
        }
    msg_id = body.get("id")
    if body.get("jsonrpc") != "2.0":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": -32600, "message": "Invalid JSON-RPC version"},
        }
    if not isinstance(body.get("method"), str) or not body["method"].strip():
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": -32600, "message": "JSON-RPC method must be a non-empty string"},
        }
    if "params" in body and not isinstance(body["params"], dict):
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": -32602, "message": "JSON-RPC params must be an object"},
        }
    protocol_header = request.headers.get("mcp-protocol-version")
    if protocol_header is not None:
        if protocol_header != MODERN_MCP_VERSION:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32600, "message": "Unsupported MCP protocol version"},
            }
        if body["method"] == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32601, "message": "initialize is not part of MCP 2026-07-28"},
            }
        routed_method = request.headers.get("mcp-method")
        if routed_method != body["method"]:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32600, "message": "Mcp-Method header must match the JSON-RPC method"},
            }
        params = body.get("params", {})
        request_meta = params.get("_meta") if isinstance(params, dict) else None
        if body["method"] != "server/discover":
            if not isinstance(request_meta, dict):
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32602, "message": "Modern MCP requests require per-request _meta"},
                }
            if request_meta.get("io.modelcontextprotocol/protocolVersion") != MODERN_MCP_VERSION:
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32602, "message": "MCP protocol metadata does not match the request header"},
                }
            capabilities = request_meta.get("io.modelcontextprotocol/clientCapabilities")
            if capabilities is not None and not isinstance(capabilities, dict):
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32602, "message": "Client capabilities metadata must be an object"},
                }
            client_info = request_meta.get("io.modelcontextprotocol/clientInfo")
            if client_info is not None and not isinstance(client_info, dict):
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32602, "message": "Client info metadata must be an object"},
                }
        if body["method"] == "tools/call":
            tool_name = params.get("name")
            if request.headers.get("mcp-name") != tool_name:
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32600, "message": "Mcp-Name header must match the requested tool"},
                }
    try:
        response = await _dispatch_mcp_request_inner(body, request)
        if protocol_header == MODERN_MCP_VERSION and isinstance(response.get("result"), dict):
            result = response["result"]
            result.setdefault("resultType", "complete")
            meta = result.setdefault("_meta", {})
            if isinstance(meta, dict):
                meta.setdefault(
                    "io.modelcontextprotocol/serverInfo",
                    {"name": "synapse-mesh", "version": settings.app_version},
                )
        return response
    except ValidationError:
        # Pydantic messages can include submitted emails, paths, or code. Return
        # and log only the error class, never the validation payload.
        logger.info("MCP client request rejected (ValidationError)")
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": -32602, "message": "Invalid tool arguments"},
        }
    except HTTPException as exc:
        logger.info("MCP client request rejected (HTTPException:%s)", exc.status_code)
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": -32602, "message": "Submission rejected by validation policy"},
        }
    except Exception as exc:
        logger.error("MCP dispatch failed (%s)", type(exc).__name__)
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {
                "code": -32603,
                "message": f"Internal RPC processing error: {type(exc).__name__}"
            }
        }


# ==============================================================================
# ROUTE HANDLERS (Supporting /mcp, /sse, /messages, and / on mcp.synapsemesh.dev)
# ==============================================================================

async def handle_mcp_get(request: Request):
    """Handles GET requests (detecting SSE vs JSON discovery)."""
    accept = request.headers.get("accept", "").lower()
    
    # If client requests SSE stream (ChatGPT / Claude SSE Transport)
    if "text/event-stream" in accept:
        if len(sse_sessions) >= MAX_SSE_SESSIONS:
            raise HTTPException(status_code=429, detail="SSE session capacity reached; retry later")
        session_id = str(uuid.uuid4())
        queue: asyncio.Queue = asyncio.Queue(maxsize=16)
        sse_sessions[session_id] = queue
        sse_session_locks[session_id] = asyncio.Lock()
        started_at = asyncio.get_running_loop().time()
        
        async def event_generator():
            try:
                # 1. Emit endpoint event pointing to messages endpoint
                endpoint_url = f"{settings.canonical_mcp_url}/messages?sessionId={session_id}"
                yield f"event: endpoint\ndata: {endpoint_url}\n\n"
                
                # 2. Stream message events from queue or send periodic keep-alives
                while True:
                    if asyncio.get_running_loop().time() - started_at >= MAX_SSE_SESSION_SECONDS:
                        break
                    if await request.is_disconnected():
                        break
                    try:
                        msg = await asyncio.wait_for(queue.get(), timeout=15.0)
                        yield f"event: message\ndata: {json.dumps(msg)}\n\n"
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
            finally:
                sse_sessions.pop(session_id, None)
                sse_session_locks.pop(session_id, None)

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"
            }
        )

    # Standard JSON discovery response
    await log_agent_access("discovery", "mcp_info", "", request)
    return {
        "status": "ready",
        "protocol": f"MCP/{MODERN_MCP_VERSION}",
        "legacyCompatibility": f"MCP/{LEGACY_MCP_VERSION}",
        "server": settings.app_name,
        "endpoint": settings.canonical_mcp_url,
        "sseEndpoint": f"{settings.canonical_mcp_url}/sse",
        "toolsAvailable": [t["name"] for t in MCP_TOOLS]
    }


MAX_MCP_PAYLOAD_BYTES = 1_000_000  # 1 MB


def _content_length_exceeds_limit(raw_value: Optional[str]) -> bool:
    if not raw_value:
        return False
    try:
        parsed = int(raw_value)
        if parsed < 0:
            raise ValueError
        return parsed > MAX_MCP_PAYLOAD_BYTES
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid Content-Length header")


async def _read_bounded_json(request: Request) -> Dict[str, Any]:
    """Stream and cap request bytes even when Content-Length is absent."""
    content_length = request.headers.get("content-length")
    if _content_length_exceeds_limit(content_length):
        raise HTTPException(status_code=413, detail="Payload too large: Max MCP request size is 1 MB")

    chunks: List[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > MAX_MCP_PAYLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Payload too large: Max MCP request size is 1 MB")
        chunks.append(chunk)
    try:
        body = json.loads(b"".join(chunks))
    except (TypeError, ValueError, json.JSONDecodeError):
        raise HTTPException(status_code=400, detail="Invalid JSON-RPC payload")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="JSON-RPC payload must be an object")
    return body


async def _dispatch_bounded_post(request: Request) -> Dict[str, Any]:
    acquired = False
    try:
        await asyncio.wait_for(_mcp_post_slots.acquire(), timeout=1.0)
        acquired = True
        body = await _read_bounded_json(request)
        return await dispatch_mcp_request(body, request)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=429, detail="MCP request capacity reached; retry later")
    finally:
        if acquired:
            _mcp_post_slots.release()


async def handle_mcp_post(request: Request):
    """Handles JSON-RPC 2.0 direct streamable HTTP requests."""
    res = await _dispatch_bounded_post(request)
    return JSONResponse(content=res)


async def handle_mcp_messages(request: Request, sessionId: Optional[str] = Query(None)):
    """Handles POST messages for active SSE sessions with backpressure management."""
    if sessionId:
        q = sse_sessions.get(sessionId)
        if q is None:
            raise HTTPException(status_code=404, detail="SSE session not found")
        lock = sse_session_locks.setdefault(sessionId, asyncio.Lock())
        async with lock:
            if q.full():
                logger.warning("SSE queue full; terminating slow or stuck consumer session")
                sse_sessions.pop(sessionId, None)
                sse_session_locks.pop(sessionId, None)
                raise HTTPException(
                    status_code=429,
                    detail="SSE consumer backpressure limit reached; session closed.",
                )
            # Dispatch only after capacity is reserved by the per-session lock,
            # so a rejected transport cannot still persist a tool side effect.
            res = await _dispatch_bounded_post(request)
            q.put_nowait(res)
            return Response(status_code=202)

    # Stateless/direct HTTP response when no legacy SSE session is requested.
    res = await _dispatch_bounded_post(request)
    return JSONResponse(content=res)


# Bind endpoints to router with all aliases
@router.get("/")
@router.head("/")
@router.options("/")
@router.get("/mcp")
@router.head("/mcp")
@router.options("/mcp")
@router.get("/sse")
@router.head("/sse")
@router.options("/sse")
@router.get("/mcp/sse")
@router.head("/mcp/sse")
@router.options("/mcp/sse")
async def mcp_get_route(request: Request):
    return await handle_mcp_get(request)


@router.post("/")
@router.options("/")
@router.post("/mcp")
@router.options("/mcp")
@router.post("/mcp/")
async def mcp_post_route(request: Request):
    return await handle_mcp_post(request)


@router.post("/mcp/messages")
@router.options("/mcp/messages")
@router.post("/messages")
@router.options("/messages")
async def mcp_messages_route(request: Request, sessionId: Optional[str] = Query(None)):
    return await handle_mcp_messages(request, sessionId)
