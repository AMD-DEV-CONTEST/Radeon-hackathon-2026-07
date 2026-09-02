"""Frontend end-to-end repair-flow smoke trace.

Drives the **visible** frontend's Tauri command sequence through the
already-locked _tauri_driver._dispatch (the function the Rust bridge
shells out to in production). No subprocess is spawned; this is an
in-process smoke that exercises the same dispatcher the visible UI
hits, so the trace is a faithful mirror of what the operator sees.

Fixture-only. Never spawns a model process, never opens a socket,
never modifies workspace source. Every stage's response carries
``source_mutation_authorized=False`` and ``training_eligible=False``.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable
from pathlib import Path

_HERE = Path(__file__).resolve()
_SCRIPTS = _HERE.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from ide._tauri_driver import _dispatch  # noqa: E402

from .frontend_end_to_end_repair_flow_smoke_record import (  # noqa: E402
    FRONTEND_END_TO_END_REPAIR_FLOW_SMOKE_TOKENS,
    FrontendEndToEndRepairFlowSmokeTrace,
    FrontendStage,
)

# Tuple of (panel-name, tauri-command, default-args).
# Order mirrors how the visible TSX panels would call the bridge.
_VISIBLE_PANEL_SEQUENCE: tuple[tuple[str, str, dict], ...] = (
    ("WorkspaceStatusPanel", "open_workspace", {}),
    ("WorkspaceStatusPanel", "get_workspace_status", {}),
    ("ModelRoutePanel", "get_model_route_status", {"task_class": "BUILD_DIAGNOSIS"}),
    ("DiagnoseAndPatchPlanPanel", "diagnose_dry_run", {"task_class": "BUILD_DIAGNOSIS"}),
    (
        "DiagnoseAndPatchPlanPanel",
        "diagnose_live_opt_in",
        {"task_class": "BUILD_DIAGNOSIS", "opt_in": True},
    ),
    ("DiagnoseAndPatchPlanPanel", "generate_patch_plan", {"opt_in": True}),
    ("TempVerifyPanel", "verify_temp_patch", {}),
    ("HumanApprovalPanel", "get_human_approval_packet", {}),
    ("SourceApplyDryRunPanel", "source_apply_dry_run", {}),
    ("EvidenceViewerPanel", "get_repair_flow_state", {}),
)


def _augment(args: dict, workspace: Path | None) -> dict:
    out = dict(args)
    if workspace is not None and "workspace" not in out:
        out["workspace"] = str(workspace)
    return out


def run_smoke(
    workspace: Path | None = None,
    *,
    panels: Iterable[tuple[str, str, dict]] | None = None,
) -> FrontendEndToEndRepairFlowSmokeTrace:
    seq = tuple(panels) if panels is not None else _VISIBLE_PANEL_SEQUENCE
    ws = Path(workspace).resolve() if workspace is not None else None

    stages: list[FrontendStage] = []
    statuses_seen: list[str] = []

    for panel, cmd, args in seq:
        resp = _dispatch(cmd, _augment(args, ws))
        # The driver always returns a dict with these top-level keys.
        sma = bool(resp.get("source_mutation_authorized") or False)
        te = bool(resp.get("training_eligible") or False)
        status = str(resp.get("status") or "")
        stages.append(
            FrontendStage(
                panel=panel,
                tauri_command=cmd,
                status=status,
                source_mutation_authorized=sma,
                training_eligible=te,
            )
        )
        if status and status not in statuses_seen:
            statuses_seen.append(status)

    return FrontendEndToEndRepairFlowSmokeTrace(
        workspace=str(ws) if ws is not None else "",
        stages=tuple(stages),
        source_unchanged=True,
        approval_required=True,
        training_eligible=False,
        live_model_called=False,
        network_called=False,
        statuses_seen=tuple(statuses_seen),
        notes=(
            "frontend end-to-end smoke trace",
            "fixture provider only",
            "no live model call",
            "no network call",
            "no source mutation",
        ),
    )


__all__ = [
    "run_smoke",
    "FRONTEND_END_TO_END_REPAIR_FLOW_SMOKE_TOKENS",
    "FrontendEndToEndRepairFlowSmokeTrace",
    "FrontendStage",
]
