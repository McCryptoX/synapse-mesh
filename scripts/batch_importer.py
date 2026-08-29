import asyncio
import json
import logging
import re
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

logging.basicConfig(level="INFO", format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("batch_importer")


async def process_candidate_recipes(json_file_path: str, force_reverify: bool = False):
    """Import legacy candidates as sanitized, unexecuted drafts.

    The historical batch files contain executable puppet fixtures.  They are
    retained as discovery material but can never be promoted by this importer.
    ``force_reverify`` is accepted for CLI compatibility and has no execution
    semantics.
    """
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

        if not isinstance(recipe_id, str) or not re.fullmatch(r"rec_[a-z0-9_-]{3,120}", recipe_id):
            skipped_count += 1
            logger.warning("Skipping candidate with invalid or reserved identifier")
            continue
        
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

        # 2. Fail-closed evidence: no legacy candidate code is executed here.
        evidence = EvidenceDefinition(
            verificationStatus="DRAFT",
            verificationNote="Legacy candidate imported without execution; structured four-stage verification is required.",
            primarySource=(
                ZeroPiiSanitizer.sanitize_text(primary_source)
                if isinstance(primary_source, str) and primary_source.startswith(("http://", "https://"))
                else None
            ),
        )
        draft_count += 1
        logger.info("[~ DRAFT] %s (%s) imported without execution", recipe_id, runtime)

        # 3. Store in Database with short-lived connection
        prob = ProblemDefinition(
            errorSignature=sanitized_error,
            runtime=runtime.lower(),
            description=sanitized_desc,
            packages=ZeroPiiSanitizer.sanitize_data(prob_dict.get("packages", {}))
        )
        sol = SolutionDefinition(
            summary=sanitized_summary,
            codeDiff=ZeroPiiSanitizer.sanitize_text(diff),
            patchDiff=ZeroPiiSanitizer.sanitize_text(diff),
            instructions=ZeroPiiSanitizer.sanitize_data(sol_dict.get("instructions", [])),
            pinnedDependencies=ZeroPiiSanitizer.sanitize_data(pinned_deps),
            doNot=ZeroPiiSanitizer.sanitize_data(do_not)
        )
        repro = ReproductionDefinition(
            script=ZeroPiiSanitizer.sanitize_text(repro_script),
            testSuite=ZeroPiiSanitizer.sanitize_text(test_suite)
        )

        try:
            db = await get_db_connection()
            await db.execute("""
                INSERT INTO recipes (
                    id, runtime, error_signature, problem_json, solution_json, 
                    reproduction_json, evidence_json, confidence_score, verification_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    runtime = excluded.runtime,
                    error_signature = excluded.error_signature,
                    problem_json = excluded.problem_json,
                    solution_json = excluded.solution_json,
                    reproduction_json = excluded.reproduction_json,
                    evidence_json = excluded.evidence_json,
                    confidence_score = excluded.confidence_score,
                    verification_status = 'DRAFT',
                    updated_at = CURRENT_TIMESTAMP
                WHERE recipes.verification_status <> 'VERIFIED'
            """, (
                recipe_id,
                runtime.lower(),
                sanitized_error,
                json.dumps(prob.model_dump()),
                json.dumps(sol.model_dump()),
                json.dumps(repro.model_dump()),
                json.dumps(evidence.model_dump(), default=str),
                0.0,
                evidence.verificationStatus
            ))
            await db.commit()
            await db.close()
        except Exception as dbe:
            logger.warning(f"Failed to persist {recipe_id} to database: {dbe}")

    logger.info(
        "=== Draft Import Completed: %s unexecuted drafts, %s invalid/reserved skipped ===",
        draft_count,
        skipped_count,
    )


if __name__ == "__main__":
    if len(sys.argv) > 1:
        target_file = sys.argv[1]
    else:
        target_file = "data/candidate_recipes.json"
    asyncio.run(process_candidate_recipes(target_file))
