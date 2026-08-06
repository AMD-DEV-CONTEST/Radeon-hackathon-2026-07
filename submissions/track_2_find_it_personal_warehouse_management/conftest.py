"""Pytest session setup: isolate all tests from the real project DB/files.

This file is loaded before any test module, so it redirects ``main.DB_PATH``,
``main.UPLOAD_DIR`` and ``main.STAGING_DIR`` to a throwaway directory under
``/tmp``.  The global ``TestClient(main.app)`` created by test modules will
therefore use the temp paths, and any test that forgets to monkeypatch is still
safe.
"""

from __future__ import annotations

import atexit
import shutil
import tempfile
from pathlib import Path

import main

_test_root = Path(tempfile.mkdtemp(prefix="Find it_test_"))
main.DB_PATH = _test_root / "videos.db"
main.UPLOAD_DIR = _test_root / "uploads"
main.STAGING_DIR = main.UPLOAD_DIR / "_staging"
main.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
main.STAGING_DIR.mkdir(parents=True, exist_ok=True)


def _cleanup_test_root() -> None:
    shutil.rmtree(_test_root, ignore_errors=True)


atexit.register(_cleanup_test_root)
