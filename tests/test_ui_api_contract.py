"""Contract tests for the UI-0 web workbench (run under `make test-governance`).

These back the UI-0 acceptance criteria by asserting that the frontend DTO
field names and the declared API path constants stay consistent with the
backend FastAPI Schema/routes. They are server-less: the backend models and
routes are inspected statically.
"""
import os
import sys
import unittest

# Allow running both via `python -m unittest` (with PYTHONPATH=.) and directly.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from scripts.validate_ui_contract import (  # noqa: E402
    validate_dto_fields,
    validate_paths,
)


class UiApiContractTests(unittest.TestCase):
    def test_dto_fields_match_backend_schema(self):
        errors = validate_dto_fields()
        self.assertEqual([], errors, "\n".join(errors))

    def test_paths_match_backend_routes(self):
        errors = validate_paths()
        self.assertEqual([], errors, "\n".join(errors))


if __name__ == "__main__":
    unittest.main()
