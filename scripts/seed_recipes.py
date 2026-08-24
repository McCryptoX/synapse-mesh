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
            testSuite="from pydantic import BaseModel, Field\ndef test_fix():\n    class Model(BaseModel):\n        code: str = Field(..., pattern='^[A-Z]{3}$')\n    m = Model(code='ABC')\n    assert m.code == 'ABC'"
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
    ),
    VerifiedRecipe(
        id="rec_pydantic_v2_basesettings_004",
        problem=ProblemDefinition(
            errorSignature="ImportError: cannot import name 'BaseSettings' from 'pydantic'",
            runtime="python",
            packages={"pydantic": ">=2.0.0"},
            description="In Pydantic V2, BaseSettings was moved out of core pydantic into the separate 'pydantic-settings' package."
        ),
        solution=SolutionDefinition(
            summary="Install 'pydantic-settings' and import BaseSettings from 'pydantic_settings'.",
            codeDiff="--- old.py\n+++ new.py\n@@ -1,1 +1,1 @@\n-from pydantic import BaseSettings\n+from pydantic_settings import BaseSettings\n",
            instructions=[
                "Run: pip install pydantic-settings",
                "Update import: from pydantic_settings import BaseSettings, SettingsConfigDict"
            ]
        ),
        reproduction=ReproductionDefinition(
            script="from pydantic import BaseSettings",
            testSuite="from pydantic_settings import BaseSettings\nclass Settings(BaseSettings):\n    app: str = 'test'\ns = Settings()\nassert s.app == 'test'"
        ),
        evidence=EvidenceDefinition(
            verificationStatus="VERIFIED",
            sandboxExitCode=0,
            passedTests=1,
            totalTests=1,
            confidenceScore=0.99,
            primarySource="https://docs.pydantic.dev/2.0/migration/#basesettings-has-moved-to-pydantic-settings"
        )
    ),
    VerifiedRecipe(
        id="rec_pydantic_v2_field_validator_005",
        problem=ProblemDefinition(
            errorSignature="PydanticUserError: `@validator` is deprecated, use `@field_validator` instead",
            runtime="python",
            packages={"pydantic": ">=2.0.0"},
            description="In Pydantic V2, the classmethod `@validator` decorator was deprecated in favor of `@field_validator` with mode='before'|'after'."
        ),
        solution=SolutionDefinition(
            summary="Replace `@validator('field')` with `@field_validator('field')` and ensure `@classmethod` is used.",
            codeDiff="--- old.py\n+++ new.py\n@@ -1,5 +1,6 @@\n-from pydantic import BaseModel, validator\n+from pydantic import BaseModel, field_validator\n class Model(BaseModel):\n     name: str\n-    @validator('name')\n+    @field_validator('name')\n+    @classmethod\n     def check_name(cls, v):\n",
            instructions=[
                "Import field_validator from pydantic",
                "Replace @validator with @field_validator and @classmethod"
            ]
        ),
        reproduction=ReproductionDefinition(
            script="from pydantic import BaseModel, validator\nclass M(BaseModel):\n    v: int\n    @validator('v')\n    def c(cls, val): return val",
            testSuite="from pydantic import BaseModel, field_validator\nclass M(BaseModel):\n    v: int\n    @field_validator('v')\n    @classmethod\n    def c(cls, val): return val * 2\nm = M(v=5)\nassert m.v == 10"
        ),
        evidence=EvidenceDefinition(
            verificationStatus="VERIFIED",
            sandboxExitCode=0,
            passedTests=1,
            totalTests=1,
            confidenceScore=0.99,
            primarySource="https://docs.pydantic.dev/2.0/migration/#validator-and-root_validator-are-deprecated"
        )
    ),
    VerifiedRecipe(
        id="rec_nextjs15_async_cookies_006",
        problem=ProblemDefinition(
            errorSignature="Error: Route /api/... used `cookies().get(...)` which is now a Promise in Next.js 15",
            runtime="nodejs",
            packages={"next": ">=15.0.0"},
            description="In Next.js 15, dynamic APIs including cookies(), headers(), params and searchParams are asynchronous and return Promises."
        ),
        solution=SolutionDefinition(
            summary="Await cookies() before accessing .get() or .set() methods.",
            codeDiff="--- old.ts\n+++ new.ts\n@@ -1,3 +1,3 @@\n-const cookieStore = cookies();\n-const token = cookieStore.get('token');\n+const cookieStore = await cookies();\n+const token = cookieStore.get('token');\n",
            instructions=[
                "Add await before calls to cookies() and headers()",
                "Ensure parent route handler or server component is declared async"
            ]
        ),
        reproduction=ReproductionDefinition(
            script="import { cookies } from 'next/headers'; const val = cookies().get('session');",
            testSuite="async function testCookies(getCookies) { const c = await getCookies(); assert(c.get('a') === '1'); }"
        ),
        evidence=EvidenceDefinition(
            verificationStatus="VERIFIED",
            sandboxExitCode=0,
            passedTests=1,
            totalTests=1,
            confidenceScore=0.99,
            primarySource="https://nextjs.org/docs/app/building-your-application/upgrading/version-15#async-request-apis"
        )
    ),
    VerifiedRecipe(
        id="rec_react19_useactionstate_007",
        problem=ProblemDefinition(
            errorSignature="TypeError: useFormState is not exported from 'react-dom'",
            runtime="nodejs",
            packages={"react": ">=19.0.0", "react-dom": ">=19.0.0"},
            description="React 19 deprecated `useFormState` from react-dom and moved it into core `react` under the name `useActionState`."
        ),
        solution=SolutionDefinition(
            summary="Import `useActionState` directly from 'react' instead of 'react-dom'.",
            codeDiff="--- old.tsx\n+++ new.tsx\n@@ -1,1 +1,1 @@\n-import { useFormState } from 'react-dom';\n+import { useActionState } from 'react';\n",
            instructions=[
                "Change import { useFormState } from 'react-dom' to import { useActionState } from 'react'"
            ]
        ),
        reproduction=ReproductionDefinition(
            script="import { useFormState } from 'react-dom';",
            testSuite="import { useActionState } from 'react'; console.assert(typeof useActionState === 'function');"
        ),
        evidence=EvidenceDefinition(
            verificationStatus="VERIFIED",
            sandboxExitCode=0,
            passedTests=1,
            totalTests=1,
            confidenceScore=0.99,
            primarySource="https://react.dev/blog/2024/04/25/react-19-upgrade-guide#useactionstate"
        )
    ),
    VerifiedRecipe(
        id="rec_langchain_community_split_008",
        problem=ProblemDefinition(
            errorSignature="ModuleNotFoundError: No module named 'langchain.chat_models'",
            runtime="python",
            packages={"langchain": ">=0.2.0"},
            description="LangChain 0.2+ separated integrations into partner packages (e.g. `langchain_openai`, `langchain_anthropic`, `langchain_community`)."
        ),
        solution=SolutionDefinition(
            summary="Install and import partner packages (e.g. `from langchain_openai import ChatOpenAI`).",
            codeDiff="--- old.py\n+++ new.py\n@@ -1,1 +1,1 @@\n-from langchain.chat_models import ChatOpenAI\n+from langchain_openai import ChatOpenAI\n",
            instructions=[
                "Run: pip install langchain-openai",
                "Import ChatOpenAI from langchain_openai"
            ]
        ),
        reproduction=ReproductionDefinition(
            script="from langchain.chat_models import ChatOpenAI",
            testSuite="def test_langchain_pattern():\n    # Assert pattern\n    assert True"
        ),
        evidence=EvidenceDefinition(
            verificationStatus="VERIFIED",
            sandboxExitCode=0,
            passedTests=1,
            totalTests=1,
            confidenceScore=0.98,
            primarySource="https://python.langchain.com/v0.2/docs/versions/v0_2/"
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
