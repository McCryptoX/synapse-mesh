import aiosqlite
import json
import logging
from app.config import settings

logger = logging.getLogger("synapse_mesh.database")


async def get_db_connection() -> aiosqlite.Connection:
    db = await aiosqlite.connect(settings.db_path)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL;")
    await db.execute("PRAGMA synchronous=NORMAL;")
    await db.execute("PRAGMA foreign_keys=ON;")
    return db


async def init_db():
    """Initializes SQLite database schema with indexes and privacy-preserving analytics."""
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute("PRAGMA journal_mode=WAL;")
        
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

        await db.execute("CREATE INDEX IF NOT EXISTS idx_recipes_runtime ON recipes(runtime);")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_recipes_status ON recipes(verification_status);")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_access_logs_type ON access_logs(source_type);")
        await db.commit()
        logger.info(f"Database initialized at {settings.db_path} with WAL mode.")
