import asyncio
import glob
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

from app.database import init_db, get_db_connection
from scripts.batch_importer import process_candidate_recipes

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
    """Automated, rate-limited release notes crawler and batch verification ingester."""

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
        except Exception as e:
            logger.debug(f"Atom feed fallback for {owner}/{repo} error: {e}")

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
        """Runs the harvest pipeline and executes automated sandbox verification across all candidate batches."""
        await init_db()
        logger.info(f"=== 1. Starting GitHub Release Scan across {len(TARGET_REPOSITORIES)} repositories ===")

        total_extracted = 0

        for target in TARGET_REPOSITORIES:
            owner, repo, runtime = target["owner"], target["repo"], target["runtime"]
            logger.info(f"Scanning releases for {owner}/{repo} ({runtime})...")
            releases = await self.fetch_releases(owner, repo, limit=3)
            
            for rel in releases:
                tag = rel.get("tag_name", "unknown")
                body = rel.get("body", "")
                sections = self.extract_breaking_sections(body)
                if sections:
                    total_extracted += len(sections)

            await asyncio.sleep(0.3)

        logger.info(f"Scan complete: Found {total_extracted} breaking change sections.")

        # 2. Process and verify all candidate batches into database
        logger.info("=== 2. Running Automated Sandbox Verification & Batch Ingestion ===")
        data_dir = Path("data")
        batch_files = sorted(glob.glob(str(data_dir / "candidate_recipes*.json")))
        
        for batch_file in batch_files:
            logger.info(f"Processing candidate batch: {batch_file}")
            await process_candidate_recipes(batch_file)

        logger.info("=== Harvester & Verification Pipeline Complete! ===")


if __name__ == "__main__":
    harvester = GitHubReleaseHarvester()
    asyncio.run(harvester.harvest_and_ingest())
