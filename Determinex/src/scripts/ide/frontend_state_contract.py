"""Frontend state contract.

Defines the JSON shape the UI is expected to render. Validates a
candidate state dict has every required section and includes the
conservative defaults (source_mutation BLOCKED, training_eligibility
False, risk_warnings present).
"""

from __future__ import annotations

from collections.abc import Mapping

from .frontend_state_contract_record import (
    FRONTEND_STATE_CONTRACT_STATUS_TOKENS,
    REQUIRED_SECTIONS,
    FrontendStateContractRecord,
)

_DEFAULT_RISK_WARNINGS: tuple[str, ...] = (
    "DIAGNOSIS_IS_ADVISORY",
    "PATCH_PLAN_IS_UNTRUSTED",
    "VERIFIER_REMAINS_SOURCE_OF_TRUTH",
    "TEMP_WORKSPACE_ONLY",
    "SOURCE_MUTATION_REQUIRES_HUMAN_APPROVAL",
    "APPROVAL_CAN_BE_REVOKED",
    "TRAINING_ELIGIBILITY_FALSE",
)


def default_risk_warnings() -> tuple[str, ...]:
    return _DEFAULT_RISK_WARNINGS


def validate_state(state: Mapping[str, object]) -> FrontendStateContractRecord:
    present = tuple(s for s in REQUIRED_SECTIONS if s in state)
    missing = tuple(s for s in REQUIRED_SECTIONS if s not in state)

    risk_warnings = tuple(state.get("risk_warnings") or ())
    if not risk_warnings:
        risk_warnings = _DEFAULT_RISK_WARNINGS

    source_mutation = str(
        state.get("source_apply", {}).get("status", "")
        if isinstance(state.get("source_apply"), dict)
        else state.get("source_apply", "")
    )
    if not source_mutation:
        source_mutation = "BLOCKED_PENDING_REAL_HUMAN_APPROVAL"

    training_eligibility = str(
        state.get("corpus_eligibility", "BLOCKED_BY_DEFAULT")
        if not isinstance(state.get("corpus_eligibility"), dict)
        else state.get("corpus_eligibility", {}).get("status", "BLOCKED_BY_DEFAULT")
    )

    statuses: list[str] = []
    if missing:
        statuses.append("FRONTEND_STATE_BLOCKED_FIELDS_MISSING")
        decision = "FRONTEND_STATE_BLOCKED_FIELDS_MISSING"
    else:
        decision = "FRONTEND_STATE_CONTRACT_READY"
        statuses.append(decision)
    statuses.append("FRONTEND_STATE_RISK_WARNINGS_PRESENT")
    statuses.append("FRONTEND_STATE_SOURCE_MUTATION_BLOCKED_VISIBLE")

    return FrontendStateContractRecord(
        decision=decision,
        sections_present=present,
        sections_missing=missing,
        risk_warnings=risk_warnings,
        source_mutation=source_mutation,
        training_eligibility=training_eligibility,
        statuses_seen=tuple(statuses),
        notes=(),
    )


def sample_ready_state() -> dict[str, object]:
    """A minimal state instance the IDE can use for a smoke render."""
    return {
        "workspace": {"path": "", "status": "WORKSPACE_OPEN_READY"},
        "adapter": {"name": "Python", "build_system_id": "pip"},
        "verifier": {"status": "WORKSPACE_OPEN_VERIFIER_AVAILABLE"},
        "model_route": {"status": "MODEL_ROUTE_DRY_RUN_DEFAULT"},
        "diagnosis": {"status": "IDE_DIAGNOSE_DRY_RUN_READY"},
        "patch_plan": {"status": "IDE_PATCH_PLAN_SOURCE_UNCHANGED"},
        "temp_verifier": {"status": "IDE_TEMP_VERIFY_HUMAN_APPROVAL_REQUIRED"},
        "human_approval": {"status": "IDE_APPROVAL_REQUIRED"},
        "source_apply": {"status": "BLOCKED_PENDING_REAL_HUMAN_APPROVAL"},
        "corpus_eligibility": {"status": "BLOCKED_BY_DEFAULT"},
        "evidence": {"locks": [], "evidence_files": []},
        "risk_warnings": list(_DEFAULT_RISK_WARNINGS),
    }


__all__ = [
    "validate_state",
    "sample_ready_state",
    "FrontendStateContractRecord",
    "FRONTEND_STATE_CONTRACT_STATUS_TOKENS",
    "REQUIRED_SECTIONS",
    "default_risk_warnings",
]
