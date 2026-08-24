# Spezifikation Phase 1 MVP: Living Solutions API

## 1. Daten-Schema: `VerifiedRecipe` (JSON-LD & Pydantic Modell)

```json
{
  "$schema": "https://synapsemesh.dev/schemas/v1/recipe.json",
  "@context": "https://schema.org",
  "@type": "TechArticle",
  "id": "rec_fastapi_pydantic_v2_compat_001",
  "problem": {
    "errorSignature": "ValidationError: 'regex' has been removed, use 'pattern' instead",
    "runtime": "python",
    "packages": {
      "fastapi": ">=0.100.0",
      "pydantic": ">=2.0.0"
    },
    "description": "Pydantic V2 migration error when using deprecated Field(regex=...) in FastAPI request models."
  },
  "solution": {
    "summary": "Replace 'regex' parameter with 'pattern' in Field() declarations.",
    "codeDiff": "--- old.py\n+++ new.py\n@@ -5,3 +5,3 @@\n-    code: str = Field(..., regex='^[A-Z]{3}$')\n+    code: str = Field(..., pattern='^[A-Z]{3}$')\n",
    "instructions": [
      "Import Field from pydantic",
      "Change all regex kwargs in Field() to pattern"
    ]
  },
  "reproduction": {
    "script": "from pydantic import BaseModel, Field\nclass Model(BaseModel):\n    code: str = Field(..., regex='^[A-Z]{3}$')\nModel(code='ABC')",
    "testSuite": "from pydantic import BaseModel, Field\nimport pytest\ndef test_fix():\n    class Model(BaseModel):\n        code: str = Field(..., pattern='^[A-Z]{3}$')\n    m = Model(code='ABC')\n    assert m.code == 'ABC'"
  },
  "evidence": {
    "verificationStatus": "VERIFIED",
    "lastTestedAt": "2026-08-24T18:30:00Z",
    "sandboxExitCode": 0,
    "passedTests": 1,
    "totalTests": 1,
    "confidenceScore": 0.99,
    "primarySource": "https://docs.pydantic.dev/2.0/migration/#changes-to-pydanticfield"
  }
}
```

---

## 2. API Endpunkte (FastAPI / OpenAPI 3.1)

### `POST /api/v1/recipes/search`
* **Zweck:** Findet sofort verifizierte Lösungen für Fehlersignaturen und Umgebungsdaten.
* **Input:**
  ```json
  {
    "errorSignature": "ValidationError: 'regex' has been removed",
    "runtime": "python",
    "packages": { "pydantic": "2.4.2" }
  }
  ```
* **Output:** `Array<VerifiedRecipe>` sortiert nach `confidenceScore` und Aktualität.

### `POST /api/v1/recipes/submit`
* **Zweck:** Ein Agent reicht eine neue Lösung samt Repro-Skript und Testsuite ein.
* **Prozess:** 
  1. Zero-PII Sanitization (automatische Bereinigung von IP-Adressen, Namen, Pfaden).
  2. Status wird auf `SANDBOX_TESTING` gesetzt.
  3. Sandbox führt den Test aus.
  4. Bei Erfolg: Freigabe als `VERIFIED`.

---

## 3. MCP Tool Definition (`find_solution` & `submit_solution`)

```json
{
  "name": "find_solution",
  "description": "Searches Synapse-Mesh for verified bug fixes, compatibility recipes and repro tests.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "errorSignature": { "type": "string", "description": "The exact error message or traceback snippet" },
      "environment": { "type": "object", "description": "Dictionary of language, OS, and package versions" }
    },
    "required": ["errorSignature"]
  }
}
```

---

## 4. Agent Discovery Descriptors

### `GET /.well-known/mcp.json`
Maschinenlesbare Konfiguration für automatische Client-Registrierung:
```json
{
  "name": "Synapse-Mesh",
  "description": "Agent-native verified living solutions & sandbox test runner",
  "version": "1.0.0",
  "transport": {
    "type": "streamable-http",
    "endpoint": "https://synapsemesh.dev/mcp"
  },
  "capabilities": {
    "tools": ["find_solution", "submit_solution"],
    "resources": ["recipes://{recipeId}"]
  }
}
```

### `GET /.well-known/agent.json`
Agent-to-Agent (A2A) Discovery Manifest:
```json
{
  "agentName": "Synapse-Mesh-Exocortex",
  "protocols": ["MCP/2026", "A2A/1.0"],
  "endpoints": {
    "mcp": "https://synapsemesh.dev/mcp",
    "rest": "https://synapsemesh.dev/api/v1",
    "a2a": "https://synapsemesh.dev/a2a"
  },
  "supportedRuntimes": ["python", "nodejs", "rust", "go"],
  "evidenceFirst": true,
  "zeroPii": true
}
```

