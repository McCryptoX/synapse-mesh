#!/usr/bin/env python3
"""
Synapse-Mesh Autonomous Evidence Pipeline CLI
=============================================

Runs the complete autonomous bridge for candidate drafts:
  Draft Ingestion -> Eligibility Gate -> Environment Preparation ->
  4-Stage Empirical Verification -> Cryptographic Evidence Run Artifact ->
  Machine-Qualified MCP Discovery.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.autonomous_pipeline import AutonomousPipelineOrchestrator, DRAFTS_DIR, EVIDENCE_RUNS_DIR

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("synapse_mesh.cli.pipeline")


def process_draft_file(draft_path: Path) -> bool:
    print(f"\n========================================================")
    print(f"[*] Processing Draft: {draft_path.name}")
    print(f"========================================================")
    
    result = AutonomousPipelineOrchestrator.process_draft_bundle(draft_path)
    if result.get("success"):
        print(f"\n[✓] SUCCESS: Draft '{result.get('bundleId')}' is verified and published!")
        print(f"    - Target Package: {result.get('package')} ({result.get('version')})")
        print(f"    - Observed Toolchains: {result.get('toolchainVersions')}")
        print(f"    - Mutations Killed: {result.get('mutationsKilled')}")
        print(f"    - Evidence Artifact: {result.get('artifactPath')}")
        return True
    else:
        print(f"\n[✗] FAILED: Draft '{draft_path.name}' was not qualified.")
        print(f"    - Rejection Code: {result.get('rejectionCode')}")
        print(f"    - Reason: {result.get('reason')}")
        return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Synapse-Mesh Autonomous Evidence Pipeline"
    )
    parser.add_argument(
        "--draft-path",
        type=Path,
        help="Path to a specific draft bundle JSON file",
    )
    parser.add_argument(
        "--all-drafts",
        action="store_true",
        help="Scan and attempt verification on all JSON files in bundles/drafts/",
    )

    args = parser.parse_args()

    if args.draft_path:
        success = process_draft_file(args.draft_path)
        return 0 if success else 1

    elif args.all_drafts:
        drafts = sorted(DRAFTS_DIR.glob("*.json"))
        if not drafts:
            print("[!] No draft files found in bundles/drafts/")
            return 0

        print(f"[*] Found {len(drafts)} drafts in {DRAFTS_DIR}")
        passed_count = 0
        failed_count = 0

        for draft_path in drafts:
            if process_draft_file(draft_path):
                passed_count += 1
            else:
                failed_count += 1

        print(f"\n========================================================")
        print(f"Pipeline Summary: {passed_count} verified & published, {failed_count} rejected/deferred.")
        print(f"========================================================")
        return 0

    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
