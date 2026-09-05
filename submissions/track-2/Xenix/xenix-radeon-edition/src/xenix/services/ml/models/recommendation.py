from __future__ import annotations

from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from ....exceptions import ValidationError
from ..contracts import (
    ApplySummary,
    ApplyTaskRequest,
    ApplyTaskResult,
    EvaluateTaskRequest,
    EvaluateTaskResult,
    FitTaskRequest,
    FitTaskResult,
    HyperparameterTuningTaskRequest,
    HyperparameterTuningTaskResult,
)
from ..dataset_loader import load_dataset
from ..types import (
    ColumnRoleKind,
    EvaluationKind,
    ModelFamily,
    ModelResultContract,
    ModelRoleDefinition,
    ModelRoleSchema,
    ModelServiceBase,
    ModelTaskKind,
)


class ItemSimilarityRecommendationParams(BaseModel):
    min_ratings_base: int = Field(default=20, ge=1, le=100000)
    min_ratings_candidate: int = Field(default=20, ge=1, le=100000)
    similarity_threshold: float = Field(default=0.4, ge=0.0, le=1.0)
    top_k: int = Field(default=5, ge=1, le=100)


class ItemSimilarityRecommendationService(ModelServiceBase):
    key = "recommendation.item_similarity"
    display_name = "Item Similarity Recommender"
    evaluation_kind = EvaluationKind.SUMMARY
    model_family = ModelFamily.RECOMMENDATION
    model_task_kind = ModelTaskKind.RECOMMENDER
    family = "Collaborative filtering"
    guidance = "Recommends similar items from shared user ratings using Euclidean similarity."
    recommendation_tier = 35
    requires_target = False
    supports_hyperparameter_tuning = False
    params_model = ItemSimilarityRecommendationParams
    train_role_schema = ModelRoleSchema(
        roles=[
            ModelRoleDefinition(
                name="user",
                kind=ColumnRoleKind.SINGLE_COLUMN,
                required=True,
                description="User or account identifier column.",
            ),
            ModelRoleDefinition(
                name="item",
                kind=ColumnRoleKind.SINGLE_COLUMN,
                required=True,
                description="Item, product, or content identifier column.",
            ),
            ModelRoleDefinition(
                name="rating",
                kind=ColumnRoleKind.SINGLE_COLUMN,
                required=True,
                description="Numeric preference or rating column.",
            ),
        ],
        additional_roles=False,
    )
    apply_role_schema = ModelRoleSchema(
        roles=[
            ModelRoleDefinition(
                name="item",
                kind=ColumnRoleKind.SINGLE_COLUMN,
                required=True,
                description="Base item column used to look up recommendations.",
            )
        ],
        additional_roles=False,
    )
    result_contract = ModelResultContract(
        train_result_kinds=["model", "table"],
        apply_result_kinds=["table"],
        preview_kinds=["model", "table", "file"],
    )

    @classmethod
    def fit(cls, request: FitTaskRequest, task_dir: Path) -> FitTaskResult:
        dataframe = load_dataset(Path(request.dataset_source_path))
        params = cls.validate_params(request.manual_training.params)
        user_column = _single_role_column(request.train_role_bindings, "user")
        item_column = _single_role_column(request.train_role_bindings, "item")
        rating_column = _single_role_column(request.train_role_bindings, "rating")
        recommendations = _build_recommendations(
            dataframe,
            user_column=user_column,
            item_column=item_column,
            rating_column=rating_column,
            params=ItemSimilarityRecommendationParams.model_validate(params),
        )

        model_artifact_path = task_dir / "models" / f"{cls.key.replace('.', '_')}.joblib"
        export_artifact_path = task_dir / "output" / "item_recommendations.csv"
        model_artifact_path.parent.mkdir(parents=True, exist_ok=True)
        export_artifact_path.parent.mkdir(parents=True, exist_ok=True)
        recommendations.to_csv(export_artifact_path, index=False)
        joblib.dump(
            {
                "model_key": cls.key,
                "user_column": user_column,
                "item_column": item_column,
                "rating_column": rating_column,
                "params": params.model_dump(mode="json"),
                "recommendations": recommendations.to_dict(orient="records"),
            },
            model_artifact_path,
        )

        return FitTaskResult(
            task_id=request.task_id,
            evaluation_kind=request.evaluation_kind,
            evaluation_policy=request.evaluation_policy,
            model_key=cls.key,
            params=params.model_dump(mode="json"),
            model_artifact_path=str(model_artifact_path),
            export_artifact_path=str(export_artifact_path),
            result_summary={
                "result_count": int(len(recommendations.index)),
                "recommendation_count": int(len(recommendations.index)),
                "unique_user_count": int(dataframe[user_column].nunique(dropna=True)),
                "unique_item_count": int(dataframe[item_column].nunique(dropna=True)),
            },
        )

    @classmethod
    def tune(cls, request: HyperparameterTuningTaskRequest, task_dir: Path) -> HyperparameterTuningTaskResult:
        raise ValidationError(f"Model '{cls.key}' does not support hyperparameter tuning.")

    @classmethod
    def evaluate(cls, request: EvaluateTaskRequest, task_dir: Path) -> EvaluateTaskResult:
        raise ValidationError(f"Model '{cls.key}' does not support evaluation.")

    @classmethod
    def apply(cls, request: ApplyTaskRequest, task_dir: Path) -> ApplyTaskResult:
        artifact = joblib.load(request.apply_model.trained_model_artifact_path)
        item_column = str(artifact.get("item_column") or (request.feature_columns[0] if request.feature_columns else ""))
        recommendations = [dict(row) for row in artifact.get("recommendations") or []]
        result_rows: list[dict[str, Any]] = []

        for input_file in request.input_files:
            dataframe = load_dataset(Path(input_file.absolute_path))
            if item_column not in dataframe.columns:
                raise ValidationError(f"Apply input '{input_file.file_name}' is missing required column: {item_column}.")
            for row_index, value in enumerate(dataframe[item_column].tolist(), start=1):
                if pd.isna(value):
                    continue
                base_item = str(value).strip()
                if not base_item:
                    continue
                matches = [
                    row
                    for row in recommendations
                    if str(row.get("base_item") or "") == base_item
                ]
                for match in matches:
                    result_rows.append(
                        {
                            "source_file": input_file.file_name,
                            "input_row_number": row_index,
                            "base_item": base_item,
                            "rank": int(match.get("rank") or 0),
                            "recommended_item": str(match.get("recommended_item") or ""),
                            "similarity": float(match.get("similarity") or 0.0),
                            "common_user_count": int(match.get("common_user_count") or 0),
                        }
                    )

        output_dir = task_dir / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "item_recommendations.csv"
        pd.DataFrame(
            result_rows,
            columns=[
                "source_file",
                "input_row_number",
                "base_item",
                "rank",
                "recommended_item",
                "similarity",
                "common_user_count",
            ],
        ).to_csv(output_path, index=False)
        return ApplyTaskResult(
            task_id=request.task_id,
            trained_model_id=request.apply_model.trained_model_id,
            model_key=cls.key,
            output_file_path=str(output_path),
            summary=ApplySummary(
                row_count=len(result_rows),
                input_file_count=len(request.input_files),
                prediction_column_name="recommended_item",
            ),
        )


def _single_role_column(role_bindings: list[dict[str, Any]], role: str) -> str:
    for binding in role_bindings:
        if binding.get("role") == role and isinstance(binding.get("columns"), list):
            columns = [str(column) for column in binding["columns"]]
            if len(columns) == 1:
                return columns[0]
    raise ValidationError(f"Recommendation model requires exactly one '{role}' column.")


def _build_recommendations(
    dataframe: pd.DataFrame,
    *,
    user_column: str,
    item_column: str,
    rating_column: str,
    params: ItemSimilarityRecommendationParams,
) -> pd.DataFrame:
    for column in (user_column, item_column, rating_column):
        if column not in dataframe.columns:
            raise ValidationError(f"Recommendation column is missing: {column}.")

    working = dataframe.loc[:, [user_column, item_column, rating_column]].copy()
    working[rating_column] = pd.to_numeric(working[rating_column], errors="coerce")
    working = working.dropna(subset=[user_column, item_column, rating_column])
    if working.empty:
        raise ValidationError("Recommendation model requires at least one valid user-item-rating row.")

    rating_pivot = working.pivot_table(
        index=user_column,
        columns=item_column,
        values=rating_column,
        aggfunc="mean",
    )
    item_rating_counts = working.groupby(item_column)[rating_column].count()
    item_values = rating_pivot.columns.tolist()
    item_labels = [str(item) for item in item_values]
    item_to_index = {item: index for index, item in enumerate(item_labels)}
    counts_by_label = {
        str(item): int(item_rating_counts[item])
        for item in item_values
    }
    base_items = [
        str(item)
        for item in item_values
        if item_rating_counts[item] >= params.min_ratings_base
    ]
    candidate_items = [
        str(item)
        for item in item_values
        if item_rating_counts[item] >= params.min_ratings_candidate
    ]

    ratings = rating_pivot.to_numpy(dtype=float)
    present = ~np.isnan(ratings)
    rows: list[dict[str, Any]] = []
    for base_item in base_items:
        base_index = item_to_index[base_item]
        base_ratings = ratings[:, base_index]
        base_present = present[:, base_index]
        candidates: list[tuple[str, float, int]] = []
        for candidate_item in candidate_items:
            if candidate_item == base_item:
                continue
            candidate_index = item_to_index[candidate_item]
            candidate_present = present[:, candidate_index]
            common_mask = base_present & candidate_present
            common_count = int(common_mask.sum())
            if common_count == 0:
                continue
            diff = base_ratings[common_mask] - ratings[common_mask, candidate_index]
            distance = float(np.sqrt(np.sum(diff * diff)))
            similarity = 1.0 / (1.0 + distance)
            if similarity >= params.similarity_threshold:
                candidates.append((candidate_item, similarity, common_count))

        candidates.sort(key=lambda item: (-item[1], -item[2], item[0]))
        for rank, (recommended_item, similarity, common_count) in enumerate(candidates[: params.top_k], start=1):
            rows.append(
                {
                    "base_item": base_item,
                    "base_rating_count": counts_by_label[base_item],
                    "rank": rank,
                    "recommended_item": recommended_item,
                    "similarity": similarity,
                    "common_user_count": common_count,
                }
            )

    return pd.DataFrame(
        rows,
        columns=[
            "base_item",
            "base_rating_count",
            "rank",
            "recommended_item",
            "similarity",
            "common_user_count",
        ],
    )
