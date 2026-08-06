from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_factory.factory_graph.frontend_bridge.agent_package_utils import write_json_objects_atomically
from agent_factory.model_pool.schema import ModelBindingRuntimeOverrides
from agent_factory.runtime_contracts import ContextContract, ModelContract, SchedulerContract


class AgentPackageConfigurationEditor:
    """Persist user-editable package configuration through validated package sources."""

    def update_context_config(self, package_root: Path, config: dict[str, Any]) -> None:
        contract_path = package_root / "contracts" / "context.json"
        document = _read_json_document(contract_path)
        document["config"] = config
        validated = ContextContract.model_validate(document).model_dump(mode="json", exclude_none=False)
        write_json_objects_atomically({contract_path: validated})

    def update_scheduler_config(self, package_root: Path, config: dict[str, Any]) -> None:
        contract_path = package_root / "contracts" / "scheduler.json"
        document = _read_json_document(contract_path)
        document["config"] = config
        validated = SchedulerContract.model_validate(document).model_dump(mode="json", exclude_none=False)
        write_json_objects_atomically({contract_path: validated})

    def update_model_overrides(
        self,
        package_root: Path,
        *,
        bindings: dict[str, Any],
        tool_bindings: dict[str, Any],
    ) -> None:
        contract_path = package_root / "contracts" / "model.json"
        document = _read_json_document(contract_path)
        contract = ModelContract.model_validate(document)
        if set(bindings) != set(contract.config.bindings):
            raise ValueError("model overrides must exactly match declared model roles")
        if set(tool_bindings) != set(contract.config.tool_bindings):
            raise ValueError("model tool overrides must exactly match declared model tools")
        next_bindings = {
            role: binding.model_copy(
                update={"overrides": ModelBindingRuntimeOverrides.model_validate(bindings[role])}
            )
            for role, binding in contract.config.bindings.items()
        }
        next_tool_bindings = {
            tool_id: binding.model_copy(
                update={"overrides": ModelBindingRuntimeOverrides.model_validate(tool_bindings[tool_id])}
            )
            for tool_id, binding in contract.config.tool_bindings.items()
        }
        validated = ModelContract.model_validate(
            contract.model_copy(
                update={
                    "config": contract.config.model_copy(
                        update={
                            "bindings": next_bindings,
                            "tool_bindings": next_tool_bindings,
                        }
                    )
                }
            )
        ).model_dump(mode="json", exclude_none=False)
        write_json_objects_atomically({contract_path: validated})

    def rebind_models(
        self,
        package_root: Path,
        *,
        bindings: dict[str, str],
        tool_bindings: dict[str, str],
    ) -> None:
        contract_path = package_root / "contracts" / "model.json"
        document = _read_json_document(contract_path)
        contract = ModelContract.model_validate(document)
        declared_bindings = set(contract.config.bindings)
        declared_tool_bindings = set(contract.config.tool_bindings)
        if set(bindings) != declared_bindings:
            raise ValueError(
                "model role selections must exactly match package roles: "
                + ", ".join(sorted(declared_bindings))
            )
        if set(tool_bindings) != declared_tool_bindings:
            raise ValueError(
                "model tool selections must exactly match package model tools: "
                + ", ".join(sorted(declared_tool_bindings))
            )
        rebound_bindings = {
            role: binding.model_copy(
                update={
                    "profile_id": bindings[role],
                    "source": "model_pool",
                    "selection_source": "manual",
                }
            )
            for role, binding in contract.config.bindings.items()
        }
        rebound_tool_bindings = {
            tool_id: binding.model_copy(
                update={
                    "profile_id": tool_bindings[tool_id],
                    "source": "model_pool",
                    "selection_source": "manual",
                }
            )
            for tool_id, binding in contract.config.tool_bindings.items()
        }
        validated = ModelContract.model_validate(
            contract.model_copy(
                update={
                    "config": contract.config.model_copy(
                        update={
                            "bindings": rebound_bindings,
                            "tool_bindings": rebound_tool_bindings,
                        }
                    )
                }
            ).model_dump(mode="python")
        ).model_dump(mode="json", exclude_none=True)
        write_json_objects_atomically({contract_path: validated})


def _read_json_document(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"package configuration file not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"package configuration file must contain an object: {path}")
    return payload
