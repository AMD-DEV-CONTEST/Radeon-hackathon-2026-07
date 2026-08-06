from __future__ import annotations

import hashlib
import math
from collections import OrderedDict
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Sequence

from .v10_contracts import V10ContractError
from .v10_supply_chain import stable_sha256


_HEX = frozenset("0123456789abcdef")


def _require_sha256(value: str, field_name: str) -> None:
    if len(value) != 64 or any(character not in _HEX for character in value):
        raise V10ContractError(f"{field_name} must be a lowercase SHA-256")


def _require_unit(value: float, field_name: str) -> None:
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise V10ContractError(f"{field_name} must be in the unit interval")


class AdapterCapability(str, Enum):
    EVIDENCE = "evidence"
    STRATEGY = "strategy"
    CREATIVE = "creative"
    COPY = "copy"
    ART = "art"
    CHANNEL = "channel"
    COMPLIANCE = "compliance"
    MEMORY = "memory"
    PLANNER = "planner"
    CRITIC = "critic"


class RegressionState(str, Enum):
    UNKNOWN = "unknown"
    PASSED = "passed"
    FAILED = "failed"


@dataclass(frozen=True)
class AdapterMetadata:
    adapter_id: str
    capability: AdapterCapability
    adapter_revision: str
    base_model_revision: str
    task_tags: tuple[str, ...]
    market_tags: tuple[str, ...]
    target_modules: tuple[str, ...]
    rank: int
    dtype: str
    size_bytes: int | None
    artifact_sha256: str | None
    training_observed: bool
    regression_state: RegressionState
    promotion_eligible: bool
    priority: int = 0

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.adapter_id,
                self.adapter_revision,
                self.base_model_revision,
                self.dtype,
            )
        ):
            raise V10ContractError("adapter identity and revisions are required")
        if not self.task_tags or not self.target_modules:
            raise V10ContractError("adapter task tags and target modules are required")
        if self.rank < 1 or self.priority < 0:
            raise V10ContractError("adapter rank must be positive and priority nonnegative")
        if self.size_bytes is not None and self.size_bytes < 1:
            raise V10ContractError("observed adapter size must be positive")
        if self.artifact_sha256 is not None:
            _require_sha256(self.artifact_sha256, "artifact_sha256")
        if self.training_observed and (
            self.artifact_sha256 is None or self.size_bytes is None
        ):
            raise V10ContractError("observed training requires a hashed sized artifact")
        if self.promotion_eligible and (
            not self.training_observed
            or self.regression_state is not RegressionState.PASSED
        ):
            raise V10ContractError("promotion requires observed training and passed regressions")

    @property
    def key(self) -> str:
        return f"{self.adapter_id}@{self.adapter_revision}"

    @property
    def serving_eligible(self) -> bool:
        return (
            self.training_observed
            and self.regression_state is RegressionState.PASSED
            and self.promotion_eligible
        )

    @property
    def digest(self) -> str:
        payload = asdict(self)
        payload["capability"] = self.capability.value
        payload["regression_state"] = self.regression_state.value
        return stable_sha256(payload)


@dataclass(frozen=True)
class RoutingContext:
    task_id: str
    capability_scores: Mapping[AdapterCapability, float]
    uncertainty: float
    market: str
    risk: float

    def __post_init__(self) -> None:
        if not self.task_id.strip() or not self.market.strip():
            raise V10ContractError("routing task and market are required")
        if not self.capability_scores:
            raise V10ContractError("at least one task capability score is required")
        for capability, score in self.capability_scores.items():
            if not isinstance(capability, AdapterCapability):
                raise V10ContractError("capability score keys must be typed")
            _require_unit(score, f"{capability.value} score")
        _require_unit(self.uncertainty, "uncertainty")
        _require_unit(self.risk, "risk")


@dataclass(frozen=True)
class RoutingDecision:
    task_id: str
    selected_adapter_key: str
    selected_capability: AdapterCapability
    reasons: tuple[str, ...]
    registry_digest: str


class AdapterRegistry:
    """Append-only adapter versions with an auditable active-pointer history."""

    def __init__(self) -> None:
        self._records: dict[str, AdapterMetadata] = {}
        self._active: dict[AdapterCapability, str] = {}
        self._history: dict[AdapterCapability, list[str]] = {}

    def register(self, metadata: AdapterMetadata) -> str:
        current = self._records.get(metadata.key)
        if current is not None and current != metadata:
            raise V10ContractError("adapter revision is immutable")
        self._records[metadata.key] = metadata
        return metadata.digest

    def get(self, key: str) -> AdapterMetadata:
        try:
            return self._records[key]
        except KeyError as error:
            raise V10ContractError(f"unknown adapter revision: {key}") from error

    def eligible(self, capability: AdapterCapability) -> tuple[AdapterMetadata, ...]:
        return tuple(
            sorted(
                (
                    item
                    for item in self._records.values()
                    if item.capability is capability and item.serving_eligible
                ),
                key=lambda item: (-item.priority, item.key),
            )
        )

    def activate(self, key: str) -> None:
        item = self.get(key)
        if not item.serving_eligible:
            raise V10ContractError("untrained or unverified adapter cannot be activated")
        self._active[item.capability] = key
        history = self._history.setdefault(item.capability, [])
        if not history or history[-1] != key:
            history.append(key)

    def rollback(self, capability: AdapterCapability) -> Mapping[str, object]:
        history = self._history.get(capability, [])
        if len(history) < 2:
            raise V10ContractError("adapter rollback needs a prior active revision")
        rolled_back_from = history.pop()
        restored = history[-1]
        self._active[capability] = restored
        body = {
            "capability": capability.value,
            "rolled_back_from": rolled_back_from,
            "restored": restored,
            "registry_digest": self.digest,
        }
        return {**body, "receipt_sha256": stable_sha256(body)}

    @property
    def digest(self) -> str:
        return stable_sha256(
            {
                "records": {
                    key: self._records[key].digest for key in sorted(self._records)
                },
                "active": {
                    key.value: value
                    for key, value in sorted(
                        self._active.items(), key=lambda item: item[0].value
                    )
                },
                "history": {
                    key.value: tuple(value)
                    for key, value in sorted(
                        self._history.items(), key=lambda item: item[0].value
                    )
                },
            }
        )


class AdapterRouter:
    def __init__(
        self,
        registry: AdapterRegistry,
        *,
        uncertainty_threshold: float = 0.75,
        risk_threshold: float = 0.80,
    ) -> None:
        _require_unit(uncertainty_threshold, "uncertainty_threshold")
        _require_unit(risk_threshold, "risk_threshold")
        self.registry = registry
        self.uncertainty_threshold = uncertainty_threshold
        self.risk_threshold = risk_threshold

    def route(self, context: RoutingContext) -> RoutingDecision:
        if context.risk >= self.risk_threshold:
            capability = AdapterCapability.COMPLIANCE
            reasons = ("risk_override", f"risk={context.risk:.4f}")
        elif context.uncertainty >= self.uncertainty_threshold:
            capability = AdapterCapability.CRITIC
            reasons = (
                "uncertainty_override",
                f"uncertainty={context.uncertainty:.4f}",
            )
        else:
            capability = sorted(
                context.capability_scores,
                key=lambda item: (-context.capability_scores[item], item.value),
            )[0]
            reasons = (
                "task_capability",
                f"score={context.capability_scores[capability]:.4f}",
            )
        candidates = self.registry.eligible(capability)
        if not candidates:
            raise V10ContractError(
                f"no serving-eligible adapter for capability {capability.value}"
            )
        market_matches = tuple(
            item for item in candidates if context.market in item.market_tags
        )
        selected = (market_matches or candidates)[0]
        if market_matches:
            reasons = (*reasons, f"market={context.market}")
        return RoutingDecision(
            task_id=context.task_id,
            selected_adapter_key=selected.key,
            selected_capability=capability,
            reasons=reasons,
            registry_digest=self.registry.digest,
        )


class AdapterCache:
    """Byte-bounded LRU that never evicts the protected active adapter."""

    def __init__(self, *, max_adapters: int, max_bytes: int) -> None:
        if max_adapters < 1 or max_bytes < 1:
            raise V10ContractError("adapter cache limits must be positive")
        self.max_adapters = max_adapters
        self.max_bytes = max_bytes
        self._items: OrderedDict[str, AdapterMetadata] = OrderedDict()
        self._protected: set[str] = set()

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(self._items)

    @property
    def used_bytes(self) -> int:
        return sum(item.size_bytes or 0 for item in self._items.values())

    def protect(self, key: str) -> None:
        if key not in self._items:
            raise V10ContractError("only a resident adapter can be protected")
        self._protected = {key}

    def get(self, key: str) -> AdapterMetadata:
        try:
            item = self._items.pop(key)
        except KeyError as error:
            raise V10ContractError(f"adapter is not cached: {key}") from error
        self._items[key] = item
        return item

    def put(self, metadata: AdapterMetadata) -> tuple[str, ...]:
        if not metadata.serving_eligible or metadata.size_bytes is None:
            raise V10ContractError("only verified sized adapters may enter cache")
        if metadata.size_bytes > self.max_bytes:
            raise V10ContractError("adapter exceeds the entire cache budget")
        staged = OrderedDict(self._items)
        staged.pop(metadata.key, None)
        staged[metadata.key] = metadata
        evicted: list[str] = []
        while (
            len(staged) > self.max_adapters
            or sum(item.size_bytes or 0 for item in staged.values()) > self.max_bytes
        ):
            candidate = next(
                (key for key in staged if key not in self._protected), None
            )
            if candidate is None or candidate == metadata.key:
                raise V10ContractError("cache cannot admit without evicting protected state")
            staged.pop(candidate)
            evicted.append(candidate)
        self._items = staged
        self._protected &= set(staged)
        return tuple(evicted)


class MergeMethod(str, Enum):
    NO_MERGE = "no_merge_control"
    WEIGHTED = "weighted_merge"
    TIES = "ties"
    DARE_TIES = "dare_ties"


@dataclass(frozen=True)
class MergeEvaluation:
    method: MergeMethod
    observed: bool
    capability_regression: bool | None
    safety_regression: bool | None
    claim_regression: bool | None
    visual_regression: bool | None
    aggregate_score: float | None

    @property
    def passed(self) -> bool:
        regressions = (
            self.capability_regression,
            self.safety_regression,
            self.claim_regression,
            self.visual_regression,
        )
        return (
            self.observed
            and all(item is False for item in regressions)
            and self.aggregate_score is not None
            and math.isfinite(self.aggregate_score)
        )


def select_merge_strategy(
    evaluations: Sequence[MergeEvaluation],
) -> MergeMethod:
    """Keep adapters independent unless a real merge clears every regression gate."""

    passed = tuple(
        item
        for item in evaluations
        if item.method is not MergeMethod.NO_MERGE and item.passed
    )
    if not passed:
        return MergeMethod.NO_MERGE
    return sorted(
        passed,
        key=lambda item: (-(item.aggregate_score or 0.0), item.method.value),
    )[0].method


class ModelRole(str, Enum):
    MAIN = "main"
    AUXILIARY = "auxiliary"


def quantization_admitted(
    *,
    role: ModelRole,
    dtype: str,
    parity_observed: bool,
    safety_regression: bool | None,
    quality_delta: float | None,
    maximum_quality_drop: float = 0.01,
) -> bool:
    normalized = dtype.lower()
    if role is ModelRole.MAIN and normalized not in {"bf16", "fp16", "fp32"}:
        return (
            parity_observed
            and safety_regression is False
            and quality_delta is not None
            and math.isfinite(quality_delta)
            and quality_delta >= -maximum_quality_drop
        )
    if normalized == "int8":
        return parity_observed and safety_regression is False
    return normalized in {"bf16", "fp16", "fp32"}


@dataclass(frozen=True)
class ModelArtifact:
    model_id: str
    revision: str
    artifact_sha256: str
    resident_bytes: int
    heavy: bool = True

    def __post_init__(self) -> None:
        if not self.model_id.strip() or not self.revision.strip():
            raise V10ContractError("model identity and revision are required")
        _require_sha256(self.artifact_sha256, "model artifact_sha256")
        if self.resident_bytes < 1:
            raise V10ContractError("model resident bytes must be positive")


@dataclass(frozen=True)
class ResidencyPlan:
    observed_available_bytes: int
    admission_fraction: float
    budget_bytes: int
    current_peak_bytes: int
    projected_peak_bytes: int
    unload_before_model_swap: bool
    single_heavy_model: bool


class SingleCardResidencyController:
    def __init__(
        self, *, observed_available_bytes: int, admission_fraction: float = 0.90
    ) -> None:
        if observed_available_bytes < 1:
            raise V10ContractError("residency requires observed available memory")
        if not math.isfinite(admission_fraction) or not 0 < admission_fraction <= 0.95:
            raise V10ContractError("residency admission fraction must be in (0, 0.95]")
        self.observed_available_bytes = observed_available_bytes
        self.admission_fraction = admission_fraction
        self.base_model: ModelArtifact | None = None
        self.adapter_bytes = 0

    @property
    def budget_bytes(self) -> int:
        return int(self.observed_available_bytes * self.admission_fraction)

    @property
    def current_bytes(self) -> int:
        return (self.base_model.resident_bytes if self.base_model else 0) + self.adapter_bytes

    def load_base(self, artifact: ModelArtifact) -> None:
        if self.base_model is not None and artifact.heavy and self.base_model.heavy:
            raise V10ContractError("only one heavy base model may be resident")
        if artifact.resident_bytes + self.adapter_bytes > self.budget_bytes:
            raise V10ContractError("base model exceeds the measured memory budget")
        self.base_model = artifact

    def set_adapter_bytes(self, value: int) -> None:
        if value < 0 or (self.base_model and self.base_model.resident_bytes + value > self.budget_bytes):
            raise V10ContractError("adapter residency exceeds the measured memory budget")
        self.adapter_bytes = value

    def plan_model_swap(self, next_model: ModelArtifact) -> ResidencyPlan:
        current = self.current_bytes
        overlapping = current + next_model.resident_bytes
        unload_first = overlapping > self.budget_bytes or (
            self.base_model is not None and self.base_model.heavy and next_model.heavy
        )
        projected = next_model.resident_bytes + self.adapter_bytes
        if projected > self.budget_bytes:
            raise V10ContractError("next model cannot fit after unload")
        return ResidencyPlan(
            observed_available_bytes=self.observed_available_bytes,
            admission_fraction=self.admission_fraction,
            budget_bytes=self.budget_bytes,
            current_peak_bytes=current,
            projected_peak_bytes=projected,
            unload_before_model_swap=unload_first,
            single_heavy_model=True,
        )

    def swap_model(self, next_model: ModelArtifact) -> Mapping[str, object]:
        plan = self.plan_model_swap(next_model)
        previous = self.base_model
        if plan.unload_before_model_swap:
            self.base_model = None
        self.base_model = next_model
        body = {
            "previous_model": previous.model_id if previous else None,
            "next_model": next_model.model_id,
            "unloaded_before_swap": plan.unload_before_model_swap,
            "projected_peak_bytes": plan.projected_peak_bytes,
            "budget_bytes": plan.budget_bytes,
        }
        return {**body, "receipt_sha256": stable_sha256(body)}


def adapter_directory_sha256(path: str | Path) -> str:
    root = Path(path)
    if not root.is_dir():
        raise V10ContractError("adapter path must be a directory")
    files = sorted(item for item in root.rglob("*") if item.is_file())
    if not files:
        raise V10ContractError("adapter directory is empty")
    payload = [
        {
            "path": item.relative_to(root).as_posix(),
            "sha256": hashlib.sha256(item.read_bytes()).hexdigest(),
        }
        for item in files
    ]
    return stable_sha256(payload)


class PeftHotSwapBackend:
    """Lazy real-PEFT LoRA hotswap with artifact and storage checks."""

    def hotswap(
        self,
        model: Any,
        adapter_path: str | Path,
        *,
        adapter_name: str,
        expected_sha256: str,
        device: str,
    ) -> Mapping[str, object]:
        _require_sha256(expected_sha256, "expected_sha256")
        observed_sha256 = adapter_directory_sha256(adapter_path)
        if observed_sha256 != expected_sha256:
            raise V10ContractError("adapter directory digest mismatch")
        try:
            import peft
            from peft.utils.hotswap import hotswap_adapter
        except ImportError as error:
            raise V10ContractError("real PEFT runtime is unavailable") from error
        before = {
            name: parameter.data_ptr()
            for name, parameter in model.named_parameters()
            if "lora_" in name and f".{adapter_name}." in name
        }
        if not before:
            raise V10ContractError("target PEFT adapter slot does not exist")
        hotswap_adapter(
            model,
            str(adapter_path),
            adapter_name=adapter_name,
            torch_device=device,
        )
        after = {
            name: parameter.data_ptr()
            for name, parameter in model.named_parameters()
            if "lora_" in name and f".{adapter_name}." in name
        }
        body = {
            "backend": "peft.utils.hotswap.hotswap_adapter",
            "peft_version": peft.__version__,
            "adapter_name": adapter_name,
            "adapter_sha256": observed_sha256,
            "parameter_slots": len(after),
            "in_place_storage_preserved": before == after,
        }
        if not body["in_place_storage_preserved"]:
            raise V10ContractError("PEFT hotswap reallocated the adapter slot")
        return {**body, "receipt_sha256": stable_sha256(body)}


def planned_capability_templates() -> tuple[Mapping[str, object], ...]:
    return tuple(
        {
            "capability": capability.value,
            "training_observed": False,
            "artifact_sha256": None,
            "promotion_eligible": False,
        }
        for capability in AdapterCapability
    )


def planned_adapter_stack_card() -> Mapping[str, object]:
    metrics = {
        "hotswap_latency_ms": None,
        "peak_radeon_memory_bytes": None,
        "crosstalk_rate": None,
        "forgetting_delta": None,
        "capability_interference": None,
        "safety_regression": None,
        "claim_regression": None,
        "visual_regression": None,
    }
    artifacts = {
        "trained_adapters": None,
        "teacher_outputs": None,
        "gkd_run": None,
        "weighted_merge": None,
        "ties_merge": None,
        "dare_merge": None,
        "bf16_export": None,
        "fp16_export": None,
        "int8_auxiliary_export": None,
        "merge_ablation_report": None,
        "compression_report": None,
        "routing_report": None,
        "frozen_stack": None,
    }
    body = {
        "schema": "ProofLaunchAdapterPseudoMoeCardV1",
        "execution_status": "control_plane_verified_training_not_executed",
        "capability_templates": planned_capability_templates(),
        "metrics": metrics,
        "artifacts": artifacts,
        "promotion_eligible": False,
        "truth_boundary": (
            "The registry, routing, hotswap, cache, rollback, quantization and "
            "single-card residency mechanisms are mechanical controls. No role "
            "adapter, merge, compression result or Radeon performance metric is claimed."
        ),
    }
    return {**body, "card_sha256": stable_sha256(body)}
