"""Core domain types.

Findings are the crown jewels — everything downstream (encryption, role
gating, audit) keys off these structures.
"""
from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class Tier(str, Enum):
    """Evidence tier. Determines how a finding is rendered and whether it
    can be actioned automatically. See Part 3 §2.4."""

    MECHANICAL = "M"      # directly extractable — certain
    CORRELATIONAL = "C"   # inferred from quasi-identifiers — quantified
    STYLISTIC = "S"       # authorship/style — suggestive only


class EditType(str, Enum):
    SUPPRESS = "suppress"
    GENERALIZE = "generalize"
    PSEUDONYMIZE = "pseudonymize"
    RESTRUCTURE = "restructure"


class Role(str, Enum):
    AUDITOR = "auditor"     # sees raw findings + evidence
    REDACTOR = "redactor"   # sees proposed edits + diff only
    VIEWER = "viewer"       # sees final document + residual risk only


@dataclass
class Span:
    """A located piece of text in the source document."""

    start: int
    end: int
    text: str
    page: int | None = None
    source: str = "body"   # body | metadata | redaction_underlay | revision


@dataclass
class Finding:
    persona: str
    tier: Tier
    claim: str                       # what the attacker concluded
    reasoning: str                   # raw transcript — AUDITOR only
    spans: list[Span] = field(default_factory=list)
    severity: float = 0.0            # 0..1
    candidate_set_size: int | None = None   # required for Tier C
    caveat: str | None = None               # required for Tier S
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    resolved: bool = False

    def __post_init__(self) -> None:
        # Tier invariants are enforced here so no code path can emit an
        # unquantified correlational claim or an uncaveated stylistic one.
        if self.tier is Tier.CORRELATIONAL and self.candidate_set_size is None:
            raise ValueError(
                f"Tier C finding {self.id!r} must carry a candidate_set_size"
            )
        if self.tier is Tier.STYLISTIC and not self.caveat:
            raise ValueError(f"Tier S finding {self.id!r} must carry a caveat")

    def redacted_for(self, role: Role) -> dict[str, Any]:
        """Role-appropriate projection. REDACTOR must never see the
        re-identification reasoning that produced the finding."""
        d = asdict(self)
        d["tier"] = self.tier.value
        if role is not Role.AUDITOR:
            d.pop("reasoning", None)
            d.pop("spans", None)
        if role is Role.VIEWER:
            d.pop("claim", None)
        return d


@dataclass
class Edit:
    finding_id: str
    edit_type: EditType
    span: Span
    replacement: str
    rationale: str


@dataclass
class IterationResult:
    """One point on the privacy/utility curve."""

    iteration: int
    findings: list[Finding]
    residual_risk: float
    utility_retained: float
    elapsed_s: float


def content_hash(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def now_ms() -> int:
    return int(time.time() * 1000)
