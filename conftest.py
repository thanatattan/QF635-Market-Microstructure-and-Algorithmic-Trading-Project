"""Pytest config: ensure the project root is importable and provide a params fixture."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.config import load_params  # noqa: E402


@pytest.fixture
def params() -> dict:
    return load_params()