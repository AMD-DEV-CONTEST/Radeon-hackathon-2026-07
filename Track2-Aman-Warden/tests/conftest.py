"""Shared test fixtures for Warden test suite."""

import sys
from pathlib import Path

# Ensure the project root is on the path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
