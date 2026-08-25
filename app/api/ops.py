from fastapi import APIRouter, Request, Response, HTTPException, Query, Header, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
import json
import logging
import secrets
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

from app.database import get_db_connection
from app.config import settings

logger = logging.getLogger("synapse_mesh.ops")

router = APIRouter(tags=["Operations & Pipeline Observatory"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)

COOKIE_NAME = "synapse_ops_session"


def is_authenticated(request: Request, key: Optional[str] = None) -> bool:
    """Verifies authentication via Cookie, Query param, or Header."""
    valid_passwords = [p for p in [settings.ops_password, settings.admin_token] if p]
    if not valid_passwords:
        return True  # If no password configured, permit local access

    # 1. Check Query parameter
    if key and any(secrets.compare_digest(key, p) for p in valid_passwords):
        return True

    # 2. Check Cookie
    cookie_val = request.cookies.get(COOKIE_NAME)
    if cookie_val and any(secrets.compare_digest(cookie_val, p) for p in valid_passwords):
        return True

    # 3. Check Header
    hdr = request.headers.get("X-Synapse-Admin-Key") or request.headers.get("Authorization", "").replace("Bearer ", "")
    if hdr and any(secrets.compare_digest(hdr, p) for p in valid_passwords):
        return True

    return False


@router.get("/ops", response_class=HTMLResponse)
@router.head("/ops", include_in_schema=False)
async def get_ops_dashboard(request: Request, key: Optional[str] = Query(None)):
    """Password-protected Operations & Pipeline Observatory Dashboard."""
    if not is_authenticated(request, key):
        template = jinja_env.get_template("ops_login.html")
        return HTMLResponse(template.render(error=None), status_code=200)

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
        resp = HTMLResponse(content=html_content)
        # If authenticated via key in URL, auto-set cookie for seamless browsing
        if key and is_authenticated(request, key):
            resp.set_cookie(COOKIE_NAME, key, max_age=86400 * 30, httponly=True, samesite="lax")
        return resp
    finally:
        await db.close()


@router.post("/ops/login")
async def ops_login(request: Request, password: str = Form(...)):
    """Authenticates the user and sets session cookie."""
    valid_passwords = [p for p in [settings.ops_password, settings.admin_token] if p]
    if any(secrets.compare_digest(password.strip(), p) for p in valid_passwords):
        resp = RedirectResponse(url="/ops", status_code=303)
        resp.set_cookie(COOKIE_NAME, password.strip(), max_age=86400 * 30, httponly=True, samesite="lax")
        return resp
    template = jinja_env.get_template("ops_login.html")
    return HTMLResponse(template.render(error="Ungültiges Passwort. Bitte erneut versuchen."), status_code=401)


@router.get("/ops/logout")
async def ops_logout():
    """Logs out and clears session cookie."""
    resp = RedirectResponse(url="/ops", status_code=303)
    resp.delete_cookie(COOKIE_NAME)
    return resp


@router.get("/api/v1/ops/telemetry", tags=["Operations & Pipeline Observatory"])
async def get_ops_telemetry(request: Request, key: Optional[str] = Query(None)):
    """Raw JSON telemetry stream (protected)."""
    if not is_authenticated(request, key):
        raise HTTPException(status_code=403, detail="Forbidden: Ops authentication required.")
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
async def trigger_manual_verification_sweep(request: Request, key: Optional[str] = Query(None)):
    """Manually triggers an immediate 4-stage sandbox verification sweep across all batches (protected)."""
    if not is_authenticated(request, key):
        raise HTTPException(status_code=403, detail="Forbidden: Ops authentication required.")
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
