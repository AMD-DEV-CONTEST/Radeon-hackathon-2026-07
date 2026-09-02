"""Contract tests for the UI-2 task workbench (run under `make test-governance`).

These back the UI-2 acceptance criteria: the frontend keeps a display-only
mirror of the task lifecycle (statuses + allowed transitions) so it can offer
only legal target statuses, while the server stays the single authority. The
tests statically compare the mirror in ``web/src/api/dto.ts`` against the
backend sources of truth.
"""
import os
import sys
import unittest

# Allow running both via `python -m unittest` (with PYTHONPATH=.) and directly.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from app.schemas.models import PhaseFTaskStatus  # noqa: E402
from app.schemas.task_sql import ALLOWED_TRANSITIONS  # noqa: E402
from scripts.validate_task_ui import (  # noqa: E402
    DTO_PATH,
    parse_frontend_statuses,
    parse_frontend_transitions,
)


class TaskUiLifecycleMirrorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = DTO_PATH.read_text(encoding="utf-8")

    def test_status_union_matches_backend_enum(self):
        self.assertEqual(
            [status.value for status in PhaseFTaskStatus],
            parse_frontend_statuses(self.source),
        )

    def test_transition_graph_matches_backend(self):
        self.assertEqual(
            {key: list(values) for key, values in ALLOWED_TRANSITIONS.items()},
            parse_frontend_transitions(self.source),
        )

    def test_final_states_have_no_outgoing_edges(self):
        transitions = parse_frontend_transitions(self.source)
        self.assertEqual([], transitions["completed"])
        self.assertEqual([], transitions["cancelled"])


if __name__ == "__main__":
    unittest.main()
