"""Records for FRONTEND_LIVE_DIAGNOSE_OPT_IN_SMOKE_LOCK_001."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

FRONTEND_LIVE_DIAGNOSE_OPT_IN_SMOKE_TOKENS = (
    "FRONTEND_LIVE_DIAGNOSE_SMOKE_READY",
    "FRONTEND_LIVE_DIAGNOSE_BLOCKED_NO_PROVIDER",
    "FRONTEND_LIVE_DIAGNOSE_BLOCKED_NOT_OPTED_IN",
    "FRONTEND_LIVE_DIAGNOSE_ADVISORY_ONLY",
    "FRONTEND_LIVE_DIAGNOSE_NO_PATCH_GENERATED",
    "FRONTEND_LIVE_DIAGNOSE_NO_SOURCE_MUTATION",
    "FRONTEND_LIVE_DIAGNOSE_NO_TRAINING_ROW",
)


@dataclass(frozen=True)
class FrontendLiveDiagnoseSmokeStage:
    name: str
    tauri_command: str
    status: str
    opt_in: bool = False
    provider_configured: bool = False


@dataclass(frozen=True)
class FrontendLiveDiagnoseSmokeTrace:
    workspace: str
    dry_run_stage: FrontendLiveDiagnoseSmokeStage
    not_opted_in_stage: FrontendLiveDiagnoseSmokeStage
    no_provider_stage: FrontendLiveDiagnoseSmokeStage
    advisory_stage: FrontendLiveDiagnoseSmokeStage
    output_advisory_only: bool
    patch_generated: bool
    source_mutated: bool
    training_row_written: bool
    statuses_seen: tuple[str, ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["statuses_seen"] = list(self.statuses_seen)
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)


__all__ = [
    "FRONTEND_LIVE_DIAGNOSE_OPT_IN_SMOKE_TOKENS",
    "FrontendLiveDiagnoseSmokeStage",
    "FrontendLiveDiagnoseSmokeTrace",
]
