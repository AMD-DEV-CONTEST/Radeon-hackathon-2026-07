"""Pytest setup for web/backend tests: put backend on sys.path + isolate data dir."""

import os
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

# Isolate runtime data (SQLite DB + job artifacts) into a temp dir.
os.environ.setdefault("LIVE_SCIENCE_DATA_DIR", tempfile.mkdtemp(prefix="live-science-test-"))
