"""Compatibility configuration for legacy API tests.

New authorization tests must set ``enforce_project_authorization=True``
explicitly. Production defaults to enforcement and does not read this test-only
environment value.
"""

import os

os.environ.setdefault("ENFORCE_PROJECT_AUTHORIZATION", "false")
