"""
governance -- Determinex's consolidated no-overclaim guardrails
============================================================
The 254-line invariant core, extracted (2026-06-14) from the ~321k-line
status/proof campaign apparatus so the same "no claim without proof" discipline
the Correctness Amplifier enforces in code is enforced for product/release claims
too -- in ONE place, guarded by ONE meta-bench test.

Public API:
    AUTHORITY_FALSE, assert_authority_closed, scan_text_for_anchor_true
    BLOCKER_ORDER, ADJUDICATOR_VERDICT_HINT, is_known_blocker
    FIXTURE_ADMISSION_STATES, is_admission_state
    current_evidence_spine_count, make_proof_record
"""

from __future__ import annotations

from governance.authority import (  # noqa: F401
    AUTHORITY_FALSE,
    AUTHORITY_NEGATIVE_INVARIANTS,
    AUTHORITY_SCAN_TERMS,
    assert_authority_closed,
    authority_flags_are_closed,
    authority_payload_is_closed,
    closed_authority_flags,
    scan_text_for_anchor_true,
)
from governance.blockers import (  # noqa: F401
    ADJUDICATOR_VERDICT_HINT,
    BLOCKER_ORDER,
    LANGUAGE_UNIVERSE_BLOCKERS,
    REQUIRED_BLOCKER_COUNTS,
    blocker_counts_template,
    is_known_blocker,
    required_blocker_counts,
)
from governance.evidence import (  # noqa: F401
    current_evidence_spine_count,
    make_proof_record,
    verify_proof_record,
    write_proof_record,
)
from governance.states import (  # noqa: F401
    FIXTURE_ADMISSION_STATES,
    SCAFFOLD_BUILD_TEST_SMOKE_STATES,
    STATE_SEPARATION_CONCEPTS,
    is_admission_state,
    state_separation_map,
)
