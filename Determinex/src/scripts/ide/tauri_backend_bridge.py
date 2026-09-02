"""Tauri backend command bridge — Python side.

A stable JSON-only command surface a Tauri (or web/CLI) frontend can
call via FFI / IPC / HTTP. Wraps the existing IDEBackendCommandSurface
with Tauri-style command names and adds a presence probe for the
Tauri Rust side (without touching it).

This rung does NOT modify any Tauri / Rust files. Tauri integration is
the frontend lane's call; here we pin the Python API the frontend can
consume.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_SCRIPTS = _HERE.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from models.local_model_config_record import LocalModelConfigRecord  # noqa: E402

from .backend_command_surface import IDEBackendCommandSurface
from .tauri_backend_bridge_record import (
    TAURI_BRIDGE_STATUS_TOKENS,
    TauriBridgeResponse,
)

_TAURI_COMMANDS: tuple[str, ...] = (
    "open_workspace",
    "get_workspace_status",
    "get_model_route_status",
    "diagnose_dry_run",
    "diagnose_live_opt_in",
    "generate_patch_plan",
    "verify_temp_patch",
    "get_human_approval_packet",
    "source_apply_dry_run",
    "get_repair_flow_state",
    # Greenfield Idea Lab (2026-06-14): preview the sound oracle, then build.
    "preview_idea_oracle",
    "build_idea",
    # Repo Clinic (2026-06-14): brownfield diagnosis via the canonical engine.
    "repair_diagnose",
    # Proof Center (2026-06-14): live no-overclaim governance state.
    "get_governance_status",
)


def tauri_commands() -> tuple[str, ...]:
    return _TAURI_COMMANDS


def _repo_root() -> Path:
    return _HERE.parent.parent.parent


def tauri_app_present(repo_root: Path | None = None) -> bool:
    """Probe whether the frontend/src-tauri/Cargo.toml exists."""
    root = Path(repo_root) if repo_root else _repo_root()
    return (root / "frontend" / "src-tauri" / "Cargo.toml").is_file()


class TauriBackendBridge:
    """Stable Python API surface a Tauri/web frontend can consume."""

    def __init__(self) -> None:
        self._surface = IDEBackendCommandSurface()

    def call(
        self,
        command: str,
        *,
        workspace: Path | None = None,
        task_class: str = "BUILD_DIAGNOSIS",
        opt_in: bool = False,
        config: LocalModelConfigRecord | None = None,
        verifier_status: str = "",
        unified_diff: str = "",
        files_changed: tuple[str, ...] = (),
        idea_text: str = "",
    ) -> TauriBridgeResponse:
        if command not in _TAURI_COMMANDS:
            return self._respond(
                command,
                "TAURI_COMMAND_BLOCKED_UNKNOWN",
                notes=(f"unknown tauri command {command!r}",),
            )

        # Map Tauri-style command names to the inner surface.
        inner_map = {
            "open_workspace": "inspect_workspace",
            "get_workspace_status": "inspect_workspace",
            "get_model_route_status": "route_model",
            "diagnose_dry_run": "diagnose_dry_run",
            "diagnose_live_opt_in": "diagnose_live_opt_in",
            "generate_patch_plan": "generate_patch_plan_opt_in",
            "verify_temp_patch": "verify_temp_patch",
            "get_human_approval_packet": "get_human_approval_packet",
            "source_apply_dry_run": "get_repair_state",  # gate decision
            "get_repair_flow_state": "get_repair_state",
            "preview_idea_oracle": "synthesize_oracle_preview",
            "build_idea": "build_from_idea_opt_in",
            "repair_diagnose": "repair_diagnose",
            "get_governance_status": "get_governance_status",
        }
        inner_cmd = inner_map[command]
        inner_res = self._surface.call(
            inner_cmd,
            workspace=workspace,
            task_class=task_class,
            opt_in=opt_in,
            config=config,
            verifier_status=verifier_status,
            unified_diff=unified_diff,
            files_changed=files_changed,
            idea_text=idea_text,
        )

        # Map inner status to Tauri status.
        status_map = {
            "IDE_COMMAND_OK": "TAURI_COMMAND_OK",
            "IDE_COMMAND_TEMP_ONLY": "TAURI_COMMAND_TEMP_ONLY",
            "IDE_COMMAND_SOURCE_MUTATION_BLOCKED": "TAURI_COMMAND_SOURCE_MUTATION_BLOCKED",
            "IDE_COMMAND_BLOCKED_NOT_OPTED_IN": "TAURI_COMMAND_BLOCKED_NOT_OPTED_IN",
            "IDE_COMMAND_BLOCKED_NO_MODEL": "TAURI_COMMAND_BLOCKED_NO_MODEL",
            "IDE_COMMAND_BLOCKED_UNKNOWN_COMMAND": "TAURI_COMMAND_BLOCKED_UNKNOWN",
            "IDE_COMMAND_NEEDS_APPROVAL": "TAURI_COMMAND_NEEDS_APPROVAL",
            "IDE_COMMAND_TIMED_OUT": "TAURI_COMMAND_TIMED_OUT",
        }
        # An UNMAPPED status is translated mechanically, never defaulted to OK.
        #
        # This was `status_map.get(inner_res.status, "TAURI_COMMAND_OK")`, so any status the
        # surface grew that nobody remembered to add here was reported to the frontend as
        # SUCCESS. Found 2026-08-02 when a new IDE_COMMAND_NEEDS_APPROVAL -- whose entire
        # purpose is to stop the frontend acting as though work had been done -- arrived as
        # TAURI_COMMAND_OK. A default that means "fine" turns every future omission into a
        # silent lie; a mechanical prefix swap propagates the truth even when this table is
        # out of date, and an unrecognisable status is surfaced verbatim rather than
        # laundered.
        status = status_map.get(inner_res.status) or (
            inner_res.status.replace("IDE_COMMAND_", "TAURI_COMMAND_", 1)
            if inner_res.status.startswith("IDE_COMMAND_")
            else (inner_res.status or "TAURI_COMMAND_UNKNOWN_STATUS")
        )

        return self._respond(
            command, status, payload=inner_res.payload, notes=tuple(inner_res.notes)
        )

    @staticmethod
    def _respond(
        command: str,
        status: str,
        *,
        payload: dict[str, object] | None = None,
        notes: tuple[str, ...] = (),
    ) -> TauriBridgeResponse:
        return TauriBridgeResponse(
            command=command,
            status=status,
            payload=dict(payload or {}),
            source_mutation_authorized=False,
            training_eligible=False,
            notes=notes,
        )


__all__ = [
    "TauriBackendBridge",
    "TauriBridgeResponse",
    "TAURI_BRIDGE_STATUS_TOKENS",
    "tauri_commands",
    "tauri_app_present",
]
