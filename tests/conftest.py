import pytest
import os
import tempfile
import asyncio
from app.config import settings
from app.database import init_db

TEST_DB_PATH = os.path.join(tempfile.gettempdir(), "test_synapse_mesh.sqlite3")
settings.db_path = TEST_DB_PATH


@pytest.fixture(autouse=True, scope="session")
def setup_test_db():
    if os.path.exists(TEST_DB_PATH):
        try:
            os.remove(TEST_DB_PATH)
        except OSError:
            pass
    asyncio.run(init_db())
    yield
    if os.path.exists(TEST_DB_PATH):
        try:
            os.remove(TEST_DB_PATH)
        except OSError:
            pass
