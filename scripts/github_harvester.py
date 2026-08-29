import asyncio
import httpx
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import init_db
from app.core.sanitizer import ZeroPiiSanitizer

logging.basicConfig(level="INFO", format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("github_harvester")

# High-impact repositories with frequent breaking changes / migration guides
TARGET_REPOSITORIES = [
    # Python
    {"owner": "fastapi", "repo": "fastapi", "runtime": "python"},
    {"owner": "pydantic", "repo": "pydantic", "runtime": "python"},
    {"owner": "encode", "repo": "httpx", "runtime": "python"},
    {"owner": "pytest-dev", "repo": "pytest", "runtime": "python"},
    {"owner": "sqlalchemy", "repo": "sqlalchemy", "runtime": "python"},
    {"owner": "pallets", "repo": "flask", "runtime": "python"},
    # JavaScript / TypeScript
    {"owner": "vercel", "repo": "next.js", "runtime": "nodejs"},
    {"owner": "facebook", "repo": "react", "runtime": "nodejs"},
    {"owner": "expressjs", "repo": "express", "runtime": "nodejs"},
    {"owner": "microsoft", "repo": "TypeScript", "runtime": "nodejs"},
    {"owner": "vitejs", "repo": "vite", "runtime": "nodejs"},
    # Docker
    {"owner": "docker", "repo": "compose", "runtime": "docker"}
]


class GitHubReleaseHarvester:
    """Automated, rate-limited release-note crawler and draft synthesizer."""

    def __init__(self, github_token: Optional[str] = None):
        self.headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Synapse-Mesh-Harvester/1.0"
        }
        token = github_token or os.environ.get("GITHUB_TOKEN")
        if token:
            self.headers["Authorization"] = f"token {token}"

    async def fetch_releases(self, owner: str, repo: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Fetches the latest official releases with automatic Atom feed fallback (zero API rate-limits)."""
        url = f"https://api.github.com/repos/{owner}/{repo}/releases?per_page={limit}"
        try:
            async with httpx.AsyncClient(timeout=10.0, headers=self.headers, follow_redirects=True) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    return resp.json()
        except Exception:
            pass

        # Rate-limit-free GitHub Atom RSS Feed fallback
        try:
            import xml.etree.ElementTree as ET
            atom_url = f"https://github.com/{owner}/{repo}/releases.atom"
            async with httpx.AsyncClient(timeout=10.0, headers={"User-Agent": "Synapse-Mesh-Harvester/1.0"}, follow_redirects=True) as client:
                resp = await client.get(atom_url)
                if resp.status_code == 200:
                    root = ET.fromstring(resp.text)
                    ns = {"atom": "http://www.w3.org/2005/Atom"}
                    items = []
                    for entry in root.findall("atom:entry", ns)[:limit]:
                        title = entry.findtext("atom:title", "", ns)
                        content = entry.findtext("atom:content", "", ns)
                        items.append({
                            "tag_name": title,
                            "name": title,
                            "body": content
                        })
                    return items
        except Exception as exc:
            logger.debug("Atom feed fallback failed for %s/%s (%s)", owner, repo, type(exc).__name__)

        return []

    def extract_breaking_sections(self, body: str) -> List[str]:
        """Extracts text sections dealing with breaking changes, deprecations, or major migrations."""
        if not body:
            return []
        
        keywords = ["breaking", "deprecated", "removed", "migration", "incompatible", "notable", "changes", "upgrade"]
        sections = []
        
        lines = body.split("\n")
        current_section = []
        is_relevant = False

        for line in lines:
            if line.startswith("#"):
                if is_relevant and current_section:
                    sections.append("\n".join(current_section))
                    current_section = []
                is_relevant = any(k in line.lower() for k in keywords)
            
            if is_relevant:
                current_section.append(line)

        if is_relevant and current_section:
            sections.append("\n".join(current_section))

        return sections

    async def harvest_and_ingest(self):
        """Crawl upstream release notes and synthesize unexecuted drafts.

        Release bodies are third-party input.  They are never executed by this
        service; promotion requires a separate verification boundary.
        """
        await init_db()
        logger.info(f"=== 1. Starting GitHub Release Scan across {len(TARGET_REPOSITORIES)} repositories ===")

        crawled_entries: List[Dict[str, Any]] = []
        total_extracted = 0

        for target in TARGET_REPOSITORIES:
            owner, repo, runtime = target["owner"], target["repo"], target["runtime"]
            logger.info(f"Scanning releases for {owner}/{repo} ({runtime})...")
            releases = await self.fetch_releases(owner, repo, limit=3)

            for rel in releases:
                tag = str(rel.get("tag_name") or rel.get("name") or "unknown")
                body = rel.get("body") or ""
                sections = self.extract_breaking_sections(body)
                if sections:
                    total_extracted += len(sections)
                    notes = "\n\n".join(sections)
                else:
                    notes = body
                if notes and len(notes.strip()) >= 40:
                    pkg = repo.replace(".js", "").lower()
                    clean_notes = ZeroPiiSanitizer.sanitize_text(notes[:8000])
                    clean_url = ZeroPiiSanitizer.sanitize_text(
                        f"https://github.com/{owner}/{repo}/releases"
                    )
                    crawled_entries.append({
                        "package": pkg,
                        "version": tag.lstrip("v"),
                        "runtime": "python" if runtime == "docker" else runtime,
                        "release_notes": clean_notes,
                        "url": clean_url,
                    })

            await asyncio.sleep(0.3)

        logger.info(
            f"Scan complete: {total_extracted} breaking-change sections, "
            f"{len(crawled_entries)} release notes queued for synthesis."
        )

        # 2. Synthesize unexecuted drafts (never golden/).
        logger.info("=== 2. Synthesize crawled notes as unexecuted drafts ===")
        try:
            from app.core.upstream_miner import (
                BundleSynthesizer,
                DRAFTS_DIR,
            )

            DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
            synthesized = 0
            for entry in crawled_entries[:24]:
                entry["trusted_code_examples"] = False
                bundle = BundleSynthesizer.synthesize_bundle(entry)
                if not bundle:
                    continue
                synthesized += 1
                bundle.status = "DRAFT"
                out_path = DRAFTS_DIR / f"{bundle.bundleId}.json"
                temp_path = DRAFTS_DIR / f".{bundle.bundleId}.{os.getpid()}.tmp"
                temp_path.write_text(json.dumps(bundle.model_dump(), indent=2), encoding="utf-8")
                os.replace(temp_path, out_path)
            logger.info("Crawled synthesis: %s unexecuted drafts.", synthesized)
        except Exception as exc:
            logger.warning("Crawled draft synthesis failed (%s)", type(exc).__name__)

        # Historical candidate batches contain executable puppet fixtures.  The
        # autonomous service intentionally does not run or promote them.
        logger.info("=== 3. Legacy executable candidate batches skipped (fail closed) ===")

        logger.info("=== Harvester & Verification Pipeline Complete! ===")


if __name__ == "__main__":
    harvester = GitHubReleaseHarvester()
    asyncio.run(harvester.harvest_and_ingest())
