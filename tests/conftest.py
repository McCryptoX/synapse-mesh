import pytest
import os
import tempfile
from app.config import settings
from app.database import init_db

# Use an isolated test database for pytest runs
TEST_DB_PATH = os.path.join(tempfile.gettempdir(), "test_synapse_mesh.sqlite3")
settings.db_path = TEST_DB_PATH


@pytest.fixture(autouse=True, scope="session")
def setup_test_db():
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)
    yield
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)
