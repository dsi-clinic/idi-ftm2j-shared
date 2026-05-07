"""Configure pytest path so tests can import from src/idi-ftm2j-shared."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src" / "idi-ftm2j-shared"))
