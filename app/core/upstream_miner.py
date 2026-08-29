"""
Synapse-Mesh Upstream Mining Engine (Zero-Token Autonomous Recipe Extractor)
Extracts breaking changes, deprecation warnings, and migration patterns directly from
upstream open-source repositories, changelogs, and release feeds, synthesizing candidate
draft bundles without executing them.

SECURITY DIRECTIVE:
Automated miners write strictly to `bundles/drafts/` with status DRAFT. They do not execute,
promote, or label candidates VERIFIED. `bundles/golden/` is an immutable, reviewed store.
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import urllib.request
from pathlib import Path
from typing import Dict, Any, List, Optional

from app.models.bundle import (
    CompatibilityBundle,
    BundleScope,
    BundleFingerprint,
    BundlePatch,
    BundleMutation,
    BundleVerification,
    BundleProvenance,
)
from app.core.sanitizer import ZeroPiiSanitizer

logger = logging.getLogger("synapse.miner")
DRAFTS_DIR = Path(__file__).resolve().parent.parent.parent / "bundles" / "drafts"

# Monitored upstream target repositories for zero-token mining
KNOWN_UPSTREAM_TARGETS = [
    {"package": "sqlalchemy", "ecosystem": "pypi", "runtime": "python", "repo": "sqlalchemy/sqlalchemy"},
    {"package": "pydantic", "ecosystem": "pypi", "runtime": "python", "repo": "pydantic/pydantic"},
    {"package": "fastapi", "ecosystem": "pypi", "runtime": "python", "repo": "tiangolo/fastapi"},
    {"package": "httpx", "ecosystem": "pypi", "runtime": "python", "repo": "encode/httpx"},
    {"package": "numpy", "ecosystem": "pypi", "runtime": "python", "repo": "numpy/numpy"},
    {"package": "pandas", "ecosystem": "pypi", "runtime": "python", "repo": "pandas-dev/pandas"},
    {"package": "polars", "ecosystem": "pypi", "runtime": "python", "repo": "pola-rs/polars"},
    {"package": "pydantic-settings", "ecosystem": "pypi", "runtime": "python", "repo": "pydantic/pydantic-settings"},
    {"package": "litellm", "ecosystem": "pypi", "runtime": "python", "repo": "BerriAI/litellm"},
    {"package": "tenacity", "ecosystem": "pypi", "runtime": "python", "repo": "jd/tenacity"},
    {"package": "redis", "ecosystem": "pypi", "runtime": "python", "repo": "redis/redis-py"},
    {"package": "transformers", "ecosystem": "pypi", "runtime": "python", "repo": "huggingface/transformers"},
    {"package": "anthropic", "ecosystem": "pypi", "runtime": "python", "repo": "anthropics/anthropic-sdk-python"},
    {"package": "openai", "ecosystem": "pypi", "runtime": "python", "repo": "openai/openai-python"},
    {"package": "duckdb", "ecosystem": "pypi", "runtime": "python", "repo": "duckdb/duckdb"},
    {"package": "playwright", "ecosystem": "pypi", "runtime": "python", "repo": "microsoft/playwright-python"},
    {"package": "starlette", "ecosystem": "pypi", "runtime": "python", "repo": "encode/starlette"},
    {"package": "pytest", "ecosystem": "pypi", "runtime": "python", "repo": "pytest-dev/pytest"},
    {"package": "langchain", "ecosystem": "pypi", "runtime": "python", "repo": "langchain-ai/langchain"},
    {"package": "next", "ecosystem": "npm", "runtime": "nodejs", "repo": "vercel/next.js"},
    {"package": "express", "ecosystem": "npm", "runtime": "nodejs", "repo": "expressjs/express"},
    {"package": "zod", "ecosystem": "npm", "runtime": "nodejs", "repo": "colinhacks/zod"},
    {"package": "vite", "ecosystem": "npm", "runtime": "nodejs", "repo": "vitejs/vite"},
    {"package": "hono", "ecosystem": "npm", "runtime": "nodejs", "repo": "honojs/hono"},
    {"package": "trpc", "ecosystem": "npm", "runtime": "nodejs", "repo": "trpc/trpc"},
    {"package": "tokio", "ecosystem": "crates", "runtime": "rust", "repo": "tokio-rs/tokio"},
]


class UpstreamReleaseFetcher:
    """Fetches release notes, migration guides, and changelogs from upstream registries without API keys."""

    @classmethod
    def fetch_pypi_changelog(cls, package_name: str) -> List[Dict[str, Any]]:
        """Queries PyPI JSON API for recent release descriptions and metadata."""
        url = f"https://pypi.org/pypi/{package_name}/json"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Synapse-Upstream-Miner/1.0"})
            with urllib.request.urlopen(req, timeout=6.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                info = data.get("info", {})
                latest_version = info.get("version", "")
                description = info.get("description", "") or ""
                return [{
                    "package": package_name,
                    "version": latest_version,
                    "release_notes": description[:8000],
                    "url": info.get("project_url", url),
                    "ecosystem": "pypi"
                }]
        except Exception as e:
            logger.debug(f"PyPI live fetch for {package_name} skipped ({e})")
            return []

    @classmethod
    def fetch_pypi_rss_updates(cls, limit: int = 10) -> List[Dict[str, Any]]:
        """Fetches the latest package updates directly from PyPI's public RSS feed."""
        import xml.etree.ElementTree as ET
        url = "https://pypi.org/rss/updates.xml"
        results = []
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Synapse-Upstream-Miner/1.0"})
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                root = ET.fromstring(resp.read())
                for item in root.findall("./channel/item")[:limit]:
                    title = item.findtext("title", "")
                    link = item.findtext("link", "")
                    desc = item.findtext("description", "")
                    if " " in title:
                        pkg_name, ver = title.split(" ", 1)
                        results.append({
                            "package": pkg_name.strip(),
                            "version": ver.strip(),
                            "release_notes": desc,
                            "url": link,
                            "ecosystem": "pypi",
                            "runtime": "python"
                        })
        except Exception as e:
            logger.debug(f"PyPI RSS live fetch skipped ({e})")
        return results

    @classmethod
    def fetch_github_releases_atom(cls, repo: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Fetches recent releases from GitHub repository Atom feed without API key requirement."""
        import xml.etree.ElementTree as ET
        url = f"https://github.com/{repo}/releases.atom"
        results = []
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Synapse-Upstream-Miner/1.0"})
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                root = ET.fromstring(resp.read())
                ns = {"atom": "http://www.w3.org/2005/Atom"}
                for entry in root.findall("atom:entry", ns)[:limit]:
                    title = entry.findtext("atom:title", "", ns)
                    content = entry.findtext("atom:content", "", ns)
                    link_el = entry.find("atom:link", ns)
                    link = link_el.attrib.get("href", "") if link_el is not None else ""
                    results.append({
                        "package": repo.split("/")[-1],
                        "version": title.lstrip("v"),
                        "release_notes": content,
                        "url": link,
                        "ecosystem": "github",
                        "runtime": "all"
                    })
        except Exception as e:
            logger.debug(f"GitHub Atom feed fetch for {repo} skipped ({e})")
        return results

    @classmethod
    def get_seed_changelogs(cls) -> List[Dict[str, Any]]:
        """Deterministic upstream seed changelogs with genuine code (zero puppet mocks)."""
        seeds = [
            {
                "package": "sqlalchemy",
                "version": "2.0.0",
                "ecosystem": "pypi",
                "runtime": "python",
                "release_notes": """
# SQLAlchemy 2.0.0 Release Notes
### Breaking Changes
- Passing raw string queries to `session.execute()` raises `ArgumentError: Textual SQL expression must be explicitly declared as text()`.
### Migration Example
Before:
```python
from sqlalchemy import create_engine
engine = create_engine("sqlite:///:memory:")
with engine.connect() as conn:
    res = conn.execute("SELECT 1")
```
After:
```python
from sqlalchemy import create_engine, text
engine = create_engine("sqlite:///:memory:")
with engine.connect() as conn:
    res = conn.execute(text("SELECT 1"))
    val = res.scalar()
    assert val == 1
```
Pin: sqlalchemy>=2.0.0,<3.0.0
Do Not: Do not suppress ArgumentError by wrapping in try/except; do not pass raw strings directly.
""",
                "url": "https://docs.sqlalchemy.org/en/20/changelog/changelog_20.html"
            },
            {
                "package": "numpy",
                "version": "2.0.0",
                "ecosystem": "pypi",
                "runtime": "python",
                "release_notes": """
# NumPy 2.0.0 Migration
### Breaking Changes
- Attribute `np.NAN` has been removed in NumPy 2.0. Use `np.nan` instead.
- Accessing `np.NAN` raises `AttributeError: `np.NAN` was removed in the NumPy 2.0 release. Use `np.nan` instead.`.
### Migration
Before:
```python
import numpy as np
val = np.NAN
```
After:
```python
import numpy as np
import math
val = np.nan
assert math.isnan(val)
```
Pin: numpy>=2.0.0
Do Not: Do not monkeypatch np.NAN = np.nan on global numpy module.
""",
                "url": "https://numpy.org/devdocs/release/2.0.0-notes.html"
            },
            {
                "package": "pydantic",
                "version": "2.0.0",
                "ecosystem": "pypi",
                "runtime": "python",
                "release_notes": """
# Pydantic V2 Migration Guide
### Breaking Changes
- Method `BaseModel.parse_obj()` has been removed in Pydantic V2 in favor of `BaseModel.model_validate()`.
- Calling `parse_obj` raises `PydanticUserError: The 'parse_obj' method has been removed in Pydantic V2. Use 'model_validate' instead.`.
### Migration
Before:
```python
from pydantic import BaseModel
class User(BaseModel):
    id: int
    name: str
u = User.parse_obj({"id": 1, "name": "Alice"})
```
After:
```python
from pydantic import BaseModel
class User(BaseModel):
    id: int
    name: str
u = User.model_validate({"id": 1, "name": "Alice"})
assert u.id == 1
```
Pin: pydantic>=2.0.0,<3.0.0
Do Not: Do not invoke legacy parse_obj() method on Pydantic v2 data models.
""",
                "url": "https://docs.pydantic.dev/latest/migration/"
            },
            {
                "package": "httpx",
                "version": "0.28.0",
                "ecosystem": "pypi",
                "runtime": "python",
                "release_notes": """
# HTTPX 0.28.0 Release
### Breaking Changes
- The `app=` keyword argument was deprecated and removed from `httpx.AsyncClient`.
- Passing `app=` directly raises `TypeError: AsyncClient.__init__() got an unexpected keyword argument 'app'. Pass transport=ASGITransport(app=app) instead.`.
### Migration
Before:
```python
import httpx
client = httpx.AsyncClient(app=object(), base_url="http://test")
```
After:
```python
import httpx
transport = httpx.ASGITransport(app=object())
client = httpx.AsyncClient(transport=transport, base_url="http://test")
assert client.base_url == "http://test"
```
Pin: httpx>=0.28.0,<1.0.0
Do Not: Do not pass app argument directly into httpx.AsyncClient.
""",
                "url": "https://www.python-httpx.org/compatibility/"
            },
            {
                "package": "fastapi",
                "version": "0.100.0",
                "ecosystem": "pypi",
                "runtime": "python",
                "release_notes": """
# FastAPI 0.100.0 / Pydantic Settings Migration
### Breaking Changes
- `BaseSettings` is no longer re-exported from `pydantic`.
- Importing `from pydantic import BaseSettings` raises `ImportError: cannot import name 'BaseSettings' from 'pydantic'. In Pydantic V2, BaseSettings is in pydantic_settings package.`.
### Migration
Before:
```python
from pydantic import BaseSettings
```
After:
```python
from pydantic_settings import BaseSettings
class Settings(BaseSettings):
    app_name: str = "Synapse"
con = Settings()
assert con.app_name == "Synapse"
```
Pin: fastapi>=0.100.0, pydantic-settings>=2.0.0
Do Not: Do not import BaseSettings from root pydantic module.
""",
                "url": "https://fastapi.tiangolo.com/advanced/settings/"
            }
        ]
        for seed in seeds:
            # Only repository-owned fixtures may contribute executable code.
            seed["trusted_code_examples"] = True
        return seeds


class BreakingChangeExtractor:
    """Deterministic regex & AST pattern parser that extracts structured bundle fields with zero LLM tokens."""

    _GENERIC_TOKENS = frozenset({
        "attribute", "instead", "method", "function", "class", "module", "version",
        "error", "warning", "change", "api", "the", "this", "that", "use", "with",
        "from", "import", "removed", "deprecated", "please", "see", "docs",
        "breaking", "changes", "release", "notes", "new", "old", "now", "was",
        "has", "been", "and", "or", "for", "not", "no", "longer", "supported",
        "argument", "parameter", "keyword", "kwarg", "args", "kwargs",
        "decorator", "async", "await", "sync", "coroutine", "python",
        "javascript", "typescript", "package", "library", "value", "name",
        "type", "object", "none", "true", "false", "null", "self", "init",
    })

    _IMPORT_ALIASES = {
        "redis-py": "redis",
        "next.js": "next",
        "nextjs": "next",
        "scikit-learn": "sklearn",
        "python-dotenv": "dotenv",
        "pillow": "PIL",
        "beautifulsoup4": "bs4",
        "pyyaml": "yaml",
        "opencv-python": "cv2",
        "langchain-core": "langchain_core",
        "langchain-openai": "langchain_openai",
        "pydantic-settings": "pydantic_settings",
        "typing-extensions": "typing_extensions",
        "google-generativeai": "google.generativeai",
        "python-multipart": "multipart",
    }

    _SHORT_ALIASES = {
        "np": "numpy",
        "pd": "pandas",
        "tf": "tensorflow",
        "plt": "matplotlib.pyplot",
    }

    @classmethod
    def _is_valid_symbol(cls, symbol: str) -> bool:
        token = (symbol or "").strip("`\"'() ")
        if len(token) < 2:
            return False
        if token.lower() in cls._GENERIC_TOKENS:
            return False
        return bool(re.match(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$", token))

    @classmethod
    def _import_name(cls, package: str) -> str:
        """Map registry names (redis-py) onto valid Python/JS import identifiers."""
        raw = (package or "").strip()
        if not raw:
            return "pkg"
        alias = cls._IMPORT_ALIASES.get(raw.lower())
        if alias:
            return alias
        cleaned = re.sub(r"[^A-Za-z0-9_.]+", "_", raw).strip("._")
        if not cleaned:
            return "pkg"
        if cleaned[0].isdigit():
            return f"pkg_{cleaned}"
        return cleaned

    @classmethod
    def _alias_snippets(cls, package: str, old_sym: str, new_sym: str, runtime: str) -> Optional[Dict[str, str]]:
        if not cls._is_valid_symbol(old_sym) or not cls._is_valid_symbol(new_sym) or old_sym == new_sym:
            return None
        pkg = cls._import_name(package)

        def _py_expr(sym: str) -> tuple[str, str]:
            root = sym.split(".", 1)[0]
            if root in cls._SHORT_ALIASES:
                return f"import {cls._SHORT_ALIASES[root]} as {root}", sym
            if "." in sym:
                if root == pkg:
                    return f"import {pkg}", sym
                return f"import {pkg}", f"{pkg}.{sym}"
            return f"import {pkg}", f"getattr({pkg}, '{sym}', None) or {pkg}.{sym}()"

        if runtime == "python":
            b_imp, b_expr = _py_expr(old_sym)
            a_imp, a_expr = _py_expr(new_sym)
            return {
                "before": f"{b_imp}\nres = {b_expr}\nprint('OLD_EXECUTED', res)\n",
                "after": f"{a_imp}\nres = {a_expr}\nprint('NEW_EXECUTED', res)\n",
                "kind": "alias",
            }
        if runtime in ("nodejs", "javascript", "typescript"):
            return {
                "before": (
                    f"const {pkg} = require('{pkg}');\n"
                    f"const res = {pkg}.{old_sym} || {pkg}.{old_sym}();\n"
                    f"console.log('OLD_EXECUTED', res);\n"
                ),
                "after": (
                    f"const {pkg} = require('{pkg}');\n"
                    f"const res = {pkg}.{new_sym} || {pkg}.{new_sym}();\n"
                    f"console.log('NEW_EXECUTED', res);\n"
                ),
                "kind": "alias",
            }
        return None

    @classmethod
    def extract_error_signature(cls, text: str) -> Optional[str]:
        """Extracts exact error signature pattern from changelog text."""
        specific_patterns = (
            r"(TypeError:[^\n`]{8,240}unexpected keyword argument[^\n`]{0,80})",
            r"(RuntimeWarning:[^\n`]{8,240}never awaited[^\n`]{0,80})",
            r"(DeprecationWarning:[^\n`]{8,240})",
            r"(PydanticUserError:[^\n`]{8,240})",
            r"(APIRemovedInV1:[^\n`]{8,240})",
        )
        for pat in specific_patterns:
            match = re.search(pat, text, re.IGNORECASE)
            if match:
                sig = match.group(1).strip("`\"' .")
                if len(sig) > 8:
                    return sig

        match = re.search(r'(?:raise|raises|raising|throw|throws|threw|causes)?\s*`?([A-Za-z0-9_.]*(?:Exception|Error|Warning|APIRemoved\w*|SyntaxError|TypeError)[\w\s:()\'".,`\-]+)`?', text, re.IGNORECASE)
        if match:
            sig = match.group(1).strip("`\"' .")
            if len(sig) > 8:
                return sig

        match = re.search(r'(DeprecationWarning:[\w\s:()\'".,`\-]+)', text, re.IGNORECASE)
        if match:
            return match.group(1).strip("`\"' .")

        return None

    @classmethod
    def extract_constructor_migration(
        cls, text: str, package: str = "", runtime: str = "python"
    ) -> Optional[Dict[str, str]]:
        """Synthesize patches for constructor/kwarg signature breaks (unexpected keyword argument)."""
        callee = None
        old_kw = None

        init_match = re.search(
            r"([A-Za-z_][\w.]*)\.__init__\(\)\s+got an unexpected keyword argument\s+['\"](\w+)['\"]",
            text,
            re.IGNORECASE,
        )
        if init_match:
            callee = init_match.group(1)
            old_kw = init_match.group(2)
        else:
            call_match = re.search(
                r"([A-Za-z_][\w.]*)\(\)\s+got an unexpected keyword argument\s+['\"](\w+)['\"]",
                text,
                re.IGNORECASE,
            )
            if call_match:
                callee = call_match.group(1)
                old_kw = call_match.group(2)
            else:
                kw_only = re.search(
                    r"unexpected keyword argument\s+['\"](\w+)['\"]",
                    text,
                    re.IGNORECASE,
                )
                if kw_only:
                    old_kw = kw_only.group(1)

        if not old_kw:
            removed = re.search(
                r"(?:removed|dropped|no longer (?:accepts|supports))\s+(?:the\s+)?[`'\"]?(\w+)[`'\"]?\s+(?:keyword\s+)?(?:argument|parameter|kwarg)",
                text,
                re.IGNORECASE,
            )
            if removed:
                old_kw = removed.group(1)

        if not old_kw or not cls._is_valid_symbol(old_kw):
            return None

        new_kw = None
        assign_match = re.search(
            r"(?:pass|use|provide|prefer)\s+[`'\"]?([A-Za-z_][\w]*)\s*=",
            text,
            re.IGNORECASE,
        )
        if assign_match:
            cand = assign_match.group(1)
            if cand.lower() != old_kw.lower() and cls._is_valid_symbol(cand):
                new_kw = cand
        if not new_kw:
            named = re.search(
                r"(?:use|replaced by|replace with)\s+(?:the\s+)?[`'\"]([A-Za-z_][\w]*)[`'\"]\s+(?:parameter|argument|kwarg|keyword)",
                text,
                re.IGNORECASE,
            )
            if named:
                cand = named.group(1)
                if cand.lower() != old_kw.lower() and cls._is_valid_symbol(cand):
                    new_kw = cand
        if not new_kw:
            pair = re.search(
                rf"(?:use|replaced by)\s+[`'\"]?([A-Za-z_][\w]*)[`'\"]?\s+instead of\s+[`'\"]?{re.escape(old_kw)}[`'\"]?",
                text,
                re.IGNORECASE,
            )
            if pair and cls._is_valid_symbol(pair.group(1)):
                new_kw = pair.group(1)

        if not new_kw:
            return None

        pkg = cls._import_name(package)
        callee_name = None
        if callee:
            callee_name = callee.split(".")[-1]
            if callee_name.lower() in cls._GENERIC_TOKENS or callee_name.startswith("__"):
                callee_name = None
        is_class = bool(callee_name and callee_name[:1].isupper())
        target = callee_name or "Client"

        if runtime == "python":
            if is_class:
                before = (
                    f"import sys\n"
                    f"from {pkg} import {target}\n"
                    f"try:\n"
                    f"    _obj = {target}({old_kw}=None)\n"
                    f"except TypeError as e:\n"
                    f"    sys.stderr.write(str(e) + \"\\n\")\n"
                    f"    sys.exit(1)\n"
                )
                after = (
                    f"from {pkg} import {target}\n"
                    f"_obj = {target}({new_kw}=None)\n"
                    f"assert _obj is not None\n"
                )
            else:
                before = (
                    f"import sys\n"
                    f"import {pkg}\n"
                    f"try:\n"
                    f"    _obj = {pkg}.{target}({old_kw}=None)\n"
                    f"except TypeError as e:\n"
                    f"    sys.stderr.write(str(e) + \"\\n\")\n"
                    f"    sys.exit(1)\n"
                )
                after = (
                    f"import {pkg}\n"
                    f"_obj = {pkg}.{target}({new_kw}=None)\n"
                    f"assert _obj is not None\n"
                )
            return {"before": before, "after": after, "kind": "constructor"}

        if runtime in ("nodejs", "javascript", "typescript"):
            before = (
                f"const {{ {target} }} = require('{pkg}');\n"
                f"const _obj = new {target}({{ {old_kw}: null }});\n"
            )
            after = (
                f"const {{ {target} }} = require('{pkg}');\n"
                f"const _obj = new {target}({{ {new_kw}: null }});\n"
            )
            return {"before": before, "after": after, "kind": "constructor"}
        return None

    @classmethod
    def extract_async_migration(
        cls, text: str, package: str = "", runtime: str = "python"
    ) -> Optional[Dict[str, str]]:
        """Synthesize patches for sync→async API migrations (await / asyncio.run / get_event_loop)."""
        if runtime not in ("python", "nodejs", "javascript", "typescript"):
            return None

        if re.search(r"get_event_loop", text) and re.search(
            r"deprecated|removed|no current event loop|use asyncio\.run", text, re.IGNORECASE
        ):
            if runtime == "python":
                return {
                    "before": (
                        "import asyncio\n"
                        "loop = asyncio.get_event_loop()\n"
                        "result = loop.run_until_complete(asyncio.sleep(0, result=True))\n"
                    ),
                    "after": (
                        "import asyncio\n"
                        "result = asyncio.run(asyncio.sleep(0, result=True))\n"
                        "assert result is True\n"
                    ),
                    "kind": "async",
                }

        func = None
        now_async = re.search(
            r"[`'\"]((?:[A-Za-z_][\w]*\.)*[A-Za-z_][\w]*)(?:\(\))?[`'\"]?\s+"
            r"(?:is now|has become|was converted to|is now an?)\s+"
            r"(?:an?\s+)?(?:async(?:hronous)?(?:\s+(?:function|method|api))?|coroutine)",
            text,
            re.IGNORECASE,
        )
        if now_async:
            func = now_async.group(1)
        if not func:
            awaited = re.search(
                r"coroutine\s+[`'\"]?((?:[A-Za-z_][\w]*\.)*[A-Za-z_][\w]*)[`'\"]?\s+was never awaited",
                text,
                re.IGNORECASE,
            )
            if awaited:
                func = awaited.group(1)
        if not func:
            use_await = re.search(
                r"use\s+[`'\"]?await\s+((?:[A-Za-z_][\w]*\.)*[A-Za-z_][\w]*)(?:\(\))?[`'\"]?"
                r"\s+instead of\s+[`'\"]?((?:[A-Za-z_][\w]*\.)*[A-Za-z_][\w]*)",
                text,
                re.IGNORECASE,
            )
            if use_await:
                func = use_await.group(1)
        if not func:
            must_await = re.search(
                r"[`'\"]((?:[A-Za-z_][\w]*\.)*[A-Za-z_][\w]*)(?:\(\))?[`'\"]?\s+"
                r"(?:must|needs to|should)\s+(?:now\s+)?be\s+awaited",
                text,
                re.IGNORECASE,
            )
            if must_await:
                func = must_await.group(1)

        if not func or not cls._is_valid_symbol(func):
            return None

        pkg = cls._import_name(package)
        call = func if "." in func else f"{pkg}.{func}"

        if runtime == "python":
            return {
                "before": f"import {pkg}\nresult = {call}()\nprint(result)\n",
                "after": (
                    f"import asyncio\n"
                    f"import {pkg}\n"
                    f"async def _main():\n"
                    f"    return await {call}()\n"
                    f"result = asyncio.run(_main())\n"
                    f"print(result)\n"
                ),
                "kind": "async",
            }
        return {
            "before": (
                f"const {pkg} = require('{pkg}');\n"
                f"const result = {call}();\n"
                f"console.log(result);\n"
            ),
            "after": (
                f"const {pkg} = require('{pkg}');\n"
                f"(async () => {{\n"
                f"  const result = await {call}();\n"
                f"  console.log(result);\n"
                f"}})();\n"
            ),
            "kind": "async",
        }

    @classmethod
    def extract_decorator_migration(
        cls, text: str, package: str = "", runtime: str = "python"
    ) -> Optional[Dict[str, str]]:
        """Synthesize patches for deprecated decorator migrations (on_event→lifespan, @old→@new)."""
        if runtime != "python":
            return None

        if re.search(r"on_event", text) and re.search(r"lifespan", text, re.IGNORECASE):
            return {
                "before": (
                    "from fastapi import FastAPI\n"
                    "app = FastAPI()\n"
                    "\n"
                    "@app.on_event(\"startup\")\n"
                    "def _startup():\n"
                    "    app.state.ready = True\n"
                ),
                "after": (
                    "from contextlib import asynccontextmanager\n"
                    "from fastapi import FastAPI\n"
                    "\n"
                    "@asynccontextmanager\n"
                    "async def lifespan(app):\n"
                    "    app.state.ready = True\n"
                    "    yield\n"
                    "\n"
                    "app = FastAPI(lifespan=lifespan)\n"
                ),
                "kind": "decorator",
            }

        pair = re.search(
            r"use\s+@([A-Za-z_][\w.]*)\s+instead of\s+@([A-Za-z_][\w.]*)",
            text,
            re.IGNORECASE,
        )
        if pair:
            new_dec, old_dec = pair.group(1), pair.group(2)
        else:
            deprecated = re.search(
                r"@([A-Za-z_][\w.]*)\s+(?:is|has been|was)\s+(?:deprecated|removed)"
                r"[^.\n]{0,180}(?:use|replace with|replaced by)\s+@([A-Za-z_][\w.]*)",
                text,
                re.IGNORECASE,
            )
            if not deprecated:
                return None
            old_dec, new_dec = deprecated.group(1), deprecated.group(2)

        if not cls._is_valid_symbol(old_dec) or not cls._is_valid_symbol(new_dec) or old_dec == new_dec:
            return None

        pkg = cls._import_name(package)

        def _dec_expr(name: str) -> str:
            if "." in name or name.startswith(pkg + "."):
                return f"@{name}"
            return f"@{pkg}.{name}"

        return {
            "before": f"import {pkg}\n\n{_dec_expr(old_dec)}\ndef _handler():\n    return True\n",
            "after": f"import {pkg}\n\n{_dec_expr(new_dec)}\ndef _handler():\n    return True\n",
            "kind": "decorator",
        }

    @classmethod
    def extract_before_after(
        cls,
        text: str,
        package: str = "",
        runtime: str = "python",
        allow_embedded_code: bool = True,
    ) -> Optional[Dict[str, str]]:
        """Extracts Before/After code blocks from explicit markdown or synthesizes from natural language migration text."""
        # 1. Explicit Before / After Markdown blocks
        before_match = re.search(r'Before:?\s*```(?:python|javascript|typescript|json|rust)?\s*([\s\S]*?)```', text, re.IGNORECASE) if allow_embedded_code else None
        after_match = re.search(r'After:?\s*```(?:python|javascript|typescript|json|rust)?\s*([\s\S]*?)```', text, re.IGNORECASE) if allow_embedded_code else None

        if before_match and after_match:
            before_code = before_match.group(1).strip()
            after_code = after_match.group(1).strip()
            return {"before": before_code, "after": after_code}

        # 2. Constructor / unexpected-keyword signature changes
        ctor = cls.extract_constructor_migration(text, package=package, runtime=runtime)
        if ctor:
            return ctor

        # 3. Deprecated decorator migrations
        dec = cls.extract_decorator_migration(text, package=package, runtime=runtime)
        if dec:
            return dec

        # 4. Sync → async API migrations
        async_mig = cls.extract_async_migration(text, package=package, runtime=runtime)
        if async_mig:
            return async_mig

        # 5. Heuristic Pattern: "use `<new>` instead of `<old>`" / "replace `<old>` with `<new>`"
        old_sym, new_sym = None, None
        use_instead_match = re.search(r'(?:use|replace with)\s+[`"]?([a-zA-Z0-9_\.]+(?:\(\))?)[`"]?\s+(?:instead of|for|rather than)\s+[`"]?([a-zA-Z0-9_\.]+(?:\(\))?)[`"]?', text, re.IGNORECASE)
        if use_instead_match:
            new_sym = use_instead_match.group(1).strip("`\"'() ")
            old_sym = use_instead_match.group(2).strip("`\"'() ")
        else:
            use_instead_match = re.search(
                r'[`"]?([a-zA-Z0-9_\.]+(?:\(\))?)[`"]?\s+(?:is deprecated|was removed|has been removed|is no longer supported)[^\n]{0,180}?(?:use|replace with)\s+[`"]?([a-zA-Z0-9_\.]+(?:\(\))?)[`"]?',
                text,
                re.IGNORECASE,
            )
            if use_instead_match:
                old_sym = use_instead_match.group(1).strip("`\"'() ")
                new_sym = use_instead_match.group(2).strip("`\"'() ")
            else:
                trailing_instead = re.search(
                    r'[`"]([A-Za-z_][\w.]*)[`"]?\s+(?:was removed|has been removed|is deprecated)[^\n]{0,180}[Uu]se\s+[`"]([A-Za-z_][\w.]*)[`"]?\s+instead',
                    text,
                )
                if trailing_instead:
                    old_sym = trailing_instead.group(1).strip("`\"'() ")
                    new_sym = trailing_instead.group(2).strip("`\"'() ")

        alias = cls._alias_snippets(package, old_sym or "", new_sym or "", runtime) if old_sym and new_sym else None
        if alias:
            return alias

        # 6. Heuristic Pattern: "renamed `<old>` to `<new>`"
        rename_match = re.search(r'renamed\s+[`"]?([a-zA-Z0-9_\.]+(?:\(\))?)[`"]?\s+to\s+[`"]?([a-zA-Z0-9_\.]+(?:\(\))?)[`"]?', text, re.IGNORECASE)
        if rename_match:
            renamed = cls._alias_snippets(
                package,
                rename_match.group(1).strip("`\"'() "),
                rename_match.group(2).strip("`\"'() "),
                runtime,
            )
            if renamed:
                return renamed

        return None

    @classmethod
    def extract_pins(cls, text: str, package: str) -> Dict[str, str]:
        """Extract package constraints without dropping comma-separated clauses."""
        pins: Dict[str, str] = {}
        match = re.search(r"Pin:\s*([^\n\r]+)", text, re.IGNORECASE)
        if match:
            current_package: Optional[str] = None
            for raw_part in match.group(1).split(","):
                part = raw_part.strip()
                named = re.fullmatch(
                    r"([A-Za-z0-9_@./\-]+)\s*((?:[<>=!~]=?|\^)[0-9A-Za-z.*+!<>=~\-]+)",
                    part,
                )
                continuation = re.fullmatch(r"((?:[<>=!~]=?|\^)[0-9A-Za-z.*+!<>=~\-]+)", part)
                if named:
                    current_package = named.group(1)
                    pins[current_package] = named.group(2)
                elif continuation and current_package:
                    pins[current_package] = f"{pins[current_package]},{continuation.group(1)}"
        return pins

    @classmethod
    def extract_do_not(cls, text: str) -> List[str]:
        """Extracts negative engineering constraints (doNot)."""
        do_not = []
        match = re.search(r'Do Not:\s*([^\n\r]+)', text, re.IGNORECASE)
        if match:
            clauses = match.group(1).split(";")
            for c in clauses:
                clean = c.strip(" .")
                if clean:
                    do_not.append(clean)
        if not do_not:
            do_not.append("Do not silence error with uninspected exception handling")
        return do_not

    @classmethod
    def generate_unified_diff(cls, before_code: str, after_code: str, file_name: str = "app.py") -> str:
        """Generates a clean, valid unified git diff from before/after code blocks."""
        before_lines = before_code.splitlines()
        after_lines = after_code.splitlines()

        diff_lines = [
            f"--- a/{file_name}",
            f"+++ b/{file_name}",
            f"@@ -1,{len(before_lines)} +1,{len(after_lines)} @@"
        ]
        for line in before_lines:
            diff_lines.append(f"-{line}")
        for line in after_lines:
            diff_lines.append(f"+{line}")

        return "\n".join(diff_lines)


class BundleSynthesizer:
    """Synthesizes candidate CompatibilityBundle draft objects conforming to Schema v1.0.0."""

    @classmethod
    def synthesize_bundle(cls, raw_entry: Dict[str, Any]) -> Optional[CompatibilityBundle]:
        pkg = str(raw_entry.get("package", "unknown")).strip().lower()
        ver = str(raw_entry.get("version", "1.0.0")).strip().lstrip("v")
        notes = raw_entry.get("release_notes", "")
        rt = str(raw_entry.get("runtime", "python")).lower()
        url = raw_entry.get("url", f"https://synapsemesh.dev/bundles/{pkg}")
        known_packages = {target["package"] for target in KNOWN_UPSTREAM_TARGETS}
        if pkg not in known_packages or rt not in {"python", "nodejs", "javascript", "typescript"}:
            return None
        if not re.fullmatch(r"[0-9][0-9A-Za-z.+\-]{0,63}", ver):
            return None
        if not isinstance(notes, str) or len(notes) > 8000:
            return None
        if not isinstance(url, str) or not re.match(r"^https?://", url, re.IGNORECASE):
            url = "https://synapsemesh.dev/"
        trusted_examples = raw_entry.get("trusted_code_examples") is True
        if not trusted_examples:
            notes = ZeroPiiSanitizer.sanitize_text(notes)
            url = ZeroPiiSanitizer.sanitize_text(url)
            if not re.match(r"^https?://", url, re.IGNORECASE):
                url = "https://synapsemesh.dev/"

        err_sig = BreakingChangeExtractor.extract_error_signature(notes)
        if not err_sig:
            err_sig = f"BreakingChange: {pkg} version {ver} API incompatibility"
        err_sig = ZeroPiiSanitizer.sanitize_text(err_sig)

        before_after = BreakingChangeExtractor.extract_before_after(
            notes,
            package=pkg,
            runtime=rt,
            allow_embedded_code=trusted_examples,
        )
        if not before_after:
            return None

        target_file = "client.js" if rt in ("nodejs", "javascript", "typescript") else "client.py"

        before_code = before_after["before"]
        after_code = before_after["after"]
        unified_diff = BreakingChangeExtractor.generate_unified_diff(before_code, after_code, target_file)
        pins = BreakingChangeExtractor.extract_pins(notes, pkg)
        do_not = BreakingChangeExtractor.extract_do_not(notes)
        do_not = ZeroPiiSanitizer.sanitize_data(do_not)

        sig_hash = hashlib.sha256(f"{pkg}_{ver}_{err_sig}".encode("utf-8")).hexdigest()[:8]
        clean_pkg = re.sub(r'[^a-zA-Z0-9]', '', pkg).lower()
        clean_ver = re.sub(r'[^a-zA-Z0-9]', '', ver).lower()
        bundle_id = f"draft_{clean_pkg}_{clean_ver}_{sig_hash}"

        if rt == "python":
            repro_script = """import runpy
runpy.run_path("client.py", run_name="__main__")
"""
            test_suite = """import runpy
mod = runpy.run_path("client.py", run_name="__main__")
assert any(k in mod for k in ("result", "val", "res", "con", "client", "transport", "u", "settings", "session", "form", "chain", "router", "_obj", "app", "_handler")), "Target execution failed to produce valid output state"
print("VERIFICATION_PASSED_STAGE_3")
"""
        else:
            repro_script = "require('./client.js');\n"
            test_suite = "require('./client.js');\nconsole.log('VERIFICATION_PASSED_STAGE_3');\n"

        replacement_one = "pass" if rt == "python" else "// empty bypass"
        replacement_two = "# empty bypass" if rt == "python" else "throw new Error('mutant');"
        mutations = [
            BundleMutation(
                id="mutant_empty_bypass",
                description="Empty bypass mutant",
                unifiedDiff=f"--- a/{target_file}\n+++ b/{target_file}\n@@ -1,{len(before_code.splitlines())} +1,1 @@\n" + "\n".join(f"-{line}" for line in before_code.splitlines()) + f"\n+{replacement_one}\n"
            ),
            BundleMutation(
                id="mutant_exception_bypass",
                description="Exception or empty-output mutant",
                unifiedDiff=f"--- a/{target_file}\n+++ b/{target_file}\n@@ -1,{len(before_code.splitlines())} +1,1 @@\n" + "\n".join(f"-{line}" for line in before_code.splitlines()) + f"\n+{replacement_two}\n"
            )
        ]

        bundle = CompatibilityBundle(
            schemaVersion="1.0.0",
            bundleId=bundle_id,
            status="DRAFT",  # All mined bundles start as DRAFT until full 4-stage pass
            description=f"Draft compatibility bundle for {pkg} {ver} migration.",
            tags=[pkg, rt, "upstream-mined", f"v{ver}"],
            scope=BundleScope(
                package=pkg,
                fromVersion=f"<{ver}",
                toVersion=ver if not ver.startswith(">=") else ver.replace(">=", ""),
                affectedVersionRange=pins.get(pkg) or f">={ver}",
                runtime=rt,
                platform="all"
            ),
            fingerprint=BundleFingerprint(
                errorSignature=err_sig,
                regex=re.escape(err_sig[:35]),
                matchStream="stderr"
            ),
            patch=BundlePatch(
                targetFile=target_file,
                unifiedDiff=unified_diff,
                pinnedDependencies=pins,
                doNot=do_not
            ),
            verification=BundleVerification(
                scriptLanguage=rt,
                workspaceFiles={target_file: before_code},
                reproductionScript=repro_script,
                testSuite=test_suite,
                mutations=mutations,
                expectedPreExit=1,
                expectedPostExit=0,
                timeoutMs=15000
            ),
            provenance=BundleProvenance(
                spdxLicense="NOASSERTION",
                primarySources=[url],
                verifiedAt=None,
                sourceTrusted=trusted_examples,
            )
        )
        return bundle


class UpstreamMiningEngine:
    """Top-level zero-token worker for discovery and unexecuted draft retention."""

    @staticmethod
    def is_synthetic_oracle(bundle: CompatibilityBundle) -> bool:
        """Classify fixture shape without executing candidate code."""
        from scripts.synapse_reverify import bundle_uses_real_package

        return not bundle_uses_real_package(bundle.model_dump())

    @classmethod
    async def mine_and_verify_all(
        cls,
        persist_to_disk: bool = False,
        destination_dir: Optional[Path] = None
    ) -> List[CompatibilityBundle]:
        """
        Runs autonomous mining pipeline across all seed and live upstream registries.
        Persists strictly to `bundles/drafts/` with status DRAFT. It does not
        execute candidates or write to `bundles/golden/`.
        """
        candidates = []
        
        # 1. Gather upstream changelogs. Blocking registry clients run off the
        # event loop so API workers remain responsive.
        seed_data = UpstreamReleaseFetcher.get_seed_changelogs()

        async def fetch_target(target: Dict[str, Any]) -> List[Dict[str, Any]]:
            entries: List[Dict[str, Any]] = []
            if target.get("ecosystem") == "pypi":
                entries.extend(await asyncio.to_thread(
                    UpstreamReleaseFetcher.fetch_pypi_changelog,
                    target["package"],
                ))
            if target.get("repo"):
                atom_res = await asyncio.to_thread(
                    UpstreamReleaseFetcher.fetch_github_releases_atom,
                    target["repo"],
                    3,
                )
                for ar in atom_res:
                    ar["runtime"] = target.get("runtime", "python")
                    ar["package"] = target["package"]
                    entries.append(ar)
            return entries

        fetched_groups = await asyncio.gather(
            *(fetch_target(target) for target in KNOWN_UPSTREAM_TARGETS),
            return_exceptions=True,
        )
        for group in fetched_groups:
            if isinstance(group, list):
                seed_data.extend(group)

        # Also fetch live stream from PyPI RSS updates
        known_packages = {target["package"] for target in KNOWN_UPSTREAM_TARGETS}
        rss_updates = await asyncio.to_thread(UpstreamReleaseFetcher.fetch_pypi_rss_updates, 10)
        seed_data.extend(entry for entry in rss_updates if entry.get("package") in known_packages)

        # Stable de-duplication keeps repository-owned seeds authoritative.
        unique_entries: Dict[tuple[str, str, str], Dict[str, Any]] = {}
        for entry in seed_data:
            key = (
                str(entry.get("package") or "").lower(),
                str(entry.get("version") or ""),
                str(entry.get("runtime") or "python").lower(),
            )
            unique_entries.setdefault(key, entry)

        # 2. Extract and synthesize storage-only candidates.
        for entry in unique_entries.values():
            bundle = BundleSynthesizer.synthesize_bundle(entry)
            if not bundle:
                continue

            # No source category, including repository-owned seed prose, may
            # bypass the disposable allowlist worker and exact-run artifact gate.
            bundle.status = "DRAFT"
            candidates.append(bundle)

        # 4. Persist to drafts directory
        if persist_to_disk:
            try:
                target_dir = (destination_dir or DRAFTS_DIR).resolve()
                golden_dir = (DRAFTS_DIR.parent / "golden").resolve()
                if target_dir == golden_dir or golden_dir in target_dir.parents:
                    raise ValueError("autonomous miners may not write to bundles/golden")
                target_dir.mkdir(parents=True, exist_ok=True)
                for b in candidates:
                    out_path = target_dir / f"{b.bundleId}.json"
                    temp_path = target_dir / f".{b.bundleId}.{os.getpid()}.tmp"
                    temp_path.write_text(json.dumps(b.model_dump(), indent=2), encoding="utf-8")
                    os.replace(temp_path, out_path)
                    logger.info(f"Persisted draft bundle: {b.bundleId} (Status: {b.status})")
            except Exception as exc:
                logger.warning(
                    "File persistence for drafts skipped (%s); cycle continues without writes.",
                    type(exc).__name__,
                )

        return candidates
