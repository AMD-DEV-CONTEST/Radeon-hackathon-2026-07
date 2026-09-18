"""Frozen trusted control plans with separately bound labeled data slots."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, ClassVar

import orjson
from pydantic import ConfigDict, Field, field_validator

from buildguard.exceptions import BuildGuardError
from buildguard.schemas.common import StrictSchema, new_id
from buildguard.security.advanced.data_policy import DataFlowPolicy
from buildguard.security.advanced.taint import TaintTrace
from buildguard.security.advanced.trust_labels import (
    TRUSTED_CONTROL_LABELS,
    LabeledData,
    Provenance,
)
from buildguard.utils.time import utc_now


class ControlPlanViolation(BuildGuardError):
    """An untrusted source or mutation attempted to change frozen control flow."""


class ControlStepDraft(StrictSchema):
    step_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
    tool_name: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    fixed_arguments: dict[str, Any] = Field(default_factory=dict)
    data_parameters: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()

    @field_validator("data_parameters", "depends_on")
    @classmethod
    def unique_values(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("control step fields must be unique")
        if any(not item.strip() for item in value):
            raise ValueError("control step fields must not be empty")
        return value


class ControlPlanDraft(StrictSchema):
    task_id: str = Field(min_length=1, max_length=128)
    steps: list[ControlStepDraft] = Field(min_length=1, max_length=100)


class FrozenControlStep(ControlStepDraft):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FrozenControlPlan(StrictSchema):
    model_config = ConfigDict(extra="forbid", frozen=True)

    plan_id: str = Field(default_factory=new_id)
    task_id: str
    steps: tuple[FrozenControlStep, ...]
    control_provenance: tuple[Provenance, ...]
    created_at: datetime = Field(default_factory=utc_now)
    integrity_digest: str = Field(min_length=64, max_length=64)


class BoundControlStep(StrictSchema):
    step_id: str
    tool_name: str
    arguments: dict[str, Any]
    depends_on: tuple[str, ...]
    plan_id: str


def _digest(task_id: str, steps: tuple[FrozenControlStep, ...]) -> str:
    payload = {
        "task_id": task_id,
        "steps": [step.model_dump(mode="json") for step in steps],
    }
    encoded = orjson.dumps(payload, option=orjson.OPT_SORT_KEYS)
    return hashlib.sha256(encoded).hexdigest()


class ControlPlanFreezer:
    """Compile control only from trusted inputs, then verify every binding."""

    _RESERVED_DATA_PARAMETERS: ClassVar[set[str]] = {
        "tool_name",
        "step_id",
        "depends_on",
    }

    def __init__(
        self,
        allowed_tools: set[str],
        policy: DataFlowPolicy | None = None,
    ) -> None:
        if not allowed_tools:
            raise ValueError("Control plans require at least one allowed tool")
        self.allowed_tools = set(allowed_tools)
        self.policy = policy or DataFlowPolicy()

    def freeze(
        self,
        draft: ControlPlanDraft,
        control_sources: list[LabeledData],
    ) -> FrozenControlPlan:
        if not control_sources:
            raise ControlPlanViolation("Control plan requires trusted provenance")
        if any(source.label not in TRUSTED_CONTROL_LABELS for source in control_sources):
            raise ControlPlanViolation(
                "Untrusted document, OCR, tool, or model output cannot form control flow"
            )
        identifiers = [step.step_id for step in draft.steps]
        if len(identifiers) != len(set(identifiers)):
            raise ControlPlanViolation("Control step IDs must be unique")
        positions = {step_id: index for index, step_id in enumerate(identifiers)}
        frozen_steps: list[FrozenControlStep] = []
        for step in draft.steps:
            if step.tool_name not in self.allowed_tools:
                raise ControlPlanViolation(f"Tool is not allowed: {step.tool_name}")
            if set(step.data_parameters) & self._RESERVED_DATA_PARAMETERS:
                raise ControlPlanViolation("Reserved control fields cannot be data parameters")
            if set(step.fixed_arguments) & set(step.data_parameters):
                raise ControlPlanViolation(
                    "A parameter cannot be both fixed control and bound data"
                )
            for dependency in step.depends_on:
                if dependency not in positions:
                    raise ControlPlanViolation(f"Unknown dependency: {dependency}")
                if positions[dependency] >= positions[step.step_id]:
                    raise ControlPlanViolation(
                        "Frozen plan dependencies must form an ordered DAG"
                    )
            frozen_steps.append(
                FrozenControlStep.model_validate(step.model_dump(mode="python"))
            )
        steps = tuple(frozen_steps)
        return FrozenControlPlan(
            task_id=draft.task_id,
            steps=steps,
            control_provenance=tuple(
                source.provenance.model_copy(deep=True)
                for source in control_sources
            ),
            integrity_digest=_digest(draft.task_id, steps),
        )

    @staticmethod
    def verify(plan: FrozenControlPlan) -> None:
        if _digest(plan.task_id, plan.steps) != plan.integrity_digest:
            raise ControlPlanViolation("Frozen control plan integrity check failed")

    def bind_step(
        self,
        plan: FrozenControlPlan,
        step_id: str,
        bindings: dict[str, LabeledData | TaintTrace],
    ) -> BoundControlStep:
        self.verify(plan)
        step = next(
            (candidate for candidate in plan.steps if candidate.step_id == step_id),
            None,
        )
        if step is None:
            raise ControlPlanViolation(f"Unknown frozen step: {step_id}")
        unknown = set(bindings) - set(step.data_parameters)
        if unknown:
            raise ControlPlanViolation(
                f"Bindings attempted to alter undeclared parameters: {sorted(unknown)}"
            )
        arguments = dict(step.fixed_arguments)
        for parameter, value in bindings.items():
            destination = self.policy.destination_for_parameter(parameter)
            self.policy.enforce(value, destination)
            arguments[parameter] = value.value
        return BoundControlStep(
            step_id=step.step_id,
            tool_name=step.tool_name,
            arguments=arguments,
            depends_on=step.depends_on,
            plan_id=plan.plan_id,
        )
