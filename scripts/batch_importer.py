import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import List, Dict, Any

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
logger = logging.getLogger("batch_importer")


async def process_candidate_recipes(json_file_path: str):
    """Loads candidate recipes, runs isolated sandbox verification, and saves verified ones."""
    await init_db()
    path = Path(json_file_path)
    if not path.exists():
        logger.error(f"File {json_file_path} not found.")
        return

    with open(path, "r", encoding="utf-8") as f:
        candidates = json.load(f)

    logger.info(f"Loaded {len(candidates)} candidate recipes for verification.")
    
    db = await get_db_connection()
    verified_count = 0
    failed_count = 0

    try:
        for idx, item in enumerate(candidates, 1):
            recipe_id = item.get("id") or f"rec_ingest_{idx:03d}"
            # Flexible support for flat or nested schema
            prob_dict = item.get("problem", {})
            sol_dict = item.get("solution", {})
            repro_dict = item.get("reproduction", {})
            evi_dict = item.get("evidence", {})

            runtime = item.get("runtime") or prob_dict.get("runtime", "python")
            error_sig = item.get("errorSignature") or prob_dict.get("errorSignature", "")
            desc = item.get("description") or prob_dict.get("description", "")
            summary = item.get("summary") or sol_dict.get("explanation", "")
            diff = item.get("codeDiff") or sol_dict.get("patchDiff", "")
            repro_script = item.get("reproScript") or repro_dict.get("script", "")
            test_suite = item.get("testSuite") or repro_dict.get("testSuite", "")
            primary_source = item.get("primarySource") or evi_dict.get("primarySource", "")

            # 1. Sanitize Data
            sanitized_desc = ZeroPiiSanitizer.sanitize_text(desc)
            sanitized_summary = ZeroPiiSanitizer.sanitize_text(summary)
            sanitized_error = ZeroPiiSanitizer.sanitize_text(error_sig)

            # 2. Automated Sandbox Verification
            evidence = await SandboxRunner.verify_recipe(
                runtime=runtime,
                test_suite=test_suite,
                primary_source=primary_source
            )

            is_verified = (evidence.verificationStatus == "VERIFIED")
            if is_verified:
                verified_count += 1
                logger.info(f"[✓ PASS] {recipe_id} ({runtime}) -> {sanitized_error[:60]}...")
            else:
                failed_count += 1
                logger.warning(f"[✗ FAIL] {recipe_id} ({runtime}) -> Exit Code {evidence.sandboxExitCode}")

            # 3. Store in Database
            prob = ProblemDefinition(
                errorSignature=sanitized_error,
                runtime=runtime.lower(),
                description=sanitized_desc,
                packages=item.get("packages", {})
            )
            sol = SolutionDefinition(
                summary=sanitized_summary,
                codeDiff=diff,
                instructions=item.get("instructions", [])
            )
            repro = ReproductionDefinition(
                script=repro_script,
                testSuite=test_suite
            )

            await db.execute("""
                INSERT OR REPLACE INTO recipes (
                    id, runtime, error_signature, problem_json, solution_json, 
                    reproduction_json, evidence_json, confidence_score, verification_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                recipe_id,
                runtime.lower(),
                sanitized_error,
                json.dumps(prob.model_dump()),
                json.dumps(sol.model_dump()),
                json.dumps(repro.model_dump()),
                json.dumps(evidence.model_dump(), default=str),
                evidence.confidenceScore,
                evidence.verificationStatus
            ))

        await db.commit()
        logger.info(f"=== Batch Import Completed: {verified_count} Verified, {failed_count} Failed ===")
    finally:
        await db.close()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        target_file = sys.argv[1]
    else:
        target_file = "data/candidate_recipes.json"
    asyncio.run(process_candidate_recipes(target_file))
