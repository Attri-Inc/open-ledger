"""Test fixtures — point the app at a throwaway seeded database.

The env var is set at import time, before any `src.*` module (which reads
OPENLEDGER_DB via src.config) is imported by the test modules.
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_TMP_DB = Path(tempfile.mkdtemp(prefix="openledger-test-")) / "openledger.db"
os.environ["OPENLEDGER_DB"] = str(_TMP_DB)

# Make scripts/seed.py importable as `seed`.
sys.path.insert(0, str(ROOT / "scripts"))


@pytest.fixture(scope="session", autouse=True)
def _seed_database():
    """Seed the throwaway DB once for the whole test session."""
    import seed  # reads OPENLEDGER_DB (set above) at import time

    seed.main()
    yield
