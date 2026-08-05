"""Machine-readable readiness matrix for arbitrary-repo repair.

Builds a :class:`ReadinessMatrix` from the apparatus's known build
adapters + the locks that have landed. Every row carries a closed-set
``ready_level`` token. The matrix is a pure function — no I/O beyond
reading lock-manifest *file names* (presence only, never contents).

Ready levels:

  * ``READY_MOCKED_TRACE`` — full mocked end-to-end trace works on a
    fixture of this shape (BuildAdapter detects, ModelRouter routes,
    MockModelClient invokes, SafePatchWorkspace applies, evidence
    captured). The four foundation rungs are landed.
  * ``READY_TEMP_PATCH_ONLY`` — verifier-backed but no live model
    admission yet; patches are only ever applied to temp workspaces.
  * ``READY_REQUIRES_LIVE_MODEL_ADMISSION`` — adapter + verifier
    exist, mocked trace works, but a live model has not been admitted
    for this row's task class.
  * ``READY_REQUIRES_VERIFIER`` — adapter exists, but the verifier
    coverage matrix marks the verifier missing or partial.
  * ``BLOCKED_UNSUPPORTED`` — no adapter; cannot proceed.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

_HERE = Path(__file__).resolve()
_SCRIPTS = _HERE.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from .arbitrary_repo_readiness_record import (
    READINESS_MATRIX_STATUS_TOKENS,
    ReadinessMatrix,
    ReadinessRow,
    ReadyLevel,
)

_REPO_ROOT = _HERE.parent.parent.parent  # scripts/intake/foo.py → repo root
_LOCKS_DIR = _REPO_ROOT / "locks" / "sentinel"


# The canonical row set the directive asks for. Tests pin this.
_CANONICAL_ROWS: tuple[dict[str, object], ...] = (
    {
        "language": "Python",
        "build_system": "pip",
        "test_framework": "pytest",
        "verifier_backed": True,
        "live_model_admitted": False,
    },
    {
        "language": "Rust",
        "build_system": "cargo",
        "test_framework": "cargo test",
        "verifier_backed": True,
        "live_model_admitted": False,
    },
    {
        "language": "Go",
        "build_system": "go",
        "test_framework": "go test",
        "verifier_backed": True,
        "live_model_admitted": False,
    },
    {
        "language": "TypeScript",
        "build_system": "npm",
        "test_framework": "jest",
        "verifier_backed": True,
        "live_model_admitted": False,
    },
    {
        "language": "TypeScript",
        "build_system": "npm",
        "test_framework": "vitest",
        "verifier_backed": True,
        "live_model_admitted": False,
    },
    {
        "language": "Java",
        "build_system": "maven",
        "test_framework": "junit",
        "verifier_backed": True,
        "live_model_admitted": False,
    },
    {
        "language": "Java",
        "build_system": "gradle",
        "test_framework": "junit",
        "verifier_backed": True,
        "live_model_admitted": False,
    },
    {
        "language": "Unknown",
        "build_system": "unknown",
        "test_framework": "",
        "verifier_backed": False,
        "live_model_admitted": False,
    },
)


def _lock_present(name: str) -> bool:
    return (_LOCKS_DIR / f"{name}.json").is_file()


def _campaign_state() -> dict[str, bool]:
    return {
        "model_router": _lock_present("MODEL_ROUTER_LOCK_001"),
        "mocked_repair": _lock_present("LLM_MOCKED_INTAKE_REPAIR_LOCK_001"),
        "safe_patch": _lock_present("SAFE_PATCH_DIFF_ROLLBACK_LOCK_001"),
        "verified_trace": _lock_present("VERIFIED_REPAIR_TRACE_LOCK_001"),
        "human_approval": _lock_present("HUMAN_APPROVAL_SOURCE_MUTATION_GATE_LOCK_001"),
        "ide_state": _lock_present("IDE_REPAIR_STATE_MODEL_LOCK_001"),
        "corpus_guard": _lock_present("CORPUS_ELIGIBILITY_REPAIR_TRACE_GUARD_LOCK_001"),
        "local_admission": _lock_present("LOCAL_MODEL_ADMISSION_POLICY_LOCK_001"),
    }


def _decide_ready_level(
    row_template: dict[str, object],
    state: dict[str, bool],
) -> ReadyLevel:
    if row_template["language"] == "Unknown":
        return ReadyLevel.BLOCKED_UNSUPPORTED

    # If verifier missing → REQUIRES_VERIFIER.
    if not row_template.get("verifier_backed", False):
        return ReadyLevel.REQUIRES_VERIFIER

    # If the four foundation rungs are landed but live admission is False,
    # we're at TEMP_PATCH_ONLY (and the row also satisfies MOCKED_TRACE).
    foundation_landed = all(
        (
            state["model_router"],
            state["mocked_repair"],
            state["safe_patch"],
            state["verified_trace"],
        )
    )

    if not foundation_landed:
        return ReadyLevel.REQUIRES_VERIFIER  # conservative fallback

    if row_template.get("live_model_admitted", False):
        # Future state — never True at this rung.
        return ReadyLevel.TEMP_PATCH_ONLY

    # Foundation landed, no live admission yet → TEMP_PATCH_ONLY for
    # supported rows. MOCKED_TRACE is implied (and lower). Choose the
    # most-specific ready level.
    if state.get("local_admission", False):
        return ReadyLevel.REQUIRES_LIVE_MODEL_ADMISSION

    return (
        ReadyLevel.READY_MOCKED_TRACE
        if not state.get("local_admission", False)
        else ReadyLevel.REQUIRES_LIVE_MODEL_ADMISSION
    )


def build_readiness_matrix() -> ReadinessMatrix:
    state = _campaign_state()
    rows: list[ReadinessRow] = []
    notes: list[str] = []

    for tpl in _CANONICAL_ROWS:
        unsupported = tpl["language"] == "Unknown"
        level = _decide_ready_level(tpl, state)
        rows.append(
            ReadinessRow(
                language=str(tpl["language"]),
                build_system=str(tpl["build_system"]),
                test_framework=str(tpl["test_framework"]),
                adapter_backed=not unsupported,
                verifier_backed=bool(tpl["verifier_backed"]),
                model_route_exists=state["model_router"],
                mocked_repair_trace_exists=state["mocked_repair"] and not unsupported,
                safe_patch_workspace_supported=state["safe_patch"] and not unsupported,
                human_approval_gate_exists=state["human_approval"],
                ide_state_exposed=state["ide_state"],
                corpus_guard_exists=state["corpus_guard"],
                live_model_admitted=bool(tpl["live_model_admitted"]),
                ready_level=level.value,
            )
        )

    if not state["local_admission"]:
        notes.append(
            "LOCAL_MODEL_ADMISSION_POLICY_LOCK_001 is metadata-only; "
            "no live admission has been granted yet."
        )

    return ReadinessMatrix(
        generated_at=datetime.now(UTC).isoformat(),
        rows=tuple(rows),
        notes=tuple(notes),
    )


__all__ = [
    "build_readiness_matrix",
    "ReadinessMatrix",
    "ReadinessRow",
    "ReadyLevel",
    "READINESS_MATRIX_STATUS_TOKENS",
]
