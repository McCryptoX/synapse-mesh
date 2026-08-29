"""Deprecated legacy seeder.

The historical seed payloads did not carry the four-stage evidence contract and
must never be inserted as VERIFIED records. Curated bundles are synchronized by
``app.database.init_db``; untrusted candidates belong in ``bundles/drafts``.
"""

import asyncio
import logging

from app.database import init_db


logger = logging.getLogger("synapse_mesh.seed")


async def seed() -> None:
    """Initialize the schema and curated mirror without legacy recipe writes."""
    await init_db()
    logger.warning(
        "Legacy recipe seeding is disabled: records without the four-stage "
        "evidence contract are not imported."
    )


if __name__ == "__main__":
    logging.basicConfig(level="INFO")
    asyncio.run(seed())
