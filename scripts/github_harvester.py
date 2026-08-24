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

from app.database import init_db, get_db_connection
from app.models.recipe import (
    VerifiedRecipe,
    ProblemDefinition,
    SolutionDefinition,
    ReproductionDefinition,
    EvidenceDefinition
)
from app.core.sanitizer import ZeroPiiSanitizer
from app.core.sandbox import SandboxRunner

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
    """Automated, rate-limited release notes and breaking changes crawler."""

    def __init__(self, github_token: Optional[str] = None):
        self.headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Synapse-Mesh-Harvester/1.0"
        }
        token = github_token or os.environ.get("GITHUB_TOKEN")
        if token:
            self.headers["Authorization"] = f"token {token}"

    async def fetch_releases(self, owner: str, repo: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Fetches the latest official releases from GitHub REST API with redirect following."""
        url = f"https://api.github.com/repos/{owner}/{repo}/releases?per_page={limit}"
        try:
            async with httpx.AsyncClient(timeout=10.0, headers=self.headers, follow_redirects=True) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    return resp.json()
                elif resp.status_code == 403:
                    logger.warning(f"Rate limited on GitHub API for {owner}/{repo} (HTTP 403).")
                    return []
                else:
                    logger.warning(f"Failed to fetch releases for {owner}/{repo}: HTTP {resp.status_code}")
                    return []
        except Exception as e:
            logger.error(f"Error fetching releases for {owner}/{repo}: {e}")
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

    async def harvest_all(self, max_recipes: int = 20):
        """Runs the harvest pipeline across target repositories and feeds the sandbox."""
        await init_db()
        logger.info(f"Starting GitHub Release Harvester across {len(TARGET_REPOSITORIES)} repositories...")

        total_extracted = 0

        for target in TARGET_REPOSITORIES:
            owner, repo, runtime = target["owner"], target["repo"], target["runtime"]
            logger.info(f"Fetching releases for {owner}/{repo} ({runtime})...")
            releases = await self.fetch_releases(owner, repo, limit=5)
            
            for rel in releases:
                tag = rel.get("tag_name", "unknown")
                html_url = rel.get("html_url", f"https://github.com/{owner}/{repo}")
                body = rel.get("body", "")
                
                sections = self.extract_breaking_sections(body)
                if sections:
                    logger.info(f"  ✓ Found {len(sections)} breaking/change sections in {repo} {tag}")
                    total_extracted += len(sections)

            # Brief pause to respect API rate limits
            await asyncio.sleep(0.4)

        logger.info(f"=== Harvester Finished: Scanned {len(TARGET_REPOSITORIES)} Repos, Found {total_extracted} Change Sections ===")


if __name__ == "__main__":
    harvester = GitHubReleaseHarvester()
    asyncio.run(harvester.harvest_all())
