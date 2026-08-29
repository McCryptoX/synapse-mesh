import aiosqlite
import json
import logging
from collections import Counter
from pathlib import Path
from typing import Any
from app.config import settings
from app.models.recipe import VERIFIED_EVIDENCE_CONTRACT
from app.core.evidence_contract import recipe_has_recorded_verification_contract
from app.core.telemetry_categories import (
    summarize_action,
    summarize_source,
    summarize_user_agent,
)

logger = logging.getLogger("synapse_mesh.database")
GOLDEN_BUNDLES_DIR = Path(__file__).resolve().parent.parent / "bundles" / "golden"


def _load_golden_bundles() -> list[tuple[Path, dict[str, Any]]]:
    bundles: list[tuple[Path, dict[str, Any]]] = []
    if not GOLDEN_BUNDLES_DIR.exists():
        return bundles
    for fpath in sorted(GOLDEN_BUNDLES_DIR.glob("*.json")):
        try:
            data = json.loads(fpath.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("bundleId"), str):
                bundles.append((fpath, data))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Golden bundle %s could not be loaded: %s", fpath.name, type(exc).__name__)
    id_counts = Counter(bundle["bundleId"] for _, bundle in bundles)
    duplicate_ids = sorted(bundle_id for bundle_id, count in id_counts.items() if count > 1)
    if duplicate_ids:
        logger.error(
            "Ambiguous duplicate Golden bundle IDs were excluded: %s",
            ", ".join(duplicate_ids),
        )
    return [
        (bundle_path, bundle)
        for bundle_path, bundle in bundles
        if id_counts[bundle["bundleId"]] == 1
    ]


def _golden_evidence(bundle: dict[str, Any], bundle_path: Path) -> tuple[dict[str, Any], str, float]:
    provenance = bundle.get("provenance") or {}
    primary_sources = provenance.get("primarySources") or []
    from app.core.run_artifacts import load_valid_run_artifact
    from app.core.evidence_lifecycle import evaluate_evidence_lifecycle

    artifact = load_valid_run_artifact(bundle, bundle_path)
    lifecycle = evaluate_evidence_lifecycle(bundle, artifact)
    contract_ready = lifecycle["qualified"] is True
    artifact_available = artifact is not None
    status = lifecycle["status"]
    # The contract is a categorical gate, not a calibrated probability.
    confidence = 0.0

    toolchain: dict[str, str] = {}
    pre_exit = -1
    post_exit = -1
    mutation_count = len((bundle.get("verification") or {}).get("mutations") or [])
    completed_at = None
    if artifact_available:
        stages = artifact["stages"]
        pre_exit = stages["pre"]["exitCode"]
        post_exit = stages["post"]["exitCode"]
        mutation_count = len(stages["mutations"])
        completed_at = artifact["completedAt"]
        toolchain = {
            str(name): str(version)
            for name, version in artifact["toolchainVersions"].items()
        }

    badges = ["BUNDLE_4_STAGE_CONTRACT"] if artifact_available else []
    if artifact_available and not contract_ready:
        badges.append(f"EVIDENCE_{status}")
    if primary_sources:
        badges.append("SOURCE_BACKED")

    evidence = {
        "verificationStatus": status,
        "evidenceContract": VERIFIED_EVIDENCE_CONTRACT if artifact_available else None,
        "verificationNote": lifecycle["reason"],
        "lastTestedAt": completed_at,
        "sandboxExitCode": post_exit if artifact_available and isinstance(post_exit, int) else -1,
        # Bundle metadata records a suite, but not an assertion count. Do not invent one.
        "passedTests": 0,
        "totalTests": 0,
        "confidenceScore": None,
        "primarySource": primary_sources[0] if primary_sources else None,
        "preExit": pre_exit if artifact_available and isinstance(pre_exit, int) else -1,
        "postExit": post_exit if artifact_available and isinstance(post_exit, int) else -1,
        "mutationsKilled": (
            f"{mutation_count}/{mutation_count}"
            if artifact_available
            else f"0/{mutation_count}"
        ),
        "toolchainVersions": toolchain,
        "badges": badges,
        # Recorded evidence has no independently verifiable run-bound isolation
        # artifact. Do not inherit historical isolation labels into SQLite.
        "isolationProfile": {},
    }
    return evidence, status, confidence


async def _apply_fail_closed_migrations(
    db: aiosqlite.Connection,
    golden_ids: set[str],
) -> tuple[int, int, int, int]:
    """Erase legacy query text and quarantine unsupported historical VERIFIED claims."""
    retention_cursor = await db.execute(
        "DELETE FROM access_logs WHERE created_at < datetime('now', '-30 days')"
    )
    purged_access_logs = max(retention_cursor.rowcount, 0)
    privacy_cursor = await db.execute(
        "UPDATE access_logs SET query_snippet = '' WHERE COALESCE(query_snippet, '') <> ''"
    )
    cleared_queries = max(privacy_cursor.rowcount, 0)

    # Older deployments stored labels that could still contain product names,
    # versions, or crawler fingerprints. Rewrite every row through the same
    # finite coarse categoriser used by current writes.
    cursor = await db.execute(
        "SELECT id, source_type, action, user_agent_summary FROM access_logs"
    )
    telemetry_updates = []
    for row in await cursor.fetchall():
        row_id, source_type, action, user_agent_summary = row
        coarse_source = summarize_source(source_type)
        coarse_action = summarize_action(action)
        coarse_client = summarize_user_agent(user_agent_summary)
        if (
            coarse_source != source_type
            or coarse_action != action
            or coarse_client != user_agent_summary
        ):
            telemetry_updates.append(
                (coarse_source, coarse_action, coarse_client, row_id)
            )
    if telemetry_updates:
        await db.executemany(
            """
            UPDATE access_logs
            SET source_type = ?, action = ?, user_agent_summary = ?
            WHERE id = ?
            """,
            telemetry_updates,
        )

    cursor = await db.execute(
        """SELECT id, problem_json, solution_json, reproduction_json, evidence_json
           FROM recipes WHERE verification_status = 'VERIFIED'"""
    )
    quarantined = 0
    for row in await cursor.fetchall():
        recipe_id = row[0]
        try:
            problem = json.loads(row[1]) if row[1] else {}
            solution = json.loads(row[2]) if row[2] else {}
            reproduction = json.loads(row[3]) if row[3] else {}
            evidence = json.loads(row[4]) if row[4] else {}
        except (TypeError, json.JSONDecodeError):
            problem = solution = reproduction = evidence = {}
        if recipe_has_recorded_verification_contract(
            recipe_id, problem, solution, reproduction, evidence
        ):
            continue

        evidence.update(
            {
                "verificationStatus": "DRAFT",
                "evidenceContract": None,
                "verificationNote": "Historical record quarantined: no current four-stage evidence contract was recorded.",
                "sandboxExitCode": -1,
                "passedTests": 0,
                "totalTests": 0,
                "confidenceScore": None,
                "preExit": -1,
                "postExit": -1,
                "mutationsKilled": "0/0",
                "badges": [],
                "isolationProfile": {},
            }
        )
        await db.execute(
            """
            UPDATE recipes
            SET evidence_json = ?, confidence_score = 0.0,
                verification_status = 'DRAFT', updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (json.dumps(evidence, default=str), recipe_id),
        )
        quarantined += 1
    return purged_access_logs, cleared_queries, quarantined, len(telemetry_updates)


async def get_db_connection() -> aiosqlite.Connection:
    db = await aiosqlite.connect(settings.db_path)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA foreign_keys=ON;")
    await db.execute("PRAGMA busy_timeout=5000;")
    return db


async def init_db():
    """Initializes SQLite database schema with indexes and privacy-preserving analytics."""
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.execute("PRAGMA synchronous=NORMAL;")
        
        # Recipes Table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS recipes (
                id TEXT PRIMARY KEY,
                runtime TEXT NOT NULL,
                error_signature TEXT NOT NULL,
                problem_json TEXT NOT NULL,
                solution_json TEXT NOT NULL,
                reproduction_json TEXT NOT NULL,
                evidence_json TEXT NOT NULL,
                confidence_score REAL NOT NULL DEFAULT 0.0,
                verification_status TEXT NOT NULL DEFAULT 'DRAFT',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        # Zero-PII Analytics & Agent Access Log
        await db.execute("""
            CREATE TABLE IF NOT EXISTS access_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_type TEXT NOT NULL, -- 'mcp_call', 'api_search', 'discovery', 'web_view'
                action TEXT NOT NULL,      -- 'find_solution', 'submit_solution', etc.
                query_snippet TEXT,
                user_agent_summary TEXT,   -- 'Claude-Desktop', 'Cursor', 'Python-httpx', 'Browser'
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # System Config (Persistent Ops Passwords & Dynamic Settings)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS system_config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        await db.execute("CREATE INDEX IF NOT EXISTS idx_recipes_runtime ON recipes(runtime);")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_recipes_status ON recipes(verification_status);")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_access_logs_type ON access_logs(source_type);")
        await db.commit()

        golden_bundles = _load_golden_bundles()
        golden_ids = {bundle["bundleId"] for _, bundle in golden_bundles}
        (
            purged_access_logs,
            cleared_queries,
            quarantined,
            coarsened_telemetry,
        ) = await _apply_fail_closed_migrations(db, golden_ids)

        # Sync curated bundles without fabricating test counts or isolation claims.
        for fpath, b in golden_bundles:
            try:
                bid = b["bundleId"]
                verification = b.get("verification") or {}
                patch = b.get("patch") or {}
                scope = b.get("scope") or {}
                fingerprint = b.get("fingerprint") or {}
                prob = {
                    "errorSignature": fingerprint["errorSignature"],
                    "runtime": scope["runtime"],
                    "packages": patch.get("pinnedDependencies") or {},
                    "description": b["description"],
                }
                sol = {
                    "summary": b["description"],
                    "codeDiff": patch.get("unifiedDiff"),
                    "patchDiff": patch.get("unifiedDiff"),
                    "instructions": [],
                    "pinnedDependencies": patch.get("pinnedDependencies") or {},
                    "doNot": patch.get("doNot") or [],
                }
                repro = {
                    "script": verification.get("reproductionScript", ""),
                    "testSuite": verification.get("testSuite", ""),
                }
                evidence, status, confidence = _golden_evidence(b, fpath)
                await db.execute("""
                    INSERT INTO recipes (id, runtime, error_signature, problem_json, solution_json, reproduction_json, evidence_json, confidence_score, verification_status, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(id) DO UPDATE SET
                        runtime = excluded.runtime,
                        error_signature = excluded.error_signature,
                        problem_json = excluded.problem_json,
                        solution_json = excluded.solution_json,
                        reproduction_json = excluded.reproduction_json,
                        evidence_json = excluded.evidence_json,
                        confidence_score = excluded.confidence_score,
                        verification_status = excluded.verification_status,
                        updated_at = CURRENT_TIMESTAMP
                """, (
                    bid,
                    scope["runtime"],
                    fingerprint["errorSignature"],
                    json.dumps(prob),
                    json.dumps(sol),
                    json.dumps(repro),
                    json.dumps(evidence),
                    confidence,
                    status,
                ))
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning("Golden bundle %s was not synchronized: %s", fpath.name, type(exc).__name__)
        await db.commit()

        logger.info(
            "Database initialized at %s; %d access logs older than 30 days purged, %d legacy query snippets cleared, %d telemetry rows coarsened, %d unsupported VERIFIED records quarantined, %d golden bundles synchronized.",
            settings.db_path,
            purged_access_logs,
            cleared_queries,
            coarsened_telemetry,
            quarantined,
            len(golden_bundles),
        )
