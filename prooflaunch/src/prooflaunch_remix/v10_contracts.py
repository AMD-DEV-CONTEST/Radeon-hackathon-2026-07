from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping, Sequence


class V10ContractError(ValueError):
    """Raised when evidence crosses a V10 truth or governance boundary."""


class EvidenceClass(str, Enum):
    SIMULATED = "simulated"
    PROXY = "proxy"
    OBSERVED = "observed"
    CAUSAL = "causal"


class EvidenceAxis(str, Enum):
    DISTILLATION = "D"
    ACADEMIC = "A"
    INNOVATION = "I"
    EVIDENCE = "E"
    TECHNICAL = "T"
    PRODUCT = "P"
    EFFECT = "X"


class TodoStatus(str, Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    PASSED = "passed"
    FALSIFIED = "falsified"
    BLOCKED = "blocked"


class BreakthroughVerdict(str, Enum):
    PROMOTE = "promote"
    HOLD = "hold"
    REJECT = "reject"


class AgencyRoleKind(str, Enum):
    SUPERVISOR = "supervisor"
    SPECIALIST = "specialist"
    HUMAN = "human"


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _require_sha256(value: str, *, field_name: str) -> None:
    if not _SHA256.fullmatch(value):
        raise V10ContractError(f"{field_name} must be a lowercase SHA-256 digest")


def stable_digest(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class EvidencePointer:
    axis: EvidenceAxis
    locator: str
    sha256: str
    evidence_class: EvidenceClass
    note: str

    def __post_init__(self) -> None:
        if not self.locator.strip():
            raise V10ContractError("evidence locator cannot be empty")
        if not self.note.strip():
            raise V10ContractError("evidence note cannot be empty")
        _require_sha256(self.sha256, field_name="evidence sha256")

    def to_dict(self) -> dict[str, str]:
        return {
            "axis": self.axis.value,
            "locator": self.locator,
            "sha256": self.sha256,
            "evidence_class": self.evidence_class.value,
            "note": self.note,
        }


@dataclass(frozen=True)
class OutcomeEvent:
    event_id: str
    metric: str
    value: float
    unit: str
    occurred_at: str
    evidence_class: EvidenceClass
    source_locator: str
    intervention: str | None = None
    randomization_unit: str | None = None
    segment: str | None = None

    def __post_init__(self) -> None:
        if not self.event_id.strip() or not self.metric.strip():
            raise V10ContractError("outcome event id and metric are required")
        if not math.isfinite(self.value):
            raise V10ContractError("outcome value must be finite")
        if not self.source_locator.strip():
            raise V10ContractError("outcome source locator is required")
        try:
            datetime.fromisoformat(self.occurred_at.replace("Z", "+00:00"))
        except ValueError as error:
            raise V10ContractError("occurred_at must be ISO-8601") from error
        if self.evidence_class == EvidenceClass.CAUSAL and (
            not self.intervention or not self.randomization_unit
        ):
            raise V10ContractError(
                "causal outcomes require an intervention and randomization unit"
            )

    @property
    def display_label(self) -> str:
        if self.evidence_class in {EvidenceClass.SIMULATED, EvidenceClass.PROXY}:
            return f"predicted {self.metric}"
        return self.metric

    def assert_business_claimable(self) -> None:
        if self.evidence_class not in {
            EvidenceClass.OBSERVED,
            EvidenceClass.CAUSAL,
        }:
            raise V10ContractError(
                "simulated or proxy outcomes cannot be published as business results"
            )


@dataclass(frozen=True)
class ClaimProof:
    claim_id: str
    claim_text: str
    source_locator: str
    source_sha256: str
    asset_id: str
    region_or_frame: str
    transform_ids: tuple[str, ...]
    approval_id: str

    def __post_init__(self) -> None:
        for field_name, value in (
            ("claim_id", self.claim_id),
            ("claim_text", self.claim_text),
            ("source_locator", self.source_locator),
            ("asset_id", self.asset_id),
            ("region_or_frame", self.region_or_frame),
            ("approval_id", self.approval_id),
        ):
            if not value.strip():
                raise V10ContractError(f"{field_name} cannot be empty")
        _require_sha256(self.source_sha256, field_name="source_sha256")


@dataclass(frozen=True)
class TransformProof:
    transform_id: str
    operation: str
    input_sha256: str
    output_sha256: str
    tool_ref: str
    parameters: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.transform_id.strip() or not self.operation.strip():
            raise V10ContractError("transform id and operation are required")
        if not self.tool_ref.strip():
            raise V10ContractError("transform tool_ref is required")
        _require_sha256(self.input_sha256, field_name="input_sha256")
        _require_sha256(self.output_sha256, field_name="output_sha256")


@dataclass(frozen=True)
class ProofManifest:
    campaign_id: str
    claims: tuple[ClaimProof, ...]
    transforms: tuple[TransformProof, ...]
    asset_hashes: Mapping[str, str]
    schema: str = "ProofLaunchProofManifestV10"

    def __post_init__(self) -> None:
        if not self.campaign_id.strip():
            raise V10ContractError("campaign_id is required")
        transform_ids = {item.transform_id for item in self.transforms}
        if len(transform_ids) != len(self.transforms):
            raise V10ContractError("transform ids must be unique")
        for asset_id, digest in self.asset_hashes.items():
            if not asset_id.strip():
                raise V10ContractError("asset id cannot be empty")
            _require_sha256(digest, field_name=f"asset_hashes[{asset_id}]")
        claim_ids: set[str] = set()
        for claim in self.claims:
            if claim.claim_id in claim_ids:
                raise V10ContractError("claim ids must be unique")
            claim_ids.add(claim.claim_id)
            if claim.asset_id not in self.asset_hashes:
                raise V10ContractError(
                    f"claim {claim.claim_id} points to an unknown asset"
                )
            unknown = set(claim.transform_ids) - transform_ids
            if unknown:
                raise V10ContractError(
                    f"claim {claim.claim_id} has unknown transforms: {sorted(unknown)}"
                )

    @property
    def digest(self) -> str:
        return stable_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "campaign_id": self.campaign_id,
            "claims": [asdict(item) for item in self.claims],
            "transforms": [asdict(item) for item in self.transforms],
            "asset_hashes": dict(sorted(self.asset_hashes.items())),
        }


@dataclass(frozen=True)
class AgencyRole:
    role_id: str
    kind: AgencyRoleKind
    permissions: frozenset[str]
    owns_state: bool = False
    max_actions: int = 1

    def __post_init__(self) -> None:
        if not self.role_id.strip():
            raise V10ContractError("agency role id is required")
        if self.max_actions < 1:
            raise V10ContractError("max_actions must be positive")


@dataclass(frozen=True)
class AgencyTopology:
    roles: tuple[AgencyRole, ...]
    max_parallel_specialists: int
    max_total_actions: int
    stop_conditions: tuple[str, ...]
    schema: str = "ProofLaunchAgencyTopologyV10"

    def __post_init__(self) -> None:
        role_ids = {role.role_id for role in self.roles}
        if len(role_ids) != len(self.roles):
            raise V10ContractError("agency role ids must be unique")
        supervisors = [
            role for role in self.roles if role.kind == AgencyRoleKind.SUPERVISOR
        ]
        state_owners = [role for role in self.roles if role.owns_state]
        if len(supervisors) != 1 or len(state_owners) != 1:
            raise V10ContractError(
                "exactly one Supervisor must own authoritative state"
            )
        if supervisors[0] != state_owners[0]:
            raise V10ContractError("the Supervisor must be the state owner")
        if self.max_parallel_specialists < 1:
            raise V10ContractError("max_parallel_specialists must be positive")
        if self.max_total_actions < sum(role.max_actions for role in supervisors):
            raise V10ContractError("max_total_actions is below the Supervisor budget")
        if not self.stop_conditions:
            raise V10ContractError("at least one explicit stop condition is required")

    def can(self, role_id: str, permission: str) -> bool:
        role = next((item for item in self.roles if item.role_id == role_id), None)
        return bool(role and permission in role.permissions)


@dataclass(frozen=True)
class BreakthroughBetSpec:
    bet_id: str
    hypothesis: str
    baseline_ids: tuple[str, ...]
    success_thresholds: Mapping[str, float]
    gpu_budget_hours: float
    elimination_rules: tuple[str, ...]
    evidence_root: str

    def __post_init__(self) -> None:
        if not self.bet_id.strip() or not self.hypothesis.strip():
            raise V10ContractError("bet id and hypothesis are required")
        if not self.baseline_ids:
            raise V10ContractError("at least one frozen baseline is required")
        if not self.success_thresholds:
            raise V10ContractError("success thresholds are required")
        if any(not math.isfinite(value) for value in self.success_thresholds.values()):
            raise V10ContractError("success thresholds must be finite")
        if self.gpu_budget_hours <= 0:
            raise V10ContractError("gpu budget must be positive")
        if not self.elimination_rules:
            raise V10ContractError("at least one elimination rule is required")
        if not self.evidence_root.strip():
            raise V10ContractError("evidence_root is required")


@dataclass(frozen=True)
class BreakthroughEvidenceBundle:
    bet_id: str
    code: tuple[EvidencePointer, ...]
    configuration: tuple[EvidencePointer, ...]
    data_rights: tuple[EvidencePointer, ...]
    logs: tuple[EvidencePointer, ...]
    ablations: tuple[EvidencePointer, ...]
    radeon_traces: tuple[EvidencePointer, ...]
    product_tests: tuple[EvidencePointer, ...]
    effect_tests: tuple[EvidencePointer, ...]
    negative_results: tuple[EvidencePointer, ...] = ()
    schema: str = "ProofLaunchBreakthroughEvidenceBundleV10"

    def missing_sections(self) -> tuple[str, ...]:
        """Return sections without outcome-grade, source-bound evidence.

        A placeholder, synthetic fixture, planned notebook, or self-score may be
        useful during implementation, but it must not make a breakthrough look
        promotion-ready.  Every mandatory section therefore needs at least one
        observed or causal pointer.  Proxy/simulated pointers remain serialized
        as honest partial evidence and keep the bet on HOLD.
        """
        required = {
            "code": self.code,
            "configuration": self.configuration,
            "data_rights": self.data_rights,
            "logs": self.logs,
            "ablations": self.ablations,
            "radeon_traces": self.radeon_traces,
            "product_tests": self.product_tests,
            "effect_tests": self.effect_tests,
        }
        acceptable = {EvidenceClass.OBSERVED, EvidenceClass.CAUSAL}
        return tuple(
            name
            for name, values in required.items()
            if not any(pointer.evidence_class in acceptable for pointer in values)
        )


@dataclass(frozen=True)
class BreakthroughMeasurement:
    metric: str
    actual: float
    threshold: float
    higher_is_better: bool
    evidence: EvidencePointer

    @property
    def passed(self) -> bool:
        return (
            self.actual >= self.threshold
            if self.higher_is_better
            else self.actual <= self.threshold
        )


@dataclass(frozen=True)
class BreakthroughDecision:
    bet_id: str
    verdict: BreakthroughVerdict
    technical: tuple[BreakthroughMeasurement, ...]
    product: tuple[BreakthroughMeasurement, ...]
    effect: tuple[BreakthroughMeasurement, ...]
    reasons: tuple[str, ...]
    decided_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @classmethod
    def evaluate(
        cls,
        spec: BreakthroughBetSpec,
        bundle: BreakthroughEvidenceBundle,
        *,
        technical: Sequence[BreakthroughMeasurement],
        product: Sequence[BreakthroughMeasurement],
        effect: Sequence[BreakthroughMeasurement],
    ) -> BreakthroughDecision:
        reasons: list[str] = []
        missing = bundle.missing_sections()
        if bundle.bet_id != spec.bet_id:
            raise V10ContractError("bet spec and evidence bundle ids do not match")
        if missing:
            reasons.append(f"missing evidence sections: {', '.join(missing)}")
        axes = {
            "technical": tuple(technical),
            "product": tuple(product),
            "effect": tuple(effect),
        }
        for axis, measurements in axes.items():
            if not measurements:
                reasons.append(f"{axis} measurements are missing")
            failed = [item.metric for item in measurements if not item.passed]
            if failed:
                reasons.append(f"{axis} thresholds failed: {', '.join(failed)}")
        verdict = (
            BreakthroughVerdict.PROMOTE
            if not reasons
            else (
                BreakthroughVerdict.REJECT
                if bundle.negative_results
                else BreakthroughVerdict.HOLD
            )
        )
        return cls(
            bet_id=spec.bet_id,
            verdict=verdict,
            technical=axes["technical"],
            product=axes["product"],
            effect=axes["effect"],
            reasons=tuple(reasons) or ("all technical, product, and effect gates passed",),
        )
