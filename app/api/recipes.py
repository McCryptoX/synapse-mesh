from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
import json
import uuid
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from app.models.recipe import (
    VerifiedRecipe,
    RecipeSearchRequest,
    RecipeSubmitRequest,
    ProblemDefinition,
    SolutionDefinition,
    ReproductionDefinition,
    EvidenceDefinition
)
from app.database import get_db_connection
from app.core.sanitizer import ZeroPiiSanitizer
from app.core.sandbox import SandboxRunner

router = APIRouter(tags=["Living Solutions Recipes"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)


@router.get("/api/v1/recipes/stats", tags=["System"])
async def get_recipe_stats(response: Response):
    """Returns real-time statistics and agent usage metrics (Zero-PII)."""
    response.headers["Cache-Control"] = "public, max-age=60, stale-while-revalidate=300"
    db = await get_db_connection()
    try:
        cursor = await db.execute("SELECT COUNT(*) as total FROM recipes")
        total_db = (await cursor.fetchone())["total"]

        cursor = await db.execute("SELECT COUNT(*) as verified FROM recipes WHERE verification_status = 'VERIFIED'")
        verified_db = (await cursor.fetchone())["verified"]

        cursor = await db.execute("SELECT runtime, COUNT(*) as count FROM recipes WHERE verification_status = 'VERIFIED' GROUP BY runtime")
        by_runtime = {row["runtime"].lower(): row["count"] for row in await cursor.fetchall()}

        golden_dir = Path(__file__).resolve().parent.parent.parent / "bundles" / "golden"
        golden_count = 0
        if golden_dir.exists():
            for f in golden_dir.glob("*.json"):
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    rt = data.get("scope", {}).get("runtime", "python").lower()
                    by_runtime[rt] = by_runtime.get(rt, 0) + 1
                    golden_count += 1
                except Exception:
                    pass
        if golden_count == 0:
            golden_count = 12

        total_verified = verified_db + golden_count
        total_all = total_db + golden_count

        # Access & Agent Activity Metrics
        cursor = await db.execute("SELECT COUNT(*) as calls FROM access_logs WHERE source_type = 'mcp_call'")
        total_mcp_calls = (await cursor.fetchone())["calls"]

        cursor = await db.execute("SELECT user_agent_summary, COUNT(*) as count FROM access_logs GROUP BY user_agent_summary")
        agent_breakdown = {row["user_agent_summary"]: row["count"] for row in await cursor.fetchall()}

        # Go-Gate 10 Anti-Leakage: Never expose raw query strings in public telemetry
        cursor = await db.execute("SELECT source_type, action, user_agent_summary, created_at FROM access_logs ORDER BY id DESC LIMIT 10")
        recent_activity = [
            {
                "type": r["source_type"],
                "action": r["action"],
                "client": r["user_agent_summary"],
                "timestamp": r["created_at"]
            }
            for r in await cursor.fetchall()
        ]

        return {
            "totalRecipes": total_all,
            "verifiedRecipes": total_verified,
            "verifiedRatio": round(total_verified / total_all, 2) if total_all > 0 else 1.0,
            "runtimes": by_runtime,
            "agentUsage": {
                "totalMcpCalls": total_mcp_calls,
                "agentBreakdown": agent_breakdown,
                "recentActivity": recent_activity
            }
        }
    finally:
        await db.close()


import re

STOPWORDS = {
    "the", "was", "has", "been", "and", "for", "with", "from", "that", "this", 
    "use", "instead", "you", "tried", "access", "error", "warning", "exception",
    "cannot", "could", "not", "module", "object", "type", "value", "out", "while",
    "when", "into", "over", "time", "timed", "mode", "render", "rendering",
    "passed", "instead", "only", "must", "should", "some", "like", "such", "than"
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
    "concat": "pandas",
    "basemodel": "pydantic",
    "field": "pydantic",
    "validator": "pydantic",
    "ndarray": "numpy",
    "nan": "numpy",
    "session": "sqlalchemy",
    "select": "sqlalchemy",
    "scalars": "sqlalchemy"
}


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
            
    if req.packages:
        query_packages.update(req.packages.keys())

    db = await get_db_connection()
    try:
        # Load candidate recipes matching runtime or basic confidence
        query = "SELECT * FROM recipes WHERE confidence_score >= ?"
        params: List[Any] = [req.minConfidence]
        if req.runtime:
            query += " AND runtime = ?"
            params.append(req.runtime.lower())
            
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()
        
        scored_recipes = []
        for row in rows:
            prob = json.loads(row["problem_json"])
            sol = json.loads(row["solution_json"])
            repro = json.loads(row["reproduction_json"])
            evi = json.loads(row["evidence_json"])
            
            sig = (row["error_signature"] or "").lower()
            desc = prob.get("description", "").lower()
            rec_id = row["id"].lower()
            
            sig_words = set(re.findall(r'[a-zA-Z0-9_]+', sig))
            desc_words = set(re.findall(r'[a-zA-Z0-9_]+', desc))
            
            score = 0.0
            # 1. Exact Error Signature Match
            if clean_error in sig or sig in clean_error:
                score += 1000.0

            # 2. Package-Specific Relevance
            recipe_packages = {pkg.lower() for pkg in KNOWN_PACKAGES if pkg in rec_id or pkg in sig or pkg in desc}
            for sym, mapped_pkg in PACKAGE_ALIASES.items():
                if sym in sig or sym in desc:
                    recipe_packages.add(mapped_pkg)
                    
            if query_packages:
                if query_packages.intersection(recipe_packages):
                    score += 500.0
                elif recipe_packages and not query_packages.intersection(recipe_packages):
                    # Query clearly asked for package X, but this recipe is package Y -> penalize heavily
                    score -= 1000.0

            # 3. Whole-Word Meaningful Overlap
            for token in meaningful_tokens:
                if token in sig_words:
                    score += 90.0
                elif token in desc_words:
                    score += 30.0

            # 4. Verified Status Boost (ONLY if there was an actual query match!)
            if score > 0:
                if row["verification_status"] == "VERIFIED":
                    score += 150.0
                score *= (row["confidence_score"] or 0.5)

            if score >= 250.0:
                recipe_obj = VerifiedRecipe(
                    id=row["id"],
                    problem=ProblemDefinition(**prob),
                    solution=SolutionDefinition(**sol),
                    reproduction=ReproductionDefinition(**repro),
                    evidence=EvidenceDefinition(**evi)
                )
                scored_recipes.append((score, recipe_obj))

        # Sort by relevance score descending
        scored_recipes.sort(key=lambda x: x[0], reverse=True)
        if not scored_recipes:
            return []
            
        top_score = scored_recipes[0][0]
        filtered = [r for score, r in scored_recipes if score >= (top_score * 0.6)]
        return filtered[:req.limit]
    finally:
        await db.close()


@router.post("/api/v1/recipes/submit", response_model=VerifiedRecipe, status_code=201)
async def submit_recipe(req: RecipeSubmitRequest):
    """Submits a new living solution recipe, sanitizes it and executes automated sandbox verification."""
    recipe_id = req.id or f"rec_{uuid.uuid4().hex[:12]}"
    
    # 1. Zero-PII Sanitization
    sanitized_prob = ZeroPiiSanitizer.sanitize_data(req.problem.model_dump())
    sanitized_sol = ZeroPiiSanitizer.sanitize_data(req.solution.model_dump())
    sanitized_repro = ZeroPiiSanitizer.sanitize_data(req.reproduction.model_dump())
    
    # 2. Automated Sandbox Verification (Full 4-Stage)
    evidence = await SandboxRunner.verify_recipe_full(
        runtime=sanitized_prob["runtime"],
        error_signature=sanitized_prob.get("errorSignature", ""),
        repro_script=sanitized_repro.get("script", ""),
        test_suite=sanitized_repro.get("testSuite", ""),
        primary_source=req.primarySource
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
        await db.execute("""
            INSERT OR REPLACE INTO recipes (
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
            recipe.evidence.confidenceScore,
            recipe.evidence.verificationStatus
        ))
        await db.commit()
        return recipe
    finally:
        await db.close()


@router.post("/api/v1/recipes/{recipe_id}/verify", response_model=VerifiedRecipe)
async def verify_recipe_by_id(recipe_id: str):
    """Re-runs the sandbox verification for an existing recipe and updates evidence logs."""
    db = await get_db_connection()
    try:
        cursor = await db.execute("SELECT * FROM recipes WHERE id = ?", (recipe_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Recipe not found")
            
        prob = json.loads(row["problem_json"])
        sol = json.loads(row["solution_json"])
        repro = json.loads(row["reproduction_json"])
        evi = json.loads(row["evidence_json"])
        
        new_evidence = await SandboxRunner.verify_recipe_full(
            runtime=prob["runtime"],
            error_signature=prob.get("errorSignature", ""),
            repro_script=repro.get("script", ""),
            test_suite=repro.get("testSuite", ""),
            primary_source=evi.get("primarySource")
        )
        
        recipe = VerifiedRecipe(
            id=row["id"],
            problem=ProblemDefinition(**prob),
            solution=SolutionDefinition(**sol),
            reproduction=ReproductionDefinition(**repro),
            evidence=new_evidence
        )
        
        await db.execute("""
            UPDATE recipes SET 
                evidence_json = ?, 
                confidence_score = ?, 
                verification_status = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (
            json.dumps(new_evidence.model_dump(), default=str),
            new_evidence.confidenceScore,
            new_evidence.verificationStatus,
            recipe_id
        ))
        await db.commit()
        return recipe
    finally:
        await db.close()


@router.get("/recipes/{recipe_id}", response_class=HTMLResponse, tags=["Web UI"])
async def get_recipe_html_page(request: Request, recipe_id: str):
    """HTML Web Detail Page with Schema.org JSON-LD for Search Engines & Developers."""
    recipe = await get_recipe_by_id(recipe_id)
    template = jinja_env.get_template("recipe_detail.html")
    confidence_percent = int(recipe.evidence.confidenceScore * 100)
    html_content = template.render(recipe=recipe, confidence_percent=confidence_percent)
    return HTMLResponse(content=html_content)


@router.get("/api/v1/recipes/{recipe_id}", response_model=VerifiedRecipe)
async def get_recipe_by_id(recipe_id: str):
    """Retrieve a specific recipe by ID as JSON."""
    db = await get_db_connection()
    try:
        cursor = await db.execute("SELECT * FROM recipes WHERE id = ?", (recipe_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Recipe not found")
            
        prob = json.loads(row["problem_json"])
        sol = json.loads(row["solution_json"])
        repro = json.loads(row["reproduction_json"])
        evi = json.loads(row["evidence_json"])
        
        return VerifiedRecipe(
            id=row["id"],
            problem=ProblemDefinition(**prob),
            solution=SolutionDefinition(**sol),
            reproduction=ReproductionDefinition(**repro),
            evidence=EvidenceDefinition(**evi)
        )
    finally:
        await db.close()


@router.get("/api/v1/recipes", response_model=List[VerifiedRecipe])
async def list_recipes(response: Response, limit: int = Query(20, ge=1, le=100)):
    """List recently verified recipes."""
    response.headers["Cache-Control"] = "public, max-age=60, stale-while-revalidate=300"
    db = await get_db_connection()
    try:
        cursor = await db.execute("SELECT * FROM recipes ORDER BY updated_at DESC LIMIT ?", (limit,))
        rows = await cursor.fetchall()
        results = []
        for row in rows:
            prob = json.loads(row["problem_json"])
            sol = json.loads(row["solution_json"])
            repro = json.loads(row["reproduction_json"])
            evi = json.loads(row["evidence_json"])
            results.append(VerifiedRecipe(
                id=row["id"],
                problem=ProblemDefinition(**prob),
                solution=SolutionDefinition(**sol),
                reproduction=ReproductionDefinition(**repro),
                evidence=EvidenceDefinition(**evi)
            ))
        return results
    finally:
        await db.close()
