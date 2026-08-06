from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol


SCHEMA_SPECIFICATION = "aahj.render-specification/v1"
LEGACY_SCHEMA_SPEC = "aahj.render-spec/v1"
SCHEMA_PLAN = "aahj.execution-plan/v1"
SCHEMA_RESULT = "aahj.execution-result/v1"
SCHEMA_PLAN_EXPORT = "aahj.execution-plan-export/v1"


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _required_text(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value.strip()


def _json_object(name: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return {str(key): item for key, item in value.items()}


@dataclass(frozen=True)
class RenderSpecification:
    """Provider-independent authored rendering intent."""

    kind: str
    request: Mapping[str, Any]
    assets: tuple[Mapping[str, Any], ...] = ()
    review_required: bool = False
    schema_version: str = SCHEMA_SPECIFICATION

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any],
        *,
        accept_legacy_schema: bool = True,
    ) -> "RenderSpecification":
        schema = value.get("schema_version")
        accepted = {SCHEMA_SPECIFICATION}
        if accept_legacy_schema:
            accepted.add(LEGACY_SCHEMA_SPEC)
        if schema not in accepted:
            raise ValueError(
                "schema_version must be "
                + " or ".join(sorted(accepted))
            )
        raw_assets = value.get("assets", [])
        if not isinstance(raw_assets, list):
            raise ValueError("assets must be an array")
        return cls(
            kind=_required_text("kind", value.get("kind")),
            request=_json_object("request", value.get("request")),
            assets=tuple(
                _json_object("asset", item) for item in raw_assets
            ),
            review_required=value.get("review_required") is True,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_SPECIFICATION,
            "kind": self.kind,
            "request": dict(self.request),
            "assets": [dict(item) for item in self.assets],
            "review_required": self.review_required,
        }

    @property
    def specification_id(self) -> str:
        return sha256_json(self.as_dict())

    @property
    def spec_id(self) -> str:
        """Compatibility spelling; use specification_id in new code."""
        return self.specification_id


@dataclass(frozen=True)
class ExecutionPlan:
    """The only mandatory hand-off to an execution backend."""

    specification_id: str
    backend: str
    model: Mapping[str, Any]
    resolved_request: Mapping[str, Any]
    output_contract: Mapping[str, Any]
    runtime_requirements: Mapping[str, Any] = field(default_factory=dict)
    evidence: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_PLAN

    def __init__(
        self,
        *,
        specification_id: str | None = None,
        spec_id: str | None = None,
        backend: str,
        model: Mapping[str, Any],
        resolved_request: Mapping[str, Any],
        output_contract: Mapping[str, Any],
        runtime_requirements: Mapping[str, Any] | None = None,
        evidence: Mapping[str, Any] | None = None,
        schema_version: str = SCHEMA_PLAN,
    ) -> None:
        resolved_id = specification_id if specification_id is not None else spec_id
        if specification_id is not None and spec_id is not None:
            if specification_id != spec_id:
                raise ValueError("specification_id and spec_id disagree")
        object.__setattr__(
            self,
            "specification_id",
            _required_text("specification_id", resolved_id),
        )
        object.__setattr__(self, "backend", _required_text("backend", backend))
        object.__setattr__(self, "model", _json_object("model", model))
        object.__setattr__(
            self,
            "resolved_request",
            _json_object("resolved_request", resolved_request),
        )
        object.__setattr__(
            self,
            "output_contract",
            _json_object("output_contract", output_contract),
        )
        object.__setattr__(
            self,
            "runtime_requirements",
            _json_object(
                "runtime_requirements",
                {} if runtime_requirements is None else runtime_requirements,
            ),
        )
        object.__setattr__(
            self,
            "evidence",
            _json_object("evidence", {} if evidence is None else evidence),
        )
        object.__setattr__(self, "schema_version", schema_version)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ExecutionPlan":
        if value.get("schema_version") != SCHEMA_PLAN:
            raise ValueError(f"schema_version must be {SCHEMA_PLAN}")
        return cls(
            specification_id=value.get(
                "specification_id", value.get("spec_id")
            ),
            backend=value.get("backend"),
            model=value.get("model"),
            resolved_request=value.get("resolved_request"),
            output_contract=value.get("output_contract"),
            runtime_requirements=value.get("runtime_requirements", {}),
            evidence=value.get("evidence", {}),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "specification_id": self.specification_id,
            "backend": self.backend,
            "model": dict(self.model),
            "resolved_request": dict(self.resolved_request),
            "output_contract": dict(self.output_contract),
            "runtime_requirements": dict(self.runtime_requirements),
            "evidence": dict(self.evidence),
        }

    @property
    def spec_id(self) -> str:
        """Compatibility spelling; use specification_id in new code."""
        return self.specification_id

    @property
    def plan_id(self) -> str:
        return sha256_json(self.as_dict())


@dataclass(frozen=True)
class ExecutionResult:
    plan_id: str
    status: str
    outputs: tuple[Mapping[str, Any], ...]
    evidence: Mapping[str, Any] = field(default_factory=dict)
    error: Mapping[str, Any] | None = None
    schema_version: str = SCHEMA_RESULT

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ExecutionResult":
        if value.get("schema_version") != SCHEMA_RESULT:
            raise ValueError(f"schema_version must be {SCHEMA_RESULT}")
        status = _required_text("status", value.get("status"))
        if status not in {"succeeded", "failed", "cancelled"}:
            raise ValueError("status must be succeeded, failed, or cancelled")
        raw_outputs = value.get("outputs", [])
        if not isinstance(raw_outputs, list):
            raise ValueError("outputs must be an array")
        raw_error = value.get("error")
        return cls(
            plan_id=_required_text("plan_id", value.get("plan_id")),
            status=status,
            outputs=tuple(
                _json_object("output", item) for item in raw_outputs
            ),
            evidence=_json_object("evidence", value.get("evidence", {})),
            error=(
                None
                if raw_error is None
                else _json_object("error", raw_error)
            ),
        )

    def as_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "status": self.status,
            "outputs": [dict(item) for item in self.outputs],
            "evidence": dict(self.evidence),
        }
        if self.error is not None:
            value["error"] = dict(self.error)
        return value

    @property
    def result_id(self) -> str:
        return sha256_json(self.as_dict())


class ExecutionBackend(Protocol):
    name: str

    def preflight(self, plan: ExecutionPlan) -> Mapping[str, Any]:
        ...

    def execute(self, plan: ExecutionPlan) -> ExecutionResult:
        ...


class BackendRegistry:
    """The sole registry allowed to dispatch execution."""

    def __init__(self) -> None:
        self._backends: dict[str, ExecutionBackend] = {}

    def register(self, backend: ExecutionBackend) -> None:
        name = _required_text("backend.name", getattr(backend, "name", None))
        if name in self._backends:
            raise ValueError(f"backend already registered: {name}")
        self._backends[name] = backend

    def get(self, name: str) -> ExecutionBackend:
        try:
            return self._backends[name]
        except KeyError as exc:
            raise KeyError(f"unknown execution backend: {name}") from exc

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._backends))


PlanResolver = Callable[
    [RenderSpecification, str, Mapping[str, Any]],
    ExecutionPlan,
]


@dataclass(frozen=True)
class RenderingExecution:
    """Convenience envelope returned by the single execution function."""

    specification: RenderSpecification
    plan: ExecutionPlan
    preflight: Mapping[str, Any]
    result: ExecutionResult

    def as_dict(self) -> dict[str, Any]:
        return {
            "specification_id": self.specification.specification_id,
            "plan_id": self.plan.plan_id,
            "result_id": self.result.result_id,
            "preflight": dict(self.preflight),
            "result": self.result.as_dict(),
        }


def execute_rendering(
    *,
    specification: RenderSpecification,
    backend_name: str,
    resolver: PlanResolver,
    registry: BackendRegistry,
    resolution_context: Mapping[str, Any] | None = None,
) -> RenderingExecution:
    """Resolve, preflight and execute through the sole public path."""

    context = {} if resolution_context is None else dict(resolution_context)
    plan = resolver(specification, backend_name, context)
    if plan.specification_id != specification.specification_id:
        raise ValueError(
            "resolver returned a plan for a different specification"
        )
    if plan.backend != backend_name:
        raise ValueError("resolver returned a plan for a different backend")

    backend = registry.get(backend_name)
    preflight = dict(backend.preflight(plan))
    if preflight.get("ready") is not True:
        raise RuntimeError(
            "backend preflight failed: " + canonical_json(preflight)
        )

    result = backend.execute(plan)
    if result.plan_id != plan.plan_id:
        raise ValueError("backend returned a result for a different plan")
    return RenderingExecution(
        specification=specification,
        plan=plan,
        preflight=preflight,
        result=result,
    )


def export_execution_plan(
    plan: ExecutionPlan,
    destination: str | Path,
) -> Path:
    """Optional transport/export operation, never a runtime checkpoint."""

    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": SCHEMA_PLAN_EXPORT,
        "plan": plan.as_dict(),
        "plan_id": plan.plan_id,
    }
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path
