"""Canonical, immutable Factory QC policy contract."""

from __future__ import annotations

import math
from typing import Any, Literal, Mapping
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ReviewMode = Literal["ALL", "EXCEPTIONS_ONLY", "OFF"]
ExhaustionPolicy = Literal["BLOCK", "DEGRADED_ACCEPT"]
StageName = Literal["keyframe", "clip", "final"]


class _FrozenStrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ScoringModelRef(_FrozenStrictModel):
    provider: str = Field(min_length=1, max_length=64)
    model_name: str = Field(min_length=1, max_length=160)
    version: str = Field(min_length=1, max_length=120)


class EvaluatorPin(_FrozenStrictModel):
    """Materialization-time resolution of mutable evaluator references."""

    prompt_revision_id: UUID
    prompt_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    rubric_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    operation_spec_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    implementation_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class ResourceBudget(_FrozenStrictModel):
    max_cost_micros: int = Field(ge=0)
    max_gpu_seconds: float = Field(ge=0)
    max_wall_seconds: float = Field(ge=0)

    @field_validator("max_cost_micros", mode="before")
    @classmethod
    def strict_cost(cls, value: Any) -> Any:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("max_cost_micros must be an integer")
        return value

    @field_validator("max_gpu_seconds", "max_wall_seconds", mode="before")
    @classmethod
    def finite_seconds(cls, value: Any) -> Any:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("resource seconds must be numeric")
        if not math.isfinite(float(value)):
            raise ValueError("resource seconds must be finite")
        return value


class FactoryQCStagePolicy(_FrozenStrictModel):
    review_mode: ReviewMode
    max_repairs: int = Field(ge=0, le=20)
    exhaustion_policy: ExhaustionPolicy
    machine_qc_required: Literal[True] = True
    scoring_model: ScoringModelRef
    prompt_version: str = Field(min_length=1, max_length=200)
    rubric_version: str = Field(min_length=1, max_length=200)
    ranking_revision: str = Field(min_length=1, max_length=200)
    ranking_weights: dict[str, float]
    resource_budget: ResourceBudget
    evaluator_pin: EvaluatorPin | None = None

    @field_validator("max_repairs", mode="before")
    @classmethod
    def strict_repairs(cls, value: Any) -> Any:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("max_repairs must be an integer")
        return value

    @field_validator("ranking_weights", mode="before")
    @classmethod
    def strict_weights(cls, value: Any) -> Any:
        if not isinstance(value, Mapping) or not value:
            raise ValueError("ranking_weights must be a non-empty object")
        normalized: dict[str, float] = {}
        for key, raw in value.items():
            if not isinstance(key, str) or not key or len(key) > 120:
                raise ValueError("ranking weight keys must be non-empty strings")
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                raise ValueError("ranking weights must be numeric")
            number = float(raw)
            if not math.isfinite(number) or number < 0:
                raise ValueError("ranking weights must be finite and non-negative")
            normalized[key] = number
        if not any(number > 0 for number in normalized.values()):
            raise ValueError("at least one ranking weight must be positive")
        return normalized


def _default_stage(stage: StageName) -> dict[str, Any]:
    return {
        "review_mode": "ALL" if stage == "keyframe" else "EXCEPTIONS_ONLY",
        "max_repairs": 0,
        "exhaustion_policy": "BLOCK",
        "machine_qc_required": True,
        "scoring_model": {
            "provider": "local",
            "model_name": "factory-qc-default",
            "version": "1",
        },
        "prompt_version": f"{stage}-machine-qc-v1",
        "rubric_version": f"{stage}-rubric-1-to-10-v1",
        "ranking_revision": "quality-ranking-v1",
        "ranking_weights": {"quality_score": 1.0, "confidence": 0.01},
        "resource_budget": {
            "max_cost_micros": 5_000_000,
            "max_gpu_seconds": 600.0,
            "max_wall_seconds": 1_800.0,
        },
    }


class FactoryQCPolicyPayload(_FrozenStrictModel):
    schema_version: Literal["factory-qc-policy.v1"] = "factory-qc-policy.v1"
    stages: dict[StageName, FactoryQCStagePolicy]

    @model_validator(mode="before")
    @classmethod
    def complete_stages(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value
        raw_stages = value.get("stages")
        if not isinstance(raw_stages, Mapping):
            return value
        unknown = set(raw_stages) - {"keyframe", "clip", "final"}
        if unknown:
            raise ValueError(f"unsupported QC stages: {sorted(unknown)}")
        completed = {
            stage: {**_default_stage(stage), **dict(raw_stages.get(stage, {}))}
            for stage in ("keyframe", "clip", "final")
        }
        return {**dict(value), "stages": completed}


class LegacyFactoryQCPolicyPayload(_FrozenStrictModel):
    """Released flat policy shape accepted only at the append boundary."""

    keyframe_human_review: ReviewMode | None = None
    clip_human_review: ReviewMode | None = None
    final_human_review: ReviewMode | None = None
    max_repairs: int = Field(default=0, ge=0, le=20)
    exhaustion_policy: ExhaustionPolicy = "BLOCK"

    @field_validator("max_repairs", mode="before")
    @classmethod
    def strict_legacy_repairs(cls, value: Any) -> Any:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("max_repairs must be an integer")
        return value

    @model_validator(mode="after")
    def require_explicit_legacy_field(self) -> "LegacyFactoryQCPolicyPayload":
        if not self.model_fields_set:
            raise ValueError("empty Factory QC policy payload is not allowed")
        return self


def normalize_factory_qc_policy(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate/canonicalize both the new contract and released flat payloads."""

    raw = dict(payload)
    if "stages" in raw or "schema_version" in raw:
        return FactoryQCPolicyPayload.model_validate(raw).model_dump(mode="json")
    legacy = LegacyFactoryQCPolicyPayload.model_validate(raw)
    stages: dict[str, dict[str, Any]] = {}
    for stage in ("keyframe", "clip", "final"):
        stages[stage] = {
            **_default_stage(stage),
            "review_mode": getattr(legacy, f"{stage}_human_review")
            or ("ALL" if stage == "keyframe" else "EXCEPTIONS_ONLY"),
            "max_repairs": legacy.max_repairs,
            "exhaustion_policy": legacy.exhaustion_policy,
        }
    return FactoryQCPolicyPayload(stages=stages).model_dump(mode="json")


def compiled_gate_policy(
    *, stage: StageName, gate_key: str, policy: FactoryQCStagePolicy,
    unit_key: str | None = None, **extra: Any,
) -> dict[str, Any]:
    model = policy.scoring_model
    evaluator = {
        "provider": model.provider,
        "model_name": model.model_name,
        "model_version": model.version,
        "prompt_key": policy.prompt_version,
        "rubric_revision_id": policy.rubric_version,
        "op_type": f"qc.evaluate.{stage}",
    }
    if policy.evaluator_pin is not None:
        evaluator.update(
            {
                "strict_frozen": True,
                **policy.evaluator_pin.model_dump(
                    mode="json", exclude_none=True
                ),
            }
        )
    result: dict[str, Any] = {
        "gate_key": gate_key,
        "stage": stage,
        "machine_qc_required": True,
        "review_mode": policy.review_mode,
        "exhaustion_policy": policy.exhaustion_policy,
        "max_repairs": policy.max_repairs,
        "budget": {
            **policy.resource_budget.model_dump(mode="json"),
            "max_repair_count": policy.max_repairs,
        },
        "ranking_revision": policy.ranking_revision,
        "ranking_weights": dict(policy.ranking_weights),
        "evaluator": evaluator,
    }
    if unit_key is not None:
        result["unit_key"] = unit_key
    result.update(extra)
    return result


__all__ = [
    "FactoryQCPolicyPayload",
    "FactoryQCStagePolicy",
    "EvaluatorPin",
    "ResourceBudget",
    "ScoringModelRef",
    "compiled_gate_policy",
    "normalize_factory_qc_policy",
]
