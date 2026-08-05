"""Records for DETERMINEX_IDE_TAURI_INTEGRATED_FINAL_STATE_LOCK_001."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

DETERMINEX_IDE_TAURI_INTEGRATED_FINAL_STATE_TOKENS = (
    "DETERMINEX_IDE_TAURI_INTEGRATED_FINAL_STATE_WRITTEN",
    "TAURI_LIB_RS_WIRING_READY",
    "FRONTEND_COMMAND_CLIENT_READY",
    "PANEL_COMMAND_WIRING_READY",
    "LOCAL_MODEL_PROVIDER_CONFIG_READY_OPT_IN",
    "OLLAMA_PROVIDER_SMOKE_READY_OR_BLOCKED_WITH_REASON",
    "LIVE_DIAGNOSE_OPT_IN_READY_OR_BLOCKED_WITH_REASON",
    "APPROVAL_PACKET_ROUNDTRIP_READY",
    "FRONTEND_REAL_FLOW_E2E_READY",
    "SOURCE_MUTATION_BLOCKED_PENDING_REAL_HUMAN_APPROVAL",
    "TRAINING_ELIGIBILITY_BLOCKED_BY_DEFAULT",
    "RELEASE_READINESS_NOT_RELEASED",
    "NEXT_UNBLOCKER_DECLARED",
)


@dataclass(frozen=True)
class DeterminexIDETauriIntegratedFinalState:
    generated_at: str
    tauri_lib_rs_wiring: str
    frontend_command_client: str
    panel_command_wiring: str
    local_model_provider_config: str
    ollama_provider_smoke: str
    live_diagnose_opt_in: str
    approval_packet_roundtrip: str
    frontend_real_flow_e2e: str
    source_mutation: str
    training_eligibility: str
    release_readiness: str
    next_unblocker: str
    upstream_locks_present: tuple[str, ...] = field(default_factory=tuple)
    upstream_locks_missing: tuple[str, ...] = field(default_factory=tuple)
    statuses_seen: tuple[str, ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["upstream_locks_present"] = list(self.upstream_locks_present)
        d["upstream_locks_missing"] = list(self.upstream_locks_missing)
        d["statuses_seen"] = list(self.statuses_seen)
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)


__all__ = [
    "DETERMINEX_IDE_TAURI_INTEGRATED_FINAL_STATE_TOKENS",
    "DeterminexIDETauriIntegratedFinalState",
]
