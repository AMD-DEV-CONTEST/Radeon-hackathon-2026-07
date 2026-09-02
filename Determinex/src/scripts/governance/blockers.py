"""
governance.blockers -- the canonical blocker taxonomy
=====================================================
One vocabulary for "why can't this proceed", consolidated (2026-06-14) from
scripts/status/_shared_blocker_taxonomy.py. This is the project-level cousin of
the Adjudicator's per-failure verdicts: the Adjudicator says what MOVE resolves a
single failure (ROUTE/MATCH/UNBLOCK/IMPOSSIBLE); this says what CLASS of external
gate is blocking a whole tool/task. ADJUDICATOR_VERDICT_HINT maps each blocker to
the amplifier verdict it most resembles, so the two taxonomies stay aligned
instead of drifting into two unrelated vocabularies.
"""

from __future__ import annotations

BLOCKER_ORDER = [
    "TOOLCHAIN_MISSING_OR_UNVERIFIED",
    "HARDWARE_OR_TOOLCHAIN_REQUIRED",
    "LOCAL_VERIFIER_REQUIRED",
    "MULTI_SERVICE_LOCAL_VERIFIER_REQUIRED",
    "SECURITY_REVIEW_REQUIRED",
    "PROVIDER_OR_NETWORK_GATE_REQUIRED",
    "LICENSE_OR_COMMERCIAL_REVIEW_REQUIRED",
    "PARSER_OR_DETECTOR_REQUIRED",
    "REGISTRY_INGESTION_REQUIRED",
    "CONCRETE_FIXTURE_REQUIRED",
    "AUTHORITY_GATE_REQUIRED",
]

REQUIRED_BLOCKER_COUNTS = {
    "LOCAL_VERIFIER_REQUIRED": 87,
    "TOOLCHAIN_MISSING_OR_UNVERIFIED": 37,
    "LICENSE_OR_COMMERCIAL_REVIEW_REQUIRED": 11,
    "HARDWARE_OR_TOOLCHAIN_REQUIRED": 9,
    "SECURITY_REVIEW_REQUIRED": 6,
    "PROVIDER_OR_NETWORK_GATE_REQUIRED": 4,
    "CONCRETE_FIXTURE_REQUIRED": 1,
    "PARSER_OR_DETECTOR_REQUIRED": 1,
    "REGISTRY_INGESTION_REQUIRED": 1,
    "MULTI_SERVICE_LOCAL_VERIFIER_REQUIRED": 0,
    "AUTHORITY_GATE_REQUIRED": 0,
}

LANGUAGE_UNIVERSE_BLOCKERS = [
    *BLOCKER_ORDER,
    "TRAINING_PRIVACY_REVIEW_REQUIRED",
    "NOT_CLAIMED",
]

# Keep the project blocker taxonomy aligned with the Adjudicator's verdicts.
# (See scripts/determinex_adjudicator.py Verdict.)
ADJUDICATOR_VERDICT_HINT = {
    "TOOLCHAIN_MISSING_OR_UNVERIFIED": "MATCH",  # install / reproduce env
    "HARDWARE_OR_TOOLCHAIN_REQUIRED": "MATCH",
    "LOCAL_VERIFIER_REQUIRED": "MATCH",
    "MULTI_SERVICE_LOCAL_VERIFIER_REQUIRED": "MATCH",
    "PROVIDER_OR_NETWORK_GATE_REQUIRED": "MATCH",
    "CONCRETE_FIXTURE_REQUIRED": "UNBLOCK",  # provide the missing fixture
    "REGISTRY_INGESTION_REQUIRED": "UNBLOCK",
    "PARSER_OR_DETECTOR_REQUIRED": "NEEDS_WORK",
    "SECURITY_REVIEW_REQUIRED": "IMPOSSIBLE",  # external human gate
    "LICENSE_OR_COMMERCIAL_REVIEW_REQUIRED": "IMPOSSIBLE",
    "AUTHORITY_GATE_REQUIRED": "IMPOSSIBLE",
}


def blocker_counts_template() -> dict[str, int]:
    return {blocker: 0 for blocker in BLOCKER_ORDER}


def required_blocker_counts() -> dict[str, int]:
    return dict(REQUIRED_BLOCKER_COUNTS)


def is_known_blocker(blocker: str) -> bool:
    return blocker in LANGUAGE_UNIVERSE_BLOCKERS
