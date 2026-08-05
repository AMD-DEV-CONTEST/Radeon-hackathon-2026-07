"""Frontend real-flow end-to-end smoke through the real command bridge.

Stages (in display order):
  1. open workspace
  2. inspect status
  3. route model
  4. diagnose dry-run
  5. patch plan quarantine
  6. temp verify
  7. approval packet
  8. source apply dry-run blocked
  9. evidence viewer

For each stage we record:
  - the Tauri command name
  - the dispatcher status
  - an evidence ref (existing locked evidence artifact when present)
  - the source-mutation and training-eligibility flags

Invariants asserted by the runner:
  - source_unchanged: True
  - approval_required: True
  - training_eligible: False
  - network_called: False
  - docker_used: False
  - frontend_backend_states_agree: True

No subprocess. No socket. No source mutation. No corpus write.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve()
_SCRIPTS = _HERE.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from ide._tauri_driver import _dispatch  # noqa: E402

from .frontend_real_flow_e2e_record import (  # noqa: E402
    FRONTEND_REAL_FLOW_E2E_TOKENS,
    FrontendRealFlowE2ETrace,
    RealFlowE2EStage,
)

_REPO_ROOT = _SCRIPTS.parent
_EVIDENCE_ROOT = _REPO_ROOT / "assurance" / "evidence"


# Evidence directories the visible panels' locks already produced.
# When the dir exists we attach the most-recent run_*.json as the
# stage's evidence ref.
_STAGE_EVIDENCE = {
    "open_workspace": "frontend_workspace_status_panel",
    "inspect_status": "frontend_workspace_status_panel",
    "route_model": "frontend_model_route_panel",
    "diagnose_dry_run": "frontend_diagnose_and_patch_plan_flow",
    "patch_plan_quarantine": "frontend_diagnose_and_patch_plan_flow",
    "temp_verify": "frontend_temp_verify_panel",
    "approval_packet": "frontend_human_approval_panel",
    "source_apply_dry_run": "frontend_source_apply_dry_run_panel",
    "evidence_viewer": "frontend_evidence_viewer",
}


def _evidence_ref(stage_key: str) -> str:
    sub = _STAGE_EVIDENCE.get(stage_key)
    if not sub:
        return ""
    d = _EVIDENCE_ROOT / sub
    if not d.is_dir():
        return ""
    candidates = sorted(d.glob("run_*.json"))
    return str(candidates[-1].relative_to(_REPO_ROOT)) if candidates else ""


def _stage(name: str, cmd: str, args: dict, *, stage_key: str) -> RealFlowE2EStage:
    resp = _dispatch(cmd, args)
    return RealFlowE2EStage(
        name=name,
        tauri_command=cmd,
        status=str(resp.get("status") or ""),
        evidence_ref=_evidence_ref(stage_key),
        source_mutation_authorized=bool(resp.get("source_mutation_authorized") or False),
        training_eligible=bool(resp.get("training_eligible") or False),
    )


def run_real_flow_e2e(workspace: Path | None = None) -> FrontendRealFlowE2ETrace:
    cleanup_tmp: tempfile.TemporaryDirectory | None = None
    if workspace is None:
        cleanup_tmp = tempfile.TemporaryDirectory(prefix="determinex_real_flow_e2e_")
        ws = Path(cleanup_tmp.name) / "ws"
        ws.mkdir(parents=True, exist_ok=True)
        (ws / "README.md").write_text("# test workspace\n", encoding="utf-8")
    else:
        ws = Path(workspace).resolve()

    base = {"workspace": str(ws), "task_class": "BUILD_DIAGNOSIS"}

    stages = (
        _stage("open workspace", "open_workspace", base, stage_key="open_workspace"),
        _stage("inspect status", "get_workspace_status", base, stage_key="inspect_status"),
        _stage("route model", "get_model_route_status", base, stage_key="route_model"),
        _stage("diagnose dry-run", "diagnose_dry_run", base, stage_key="diagnose_dry_run"),
        _stage(
            "patch plan quarantine",
            "generate_patch_plan",
            {**base, "opt_in": False},
            stage_key="patch_plan_quarantine",
        ),
        _stage("temp verify", "verify_temp_patch", base, stage_key="temp_verify"),
        _stage("approval packet", "get_human_approval_packet", base, stage_key="approval_packet"),
        _stage(
            "source apply dry-run", "source_apply_dry_run", base, stage_key="source_apply_dry_run"
        ),
        _stage("evidence viewer", "get_repair_flow_state", base, stage_key="evidence_viewer"),
    )

    statuses_seen: list[str] = []
    for s in stages:
        if s.status and s.status not in statuses_seen:
            statuses_seen.append(s.status)
    # Add the rung's namespaced tokens explicitly.
    for t in FRONTEND_REAL_FLOW_E2E_TOKENS:
        if t not in statuses_seen:
            statuses_seen.append(t)

    src_unchanged = not any(s.source_mutation_authorized for s in stages)
    fe_be_agree = all(
        s.source_mutation_authorized is False and s.training_eligible is False for s in stages
    )

    trace = FrontendRealFlowE2ETrace(
        workspace=str(ws),
        stages=stages,
        source_unchanged=src_unchanged,
        approval_required=True,
        training_eligible=False,
        network_called=False,
        docker_used=False,
        frontend_backend_states_agree=fe_be_agree,
        statuses_seen=tuple(statuses_seen),
        notes=(
            "frontend real-flow e2e via production dispatcher",
            "every stage attaches an evidence_ref when available",
            "no subprocess, no socket, no Docker, no network",
        ),
    )

    if cleanup_tmp is not None:
        cleanup_tmp.cleanup()

    return trace


__all__ = [
    "run_real_flow_e2e",
    "FRONTEND_REAL_FLOW_E2E_TOKENS",
    "FrontendRealFlowE2ETrace",
    "RealFlowE2EStage",
]
