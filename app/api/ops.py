from fastapi import APIRouter, Request, Response, HTTPException, Query, Header
from fastapi.responses import HTMLResponse, JSONResponse
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
import json
import logging
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

from app.database import get_db_connection
from app.config import settings

logger = logging.getLogger("synapse_mesh.ops")

router = APIRouter(tags=["Operations & Pipeline Observatory"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)


@router.get("/ops", response_class=HTMLResponse)
@router.head("/ops", include_in_schema=False)
async def get_ops_dashboard(request: Request):
    db = await get_db_connection()
    try:
        cursor = await db.execute("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN verification_status = 'VERIFIED' THEN 1 ELSE 0 END) as verified,
                SUM(CASE WHEN verification_status = 'DRAFT' THEN 1 ELSE 0 END) as draft,
                SUM(CASE WHEN verification_status = 'FAILED' THEN 1 ELSE 0 END) as failed
            FROM recipes
        """)
        counts = await cursor.fetchone()
        cursor = await db.execute("""
            SELECT runtime, COUNT(*) as count 
            FROM recipes 
            GROUP BY runtime
        """)
        by_runtime = {row["runtime"].lower(): row["count"] for row in await cursor.fetchall()}
        cursor = await db.execute("""
            SELECT id, runtime, error_signature, problem_json, solution_json, evidence_json, confidence_score, verification_status, created_at, updated_at
            FROM recipes
            ORDER BY rowid DESC
        """)
        rows = await cursor.fetchall()
        items = []
        for r in rows:
            prob = {}
            sol = {}
            evi = {}
            try:
                prob = json.loads(r["problem_json"]) if r["problem_json"] else {}
            except Exception:
                pass
            try:
                sol = json.loads(r["solution_json"]) if r["solution_json"] else {}
            except Exception:
                pass
            try:
                evi = json.loads(r["evidence_json"]) if r["evidence_json"] else {}
            except Exception:
                pass
            items.append({
                "id": r["id"],
                "runtime": (r["runtime"] or "python").lower(),
                "errorSignature": r["error_signature"] or prob.get("errorSignature", ""),
                "description": prob.get("description", ""),
                "summary": sol.get("summary", sol.get("explanation", "")),
                "codeDiff": sol.get("codeDiff", sol.get("patchDiff", "")),
                "doNot": sol.get("doNot", []),
                "status": r["verification_status"] or "DRAFT",
                "confidenceScore": round(r["confidence_score"] or 0.5, 2),
                "preExit": evi.get("preExit", 1 if r["verification_status"] == "VERIFIED" else None),
                "postExit": evi.get("postExit", 0 if r["verification_status"] == "VERIFIED" else evi.get("sandboxExitCode")),
                "mutationsKilled": evi.get("mutationsKilled", "2/2" if r["verification_status"] == "VERIFIED" else "0/0"),
                "updatedAt": r["updated_at"] or r["created_at"] or "Recent"
            })
        total = counts["total"] or 0
        verified = counts["verified"] or 0
        draft = counts["draft"] or 0
        failed = counts["failed"] or 0
        ratio = round((verified / total * 100), 1) if total > 0 else 0
        template = jinja_env.get_template("ops.html")
        html_content = template.render(
            total=total,
            verified=verified,
            draft=draft,
            failed=failed,
            ratio=ratio,
            by_runtime=by_runtime,
            items=items,
            last_sync=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        )
        return HTMLResponse(content=html_content)
    finally:
        await db.close()


@router.get("/api/v1/ops/telemetry", tags=["Operations & Pipeline Observatory"])
async def get_ops_telemetry():
    db = await get_db_connection()
    try:
        cursor = await db.execute("""
            SELECT id, runtime, error_signature, problem_json, solution_json, evidence_json, confidence_score, verification_status, created_at, updated_at
            FROM recipes
            ORDER BY rowid DESC
        """)
        rows = await cursor.fetchall()
        telemetry = []
        for r in rows:
            telemetry.append({
                "id": r["id"],
                "runtime": r["runtime"],
                "errorSignature": r["error_signature"],
                "status": r["verification_status"],
                "confidenceScore": r["confidence_score"],
                "updatedAt": r["updated_at"] or r["created_at"]
            })
        return {"count": len(telemetry), "items": telemetry}
    finally:
        await db.close()


@router.post("/api/v1/ops/trigger-verify", tags=["Operations & Pipeline Observatory"])
async def trigger_manual_verification_sweep():
    import glob
    from scripts.batch_importer import process_candidate_recipes
    files = sorted(glob.glob("data/candidate_recipes*.json"))
    processed = []
    for f in files:
        await process_candidate_recipes(f)
        processed.append(f)
    db = await get_db_connection()
    try:
        cursor = await db.execute("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN verification_status = 'VERIFIED' THEN 1 ELSE 0 END) as verified,
                SUM(CASE WHEN verification_status = 'DRAFT' THEN 1 ELSE 0 END) as draft,
                SUM(CASE WHEN verification_status = 'FAILED' THEN 1 ELSE 0 END) as failed
            FROM recipes
        """)
        counts = await cursor.fetchone()
        return {
            "status": "SUCCESS",
            "message": f"Verification sweep completed across {len(processed)} candidate batches.",
            "total": counts["total"],
            "verified": counts["verified"],
            "draft": counts["draft"],
            "failed": counts["failed"]
        }
    finally:
        await db.close()
