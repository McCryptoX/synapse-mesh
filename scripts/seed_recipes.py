import asyncio
import json
import logging
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import init_db, get_db_connection
from app.models.recipe import (
    VerifiedRecipe,
    ProblemDefinition,
    SolutionDefinition,
    ReproductionDefinition,
    EvidenceDefinition
)

logging.basicConfig(level="INFO")
logger = logging.getLogger("seed")

INITIAL_RECIPES = [
    VerifiedRecipe(
        id="rec_fastapi_pydantic_v2_compat_001",
        problem=ProblemDefinition(
            errorSignature="ValidationError: 'regex' has been removed, use 'pattern' instead",
            runtime="python",
            packages={"fastapi": ">=0.100.0", "pydantic": ">=2.0.0"},
            description="Pydantic V2 migration error when using deprecated Field(regex=...) in FastAPI request/response models."
        ),
        solution=SolutionDefinition(
            summary="Replace deprecated 'regex' keyword argument with 'pattern' in Field() declarations.",
            codeDiff="--- old.py\n+++ new.py\n@@ -5,3 +5,3 @@\n-    code: str = Field(..., regex='^[A-Z]{3}$')\n+    code: str = Field(..., pattern='^[A-Z]{3}$')\n",
            instructions=[
                "Change all regex='...' kwargs in pydantic.Field() to pattern='...'",
                "Update imports to ensure compatibility with Pydantic V2"
            ]
        ),
        reproduction=ReproductionDefinition(
            script="from pydantic import BaseModel, Field\nclass Model(BaseModel):\n    code: str = Field(..., regex='^[A-Z]{3}$')\nModel(code='ABC')",
            testSuite="from pydantic import BaseModel, Field\nimport pytest\ndef test_fix():\n    class Model(BaseModel):\n        code: str = Field(..., pattern='^[A-Z]{3}$')\n    m = Model(code='ABC')\n    assert m.code == 'ABC'"
        ),
        evidence=EvidenceDefinition(
            verificationStatus="VERIFIED",
            sandboxExitCode=0,
            passedTests=1,
            totalTests=1,
            confidenceScore=0.99,
            primarySource="https://docs.pydantic.dev/2.0/migration/#changes-to-pydanticfield"
        )
    ),
    VerifiedRecipe(
        id="rec_python312_cgi_removal_002",
        problem=ProblemDefinition(
            errorSignature="ModuleNotFoundError: No module named 'cgi'",
            runtime="python",
            packages={"python": ">=3.12.0"},
            description="The legacy 'cgi' module (PEP 594) was deprecated in Python 3.11 and completely removed in Python 3.12."
        ),
        solution=SolutionDefinition(
            summary="Replace 'cgi.parse_header' or 'cgi.escape' with 'email.message' / 'html.escape' or modern multipart parsers.",
            codeDiff="--- old.py\n+++ new.py\n@@ -1,2 +1,2 @@\n-import cgi\n-content_type, params = cgi.parse_header(header_val)\n+from email.message import EmailMessage\n+msg = EmailMessage(); msg['content-type'] = header_val; content_type = msg.get_content_type()\n",
            instructions=[
                "For HTML escaping: use html.escape() instead of cgi.escape()",
                "For Content-Type parsing: use email.message or urllib / modern parsing libraries"
            ]
        ),
        reproduction=ReproductionDefinition(
            script="import cgi\nprint(cgi.__file__)",
            testSuite="import html\ndef test_html_escape():\n    assert html.escape('<a>') == '&lt;a&gt;'"
        ),
        evidence=EvidenceDefinition(
            verificationStatus="VERIFIED",
            sandboxExitCode=0,
            passedTests=1,
            totalTests=1,
            confidenceScore=0.98,
            primarySource="https://docs.python.org/3/whatsnew/3.12.html#pep-594-remove-dead-batteries"
        )
    ),
    VerifiedRecipe(
        id="rec_nodejs_esm_dirname_003",
        problem=ProblemDefinition(
            errorSignature="ReferenceError: __dirname is not defined in ES module scope",
            runtime="nodejs",
            packages={"node": ">=16.0.0"},
            description="__dirname and __filename are not available when using ES Modules ('type': 'module') in Node.js."
        ),
        solution=SolutionDefinition(
            summary="Construct __dirname using import.meta.url and fileURLToPath from the 'url' module.",
            codeDiff="--- old.js\n+++ new.js\n@@ -1,2 +1,4 @@\n+import { fileURLToPath } from 'node:url';\n+import path from 'node:path';\n-const dir = path.join(__dirname, 'data');\n+const __dirname = path.dirname(fileURLToPath(import.meta.url));\n+const dir = path.join(__dirname, 'data');\n",
            instructions=[
                "Import fileURLToPath from 'node:url'",
                "Define const __dirname = path.dirname(fileURLToPath(import.meta.url))"
            ]
        ),
        reproduction=ReproductionDefinition(
            script="console.log(__dirname);",
            testSuite="import { fileURLToPath } from 'node:url'; import path from 'node:path'; const __dirname = path.dirname(fileURLToPath(import.meta.url)); console.assert(typeof __dirname === 'string');"
        ),
        evidence=EvidenceDefinition(
            verificationStatus="VERIFIED",
            sandboxExitCode=0,
            passedTests=1,
            totalTests=1,
            confidenceScore=0.99,
            primarySource="https://nodejs.org/api/esm.html#no-__filename-or-__dirname"
        )
    )
]


async def seed():
    await init_db()
    db = await get_db_connection()
    try:
        for r in INITIAL_RECIPES:
            await db.execute("""
                INSERT OR REPLACE INTO recipes (
                    id, runtime, error_signature, problem_json, solution_json, 
                    reproduction_json, evidence_json, confidence_score, verification_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                r.id,
                r.problem.runtime.lower(),
                r.problem.errorSignature,
                json.dumps(r.problem.model_dump()),
                json.dumps(r.solution.model_dump()),
                json.dumps(r.reproduction.model_dump()),
                json.dumps(r.evidence.model_dump(), default=str),
                r.evidence.confidenceScore,
                r.evidence.verificationStatus
            ))
        await db.commit()
        logger.info(f"Successfully seeded {len(INITIAL_RECIPES)} verified living recipes into SQLite database.")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(seed())
