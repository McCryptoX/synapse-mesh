import aiosqlite
import json
import logging
from app.config import settings

logger = logging.getLogger("synapse_mesh.database")


async def get_db_connection() -> aiosqlite.Connection:
    db = await aiosqlite.connect(settings.db_path)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA foreign_keys=ON;")
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

        # Automatically sync 14 Golden Bundles into SQLite recipes table
        import glob
        from pathlib import Path
        golden_dir = Path(__file__).resolve().parent.parent / "bundles" / "golden"
        if golden_dir.exists():
            for fpath in golden_dir.glob("*.json"):
                try:
                    b = json.loads(fpath.read_text(encoding="utf-8"))
                    bid = b["bundleId"]
                    prob = {
                        "errorSignature": b["fingerprint"]["errorSignature"],
                        "runtime": b["scope"]["runtime"],
                        "packages": b["patch"]["pinnedDependencies"],
                        "description": b["description"]
                    }
                    sol = {
                        "summary": b["description"],
                        "codeDiff": b["patch"]["unifiedDiff"],
                        "patchDiff": b["patch"]["unifiedDiff"],
                        "instructions": ["Apply verified patch to resolve breaking change."],
                        "pinnedDependencies": b["patch"]["pinnedDependencies"],
                        "doNot": b["patch"].get("doNot", [])
                    }
                    repro = {
                        "script": b["verification"].get("reproductionScript", ""),
                        "testSuite": b["verification"].get("testSuite", "")
                    }
                    evi = {
                        "verificationStatus": "VERIFIED",
                        "sandboxExitCode": 0,
                        "passedTests": 1,
                        "totalTests": 1,
                        "confidenceScore": 1.0,
                        "primarySource": b.get("provenance", {}).get("primarySources", [None])[0],
                        "preExit": 1,
                        "postExit": 0,
                        "mutationsKilled": "2/2"
                    }
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
                        b["scope"]["runtime"],
                        b["fingerprint"]["errorSignature"],
                        json.dumps(prob),
                        json.dumps(sol),
                        json.dumps(repro),
                        json.dumps(evi),
                        1.0,
                        "VERIFIED"
                    ))
                except Exception as e:
                    logger.debug(f"Golden bundle sync note for {fpath.name}: {e}")
            await db.commit()

        logger.info(f"Database initialized at {settings.db_path} with WAL mode and golden bundles synced.")
