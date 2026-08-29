from fastapi import APIRouter, Request, Query, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
import json
import logging
import hashlib
import secrets
import time
from datetime import datetime, timezone
from typing import Optional

from app.database import get_db_connection
from app.config import settings
from app.models.recipe import VERIFIED_EVIDENCE_CONTRACT
from app.core.evidence_contract import (
    recipe_backing_lifecycle,
    recipe_has_recorded_verification_contract,
)
from app.core.registry_snapshot import build_registry_snapshot

logger = logging.getLogger("synapse_mesh.ops")

router = APIRouter(tags=["Operations & Pipeline Observatory"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)

COOKIE_NAME = "synapse_ops_session"
SESSION_KEY_PREFIX = "ops_session:"
SESSION_TTL_SECONDS = 60 * 60
PASSWORD_HASH_ITERATIONS = 310_000


def _effective_ops_status(
    recorded_status: Optional[str],
    recipe_id: str,
    problem: dict,
    solution: dict,
    reproduction: dict,
    evidence: dict,
) -> str:
    """Return the fail-closed status presented by private operations views."""
    if (
        recorded_status == "VERIFIED"
        and recipe_has_recorded_verification_contract(
            recipe_id, problem, solution, reproduction, evidence
        )
    ):
        return "VERIFIED"
    if recorded_status == "VERIFIED":
        lifecycle = recipe_backing_lifecycle(recipe_id)
        if isinstance(lifecycle, dict) and lifecycle.get("status") in {
            "STALE", "BROKEN", "DISPUTED", "SUPERSEDED"
        }:
            return lifecycle["status"]
        return "DRAFT"
    return recorded_status or "UNKNOWN"


def hash_ops_password(raw_pass: str) -> str:
    """Creates a versioned, randomly salted password hash for database storage."""
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        raw_pass.strip().encode("utf-8"),
        bytes.fromhex(salt),
        PASSWORD_HASH_ITERATIONS,
    ).hex()
    return f"pbkdf2_sha256${PASSWORD_HASH_ITERATIONS}${salt}${digest}"


def _legacy_ops_password_hash(raw_pass: str) -> str:
    """Reads the pre-v1 database format only; it is upgraded after a valid login."""
    return hashlib.sha256(
        f"synapse_ops_salt_2026_{raw_pass.strip()}".encode("utf-8")
    ).hexdigest()


def _password_hash_matches(raw_pass: str, encoded_hash: str) -> bool:
    if not raw_pass or not encoded_hash:
        return False
    if encoded_hash.startswith("pbkdf2_sha256$"):
        try:
            algorithm, iterations_text, salt, expected = encoded_hash.split("$", 3)
            if algorithm != "pbkdf2_sha256":
                return False
            iterations = int(iterations_text)
            if iterations < 100_000 or iterations > 2_000_000:
                return False
            candidate = hashlib.pbkdf2_hmac(
                "sha256",
                raw_pass.strip().encode("utf-8"),
                bytes.fromhex(salt),
                iterations,
            ).hex()
            return secrets.compare_digest(candidate, expected)
        except (TypeError, ValueError):
            return False

    # Compatibility with existing database hashes. This is not a fallback
    # credential: it is the single authoritative DB value and is upgraded on login.
    if len(encoded_hash) == 64:
        return secrets.compare_digest(_legacy_ops_password_hash(raw_pass), encoded_hash)
    return False


async def verify_ops_password(db, raw_pass: str) -> bool:
    """Verifies DB credential exclusively, or configured bootstrap secret if absent."""
    if not raw_pass or len(raw_pass) > 1024:
        return False

    cursor = await db.execute("SELECT value FROM system_config WHERE key = 'ops_password_hash'")
    row = await cursor.fetchone()
    if row and row["value"]:
        # A persisted hash is authoritative. Never fall back to an environment
        # credential after password rotation or database provisioning.
        return _password_hash_matches(raw_pass, row["value"])

    bootstrap_secrets = [p.strip() for p in (settings.ops_password, settings.admin_token) if p.strip()]
    return any(secrets.compare_digest(raw_pass.strip(), p) for p in bootstrap_secrets)


def _session_db_key(token: str) -> str:
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return f"{SESSION_KEY_PREFIX}{digest}"


async def _delete_expired_sessions(db) -> None:
    cursor = await db.execute(
        "SELECT key, value FROM system_config WHERE key GLOB ?",
        (f"{SESSION_KEY_PREFIX}*",),
    )
    now = int(time.time())
    expired = []
    for row in await cursor.fetchall():
        try:
            expires_at = int(json.loads(row["value"])["expiresAt"])
        except (TypeError, ValueError, KeyError, json.JSONDecodeError):
            expires_at = 0
        if expires_at <= now:
            expired.append((row["key"],))
    if expired:
        await db.executemany("DELETE FROM system_config WHERE key = ?", expired)


async def create_ops_session(db) -> str:
    """Issues an opaque token; only its SHA-256 digest is persisted server-side."""
    await _delete_expired_sessions(db)
    token = secrets.token_urlsafe(32)
    expires_at = int(time.time()) + SESSION_TTL_SECONDS
    await db.execute(
        """
        INSERT INTO system_config (key, value, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP
        """,
        (_session_db_key(token), json.dumps({"expiresAt": expires_at})),
    )
    await db.commit()
    return token


def ops_cookie_params(token: str) -> dict:
    return {
        "key": COOKIE_NAME,
        "value": token,
        "max_age": SESSION_TTL_SECONDS,
        "httponly": True,
        "secure": True,
        "samesite": "strict",
        "path": "/",
    }


async def session_token_valid(db, token: str) -> bool:
    """Validates only opaque, unexpired sessions recorded server-side."""
    if not token or len(token) > 128:
        return False
    cursor = await db.execute(
        "SELECT value FROM system_config WHERE key = ?", (_session_db_key(token),)
    )
    row = await cursor.fetchone()
    if not row:
        return False
    try:
        expires_at = int(json.loads(row["value"])["expiresAt"])
    except (TypeError, ValueError, KeyError, json.JSONDecodeError):
        expires_at = 0
    if expires_at <= int(time.time()):
        await db.execute("DELETE FROM system_config WHERE key = ?", (_session_db_key(token),))
        await db.commit()
        return False
    return True


async def is_authenticated(request: Request, db) -> bool:
    """Verifies an opaque cookie session or an explicit authorization header."""
    cookie_val = request.cookies.get(COOKIE_NAME)
    if cookie_val and await session_token_valid(db, cookie_val):
        return True

    authorization = request.headers.get("Authorization", "")
    hdr = request.headers.get("X-Synapse-Admin-Key")
    if not hdr and authorization.lower().startswith("bearer "):
        hdr = authorization[7:]
    if hdr and await verify_ops_password(db, hdr):
        return True

    return False


def _no_store(response):
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


async def _persist_or_upgrade_password_hash(db, raw_pass: str) -> None:
    """Pins a bootstrap credential and upgrades the legacy DB hash after login."""
    cursor = await db.execute("SELECT value FROM system_config WHERE key = 'ops_password_hash'")
    row = await cursor.fetchone()
    if row and row["value"].startswith("pbkdf2_sha256$"):
        return
    await db.execute(
        """
        INSERT INTO system_config (key, value, updated_at)
        VALUES ('ops_password_hash', ?, CURRENT_TIMESTAMP)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP
        """,
        (hash_ops_password(raw_pass),),
    )
    await db.commit()


@router.get("/ops", response_class=HTMLResponse)
@router.head("/ops", include_in_schema=False)
async def get_ops_dashboard(
    request: Request,
    msg: Optional[str] = Query(None),
    err: Optional[str] = Query(None)
):
    """Password-protected Operations & Pipeline Observatory Dashboard."""
    db = await get_db_connection()
    try:
        if not await is_authenticated(request, db):
            template = jinja_env.get_template("ops_login.html")
            return _no_store(HTMLResponse(template.render(error=None), status_code=200))

        snapshot = await build_registry_snapshot(db)
        items = [entry.as_ops_item() for entry in snapshot.entries]
        ratio = (
            round(snapshot.evidence_qualified_curated / snapshot.curated * 100, 1)
            if snapshot.curated
            else 0
        )
        template = jinja_env.get_template("ops.html")
        html_content = template.render(
            total=snapshot.total,
            curated=snapshot.curated,
            verified=snapshot.evidence_qualified_curated,
            unverified_curated=(
                snapshot.curated - snapshot.evidence_qualified_curated
            ),
            draft=snapshot.drafts,
            failed=snapshot.failed,
            invalid_records=snapshot.invalid_records,
            ratio=ratio,
            by_runtime=snapshot.by_runtime,
            items=items,
            snapshot_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            msg=msg,
            err=err
        )
        return _no_store(HTMLResponse(content=html_content))
    finally:
        await db.close()


@router.post("/ops/login")
async def ops_login(request: Request, password: str = Form(...)):
    """Authenticates the user and sets session cookie."""
    db = await get_db_connection()
    try:
        if await verify_ops_password(db, password):
            await _persist_or_upgrade_password_hash(db, password)
            token = await create_ops_session(db)
            resp = _no_store(RedirectResponse(url="/ops", status_code=303))
            resp.set_cookie(**ops_cookie_params(token))
            return resp
        template = jinja_env.get_template("ops_login.html")
        return _no_store(HTMLResponse(template.render(error="Invalid password. Please try again."), status_code=401))
    finally:
        await db.close()


@router.post("/ops/change-password")
async def ops_change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...)
):
    """Allows authenticated user to change the ops dashboard password directly."""
    db = await get_db_connection()
    try:
        if not await is_authenticated(request, db) or not await verify_ops_password(db, current_password):
            return _no_store(RedirectResponse(url="/ops?err=Current+password+is+invalid", status_code=303))

        if new_password != confirm_password:
            return _no_store(RedirectResponse(url="/ops?err=New+passwords+do+not+match", status_code=303))

        if len(new_password.strip()) < 12:
            return _no_store(RedirectResponse(url="/ops?err=New+password+must+be+at+least+12+characters+long", status_code=303))

        # Store the new hash and revoke every pre-rotation session.
        new_hash = hash_ops_password(new_password)
        await db.execute("""
            INSERT INTO system_config (key, value, updated_at) 
            VALUES ('ops_password_hash', ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP
        """, (new_hash,))
        await db.execute(
            "DELETE FROM system_config WHERE key GLOB ?", (f"{SESSION_KEY_PREFIX}*",)
        )
        await db.commit()

        token = await create_ops_session(db)
        resp = _no_store(RedirectResponse(url="/ops?msg=Password+successfully+updated", status_code=303))
        resp.set_cookie(**ops_cookie_params(token))
        return resp
    finally:
        await db.close()


@router.post("/ops/logout")
async def ops_logout(request: Request):
    """Logs out and clears session cookie."""
    token = request.cookies.get(COOKIE_NAME)
    if token:
        db = await get_db_connection()
        try:
            await db.execute("DELETE FROM system_config WHERE key = ?", (_session_db_key(token),))
            await db.commit()
        finally:
            await db.close()
    resp = _no_store(RedirectResponse(url="/ops", status_code=303))
    resp.delete_cookie(COOKIE_NAME, path="/", secure=True, httponly=True, samesite="strict")
    return resp


@router.get("/api/v1/ops/telemetry", tags=["Operations & Pipeline Observatory"])
async def get_ops_telemetry(request: Request):
    """Raw JSON telemetry stream (protected)."""
    db = await get_db_connection()
    try:
        if not await is_authenticated(request, db):
            return _no_store(JSONResponse({"detail": "Forbidden: Ops authentication required."}, status_code=403))
        snapshot = await build_registry_snapshot(db)
        telemetry = [entry.as_ops_item() for entry in snapshot.entries]
        return _no_store(
            JSONResponse(
                {
                    "count": snapshot.total,
                    "recordClassCounts": {
                        "CURATED": snapshot.curated,
                        "DRAFT": snapshot.drafts,
                        "FAILED": snapshot.failed,
                    },
                    "evidenceQualifiedCurated": snapshot.evidence_qualified_curated,
                    "invalidRecords": snapshot.invalid_records,
                    "items": telemetry,
                }
            )
        )
    finally:
        await db.close()


@router.post("/api/v1/ops/trigger-verify", tags=["Operations & Pipeline Observatory"])
async def trigger_manual_verification_sweep(request: Request):
    """Fail closed instead of running code inside an HTTP request worker."""
    db = await get_db_connection()
    try:
        if not await is_authenticated(request, db):
            return _no_store(JSONResponse({"detail": "Forbidden: Ops authentication required."}, status_code=403))
        return _no_store(JSONResponse(
            {
                "status": "DISABLED",
                "detail": (
                    "Synchronous server-side verification is disabled. The autonomous worker "
                    "continues source discovery and draft maintenance; hostile-code verification "
                    "requires a dedicated isolated job runner."
                ),
            },
            status_code=503,
        ))
    finally:
        await db.close()
