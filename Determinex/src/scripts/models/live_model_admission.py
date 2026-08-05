"""Live local-model admission gate.

Opt-in, bounded, evidence-recorded capability. Dry-run remains the
default; live admission requires an explicit ``opt_in_live=True`` flag
in the config. Even ``READY`` records leave source mutation, corpus
write, and training eligibility blocked — those gates are independent
and remain closed.

Pipeline:

    LiveModelAdmissionGate.evaluate(candidate, task_class, route_record)
      → LiveModelAdmissionRecord

The gate composes:
  * :class:`LocalModelAdmissionPolicy` (metadata-only checks from
    LOCAL_MODEL_ADMISSION_POLICY_LOCK_001)
  * :class:`LocalModelInventory` (passive availability check)
  * :class:`ModelRouter` route record (router_decision_ref)

The gate performs no I/O. It never calls a model. It never spawns a
subprocess. It never reaches the network.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .live_model_admission_record import (
    LOCAL_MODEL_LIVE_ADMISSION_STATUS_TOKENS,
    LiveAdmissionMode,
    LiveModelAdmissionRecord,
)
from .local_model_admission_policy import (
    LocalModelAdmissionPolicy,
    LocalModelCandidate,
    ModelProvider,
)
from .model_inventory import LocalModelInventory
from .model_router import CURRENT_MODEL_IDS, STALE_MODEL_IDS, TaskClass
from .model_router_record import RouteRecord

# Provider-type classification. Network providers are not part of the
# local-model admission surface and are always blocked here. The
# LOCAL_HF / OLLAMA / EXECUTABLE_ADAPTER providers are local-only.
_LOCAL_PROVIDERS: frozenset[str] = frozenset(
    {
        ModelProvider.OLLAMA.value,
        ModelProvider.LOCAL_HF.value,
        ModelProvider.EXECUTABLE_ADAPTER.value,
        ModelProvider.NO_MODEL.value,
    }
)

# Network providers — kept here for clarity. Any non-local provider
# string is treated as network/unknown and refused.
_NETWORK_PROVIDER_TOKENS: frozenset[str] = frozenset(
    {
        "anthropic",
        "openai",
        "google",
        "deepseek",
        "gemini",
        "openrouter",
        "vllm-remote",
        "cloud",
        "network",
    }
)


@dataclass(frozen=True)
class LiveModelAdmissionConfig:
    mode: LiveAdmissionMode = LiveAdmissionMode.DRY_RUN
    opt_in_live: bool = False
    require_pinned_id: bool = True
    allow_network_provider: bool = False
    allowed_task_classes: frozenset[str] = field(
        default_factory=lambda: frozenset(t.value for t in TaskClass if t is not TaskClass.UNKNOWN)
    )


class LiveModelAdmissionGate:
    """Stateless live-admission decision surface."""

    def __init__(
        self,
        config: LiveModelAdmissionConfig | None = None,
        policy: LocalModelAdmissionPolicy | None = None,
    ) -> None:
        self._config = config or LiveModelAdmissionConfig()
        self._policy = policy or LocalModelAdmissionPolicy()

    @property
    def config(self) -> LiveModelAdmissionConfig:
        return self._config

    def evaluate(
        self,
        candidate: LocalModelCandidate,
        task_class: TaskClass | str,
        inventory: LocalModelInventory | None,
        route_record: RouteRecord | None = None,
    ) -> LiveModelAdmissionRecord:
        tc = task_class.value if isinstance(task_class, TaskClass) else str(task_class)
        route_ref = route_record.decision if route_record is not None else ""

        # 0. Dry-run is the default — refuses live admission outright.
        if self._config.mode is not LiveAdmissionMode.OPT_IN_LIVE:
            return self._blocked(
                candidate,
                tc,
                route_ref,
                "LOCAL_MODEL_LIVE_ADMISSION_BLOCKED_DRY_RUN_DEFAULT",
                "config.mode is DRY_RUN (default); live admission requires "
                "mode=OPT_IN_LIVE and opt_in_live=True",
            )

        # 1. Explicit opt-in flag required.
        if not self._config.opt_in_live:
            return self._blocked(
                candidate,
                tc,
                route_ref,
                "LOCAL_MODEL_LIVE_ADMISSION_BLOCKED_NO_CONFIG",
                "config.opt_in_live=False; explicit caller opt-in required",
            )

        # 2. Inventory required.
        if inventory is None or not bool(inventory):
            return self._blocked(
                candidate,
                tc,
                route_ref,
                "LOCAL_MODEL_LIVE_ADMISSION_BLOCKED_MISSING_INVENTORY",
                "no LocalModelInventory supplied or inventory is empty",
            )

        # 3. Unknown / network provider.
        if candidate.provider in _NETWORK_PROVIDER_TOKENS:
            if not self._config.allow_network_provider:
                return self._blocked(
                    candidate,
                    tc,
                    route_ref,
                    "LOCAL_MODEL_LIVE_ADMISSION_BLOCKED_NETWORK_PROVIDER",
                    f"candidate.provider {candidate.provider!r} is a network "
                    f"provider; allow_network_provider=False",
                    network_required=True,
                )
        if candidate.provider not in _LOCAL_PROVIDERS:
            return self._blocked(
                candidate,
                tc,
                route_ref,
                "LOCAL_MODEL_LIVE_ADMISSION_BLOCKED_UNKNOWN_PROVIDER",
                f"candidate.provider {candidate.provider!r} is not a known local provider",
            )

        # 4. Stale id.
        if candidate.model_id in STALE_MODEL_IDS:
            return self._blocked(
                candidate,
                tc,
                route_ref,
                "LOCAL_MODEL_LIVE_ADMISSION_BLOCKED_STALE_MODEL_ID",
                f"model_id {candidate.model_id!r} is in STALE_MODEL_IDS",
                stale_model_id_detected=True,
            )

        # 5. Unpinned id (not in CURRENT_MODEL_IDS).
        if (
            self._config.require_pinned_id
            and candidate.provider != ModelProvider.NO_MODEL.value
            and candidate.model_id not in CURRENT_MODEL_IDS
        ):
            return self._blocked(
                candidate,
                tc,
                route_ref,
                "LOCAL_MODEL_LIVE_ADMISSION_BLOCKED_UNPINNED_MODEL",
                f"model_id {candidate.model_id!r} not pinned in CURRENT_MODEL_IDS",
            )

        # 6. Unsupported task class.
        if tc not in self._config.allowed_task_classes:
            return self._blocked(
                candidate,
                tc,
                route_ref,
                "LOCAL_MODEL_LIVE_ADMISSION_BLOCKED_UNSUPPORTED_TASK_CLASS",
                f"task_class {tc!r} not in policy.allowed_task_classes",
            )

        # 7. Candidate must be metadata-admitted by the base policy.
        meta = self._policy.evaluate(candidate)
        if not meta.is_admitted:
            # Bubble up the base policy's refusal as a metadata-only
            # decision; never opens live.
            return LiveModelAdmissionRecord(
                model_id=candidate.model_id,
                provider=candidate.provider,
                task_class=tc,
                route_decision_ref=route_ref,
                availability_checked=False,
                pinned=candidate.model_id in CURRENT_MODEL_IDS,
                stale_model_id_detected=False,
                network_required=candidate.requires_network,
                decision="LOCAL_MODEL_LIVE_ADMISSION_METADATA_ONLY",
                live_call_authorized=False,
                source_mutation_authorized=False,
                corpus_write_authorized=False,
                training_eligible=False,
                notes=(f"base policy refused: {meta.decision}",),
            )

        # 8. Availability check.
        if not inventory.is_available(candidate.model_id):
            return self._blocked(
                candidate,
                tc,
                route_ref,
                "LOCAL_MODEL_LIVE_ADMISSION_BLOCKED_MODEL_UNAVAILABLE",
                f"model_id {candidate.model_id!r} not present in inventory",
            )

        # All checks passed — admit live. Source mutation, corpus
        # write, and training eligibility remain blocked.
        return LiveModelAdmissionRecord(
            model_id=candidate.model_id,
            provider=candidate.provider,
            task_class=tc,
            route_decision_ref=route_ref,
            availability_checked=True,
            pinned=candidate.model_id in CURRENT_MODEL_IDS,
            stale_model_id_detected=False,
            network_required=candidate.requires_network,
            decision="LOCAL_MODEL_LIVE_ADMISSION_READY",
            live_call_authorized=True,
            source_mutation_authorized=False,
            corpus_write_authorized=False,
            training_eligible=False,
            notes=(
                "live admission granted; downstream gates "
                "(source mutation, corpus, training) remain closed",
            ),
        )

    @staticmethod
    def _blocked(
        candidate: LocalModelCandidate,
        task_class: str,
        route_ref: str,
        decision: str,
        reason: str,
        *,
        stale_model_id_detected: bool = False,
        network_required: bool = False,
    ) -> LiveModelAdmissionRecord:
        return LiveModelAdmissionRecord(
            model_id=candidate.model_id,
            provider=candidate.provider,
            task_class=task_class,
            route_decision_ref=route_ref,
            availability_checked=False,
            pinned=candidate.model_id in CURRENT_MODEL_IDS,
            stale_model_id_detected=stale_model_id_detected,
            network_required=network_required,
            decision=decision,
            live_call_authorized=False,
            source_mutation_authorized=False,
            corpus_write_authorized=False,
            training_eligible=False,
            notes=(reason,),
        )


__all__ = [
    "LiveModelAdmissionGate",
    "LiveModelAdmissionConfig",
    "LiveModelAdmissionRecord",
    "LiveAdmissionMode",
    "LOCAL_MODEL_LIVE_ADMISSION_STATUS_TOKENS",
]
