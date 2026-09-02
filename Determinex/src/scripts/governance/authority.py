"""
governance.authority -- the anti-overclaim truth anchors
========================================================
The project's institutional memory of what it has NOT yet earned the right to
claim. Consolidated (2026-06-14) from scripts/status/_shared_authority_guards.py
so the same discipline the Correctness Amplifier enforces in code ("no claim
without proof") is enforced for product/release claims too. One canonical home,
guarded by one meta-bench test, instead of 1,175 generated lane tests.

Flip an anchor to True ONLY when it is genuinely, provably earned -- and then the
meta-bench's test_authority_closed will tell you the moment a claim outruns its
proof.
"""

from __future__ import annotations

from typing import Any

# Claims that MUST stay False until genuinely earned + proven.
AUTHORITY_FALSE: dict[str, bool] = {
    "release_ready": False,
    "launch_readiness_granted": False,
    "release_readiness_granted": False,
    "production_readiness_granted": False,
    "training_eligible": False,
    "training_rows_written": False,
    "source_mutation_authorized": False,
    "real_user_source_mutation_authorized": False,
    "approval_authority_granted": False,
    "proof_execution_authority_granted": False,
    "broad_claims_granted": False,
    "artifact_import_authorized": False,
    "benchmark_execution_authorized": False,
    "programbench_execution_authorized": False,
    "release_deploy_workflow_created": False,
    "release_supported": False,
    "support_depth_promotion_granted": False,
    "universal_support_claimed": False,
}

# Terms a scanner greps for to catch an anchor being asserted positively.
AUTHORITY_SCAN_TERMS = [
    "source_mutation",
    "real_user_source_mutation",
    "proof_execution",
    "release_ready",
    "release_readiness",
    "production_readiness",
    "release_supported",
    "support_depth",
    "training_eligible",
    "training_rows",
    "broad_claims",
    "universal_support",
]

# Human-readable invariants for docs/reports.
AUTHORITY_NEGATIVE_INVARIANTS = [
    "release support remains closed",
    "launch readiness remains closed",
    "release readiness remains closed",
    "production readiness remains closed",
    "source mutation authority remains closed",
    "real-user source mutation authority remains closed",
    "proof execution authority remains closed",
    "training eligibility remains closed",
    "broad claims remain closed",
    "universal support remains unclaimed",
    "support-depth promotion remains closed",
]


def closed_authority_flags() -> dict[str, bool]:
    return dict(AUTHORITY_FALSE)


def authority_flags_are_closed(flags: dict[str, Any]) -> bool:
    return all(flags.get(key) is False for key in AUTHORITY_FALSE)


def authority_payload_is_closed(payload: dict[str, Any]) -> bool:
    authority = payload.get("authority")
    if not isinstance(authority, dict) or not authority_flags_are_closed(authority):
        return False
    for key in AUTHORITY_FALSE:
        if payload.get(key) is True:
            return False
    return True


def json_anchor_violations(obj: Any) -> list[str]:
    """Structure-aware check: flag an anchor only when set True at the TOP LEVEL
    or inside an `authority` block -- never a per-cell field of the same name
    nested in an array. This is the precise check the original apparatus used
    (authority_payload_is_closed); a raw text grep collides with per-cell fields
    like 'release_supported' that legitimately appear deep in evidence records."""
    if not isinstance(obj, dict):
        return []
    hits = []
    authority = obj.get("authority") if isinstance(obj.get("authority"), dict) else {}
    for key in AUTHORITY_FALSE:
        if obj.get(key) is True or authority.get(key) is True:
            hits.append(key)
    return hits


def assert_authority_closed() -> None:
    """Raise if any anchor has silently flipped to True. The in-code guard."""
    violations = [k for k, v in AUTHORITY_FALSE.items() if v is not False]
    if violations:
        raise AssertionError(
            "AUTHORITY OVERCLAIM: anchors flipped True without proof: " + ", ".join(violations)
        )


def scan_text_for_anchor_true(text: str) -> list[str]:
    """Return anchors asserted true as a STRUCTURED JSON/YAML boolean assignment
    -- i.e. a quoted key immediately followed by a colon and a bare `true`/`1`:
        "release_ready": true        -> match (real overclaim)
        "release_ready": false       -> no match
        "release_ready=True -> BLOCKED..."  -> NO match (rule-description string)
    The `=` form and string-embedded `True` are deliberately NOT matched: those are
    how the guard RULES describe what to block, not actual assertions. Precise by
    design -- a guard that false-alarms is its own slop."""
    import re

    hits = []
    for key in AUTHORITY_FALSE:
        # double-quoted JSON key, colon, bare lowercase true / 1 (json bool)
        if re.search(rf'"{re.escape(key)}"\s*:\s*(true|1)\s*[,}}\n\r]', text):
            hits.append(key)
    return hits
