"""
governance.states -- fixture/verifier admission state machine
=============================================================
The canonical states a test fixture or verifier passes through (detected ->
classified -> ... -> admitted / refused / blocked). Consolidated (2026-06-14)
from scripts/status/_shared_state_terms.py. Used to keep fixture admission and
support-depth promotion honest and explicit rather than implicit.
"""

from __future__ import annotations

FIXTURE_ADMISSION_STATES = [
    "detected",
    "classified",
    "routed",
    "fixture_required",
    "fixture_candidate",
    "fixture_admitted_static",
    "fixture_admitted_build_candidate",
    "fixture_admitted_test_candidate",
    "fixture_admitted_smoke_candidate",
    "verifier_candidate",
    "support_depth_candidate",
    "support_depth_promoted",
    "refused",
    "deferred",
    "blocked",
]

SCAFFOLD_BUILD_TEST_SMOKE_STATES = [
    "detected",
    "classified",
    "routed",
    "fixture_required",
    "fixture_candidate",
    "fixture_admitted_static",
    "fixture_admitted_build_candidate",
    "scaffold_candidate",
    "scaffold_blocked",
    "build_candidate",
    "build_blocked",
    "test_candidate",
    "test_blocked",
    "smoke_candidate",
    "smoke_blocked",
    "support_depth_candidate",
    "support_depth_promoted",
    "refused",
    "deferred",
    "blocked",
]

STATE_SEPARATION_CONCEPTS = [
    "fixture_admission",
    "verifier_inventory",
    "scaffold_candidacy",
    "build_candidacy",
    "test_candidacy",
    "smoke_candidacy",
    "support_depth_candidacy",
    "support_depth_promotion",
    "release_support",
]


def state_separation_map() -> dict[str, bool]:
    return {name: True for name in STATE_SEPARATION_CONCEPTS}


def is_admission_state(state: str) -> bool:
    return state in FIXTURE_ADMISSION_STATES or state in SCAFFOLD_BUILD_TEST_SMOKE_STATES
