from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .files import atomic_write_bytes, sha256_file


class ComfyBindingError(ValueError):
    """Raised when a frozen workflow binding is missing, unsafe, or out of range."""


def canonical_sha256(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


@dataclass(frozen=True)
class BoundComfyWorkflow:
    workflow_id: str
    wrapper_sha256: str
    values_sha256: str
    bound_workflow_sha256: str
    output_node_ids: tuple[str, ...]
    resolved_values: Mapping[str, object]
    workflow: Mapping[str, object]

    def save(self, path: str | Path) -> None:
        target = Path(path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(
            target,
            (
                json.dumps(self.workflow, ensure_ascii=False, indent=2, sort_keys=True)
                + "\n"
            ).encode("utf-8"),
        )


class FrozenComfyWorkflowBinder:
    def __init__(
        self,
        project_root: str | Path,
        config_path: str | Path = "config/comfyui_execution_bindings_v1.json",
    ) -> None:
        self.project_root = Path(project_root).resolve()
        candidate = Path(config_path)
        self.config_path = (
            candidate.resolve()
            if candidate.is_absolute()
            else (self.project_root / candidate).resolve()
        )
        try:
            self.config_path.relative_to(self.project_root)
        except ValueError as error:
            raise ComfyBindingError("binding config must remain inside project root") from error
        self.config = json.loads(self.config_path.read_text(encoding="utf-8"))
        if self.config.get("schema") != "ProofLaunchComfyUIExecutionBindingsV1":
            raise ComfyBindingError("unexpected binding config schema")
        workflows = self.config.get("workflows")
        if not isinstance(workflows, dict) or not workflows:
            raise ComfyBindingError("binding config has no workflows")
        for workflow_id, spec in workflows.items():
            self._validate_static_spec(workflow_id, spec)

    @property
    def workflow_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self.config["workflows"]))

    def bind(self, workflow_id: str, values: Mapping[str, object]) -> BoundComfyWorkflow:
        spec = self.config["workflows"].get(workflow_id)
        if not isinstance(spec, dict):
            raise ComfyBindingError(f"unknown workflow_id: {workflow_id}")
        bindings = spec["bindings"]
        unknown = set(values) - set(bindings)
        if unknown:
            raise ComfyBindingError(f"unknown binding values: {sorted(unknown)}")
        wrapper_path = self._project_path(spec["wrapper_path"])
        workflow = json.loads(wrapper_path.read_text(encoding="utf-8"))
        resolved = {}
        for logical_name, binding in bindings.items():
            if logical_name in values:
                value = values[logical_name]
            elif "default" in binding:
                value = binding["default"]
            elif binding.get("required") is True:
                raise ComfyBindingError(f"required binding missing: {logical_name}")
            else:
                continue
            self._validate_value(logical_name, value, binding)
            node = workflow[binding["node_id"]]
            node["inputs"][binding["input_name"]] = value
            resolved[logical_name] = value
        values_sha256 = canonical_sha256(resolved)
        bound_sha256 = canonical_sha256(workflow)
        return BoundComfyWorkflow(
            workflow_id=workflow_id,
            wrapper_sha256=spec["wrapper_sha256"],
            values_sha256=values_sha256,
            bound_workflow_sha256=bound_sha256,
            output_node_ids=tuple(spec["output_node_ids"]),
            resolved_values=resolved,
            workflow=workflow,
        )

    def _validate_static_spec(self, workflow_id: str, spec: object) -> None:
        if not isinstance(spec, dict):
            raise ComfyBindingError(f"workflow spec must be an object: {workflow_id}")
        wrapper_path = self._project_path(spec["wrapper_path"])
        if not wrapper_path.is_file() or sha256_file(wrapper_path) != spec["wrapper_sha256"]:
            raise ComfyBindingError(f"wrapper hash drift: {workflow_id}")
        workflow = json.loads(wrapper_path.read_text(encoding="utf-8"))
        output_ids = spec.get("output_node_ids")
        if not isinstance(output_ids, list) or not output_ids:
            raise ComfyBindingError(f"output nodes missing: {workflow_id}")
        if any(output_id not in workflow for output_id in output_ids):
            raise ComfyBindingError(f"output node drift: {workflow_id}")
        bindings = spec.get("bindings")
        if not isinstance(bindings, dict) or not bindings:
            raise ComfyBindingError(f"bindings missing: {workflow_id}")
        targets = set()
        for logical_name, binding in bindings.items():
            if not isinstance(binding, dict):
                raise ComfyBindingError(f"binding must be an object: {logical_name}")
            node_id = binding.get("node_id")
            input_name = binding.get("input_name")
            node = workflow.get(node_id)
            if not isinstance(node, dict) or not isinstance(node.get("inputs"), dict):
                raise ComfyBindingError(f"binding node drift: {workflow_id}.{logical_name}")
            if input_name not in node["inputs"]:
                raise ComfyBindingError(f"binding input drift: {workflow_id}.{logical_name}")
            target = (node_id, input_name)
            if target in targets:
                raise ComfyBindingError(f"duplicate binding target: {workflow_id}.{target}")
            targets.add(target)
            if "default" in binding:
                self._validate_value(logical_name, binding["default"], binding)
        serialized = json.dumps(bindings).casefold()
        for forbidden in ("unet_name", "clip_name", "vae_name", "lora_name", "ckpt_name"):
            if forbidden in serialized:
                raise ComfyBindingError(
                    f"model loader names cannot be user-overridable: {workflow_id}.{forbidden}"
                )

    def _project_path(self, relative: str) -> Path:
        path = (self.project_root / relative).resolve()
        try:
            path.relative_to(self.project_root)
        except ValueError as error:
            raise ComfyBindingError("workflow path escaped project root") from error
        return path

    @staticmethod
    def _validate_value(logical_name: str, value: object, binding: Mapping[str, object]) -> None:
        value_type = binding.get("type")
        if value_type == "string":
            if not isinstance(value, str):
                raise ComfyBindingError(f"{logical_name} must be a string")
            if len(value.strip()) < int(binding.get("min_length", 0)):
                raise ComfyBindingError(f"{logical_name} is too short")
            if len(value) > int(binding.get("max_length", 1_000_000)):
                raise ComfyBindingError(f"{logical_name} is too long")
        elif value_type == "integer":
            if type(value) is not int:
                raise ComfyBindingError(f"{logical_name} must be an integer")
        elif value_type == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ComfyBindingError(f"{logical_name} must be numeric")
        else:
            raise ComfyBindingError(f"{logical_name} has unsupported binding type")
        if "enum" in binding and value not in binding["enum"]:
            raise ComfyBindingError(f"{logical_name} is not an allowed value")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in binding and value < binding["minimum"]:
                raise ComfyBindingError(f"{logical_name} is below minimum")
            if "maximum" in binding and value > binding["maximum"]:
                raise ComfyBindingError(f"{logical_name} exceeds maximum")
            if "multiple_of" in binding:
                offset = binding.get("offset", 0)
                if (value - offset) % binding["multiple_of"] != 0:
                    raise ComfyBindingError(
                        f"{logical_name} must satisfy (value - {offset}) % "
                        f"{binding['multiple_of']} == 0"
                    )
