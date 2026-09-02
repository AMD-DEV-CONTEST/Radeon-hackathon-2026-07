"""Tauri Rust → Python driver.

The Tauri Rust bridge (frontend/src-tauri/src/ide_repair_bridge.rs)
shells out to this script with two args:

    python scripts/ide/_tauri_driver.py <command> <args_json>

stdout is a single JSON line shaped as the Rust struct
``IdeRepairResponse``. stderr is reserved for diagnostics. Exit codes:

    0 — command produced a valid response (even if BLOCKED)
    1 — driver internal error (malformed input, missing module, etc.)

This script never performs source mutation, never calls a live model,
never accesses the network. Every command path goes through the
already-locked IDEBackendCommandSurface.
"""

from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_SCRIPTS = _HERE.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from ide.backend_command_surface import IDEBackendCommandSurface  # noqa: E402

_MODEL_COMMANDS = {"build_idea", "diagnose_live_opt_in", "generate_patch_plan"}
_DEFAULT_LOCAL_MODEL = "determinex-engineer-v11-dsl"


def _build_local_config(model_id: str):
    try:
        from models.local_model_config_wizard import LocalModelConfigWizard, WizardConfig
    except Exception:
        return None
    root = Path.home() / ".determinex" / "local_models"
    rec = LocalModelConfigWizard(WizardConfig(config_root=root)).write_config(
        provider="ollama",
        model_id=model_id or _DEFAULT_LOCAL_MODEL,
        capabilities=("code",),
        task_classes_allowed=("BUILD_DIAGNOSIS",),
        enabled=True,
    )
    return rec if getattr(rec, "is_written", False) else None


def _respond(
    command: str, status: str, payload: dict | None = None, notes: tuple[str, ...] = ()
) -> dict[str, object]:
    return {
        "command": command,
        "status": status,
        "payload": payload or {},
        "source_mutation_authorized": False,
        "training_eligible": False,
        "notes": list(notes),
    }


def _dispatch(command: str, args: dict[str, object]) -> dict[str, object]:
    surface = IDEBackendCommandSurface()
    workspace = args.get("workspace")
    workspace_path = Path(workspace) if isinstance(workspace, str) and workspace else None
    task_class = str(args.get("task_class") or "BUILD_DIAGNOSIS")
    opt_in = bool(args.get("opt_in") or False)
    unified_diff = str(args.get("unified_diff") or "")
    user_request = str(args.get("user_request") or args.get("idea_text") or "")
    idea_text = str(args.get("idea_text") or "")
    learning_mode = str(args.get("mode") or "")
    learning_context = str(args.get("context") or "")
    corpus_query = str(args.get("corpus_query") or "")
    corpus_mode = str(args.get("corpus_mode") or "ask")
    config = None
    if command in _MODEL_COMMANDS or args.get("model_id"):
        config = _build_local_config(str(args.get("model_id") or ""))

    # Tauri command → inner surface command map.
    if command == "open_workspace" or command == "get_workspace_status":
        inner = "inspect_workspace"
    elif command == "get_model_route_status":
        inner = "route_model"
    elif command == "diagnose_dry_run":
        inner = "diagnose_dry_run"
    elif command == "diagnose_live_opt_in":
        inner = "diagnose_live_opt_in"
    elif command == "generate_patch_plan":
        inner = "generate_patch_plan_opt_in"
    elif command == "verify_temp_patch":
        inner = "verify_temp_patch"
    elif command == "get_human_approval_packet":
        inner = "get_human_approval_packet"
    elif command == "source_apply_dry_run":
        # CLAUDE-AUTH-006 remediation: now routes to a dedicated
        # source_apply_dry_run inner command (not get_repair_state).
        # The inner command still never performs a real apply.
        inner = "source_apply_dry_run"
    elif command == "get_repair_flow_state":
        inner = "get_repair_state"
    elif command == "generate_llm_program_advisory":
        inner = "generate_llm_program_advisory"
    elif command == "preview_idea_oracle":
        inner = "synthesize_oracle_preview"
    elif command == "build_idea":
        inner = "build_from_idea_opt_in"
    elif command == "repair_diagnose":
        inner = "repair_diagnose"
    elif command == "get_governance_status":
        inner = "get_governance_status"
    # DETERMINEX_TAURI_UNIFIED_PRODUCT_COMMAND_SURFACE_LOCK_001 (rung 1).
    # Read-only unified-product view-model commands. Tauri verb maps
    # 1:1 to the inner surface command (command_name_matches_behavior).
    elif command in (
        "get_unified_product_navigation_model",
        "get_idea_lab_workflow_state",
        "get_repo_clinic_workflow_state",
        "get_maintenance_bay_workflow_state",
        "get_learning_studio_workflow_state",
        "generate_learning_studio_content",
        "run_maintenance_bay_scan",
        "get_proof_operator_center_state",
        "get_user_level_teaching_windows",
        "get_unified_splash_demo_spec",
        # DETERMINEX_REACT_IDEA_LAB_VERIFIED_DEMO_STATUS_BINDING_LOCK_001
        "get_idea_lab_verified_demo_status",
        # DETERMINEX_REACT_REPO_CLINIC_VERIFIED_DEMO_STATUS_BINDING_LOCK_001
        "get_repo_clinic_verified_demo_status",
        # DETERMINEX_REACT_MAINTENANCE_BAY_VERIFIED_DEMO_STATUS_BINDING_LOCK_001
        "get_maintenance_bay_verified_demo_status",
        # DETERMINEX_REACT_LEARNING_STUDIO_VERIFIED_DEMO_STATUS_BINDING_LOCK_001
        "get_learning_studio_verified_demo_status",
        # DETERMINEX_REACT_PROOF_OPERATOR_CENTER_MILESTONE_DASHBOARD_BINDING_LOCK_001
        "get_proof_operator_center_milestone_dashboard_status",
        "query_corpus",
    ):
        inner = command
    else:
        return _respond(
            command, "TAURI_COMMAND_BLOCKED_UNKNOWN", notes=(f"unknown command {command!r}",)
        )

    res = surface.call(
        inner,
        workspace=workspace_path,
        task_class=task_class,
        opt_in=opt_in,
        config=config,
        unified_diff=unified_diff,
        idea_text=idea_text,
        user_request=user_request,
        learning_mode=learning_mode,
        learning_context=learning_context,
        corpus_query=corpus_query,
        corpus_mode=corpus_mode,
    )

    # Map inner status → Tauri status (mirrors the Python tauri_backend_bridge).
    inner_to_tauri = {
        "IDE_COMMAND_OK": "TAURI_COMMAND_OK",
        "IDE_COMMAND_TEMP_ONLY": "TAURI_COMMAND_TEMP_ONLY",
        "IDE_COMMAND_SOURCE_MUTATION_BLOCKED": "TAURI_COMMAND_SOURCE_MUTATION_BLOCKED",
        "IDE_COMMAND_BLOCKED_NOT_OPTED_IN": "TAURI_COMMAND_BLOCKED_NOT_OPTED_IN",
        "IDE_COMMAND_BLOCKED_NO_MODEL": "TAURI_COMMAND_BLOCKED_NO_MODEL",
        "IDE_COMMAND_BLOCKED_UNKNOWN_COMMAND": "TAURI_COMMAND_BLOCKED_UNKNOWN",
    }
    # An UNMAPPED status is translated mechanically, never defaulted to OK -- the same fix
    # as tauri_backend_bridge.call, which this table mirrors. Found 2026-08-02 by an AST
    # scan for `.get(..., <success literal>)` after the bridge's copy was fixed by hand:
    # the duplicate here would have kept reporting every unmapped status as success, so the
    # frontend's behaviour would have depended on which of the two paths it happened to
    # take. A default that means "fine" makes every future omission a silent lie.
    status = inner_to_tauri.get(res.status) or (
        res.status.replace("IDE_COMMAND_", "TAURI_COMMAND_", 1)
        if res.status.startswith("IDE_COMMAND_")
        else (res.status or "TAURI_COMMAND_UNKNOWN_STATUS")
    )
    return _respond(command, status, payload=res.payload, notes=tuple(res.notes))


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(
            json.dumps(
                _respond(
                    "",
                    "TAURI_RUST_COMMAND_BRIDGE_BLOCKED_BACKEND_MISSING",
                    notes=("driver invoked without command/args",),
                )
            )
        )
        return 1
    command = argv[1]
    try:
        args = json.loads(argv[2])
        if not isinstance(args, dict):
            raise ValueError("args must be a JSON object")
    except (ValueError, json.JSONDecodeError) as exc:
        print(
            json.dumps(
                _respond(
                    command,
                    "TAURI_RUST_COMMAND_BRIDGE_BLOCKED_BACKEND_MISSING",
                    notes=(f"bad args JSON: {exc}",),
                )
            )
        )
        return 1

    # stdout is a JSON-only channel: ide_repair_bridge.rs feeds the whole of it
    # to serde_json::from_str, so a single stray print anywhere downstream turns
    # a good result into "malformed JSON from driver".
    #
    # That was not hypothetical. build_idea reaches determinex_verified_search,
    # whose per-sample progress lines ("[vs] r1 s1/6 t=0.0 gen 3s verify 1s ->
    # 1 fail") go to stdout. A real run emitted 12 of them ahead of a perfectly
    # valid response, and the Rust side rejected the lot with "expected value at
    # line 1 column 6" -- column 6 being the "[vs]" prefix. The amplifier had
    # actually done the work; only the transport was broken.
    #
    # Redirecting stdout to stderr for the dispatch keeps that output visible in
    # the app log (where it is genuinely useful progress) while guaranteeing the
    # only thing on real stdout is the response. Fixes every command at once
    # rather than chasing prints library by library.
    real_stdout = sys.stdout
    try:
        with contextlib.redirect_stdout(sys.stderr):
            response = _dispatch(command, args)
    except Exception as exc:  # noqa: BLE001 - must still answer in JSON
        response = _respond(
            command,
            "TAURI_RUST_COMMAND_BRIDGE_BLOCKED_BACKEND_MISSING",
            notes=(f"driver raised: {exc}",),
        )
    # Single-line JSON for the Rust side.
    print(json.dumps(response), file=real_stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
