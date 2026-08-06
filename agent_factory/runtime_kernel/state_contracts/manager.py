from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator

from agent_factory.runtime_kernel.errors import RuntimeKernelError

_NAMESPACE_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")


@dataclass(frozen=True, slots=True)
class StateNamespaceSpec:
    namespace: str
    schema: dict[str, Any]
    initial_state: dict[str, Any]
    writable_node_ids: frozenset[str]

    def __post_init__(self) -> None:
        if not _NAMESPACE_RE.fullmatch(self.namespace):
            raise RuntimeKernelError(f"invalid package_state namespace: {self.namespace}")
        Draft202012Validator.check_schema(self.schema)
        Draft202012Validator(self.schema).validate(self.initial_state)


class PackageStateManager:
    def __init__(self, namespaces: list[StateNamespaceSpec] | tuple[StateNamespaceSpec, ...]) -> None:
        specs: dict[str, StateNamespaceSpec] = {}
        for spec in namespaces:
            if spec.namespace in specs:
                raise RuntimeKernelError(f"duplicate package_state namespace: {spec.namespace}")
            specs[spec.namespace] = spec
        self._specs = specs

    @property
    def namespaces(self) -> tuple[str, ...]:
        return tuple(sorted(self._specs))

    def initial_state(self) -> dict[str, Any]:
        return {
            namespace: copy.deepcopy(spec.initial_state)
            for namespace, spec in self._specs.items()
        }

    def validate_patch(self, *, node_id: str, patch: Any) -> None:
        if not isinstance(patch, dict):
            raise RuntimeKernelError("package_state patch must be an object")
        for namespace, value in patch.items():
            spec = self._specs.get(str(namespace))
            if spec is None:
                raise RuntimeKernelError(f"node {node_id} attempted to write undeclared package_state namespace: {namespace}")
            if "*" not in spec.writable_node_ids and node_id not in spec.writable_node_ids:
                raise RuntimeKernelError(f"node {node_id} is not allowed to write package_state namespace: {namespace}")
            if not isinstance(value, dict):
                raise RuntimeKernelError(f"package_state namespace {namespace} must be an object")
            Draft202012Validator(spec.schema).validate(value)

    def validate_full_state(self, value: Any) -> None:
        if not isinstance(value, dict):
            raise RuntimeKernelError("package_state must be an object")
        unknown = set(value).difference(self._specs)
        if unknown:
            raise RuntimeKernelError("package_state contains undeclared namespaces: " + ", ".join(sorted(unknown)))
        for namespace, spec in self._specs.items():
            if namespace not in value:
                raise RuntimeKernelError(f"package_state missing required namespace: {namespace}")
            if not isinstance(value[namespace], dict):
                raise RuntimeKernelError(f"package_state namespace {namespace} must be an object")
            Draft202012Validator(spec.schema).validate(value[namespace])
