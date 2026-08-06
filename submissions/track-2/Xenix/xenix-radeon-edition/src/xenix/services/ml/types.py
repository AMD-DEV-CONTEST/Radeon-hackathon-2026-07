from __future__ import annotations

import re
from abc import ABC, abstractmethod
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..storage.models import ProblemKind

if TYPE_CHECKING:
    from .contracts import (
        ApplyTaskRequest,
        ApplyTaskResult,
        EvaluateTaskRequest,
        EvaluateTaskResult,
        FitTaskRequest,
        FitTaskResult,
        HyperparameterTuningTaskRequest,
        HyperparameterTuningTaskResult,
    )


class ModelFamily(StrEnum):
    SUPERVISED = "supervised"
    CLUSTERING = "clustering"
    ANOMALY_DETECTION = "anomaly_detection"
    ASSOCIATION_RULES = "association_rules"
    RECOMMENDATION = "recommendation"
    TEXT_ANALYSIS = "text_analysis"


class ModelTaskKind(StrEnum):
    PREDICTOR = "predictor"
    SEGMENTER = "segmenter"
    ANOMALY_SCORER = "anomaly_scorer"
    RULE_MINER = "rule_miner"
    RECOMMENDER = "recommender"


class EvaluationKind(StrEnum):
    REGRESSION = "regression"
    CLASSIFICATION = "classification"
    SUMMARY = "summary"
    NONE = "none"


class ColumnRoleKind(StrEnum):
    SINGLE_COLUMN = "single_column"
    MANY_COLUMNS = "many_columns"


_MODEL_KEY_SEGMENT = re.compile(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*\Z")


def parse_model_key(model_key: object) -> tuple[str, ...]:
    if not isinstance(model_key, str) or not model_key.strip():
        raise ValueError("Model key must be a non-empty string.")
    segments = tuple(model_key.split("."))
    if len(segments) < 2 or any(
        _MODEL_KEY_SEGMENT.fullmatch(segment) is None for segment in segments
    ):
        raise ValueError(
            f"Model key {model_key!r} must be dot-separated lower_snake_case segments."
        )
    return segments


class _CatalogDeclaration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ModelRoleDefinition(_CatalogDeclaration):
    name: str
    kind: ColumnRoleKind
    required: bool = True
    description: str = ""

    @field_validator("name")
    @classmethod
    def _name_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Role name must not be blank.")
        return value


class ColumnRoleBinding(BaseModel):
    role: str
    columns: list[str] = Field(default_factory=list)
    role_kind: ColumnRoleKind | None = None
    required: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class ModelRoleSchema(_CatalogDeclaration):
    roles: list[ModelRoleDefinition]
    additional_roles: bool = False

    @model_validator(mode="after")
    def _roles_must_be_present_and_unique(self) -> Self:
        if not self.roles:
            raise ValueError("Role schema must contain at least one role.")
        role_names = [role.name for role in self.roles]
        if len(set(role_names)) != len(role_names):
            raise ValueError("Role schema must not contain duplicate role names.")
        return self


class ModelResultContract(_CatalogDeclaration):
    train_result_kinds: list[str]
    apply_result_kinds: list[str]
    preview_kinds: list[str]

    @field_validator("train_result_kinds", "apply_result_kinds", "preview_kinds")
    @classmethod
    def _result_kinds_must_not_be_empty_or_blank(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("Result kinds must not be empty.")
        if any(not kind.strip() for kind in value):
            raise ValueError("Result kinds must not contain blank values.")
        return value


class ModelCatalogEntry(_CatalogDeclaration):
    model_key: str
    display_name: str
    problem_kind: ProblemKind | None = None
    evaluation_kind: EvaluationKind
    summary_metric_name: str | None = None
    model_family: ModelFamily
    model_task_kind: ModelTaskKind
    family: str = "General"
    guidance: str = ""
    recommendation_tier: int = 100
    requires_target: bool
    supports_fit: bool = True
    supports_hyperparameter_tuning: bool
    train_role_schema: ModelRoleSchema
    apply_role_schema: ModelRoleSchema
    result_contract: ModelResultContract
    param_schema: dict[str, Any]
    param_grid_schema: dict[str, Any] | None = None

    @field_validator("model_key")
    @classmethod
    def _model_key_must_be_valid(cls, value: str) -> str:
        parse_model_key(value)
        return value

    @model_validator(mode="after")
    def _catalog_contracts_must_be_consistent(self) -> Self:
        has_grid_schema = self.param_grid_schema is not None
        if self.supports_hyperparameter_tuning != has_grid_schema:
            raise ValueError(
                "supports_hyperparameter_tuning must match "
                "param_grid_schema availability."
            )

        if self.evaluation_kind is EvaluationKind.SUMMARY:
            if self.summary_metric_name is None or not self.summary_metric_name.strip():
                raise ValueError(
                    "Summary evaluation requires a non-blank summary_metric_name."
                )
        elif self.summary_metric_name is not None:
            raise ValueError(
                "summary_metric_name is only valid for summary evaluation."
            )
        return self


class ModelServiceBase(ABC):
    key: ClassVar[str]
    display_name: ClassVar[str]
    problem_kind: ClassVar[ProblemKind | None] = None
    evaluation_kind: ClassVar[EvaluationKind | None] = None
    summary_metric_name: ClassVar[str | None] = None
    family: ClassVar[str] = "General"
    guidance: ClassVar[str] = ""
    recommendation_tier: ClassVar[int] = 100
    requires_target: ClassVar[bool] = True
    supports_fit: ClassVar[bool] = True
    supports_hyperparameter_tuning: ClassVar[bool] = True
    model_family: ClassVar[ModelFamily | None] = None
    model_task_kind: ClassVar[ModelTaskKind | None] = None
    train_role_schema: ClassVar[ModelRoleSchema | None] = None
    apply_role_schema: ClassVar[ModelRoleSchema | None] = None
    result_contract: ClassVar[ModelResultContract | None] = None
    params_model: ClassVar[type[BaseModel]]
    param_grid_model: ClassVar[type[BaseModel] | None] = None

    @classmethod
    def catalog_entry(cls) -> ModelCatalogEntry:
        model_family = (
            cls.model_family
            if cls.model_family is not None
            else cls._default_model_family()
        )
        model_task_kind = (
            cls.model_task_kind
            if cls.model_task_kind is not None
            else cls._default_model_task_kind()
        )
        evaluation_kind = (
            cls.evaluation_kind
            if cls.evaluation_kind is not None
            else cls._default_evaluation_kind()
        )
        summary_metric_name = (
            cls.summary_metric_name
            if cls.summary_metric_name is not None
            else cls._default_summary_metric_name(model_task_kind)
        )
        return ModelCatalogEntry(
            model_key=cls.key,
            display_name=cls.display_name,
            problem_kind=cls.problem_kind,
            evaluation_kind=evaluation_kind,
            summary_metric_name=summary_metric_name,
            model_family=model_family,
            model_task_kind=model_task_kind,
            family=cls.family,
            guidance=cls.guidance,
            recommendation_tier=cls.recommendation_tier,
            requires_target=cls.requires_target,
            supports_fit=cls.supports_fit,
            supports_hyperparameter_tuning=cls.supports_hyperparameter_tuning,
            train_role_schema=cls.train_role_schema or cls._default_train_role_schema(),
            apply_role_schema=cls.apply_role_schema or cls._default_apply_role_schema(),
            result_contract=cls.result_contract or cls._default_result_contract(model_task_kind),
            param_schema=cls.params_model.model_json_schema(),
            param_grid_schema=(
                cls.param_grid_model.model_json_schema()
                if cls.param_grid_model is not None
                else None
            ),
        )

    @classmethod
    def validate_params(cls, payload: dict[str, Any]) -> BaseModel:
        return cls.params_model.model_validate(payload)

    @classmethod
    def validate_param_grid(cls, payload: dict[str, Any]) -> BaseModel:
        if cls.param_grid_model is None:
            raise ValueError(f"Model '{cls.key}' does not support hyperparameter tuning.")
        return cls.param_grid_model.model_validate(payload)

    @classmethod
    def _default_model_family(cls) -> ModelFamily:
        problem_kind = cls.problem_kind
        if problem_kind in {ProblemKind.REGRESSION, ProblemKind.CLASSIFICATION}:
            return ModelFamily.SUPERVISED
        if problem_kind is ProblemKind.CLUSTERING:
            return ModelFamily.CLUSTERING
        if problem_kind is ProblemKind.ANOMALY_DETECTION:
            return ModelFamily.ANOMALY_DETECTION
        raise ValueError(f"Model '{cls.key}' has no default model family.")

    @classmethod
    def _default_model_task_kind(cls) -> ModelTaskKind:
        problem_kind = cls.problem_kind
        if problem_kind in {ProblemKind.REGRESSION, ProblemKind.CLASSIFICATION}:
            return ModelTaskKind.PREDICTOR
        if problem_kind is ProblemKind.CLUSTERING:
            return ModelTaskKind.SEGMENTER
        if problem_kind is ProblemKind.ANOMALY_DETECTION:
            return ModelTaskKind.ANOMALY_SCORER
        raise ValueError(f"Model '{cls.key}' has no default model task kind.")

    @classmethod
    def _default_evaluation_kind(cls) -> EvaluationKind:
        problem_kind = cls.problem_kind
        if problem_kind is ProblemKind.REGRESSION:
            return EvaluationKind.REGRESSION
        if problem_kind is ProblemKind.CLASSIFICATION:
            return EvaluationKind.CLASSIFICATION
        if problem_kind in {ProblemKind.CLUSTERING, ProblemKind.ANOMALY_DETECTION}:
            return EvaluationKind.SUMMARY
        raise ValueError(f"Model '{cls.key}' has no default evaluation kind.")

    @classmethod
    def _default_summary_metric_name(cls, model_task_kind: ModelTaskKind) -> str | None:
        metric_names = {
            ModelTaskKind.SEGMENTER: "cluster_count",
            ModelTaskKind.ANOMALY_SCORER: "anomaly_count",
            ModelTaskKind.RULE_MINER: "rule_count",
            ModelTaskKind.RECOMMENDER: "recommendation_count",
        }
        return metric_names.get(model_task_kind)

    @classmethod
    def _default_train_role_schema(cls) -> ModelRoleSchema:
        roles = [
            ModelRoleDefinition(
                name="feature",
                kind=ColumnRoleKind.MANY_COLUMNS,
                required=True,
                description="Input columns used to train the analyzer.",
            )
        ]
        if cls.requires_target:
            roles.append(
                ModelRoleDefinition(
                    name="target",
                    kind=ColumnRoleKind.SINGLE_COLUMN,
                    required=True,
                    description="Outcome column the analyzer learns to predict.",
                )
            )
        return ModelRoleSchema(roles=roles, additional_roles=False)

    @classmethod
    def _default_apply_role_schema(cls) -> ModelRoleSchema:
        return ModelRoleSchema(
            roles=[
                ModelRoleDefinition(
                    name="feature",
                    kind=ColumnRoleKind.MANY_COLUMNS,
                    required=True,
                    description="Input columns required when applying the trained analyzer.",
                )
            ],
            additional_roles=False,
        )

    @classmethod
    def _default_result_contract(cls, model_task_kind: ModelTaskKind) -> ModelResultContract:
        if model_task_kind is ModelTaskKind.PREDICTOR:
            return ModelResultContract(
                train_result_kinds=["model", "metrics", "report"],
                apply_result_kinds=["table"],
                preview_kinds=["model", "table", "file"],
            )
        if model_task_kind is ModelTaskKind.SEGMENTER:
            return ModelResultContract(
                train_result_kinds=["model", "table"],
                apply_result_kinds=["table"],
                preview_kinds=["model", "table", "file"],
            )
        if model_task_kind is ModelTaskKind.ANOMALY_SCORER:
            return ModelResultContract(
                train_result_kinds=["model", "table"],
                apply_result_kinds=["table"],
                preview_kinds=["model", "table", "file"],
            )
        if model_task_kind is ModelTaskKind.RULE_MINER:
            return ModelResultContract(
                train_result_kinds=["model", "table"],
                apply_result_kinds=["table"],
                preview_kinds=["model", "table", "file"],
            )
        if model_task_kind is ModelTaskKind.RECOMMENDER:
            return ModelResultContract(
                train_result_kinds=["model", "table"],
                apply_result_kinds=["table"],
                preview_kinds=["model", "table", "file"],
            )
        raise ValueError(
            f"Model '{cls.key}' has no default result contract for "
            f"{model_task_kind.value!r}."
        )

    @classmethod
    @abstractmethod
    def fit(cls, request: FitTaskRequest, task_dir: Path) -> FitTaskResult:
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def tune(cls, request: HyperparameterTuningTaskRequest, task_dir: Path) -> HyperparameterTuningTaskResult:
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def evaluate(cls, request: EvaluateTaskRequest, task_dir: Path) -> EvaluateTaskResult:
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def apply(cls, request: ApplyTaskRequest, task_dir: Path) -> ApplyTaskResult:
        raise NotImplementedError
