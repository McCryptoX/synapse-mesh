import pytest
import asyncio
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.core.signature_matcher import SignatureMatcher
from app.core.sandbox import SandboxRunner


@pytest.mark.asyncio
async def test_submission_without_mutations_receives_provisional_tier():
    """
    Ensures that submitting a recipe without mutations is strictly labeled as PROVISIONAL
    (tier: COMMUNITY_UNMUTATED_PROVISIONAL, confidence: 0.65), preventing label dilution.
    """
    repro = "import sys\nprint('CustomError: test unmutated')\nsys.exit(1)\n"
    test_suite = "import sys\nprint('PASS')\nsys.exit(0)\n"

    evidence = await SandboxRunner.verify_recipe_full(
        runtime="python",
        error_signature="CustomError: test unmutated",
        repro_script=repro,
        test_suite=test_suite,
        mutations=None
    )

    assert evidence.verificationStatus == "PROVISIONAL"
    assert evidence.confidenceScore == 0.65
    assert evidence.mutationsKilled == "0/0"


@pytest.mark.asyncio
async def test_submission_with_multi_mutations_receives_verified():
    """
    Ensures that only recipes with >=2 killed mutations receive full VERIFIED status (0.99).
    """
    repro = "import sys\nprint('CustomError: test mutated')\nsys.exit(1)\n"
    test_suite = "import sys\nprint('PASS')\nsys.exit(0)\n"
    mut1 = "import sys\nsys.exit(1)\n"
    mut2 = "import sys\nsys.exit(1)\n"

    evidence = await SandboxRunner.verify_recipe_full(
        runtime="python",
        error_signature="CustomError: test mutated",
        repro_script=repro,
        test_suite=test_suite,
        mutations=[mut1, mut2]
    )

    assert evidence.verificationStatus == "VERIFIED"
    assert evidence.confidenceScore == 0.99
    assert evidence.mutationsKilled == "2/2"


def test_signature_matcher_rejects_exception_class_mismatch():
    """
    Ensures that queries with differing exception classes (e.g. TypeError vs ValueError)
    are strictly rejected, preventing false-positive token bleed.
    """
    q = "TypeError: unsupported operand type for +: 'int' and 'str'"
    t = "ValueError: unsupported operand type for +: 'int' and 'str'"

    is_matched, conf = SignatureMatcher.compute_match(q, t)
    assert not is_matched
    assert conf == 0.0
