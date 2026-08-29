from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
import json
import uuid
import sqlite3
import re
from typing import List, Optional, Any
from app.models.recipe import (
    VerifiedRecipe,
    RecipeSearchRequest,
    RecipeSubmitRequest,
    ProblemDefinition,
    SolutionDefinition,
    ReproductionDefinition,
    EvidenceDefinition,
    VERIFIED_EVIDENCE_CONTRACT,
)
from app.database import get_db_connection
from app.config import settings
from app.core.sanitizer import ZeroPiiSanitizer
from app.core.registry_snapshot import build_registry_snapshot, project_recipe_row
from app.core.version_matcher import VersionMatcher
from app.core.telemetry_categories import (
    summarize_action,
    summarize_source,
    summarize_user_agent,
)

router = APIRouter(tags=["Living Solutions Recipes"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)

RECIPE_ID_PATTERN = re.compile(r"^rec_[a-z0-9][a-z0-9_-]{0,59}$")


def _recipe_from_row(row: Any) -> Optional[VerifiedRecipe]:
    """Compatibility wrapper for callers and focused regression tests."""
    return project_recipe_row(row)


@router.get("/api/v1/recipes/stats", tags=["System"])
async def get_recipe_stats(response: Response):
    """Return one internally consistent registry snapshot and coarse usage."""
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    db = await get_db_connection()
    try:
        snapshot = await build_registry_snapshot(db)

        # Access & Agent Activity Metrics
        cursor = await db.execute("SELECT COUNT(*) as calls FROM access_logs WHERE source_type = 'mcp_call'")
        total_mcp_calls = (await cursor.fetchone())["calls"]

        cursor = await db.execute("SELECT user_agent_summary, COUNT(*) as count FROM access_logs GROUP BY user_agent_summary")
        agent_breakdown: dict[str, int] = {}
        for row in await cursor.fetchall():
            category = summarize_user_agent(row["user_agent_summary"])
            agent_breakdown[category] = agent_breakdown.get(category, 0) + row["count"]
        agent_breakdown = dict(sorted(agent_breakdown.items()))

        # Go-Gate 10 Anti-Leakage: Never expose raw query strings in public telemetry
        cursor = await db.execute("SELECT source_type, action, user_agent_summary, created_at FROM access_logs ORDER BY id DESC LIMIT 10")
        recent_activity = [
            {
                "type": summarize_source(r["source_type"]),
                "action": summarize_action(r["action"]),
                "client": summarize_user_agent(r["user_agent_summary"]),
                "timestamp": r["created_at"]
            }
            for r in await cursor.fetchall()
        ]

        return {
            # Compatibility keys retain their names while their values now
            # come from the same validated snapshot as the list and Ops UI.
            "totalRecipes": snapshot.total,
            "verifiedRecipes": snapshot.evidence_qualified_curated,
            "goldenBundles": snapshot.curated,
            "draftRecipes": snapshot.drafts,
            "runtimes": snapshot.by_runtime,
            # Explicit orthogonal taxonomy for new clients.
            "curatedBundles": snapshot.curated,
            "evidenceQualifiedCurated": snapshot.evidence_qualified_curated,
            "unverifiedCurated": (
                snapshot.curated - snapshot.evidence_qualified_curated
            ),
            "failedRecipes": snapshot.failed,
            "invalidRecords": snapshot.invalid_records,
            "recordClassCounts": {
                "CURATED": snapshot.curated,
                "DRAFT": snapshot.drafts,
                "FAILED": snapshot.failed,
            },
            "evidenceStatusCounts": snapshot.evidence_statuses,
            "agentUsage": {
                "totalMcpCalls": total_mcp_calls,
                "agentBreakdown": agent_breakdown,
                "recentActivity": recent_activity
            }
        }
    finally:
        await db.close()


STOPWORDS = {
    "the", "was", "has", "been", "and", "for", "with", "from", "that", "this", 
    "use", "instead", "you", "tried", "access", "error", "warning", "exception",
    "cannot", "could", "not", "module", "object", "type", "value", "out", "while",
    "when", "into", "over", "time", "timed", "mode", "render", "rendering",
    "passed", "instead", "only", "must", "should", "some", "like", "such", "than",
    "after", "failed", "processing", "unrelated", "while"
}

KNOWN_PACKAGES = {
    "numpy", "pandas", "sqlalchemy", "pydantic", "fastapi", "httpx", "express", "next", 
    "tokio", "pytest", "docker", "compose", "typescript", "duckdb", "mysql", 
    "sqlite", "react", "vite", "flask", "django", "openai"
}

PACKAGE_ALIASES = {
    "dataframe": "pandas",
    "series": "pandas",
    "read_csv": "pandas",
    "read_parquet": "pandas",
    "basemodel": "pydantic"
}


def _normalise_package_versions(
    packages: Optional[dict[str, str]],
) -> dict[str, str]:
    if not packages:
        return {}
    return {str(name).lower(): version for name, version in packages.items()}


def _recipe_package_names(recipe: VerifiedRecipe) -> set[str]:
    searchable = " ".join(
        (
            recipe.id.lower(),
            recipe.problem.errorSignature.lower(),
            recipe.problem.description.lower(),
        )
    )
    names = {package for package in KNOWN_PACKAGES if package in searchable}
    for symbol, package in PACKAGE_ALIASES.items():
        if symbol in searchable:
            names.add(package)
    return names


def recipe_matches_requested_evidence_versions(
    recipe: VerifiedRecipe,
    packages: Optional[dict[str, str]],
    *,
    require_explicit: bool = False,
) -> bool:
    """Keep run-bound evidence scoped to its exact observed package release."""
    requested = _normalise_package_versions(packages)
    if not requested:
        return not require_explicit

    relevant = set(requested).intersection(_recipe_package_names(recipe))
    if not relevant:
        return False

    observed = {
        str(name).lower(): version
        for name, version in recipe.evidence.toolchainVersions.items()
    }
    return all(
        VersionMatcher.matches_exact_observed_version(
            requested[package], observed.get(package)
        )
        for package in relevant
    )


@router.post("/api/v1/recipes/search", response_model=List[VerifiedRecipe])
async def search_recipes(req: RecipeSearchRequest):
    """High-precision search for verified solutions with exact whole-word scoring and package relevance."""
    clean_error = ZeroPiiSanitizer.sanitize_text(req.errorSignature.strip()).lower()
    raw_tokens = [w.strip(".:(),'\"`") for w in clean_error.split()]
    meaningful_tokens = [t for t in raw_tokens if len(t) > 3 and t not in STOPWORDS]
    
    # Detect target packages from query and symbol aliases
    query_packages = {t for t in raw_tokens if t in KNOWN_PACKAGES}
    for t in raw_tokens:
        if t in PACKAGE_ALIASES:
            query_packages.add(PACKAGE_ALIASES[t])
            
    requested_package_versions = _normalise_package_versions(req.packages)
    query_packages.update(requested_package_versions)

    snapshot = await build_registry_snapshot()
    from app.core.signature_matcher import SignatureMatcher

    scored_recipes = []
    for entry in snapshot.entries:
        recipe_obj = entry.recipe
        if entry.evidence_status != "VERIFIED":
            continue
        if req.runtime and recipe_obj.problem.runtime.lower() != req.runtime.lower():
            continue

        sig = recipe_obj.problem.errorSignature
        desc = recipe_obj.problem.description.lower()
        rec_id = recipe_obj.id.lower()

        # Package-Specific Relevance
        recipe_packages = _recipe_package_names(recipe_obj)

        if query_packages and not query_packages.intersection(recipe_packages):
            continue
        if req.packages and not recipe_matches_requested_evidence_versions(
            recipe_obj, req.packages
        ):
            continue

        is_matched, match_conf = SignatureMatcher.compute_match(
            req.errorSignature, sig
        )
        if not is_matched or match_conf < 0.70:
            continue

        score = match_conf * 1000.0 + 100.0
        scored_recipes.append((score, recipe_obj))

    scored_recipes.sort(key=lambda x: x[0], reverse=True)
    if not scored_recipes:
        return []

    top_score = scored_recipes[0][0]
    filtered = [r for score, r in scored_recipes if score >= (top_score * 0.6)]
    return filtered[:req.limit]


async def store_recipe_draft(req: RecipeSubmitRequest) -> VerifiedRecipe:
    """Sanitize and persist a public submission as DRAFT without executing its code."""
    recipe_id = req.id or f"rec_{uuid.uuid4().hex[:12]}"
    if recipe_id.startswith("bundle_"):
        raise HTTPException(status_code=422, detail="The bundle_ namespace is reserved for curated bundles")
    if not RECIPE_ID_PATTERN.fullmatch(recipe_id):
        raise HTTPException(
            status_code=422,
            detail="Recipe IDs must start with rec_ and contain only lowercase letters, digits, underscores, or hyphens",
        )

    sanitized_prob = ZeroPiiSanitizer.sanitize_data(req.problem.model_dump())
    sanitized_sol = ZeroPiiSanitizer.sanitize_data(req.solution.model_dump())
    sanitized_repro = ZeroPiiSanitizer.sanitize_data(req.reproduction.model_dump())
    sanitized_source = ZeroPiiSanitizer.sanitize_text(req.primarySource) if req.primarySource else None

    evidence = EvidenceDefinition(
        primarySource=sanitized_source,
        verificationNote="Public submission stored without server-side code execution; independent verification is required.",
    )

    recipe = VerifiedRecipe(
        id=recipe_id,
        problem=ProblemDefinition(**sanitized_prob),
        solution=SolutionDefinition(**sanitized_sol),
        reproduction=ReproductionDefinition(**sanitized_repro),
        evidence=evidence
    )

    db = await get_db_connection()
    try:
        try:
            await db.execute("""
                INSERT INTO recipes (
                    id, runtime, error_signature, problem_json, solution_json,
                    reproduction_json, evidence_json, confidence_score, verification_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                recipe.id,
                recipe.problem.runtime.lower(),
                recipe.problem.errorSignature,
                json.dumps(recipe.problem.model_dump()),
                json.dumps(recipe.solution.model_dump()),
                json.dumps(recipe.reproduction.model_dump()),
                json.dumps(recipe.evidence.model_dump(), default=str),
                0.0,
                "DRAFT",
            ))
            await db.commit()
        except sqlite3.IntegrityError as exc:
            await db.rollback()
            raise HTTPException(status_code=409, detail="A recipe with this ID already exists") from exc
    finally:
        await db.close()
    return recipe


@router.post("/api/v1/recipes/submit", response_model=VerifiedRecipe, status_code=201)
async def submit_recipe(req: RecipeSubmitRequest):
    """Store a sanitized public submission as an unexecuted DRAFT."""
    return await store_recipe_draft(req)


@router.post("/api/v1/recipes/{recipe_id}/verify", response_model=VerifiedRecipe)
async def verify_recipe_by_id(recipe_id: str):
    """Fail closed: public requests cannot execute stored community code."""
    raise HTTPException(
        status_code=403,
        detail="Server-side verification of public recipes is disabled; use the controlled bundle verification pipeline",
    )


@router.get("/recipes/{recipe_id}", response_class=HTMLResponse, tags=["Web UI"])
async def get_recipe_html_page(request: Request, recipe_id: str):
    """HTML Web Detail Page with Schema.org JSON-LD for Search Engines & Developers."""
    recipe = await get_recipe_by_id(recipe_id)
    template = jinja_env.get_template("recipe_detail.html")
    html_content = template.render(
        recipe=recipe,
        active_page="",
        canonical_mcp_url=settings.canonical_mcp_url,
    )
    return HTMLResponse(content=html_content)


@router.get("/api/v1/recipes/{recipe_id}", response_model=VerifiedRecipe)
async def get_recipe_by_id(recipe_id: str):
    """Retrieve a record from the same current snapshot used by list and Ops."""
    entry = (await build_registry_snapshot()).find(recipe_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Recipe not found")
    return entry.recipe


@router.get("/api/v1/recipes", response_model=List[VerifiedRecipe])
async def list_recipes(
    response: Response,
    limit: int = Query(200, ge=1, le=1000),
    status: Optional[str] = Query(None)
):
    """List the current registry; filters are applied before the limit."""
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    entries = list((await build_registry_snapshot()).entries)
    if status:
        normalized = status.upper()
        if normalized in {"CURATED", "DRAFT", "FAILED"}:
            entries = [entry for entry in entries if entry.record_class == normalized]
        else:
            entries = [entry for entry in entries if entry.evidence_status == normalized]
    return [entry.recipe for entry in entries[:limit]]
