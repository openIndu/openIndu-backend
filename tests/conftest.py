"""Shared test fixtures for unit and integration tests."""
import os
import tempfile

# Force SQLite before any app module is imported
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

import pytest


@pytest.fixture(scope="function")
def temp_data_dir():
    """Temporary directory for file storage tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir
