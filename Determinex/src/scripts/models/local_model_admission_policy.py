"""Local model admission policy — metadata only, no live calls.

Defines what it would take for the apparatus to *eventually* admit a
live local model. This rung emits decisions on candidate metadata only.
No model runs. No subprocess. No network. The policy returns one of the
LOCAL_MODEL_BLOCKED_* statuses or, if every metadata check passes,
``LOCAL_MODEL_METADATA_ADMITTED`` — a precursor to a future LIVE
admission rung that would then attempt a probe.

Rules:

  1. The candidate's ``model_id`` must NOT be in
     :data:`STALE_MODEL_IDS` (from the router lock).
  2. The candidate's ``provider`` must be a known ``ModelProvider``
     enum value. Unknown providers are blocked.
  3. If ``requires_network=True``, the policy refuses unless an
     explicit ``allow_network_models`` flag is True (False by default).
  4. The candidate must declare at least one capability tag.
  5. The candidate's ``supported_task_classes`` must overlap with the
     policy's ``allowed_task_classes`` (defaults to every TaskClass
     except UNKNOWN; deny is via empty intersection).
  6. By default, ``allow_unverified_ids=False`` — a candidate whose id
     is not in :data:`CURRENT_MODEL_IDS` is blocked unless the policy
     opts in.

Even when every check passes, ``execution_authorized=False``. Live
execution requires a *separate* admission step in a later rung.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .local_model_admission_record import (
    LOCAL_MODEL_ADMISSION_STATUS_TOKENS,
    LocalModelAdmissionDecision,
    LocalModelCandidate,
    ModelProvider,
)
from .model_router import CURRENT_MODEL_IDS, STALE_MODEL_IDS, TaskClass

_DEFAULT_ALLOWED_TASK_CLASSES: frozenset[str] = frozenset(
    t.value for t in TaskClass if t is not TaskClass.UNKNOWN
)


@dataclass(frozen=True)
class LocalModelAdmissionConfig:
    allow_network_models: bool = False
    allow_unverified_ids: bool = False
    allowed_task_classes: frozenset[str] = field(
        default_factory=lambda: _DEFAULT_ALLOWED_TASK_CLASSES
    )
    stale_model_ids: frozenset[str] = field(default_factory=lambda: frozenset(STALE_MODEL_IDS))
    current_model_ids: frozenset[str] = field(default_factory=lambda: frozenset(CURRENT_MODEL_IDS))


class LocalModelAdmissionPolicy:
    """Stateless metadata-admission policy."""

    KNOWN_PROVIDERS: frozenset[str] = frozenset(p.value for p in ModelProvider)

    def __init__(self, config: LocalModelAdmissionConfig | None = None) -> None:
        self._config = config or LocalModelAdmissionConfig()

    @property
    def config(self) -> LocalModelAdmissionConfig:
        return self._config

    @staticmethod
    def required() -> LocalModelAdmissionDecision:
        """Default decision for an IDE wanting to render the prompt."""
        return LocalModelAdmissionDecision(
            decision="LOCAL_MODEL_ADMISSION_REQUIRED",
            candidate_id="",
            provider="",
            reason="awaiting candidate metadata",
            metadata_admitted=False,
            execution_authorized=False,
            training_eligible=False,
        )

    def evaluate(self, candidate: LocalModelCandidate) -> LocalModelAdmissionDecision:
        # 1. Unknown provider.
        if candidate.provider not in self.KNOWN_PROVIDERS:
            return self._blocked(
                candidate,
                "LOCAL_MODEL_BLOCKED_UNKNOWN_PROVIDER",
                f"provider {candidate.provider!r} not in {sorted(self.KNOWN_PROVIDERS)}",
            )

        # 2. Stale id.
        if candidate.model_id in self._config.stale_model_ids:
            return self._blocked(
                candidate,
                "LOCAL_MODEL_BLOCKED_STALE_ID",
                f"model_id {candidate.model_id!r} is in STALE_MODEL_IDS",
            )

        # 3. Network model gating.
        if candidate.requires_network and not self._config.allow_network_models:
            return self._blocked(
                candidate,
                "LOCAL_MODEL_BLOCKED_NETWORK_MODEL",
                "candidate.requires_network=True but allow_network_models=False",
            )

        # 4. Unverified id.
        if (
            candidate.model_id not in self._config.current_model_ids
            and not self._config.allow_unverified_ids
            and candidate.provider != ModelProvider.NO_MODEL.value
        ):
            return self._blocked(
                candidate,
                "LOCAL_MODEL_BLOCKED_UNVERIFIED_ID",
                f"model_id {candidate.model_id!r} not in CURRENT_MODEL_IDS; "
                f"allow_unverified_ids=False",
            )

        # 5. Capability declaration required.
        if candidate.provider != ModelProvider.NO_MODEL.value and not candidate.capability_tags:
            return self._blocked(
                candidate,
                "LOCAL_MODEL_BLOCKED_MISSING_CAPABILITIES",
                "candidate must declare at least one capability_tag",
            )

        # 6. Task-class overlap.
        candidate_tcs = set(candidate.supported_task_classes)
        allowed = set(self._config.allowed_task_classes)
        overlap = candidate_tcs & allowed
        if candidate.provider != ModelProvider.NO_MODEL.value and not overlap:
            return self._blocked(
                candidate,
                "LOCAL_MODEL_BLOCKED_UNSUPPORTED_TASK_CLASS",
                f"candidate.supported_task_classes {sorted(candidate_tcs)} has "
                f"no overlap with policy.allowed_task_classes",
            )

        # All checks passed — metadata is admitted. Execution still NOT
        # authorized; that's a future rung.
        return LocalModelAdmissionDecision(
            decision="LOCAL_MODEL_METADATA_ADMITTED",
            candidate_id=candidate.model_id,
            provider=candidate.provider,
            reason="metadata satisfies policy",
            admitted_capabilities=tuple(candidate.capability_tags),
            admitted_task_classes=tuple(sorted(overlap)),
            metadata_admitted=True,
            execution_authorized=False,
            training_eligible=False,
            notes=("metadata-only admission; live admission requires a follow-up rung",),
        )

    @staticmethod
    def _blocked(
        candidate: LocalModelCandidate,
        decision: str,
        reason: str,
    ) -> LocalModelAdmissionDecision:
        return LocalModelAdmissionDecision(
            decision=decision,
            candidate_id=candidate.model_id,
            provider=candidate.provider,
            reason=reason,
            metadata_admitted=False,
            execution_authorized=False,
            training_eligible=False,
            notes=(reason,),
        )


__all__ = [
    "LocalModelAdmissionPolicy",
    "LocalModelAdmissionConfig",
    "LocalModelCandidate",
    "LocalModelAdmissionDecision",
    "ModelProvider",
    "LOCAL_MODEL_ADMISSION_STATUS_TOKENS",
]
