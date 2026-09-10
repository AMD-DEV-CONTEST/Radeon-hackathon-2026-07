"""specstyle domain enums.

Uses ``enum.StrEnum`` so ``member.name == member.value`` and values are
strings. JSON round trips are reliable, and unknown values raise ``ValueError``
without ``_missing_``, aliases, or permissive conversion. Every value is
written explicitly rather than generated with ``auto()``.
"""

import enum


class RuleStatus(enum.StrEnum):
    """Rule execution status. Never includes ``NOT_APPLICABLE``."""

    PASS = "PASS"
    FAIL = "FAIL"
    WARNING = "WARNING"
    UNVERIFIABLE = "UNVERIFIABLE"


class StaticApplicability(enum.StrEnum):
    """Static rule applicability emitted only by the compiler.

    ``NOT_APPLICABLE`` belongs exclusively to this enum.
    """

    APPLICABLE = "APPLICABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ArtifactStatus(enum.StrEnum):
    """Output terminal state. ``APPROVED`` is the allowlisted terminal state."""

    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class DecisionReason(enum.StrEnum):
    """Reason for a terminal decision."""

    ALL_REQUIRED_PASS = "ALL_REQUIRED_PASS"
    REQUIRED_GATE_FAILED = "REQUIRED_GATE_FAILED"
    REQUIRED_GATE_UNVERIFIABLE = "REQUIRED_GATE_UNVERIFIABLE"
    REPAIR_EXHAUSTED = "REPAIR_EXHAUSTED"
    MANUAL_POLICY = "MANUAL_POLICY"


class RepairStopReason(enum.StrEnum):
    """Reason for stopping repair."""

    PASS_ALL_REQUIRED = "PASS_ALL_REQUIRED"
    NO_ACTION = "NO_ACTION"
    NO_IMPROVEMENT = "NO_IMPROVEMENT"
    MAX_ROUNDS = "MAX_ROUNDS"
    UNVERIFIABLE = "UNVERIFIABLE"
    MANUAL_REQUEST = "MANUAL_REQUEST"


class RuleLevel(enum.StrEnum):
    """Verification layer: L1 technical, L2 style, or L3 domain-specific."""

    L1 = "L1"
    L2 = "L2"
    L3 = "L3"


class RuleScope(enum.StrEnum):
    """Rule scope: one ``ITEM`` or an entire ``BATCH``."""

    ITEM = "ITEM"
    BATCH = "BATCH"
