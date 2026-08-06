from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any

from agent_factory.create_agent.models import SYSTEM_STATE_FILE, SystemManufacturingState, SystemStage, initial_system_manufacturing_state


CREATE_AGENT_STAGE_CONTEXT_RESOURCE = "create_agent_stage_context"


@dataclass(frozen=True, slots=True)
class CreateAgentStageContext:
    workspace_root: Path

    @classmethod
    def from_workspace_root(cls, root: str | Path) -> "CreateAgentStageContext":
        return cls(Path(root).expanduser().resolve())

    @property
    def system_state_path(self) -> Path:
        return self.workspace_root / SYSTEM_STATE_FILE

    def read_state(self) -> SystemManufacturingState:
        if not self.system_state_path.exists():
            return initial_system_manufacturing_state()
        return SystemManufacturingState.model_validate_json(self.system_state_path.read_text(encoding="utf-8"))

    def write_state(self, state: SystemManufacturingState) -> None:
        self.system_state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.system_state_path.with_name(f".{self.system_state_path.name}.{os.getpid()}.tmp")
        tmp_path.write_text(json.dumps(state.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp_path.replace(self.system_state_path)

    def active_stage(self) -> SystemStage | None:
        return self.read_state().active_stage()

    def assert_known_focus(self, requested_system_id: str) -> SystemStage:
        requested = str(requested_system_id or "").strip()
        for stage in self.read_state().stages:
            if stage.system_id == requested:
                return stage
        raise ValueError(f"unknown create-agent focus: {requested!r}")

    def focus_alignment_facts(self, requested_system_id: str) -> dict[str, Any]:
        active = self.active_stage()
        requested = str(requested_system_id or "").strip()
        return {
            "requested_focus_id": requested,
            "active_focus_id": active.system_id if active else "",
            "focus_matches": bool(active and requested == active.system_id),
        }

    def file_focuses(self) -> dict[str, str]:
        focuses: dict[str, str] = {}
        for stage in self.read_state().stages:
            system_id = str(stage.system_id or "").strip()
            if not system_id:
                continue
            for item in stage.focus_files:
                cleaned = str(item or "").strip()
                if cleaned:
                    focuses[cleaned] = system_id
        return focuses

    def active_focus_files(self) -> list[str]:
        active = self.active_stage()
        return list(active.focus_files) if active else []


def stage_context_payload(workspace_root: str | Path) -> dict[str, str]:
    return {"workspace_root": str(Path(workspace_root).expanduser().resolve())}


def stage_context_from_resources(resources: dict[str, Any]) -> CreateAgentStageContext | None:
    raw = resources.get(CREATE_AGENT_STAGE_CONTEXT_RESOURCE)
    if raw is None:
        filesystem = resources.get("filesystem")
        if isinstance(filesystem, dict):
            raw = filesystem.get(CREATE_AGENT_STAGE_CONTEXT_RESOURCE)
    if isinstance(raw, dict) and isinstance(raw.get("workspace_root"), str):
        return CreateAgentStageContext.from_workspace_root(raw["workspace_root"])
    if isinstance(raw, str) and raw.strip():
        return CreateAgentStageContext.from_workspace_root(raw)
    return None
