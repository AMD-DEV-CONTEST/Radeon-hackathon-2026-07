"""Local model admission records.

Defines the candidate-metadata schema and the admission-decision record
for LOCAL_MODEL_ADMISSION_POLICY_LOCK_001. Even the metadata schema is
conservative: a candidate must declare provider type, capabilities,
and task-class compatibility before the policy may admit it.

This rung admits METADATA only — it does not call any model. The
``LOCAL_MODEL_METADATA_ADMITTED`` decision means "this candidate's
metadata satisfies the policy; future rungs may proceed to live
admission."
"""

from __future__ import annotations

import enum
import json
from dataclasses import asdict, dataclass, field

LOCAL_MODEL_ADMISSION_STATUS_TOKENS = (
    "LOCAL_MODEL_ADMISSION_POLICY_WRITTEN",
    "LOCAL_MODEL_ADMISSION_REQUIRED",
    "LOCAL_MODEL_BLOCKED_STALE_ID",
    "LOCAL_MODEL_BLOCKED_UNKNOWN_PROVIDER",
    "LOCAL_MODEL_BLOCKED_NETWORK_MODEL",
    "LOCAL_MODEL_BLOCKED_UNSUPPORTED_TASK_CLASS",
    "LOCAL_MODEL_BLOCKED_MISSING_CAPABILITIES",
    "LOCAL_MODEL_BLOCKED_UNVERIFIED_ID",
    "LOCAL_MODEL_METADATA_ADMITTED",
)


class ModelProvider(str, enum.Enum):
    OLLAMA = "ollama"
    LOCAL_HF = "local_hf"
    EXECUTABLE_ADAPTER = "executable_adapter"
    NO_MODEL = "no_model"


@dataclass(frozen=True)
class LocalModelCandidate:
    """Metadata-only declaration of a local model.

    No live probe runs at this rung. Callers (a future LIVE rung)
    populate this from on-disk config or an opt-in ``ollama list``
    invocation routed through ``intake.hardened_runner``.
    """

    model_id: str
    provider: str  # one of ModelProvider values
    capability_tags: tuple[str, ...] = field(default_factory=tuple)
    supported_task_classes: tuple[str, ...] = field(default_factory=tuple)
    requires_network: bool = False
    declared_local: bool = True

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["capability_tags"] = list(self.capability_tags)
        d["supported_task_classes"] = list(self.supported_task_classes)
        return d


@dataclass(frozen=True)
class LocalModelAdmissionDecision:
    decision: str
    candidate_id: str
    provider: str
    reason: str = ""
    admitted_capabilities: tuple[str, ...] = field(default_factory=tuple)
    admitted_task_classes: tuple[str, ...] = field(default_factory=tuple)
    metadata_admitted: bool = False
    execution_authorized: bool = False
    training_eligible: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["admitted_capabilities"] = list(self.admitted_capabilities)
        d["admitted_task_classes"] = list(self.admitted_task_classes)
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @property
    def is_admitted(self) -> bool:
        return self.decision == "LOCAL_MODEL_METADATA_ADMITTED"

    @property
    def is_blocked(self) -> bool:
        return self.decision.startswith("LOCAL_MODEL_BLOCKED_")
