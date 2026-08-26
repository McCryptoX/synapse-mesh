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
    ProblemDefinition,
    SolutionDefinition,
    ReproductionDefinition,
    EvidenceDefinition
)
from app.core.sanitizer import ZeroPiiSanitizer
from app.core.sandbox import SandboxRunner

logging.basicConfig(level="INFO", format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("batch_importer")


async def process_candidate_recipes(json_file_path: str, force_reverify: bool = False):
    """Loads candidate recipes, runs genuine 4-stage sandbox verification on new/changed items, and stores verified ones."""
    await init_db()
    path = Path(json_file_path)
    if not path.exists():
        logger.error(f"File {json_file_path} not found.")
        return

    with open(path, "r", encoding="utf-8") as f:
        candidates = json.load(f)

    logger.info(f"Loaded {len(candidates)} candidate recipes from {path.name}.")
    
    verified_count = 0
    draft_count = 0
    failed_count = 0
    skipped_count = 0

    for idx, item in enumerate(candidates, 1):
        recipe_id = item.get("id") or f"rec_ingest_{idx:03d}"

        # 0. Incremental Ingestion Gate: Skip if already verified in DB unless force_reverify is requested
        if not force_reverify:
            try:
                db_check = await get_db_connection()
                cur = await db_check.execute("SELECT verification_status FROM recipes WHERE id = ?", (recipe_id,))
                row = await cur.fetchone()
                await db_check.close()
                if row and row["verification_status"] == "VERIFIED":
                    skipped_count += 1
                    verified_count += 1
                    continue
            except Exception:
                pass
        
        prob_dict = item.get("problem", {})
        sol_dict = item.get("solution", {})
        repro_dict = item.get("reproduction", {})
        evi_dict = item.get("evidence", {})

        runtime = item.get("runtime") or prob_dict.get("runtime", "python")
        error_sig = item.get("errorSignature") or prob_dict.get("errorSignature", "")
        desc = item.get("description") or prob_dict.get("description", "")
        summary = item.get("summary") or sol_dict.get("explanation", "")
        diff = item.get("codeDiff") or sol_dict.get("patchDiff", "")
        pinned_deps = sol_dict.get("pinnedDependencies") or prob_dict.get("packages", {})
        do_not = sol_dict.get("doNot", [])
        mutations = item.get("mutations", [])
        
        repro_script = item.get("reproScript") or repro_dict.get("script", "")
        test_suite = item.get("testSuite") or repro_dict.get("testSuite", "")
        primary_source = item.get("primarySource") or evi_dict.get("primarySource", "")

        # 1. Sanitize Data
        sanitized_desc = ZeroPiiSanitizer.sanitize_text(desc)
        sanitized_summary = ZeroPiiSanitizer.sanitize_text(summary)
        sanitized_error = ZeroPiiSanitizer.sanitize_text(error_sig)

        # 2. Genuine 4-Stage Sandbox Verification
        evidence = await SandboxRunner.verify_recipe_full(
            runtime=runtime,
            error_signature=sanitized_error,
            repro_script=repro_script,
            test_suite=test_suite,
            mutations=mutations,
            primary_source=primary_source
        )

        if evidence.verificationStatus == "VERIFIED":
            verified_count += 1
            logger.info(f"[✓ VERIFIED] {recipe_id} ({runtime}) -> Pre:{evidence.preExit} Post:{evidence.postExit} Mut:{evidence.mutationsKilled}")
        elif evidence.verificationStatus in ("PROVISIONAL", "DRAFT"):
            draft_count += 1
            logger.info(f"[~ {evidence.verificationStatus}] {recipe_id} ({runtime}) -> Status {evidence.verificationStatus}, awaiting mutations.")
        else:
            failed_count += 1
            logger.warning(f"[✗ FAILED] {recipe_id} ({runtime}) -> Sandbox Exit {evidence.sandboxExitCode}")

        # 3. Store in Database with short-lived connection
        prob = ProblemDefinition(
            errorSignature=sanitized_error,
            runtime=runtime.lower(),
            description=sanitized_desc,
            packages=prob_dict.get("packages", {})
        )
        sol = SolutionDefinition(
            summary=sanitized_summary,
            codeDiff=diff,
            patchDiff=diff,
            instructions=sol_dict.get("instructions", []),
            pinnedDependencies=pinned_deps,
            doNot=do_not
        )
        repro = ReproductionDefinition(
            script=repro_script,
            testSuite=test_suite
        )

        try:
            db = await get_db_connection()
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
            await db.close()
        except Exception as dbe:
            logger.warning(f"Failed to persist {recipe_id} to database: {dbe}")

    logger.info(f"=== Import Completed: {verified_count} VERIFIED ({skipped_count} incremental skips), {draft_count} PROVISIONAL/DRAFT, {failed_count} FAILED ===")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        target_file = sys.argv[1]
    else:
        target_file = "data/candidate_recipes.json"
    asyncio.run(process_candidate_recipes(target_file))
