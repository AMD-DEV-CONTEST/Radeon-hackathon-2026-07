from __future__ import annotations

from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from pydantic import BaseModel, Field
from sklearn.base import clone
from sklearn.cluster import KMeans
from sklearn.decomposition import LatentDirichletAllocation
from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.model_selection import GridSearchCV, train_test_split

from ....exceptions import ValidationError
from ...storage.models import ProblemKind
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
    TuningSummary,
)
from ..dataset_loader import load_dataset, load_holdout_frame
from ..evaluation import build_metric_snapshot, scoring_name_for_policy
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

_TEXT_RANDOM_STATE = 42


class TokenizedTextClassificationParams(BaseModel):
    max_features: int = Field(default=3000, ge=200, le=50000)
    ngram_max: int = Field(default=1, ge=1, le=2)
    c: float = Field(default=1.0, gt=0.0, le=100.0)
    max_iter: int = Field(default=500, ge=100, le=5000)


class TokenizedTextClassificationParamGrid(BaseModel):
    max_features: list[int] = Field(default=[2000, 5000])
    ngram_max: list[int] = Field(default=[1, 2])
    c: list[float] = Field(default=[0.5, 1.0, 2.0])


class TokenizedTextClusteringParams(BaseModel):
    n_clusters: int = Field(default=4, ge=2, le=20)
    max_features: int = Field(default=3000, ge=200, le=50000)
    ngram_max: int = Field(default=1, ge=1, le=2)
    max_iter: int = Field(default=300, ge=50, le=2000)


class TokenizedTextTopicModelingParams(BaseModel):
    topic_count: int = Field(default=4, ge=2, le=20)
    max_features: int = Field(default=3000, ge=200, le=50000)
    max_iter: int = Field(default=20, ge=5, le=200)
    top_terms_per_topic: int = Field(default=8, ge=3, le=20)


class TokenizedTextSimilarityParams(BaseModel):
    max_features: int = Field(default=3000, ge=200, le=50000)
    ngram_max: int = Field(default=1, ge=1, le=2)
    top_k: int = Field(default=5, ge=1, le=50)
    min_similarity: float = Field(default=0.1, ge=0.0, le=1.0)


class TokenizedTextClassificationService(ModelServiceBase):
    key = "text.classification.logistic_regression_tfidf"
    display_name = "Tokenized Text Classification"
    problem_kind = ProblemKind.CLASSIFICATION
    family = "Text classification"
    guidance = "Predicts one label from a tokenized Chinese text column using TF-IDF and logistic regression."
    recommendation_tier = 25
    model_family = ModelFamily.TEXT_ANALYSIS
    model_task_kind = ModelTaskKind.PREDICTOR
    params_model = TokenizedTextClassificationParams
    param_grid_model = TokenizedTextClassificationParamGrid
    train_role_schema = ModelRoleSchema(
        roles=[
            ModelRoleDefinition(
                name="text",
                kind=ColumnRoleKind.SINGLE_COLUMN,
                required=True,
                description="Pre-tokenized text column, typically token_text from data.tokenize.",
            ),
            ModelRoleDefinition(
                name="target",
                kind=ColumnRoleKind.SINGLE_COLUMN,
                required=True,
                description="Target label column to predict.",
            ),
        ],
        additional_roles=False,
    )
    apply_role_schema = ModelRoleSchema(
        roles=[
            ModelRoleDefinition(
                name="text",
                kind=ColumnRoleKind.SINGLE_COLUMN,
                required=True,
                description="Pre-tokenized text column used for prediction.",
            )
        ],
        additional_roles=False,
    )

    @classmethod
    def fit(cls, request: FitTaskRequest, task_dir: Path) -> FitTaskResult:
        dataframe = load_dataset(Path(request.dataset_source_path))
        params = cls.validate_params(request.manual_training.params)
        text_column = _single_role_column(request.train_role_bindings, "text")
        target_column = _single_role_column(request.train_role_bindings, "target")
        texts, labels = _prepare_supervised_text(dataframe, text_column=text_column, target_column=target_column)
        train_texts, holdout_texts, train_labels, holdout_labels = _text_train_test_split(texts, labels, request)

        estimator = cls._build_estimator(params)
        estimator.text_column = text_column
        estimator.fit(train_texts, train_labels)
        final_estimator = cls._build_estimator(params)
        final_estimator.text_column = text_column
        final_estimator.fit(texts, labels)

        model_artifact_path = task_dir / "models" / f"{cls.key.replace('.', '_')}.joblib"
        final_model_artifact_path = task_dir / "models" / f"{cls.key.replace('.', '_')}-final.joblib"
        holdout_artifact_path = task_dir / "input" / "holdout.pkl"
        model_artifact_path.parent.mkdir(parents=True, exist_ok=True)
        holdout_artifact_path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(estimator, model_artifact_path)
        joblib.dump(final_estimator, final_model_artifact_path)
        _save_text_holdout(holdout_texts, holdout_labels, text_column=text_column, target_column=target_column, path=holdout_artifact_path)

        return FitTaskResult(
            task_id=request.task_id,
            evaluation_kind=request.evaluation_kind,
            evaluation_policy=request.evaluation_policy,
            model_key=cls.key,
            params=params.model_dump(mode="json"),
            model_artifact_path=str(model_artifact_path),
            final_model_artifact_path=str(final_model_artifact_path),
            holdout_artifact_path=str(holdout_artifact_path),
            result_summary={
                "class_count": int(labels.nunique(dropna=True)),
                "train_row_count": int(len(train_texts.index)),
                "holdout_row_count": int(len(holdout_texts.index)),
                "evaluation_model_training_scope": "holdout_train_split",
                "apply_model_training_scope": "all_eligible_rows",
                "text_column": text_column,
                "target_column": target_column,
            },
        )

    @classmethod
    def tune(cls, request: HyperparameterTuningTaskRequest, task_dir: Path) -> HyperparameterTuningTaskResult:
        dataframe = load_dataset(Path(request.dataset_source_path))
        grid = cls.validate_param_grid(request.hyperparameter_tuning.param_grid)
        text_column = _single_role_column(request.train_role_bindings, "text")
        target_column = _single_role_column(request.train_role_bindings, "target")
        texts, labels = _prepare_supervised_text(dataframe, text_column=text_column, target_column=target_column)
        train_texts, holdout_texts, train_labels, holdout_labels = _text_train_test_split(texts, labels, request)

        search = GridSearchCV(
            estimator=cls._build_estimator(),
            param_grid={
                "vectorizer__max_features": grid.max_features,
                "vectorizer__ngram_range": [(1, int(value)) for value in grid.ngram_max],
                "model__C": grid.c,
            },
            cv=request.evaluation_policy.cv_folds,
            scoring=scoring_name_for_policy(request.evaluation_policy),
            n_jobs=1,
        )
        search.fit(train_texts, train_labels)
        estimator = search.best_estimator_
        estimator.text_column = text_column
        final_estimator = clone(search.best_estimator_)
        final_estimator.text_column = text_column
        final_estimator.fit(texts, labels)

        model_artifact_path = task_dir / "models" / f"{cls.key.replace('.', '_')}.joblib"
        final_model_artifact_path = task_dir / "models" / f"{cls.key.replace('.', '_')}-final.joblib"
        holdout_artifact_path = task_dir / "input" / "holdout.pkl"
        model_artifact_path.parent.mkdir(parents=True, exist_ok=True)
        holdout_artifact_path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(estimator, model_artifact_path)
        joblib.dump(final_estimator, final_model_artifact_path)
        _save_text_holdout(holdout_texts, holdout_labels, text_column=text_column, target_column=target_column, path=holdout_artifact_path)

        return HyperparameterTuningTaskResult(
            task_id=request.task_id,
            evaluation_kind=request.evaluation_kind,
            evaluation_policy=request.evaluation_policy,
            model_key=cls.key,
            best_params=_serialize_search_best_params(search.best_params_),
            model_artifact_path=str(model_artifact_path),
            final_model_artifact_path=str(final_model_artifact_path),
            holdout_artifact_path=str(holdout_artifact_path),
            result_summary={
                "class_count": int(labels.nunique(dropna=True)),
                "train_row_count": int(len(train_texts.index)),
                "holdout_row_count": int(len(holdout_texts.index)),
                "evaluation_model_training_scope": "holdout_train_split",
                "apply_model_training_scope": "all_eligible_rows",
                "text_column": text_column,
                "target_column": target_column,
            },
            tuning_summary=TuningSummary(
                best_params=_serialize_search_best_params(search.best_params_),
                cv_summary={
                    "best_score": float(search.best_score_),
                    "candidate_count": len(search.cv_results_["params"]),
                },
            ),
        )

    @classmethod
    def evaluate(cls, request: EvaluateTaskRequest, task_dir: Path) -> EvaluateTaskResult:
        estimator = joblib.load(request.evaluate_model.trained_model_artifact_path)
        holdout = load_holdout_frame(Path(request.evaluate_model.holdout_artifact_path))
        text_column = _single_role_column(request.train_role_bindings, "text")
        target_column = _single_role_column(request.train_role_bindings, "target")
        texts = _normalize_token_text_series(holdout[text_column])
        labels = holdout[target_column].copy()
        predictions = estimator.predict(texts)
        probabilities = estimator.predict_proba(texts) if hasattr(estimator, "predict_proba") else None
        classes = getattr(estimator, "classes_", None)
        metrics = build_metric_snapshot(
            request.evaluation_kind,
            labels,
            predictions,
            y_proba=probabilities,
            classes=classes,
        )
        return EvaluateTaskResult(
            task_id=request.task_id,
            evaluation_kind=request.evaluation_kind,
            evaluation_policy=request.evaluation_policy,
            trained_model_id=request.evaluate_model.trained_model_id,
            model_key=cls.key,
            evaluation=metrics,
        )

    @classmethod
    def apply(cls, request: ApplyTaskRequest, task_dir: Path) -> ApplyTaskResult:
        estimator = joblib.load(request.apply_model.trained_model_artifact_path)
        text_column = _single_role_column_from_artifact(estimator, request.feature_columns)
        result_frames: list[pd.DataFrame] = []
        for input_file in request.input_files:
            dataframe = load_dataset(Path(input_file.absolute_path))
            if text_column not in dataframe.columns:
                raise ValidationError(f"Apply input '{input_file.file_name}' is missing required column: {text_column}.")
            texts = _normalize_token_text_series(dataframe[text_column])
            predictions = estimator.predict(texts)
            result_frame = dataframe.copy()
            result_frame["prediction"] = predictions
            if hasattr(estimator, "predict_proba"):
                scores = estimator.predict_proba(texts).max(axis=1)
                result_frame["prediction_score"] = [float(score) for score in scores]
            if len(request.input_files) > 1:
                result_frame["source_file"] = input_file.file_name
            result_frames.append(result_frame)

        output_path = _write_apply_output(task_dir, "text_classification_predictions.csv", result_frames)
        return ApplyTaskResult(
            task_id=request.task_id,
            trained_model_id=request.apply_model.trained_model_id,
            model_key=cls.key,
            output_file_path=str(output_path),
            summary=ApplySummary(
                row_count=int(sum(len(frame.index) for frame in result_frames)),
                input_file_count=len(request.input_files),
                prediction_column_name="prediction",
            ),
        )

    @classmethod
    def _build_estimator(cls, params: TokenizedTextClassificationParams | None = None):
        typed = TokenizedTextClassificationParams.model_validate(params or {})
        vectorizer = TfidfVectorizer(
            tokenizer=str.split,
            preprocessor=None,
            token_pattern=None,
            lowercase=False,
            max_features=typed.max_features,
            ngram_range=(1, typed.ngram_max),
        )
        model = LogisticRegression(
            C=typed.c,
            max_iter=typed.max_iter,
            random_state=_TEXT_RANDOM_STATE,
        )
        estimator = _TextVectorizerClassifier(vectorizer=vectorizer, model=model)
        estimator.text_column = None
        return estimator


class TokenizedTextClusteringService(ModelServiceBase):
    key = "text.clustering.kmeans_tfidf"
    display_name = "Tokenized Text Clustering"
    problem_kind = ProblemKind.CLUSTERING
    evaluation_kind = EvaluationKind.SUMMARY
    summary_metric_name = "cluster_count"
    family = "Text clustering"
    guidance = "Groups tokenized Chinese text rows into clusters using TF-IDF and KMeans."
    recommendation_tier = 35
    model_family = ModelFamily.TEXT_ANALYSIS
    model_task_kind = ModelTaskKind.SEGMENTER
    requires_target = False
    supports_hyperparameter_tuning = False
    params_model = TokenizedTextClusteringParams
    train_role_schema = ModelRoleSchema(
        roles=[
            ModelRoleDefinition(
                name="text",
                kind=ColumnRoleKind.SINGLE_COLUMN,
                required=True,
                description="Pre-tokenized text column, typically token_text from data.tokenize.",
            )
        ],
        additional_roles=False,
    )
    apply_role_schema = train_role_schema

    @classmethod
    def fit(cls, request: FitTaskRequest, task_dir: Path) -> FitTaskResult:
        dataframe = load_dataset(Path(request.dataset_source_path))
        params = cls.validate_params(request.manual_training.params)
        text_column = _single_role_column(request.train_role_bindings, "text")
        texts = _normalize_token_text_series(dataframe[text_column])
        non_empty_mask = texts.ne("")
        if not non_empty_mask.any():
            raise ValidationError("Text clustering requires at least one non-empty tokenized text row.")
        vectorizer = _tfidf_vectorizer(max_features=params.max_features, ngram_max=params.ngram_max)
        matrix = vectorizer.fit_transform(texts.loc[non_empty_mask])
        model = KMeans(
            n_clusters=params.n_clusters,
            n_init=10,
            max_iter=params.max_iter,
            random_state=_TEXT_RANDOM_STATE,
        )
        labels = model.fit_predict(matrix)

        model_artifact_path = task_dir / "models" / f"{cls.key.replace('.', '_')}.joblib"
        export_artifact_path = task_dir / "output" / "text_cluster_assignments.csv"
        model_artifact_path.parent.mkdir(parents=True, exist_ok=True)
        export_artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact = {
            "model_key": cls.key,
            "text_column": text_column,
            "vectorizer": vectorizer,
            "model": model,
            "params": params.model_dump(mode="json"),
            "top_terms_by_cluster": _top_terms_from_centers(
                model.cluster_centers_,
                vectorizer.get_feature_names_out(),
                top_n=8,
                label_prefix="cluster",
            ),
        }
        joblib.dump(artifact, model_artifact_path)

        result_frame = dataframe.copy()
        result_frame["cluster_id"] = pd.NA
        result_frame.loc[non_empty_mask, "cluster_id"] = [int(value) for value in labels]
        result_frame.to_csv(export_artifact_path, index=False)

        return FitTaskResult(
            task_id=request.task_id,
            evaluation_kind=request.evaluation_kind,
            evaluation_policy=request.evaluation_policy,
            model_key=cls.key,
            params=params.model_dump(mode="json"),
            model_artifact_path=str(model_artifact_path),
            export_artifact_path=str(export_artifact_path),
            result_summary={
                "cluster_count": int(params.n_clusters),
                "trained_row_count": int(non_empty_mask.sum()),
                "empty_text_row_count": int((~non_empty_mask).sum()),
                "text_column": text_column,
                "top_terms_by_cluster": artifact["top_terms_by_cluster"],
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
        text_column = str(artifact.get("text_column") or (request.feature_columns[0] if request.feature_columns else ""))
        vectorizer = artifact["vectorizer"]
        model = artifact["model"]
        result_frames: list[pd.DataFrame] = []
        for input_file in request.input_files:
            dataframe = load_dataset(Path(input_file.absolute_path))
            if text_column not in dataframe.columns:
                raise ValidationError(f"Apply input '{input_file.file_name}' is missing required column: {text_column}.")
            texts = _normalize_token_text_series(dataframe[text_column])
            non_empty_mask = texts.ne("")
            result_frame = dataframe.copy()
            result_frame["cluster_id"] = pd.NA
            if non_empty_mask.any():
                predictions = model.predict(vectorizer.transform(texts.loc[non_empty_mask]))
                result_frame.loc[non_empty_mask, "cluster_id"] = [int(value) for value in predictions]
            if len(request.input_files) > 1:
                result_frame["source_file"] = input_file.file_name
            result_frames.append(result_frame)

        output_path = _write_apply_output(task_dir, "text_cluster_predictions.csv", result_frames)
        return ApplyTaskResult(
            task_id=request.task_id,
            trained_model_id=request.apply_model.trained_model_id,
            model_key=cls.key,
            output_file_path=str(output_path),
            summary=ApplySummary(
                row_count=int(sum(len(frame.index) for frame in result_frames)),
                input_file_count=len(request.input_files),
                prediction_column_name="cluster_id",
            ),
        )


class TokenizedTextTopicModelingService(ModelServiceBase):
    key = "text.topic_modeling.lda"
    display_name = "Tokenized Topic Modeling"
    evaluation_kind = EvaluationKind.SUMMARY
    summary_metric_name = "topic_count"
    family = "Topic modeling"
    guidance = "Finds recurring tokenized Chinese text themes using CountVectorizer and LDA."
    recommendation_tier = 40
    model_family = ModelFamily.TEXT_ANALYSIS
    model_task_kind = ModelTaskKind.SEGMENTER
    requires_target = False
    supports_hyperparameter_tuning = False
    params_model = TokenizedTextTopicModelingParams
    train_role_schema = ModelRoleSchema(
        roles=[
            ModelRoleDefinition(
                name="text",
                kind=ColumnRoleKind.SINGLE_COLUMN,
                required=True,
                description="Pre-tokenized text column, typically token_text from data.tokenize.",
            )
        ],
        additional_roles=False,
    )
    apply_role_schema = train_role_schema

    @classmethod
    def fit(cls, request: FitTaskRequest, task_dir: Path) -> FitTaskResult:
        dataframe = load_dataset(Path(request.dataset_source_path))
        params = cls.validate_params(request.manual_training.params)
        text_column = _single_role_column(request.train_role_bindings, "text")
        texts = _normalize_token_text_series(dataframe[text_column])
        non_empty_mask = texts.ne("")
        if not non_empty_mask.any():
            raise ValidationError("Topic modeling requires at least one non-empty tokenized text row.")

        vectorizer = CountVectorizer(
            tokenizer=str.split,
            preprocessor=None,
            token_pattern=None,
            lowercase=False,
            max_features=params.max_features,
        )
        matrix = vectorizer.fit_transform(texts.loc[non_empty_mask])
        model = LatentDirichletAllocation(
            n_components=params.topic_count,
            max_iter=params.max_iter,
            learning_method="batch",
            random_state=_TEXT_RANDOM_STATE,
        )
        topic_matrix = model.fit_transform(matrix)
        dominant_topics = topic_matrix.argmax(axis=1)
        dominant_scores = topic_matrix.max(axis=1)
        top_terms_by_topic = _top_terms_from_centers(
            model.components_,
            vectorizer.get_feature_names_out(),
            top_n=params.top_terms_per_topic,
            label_prefix="topic",
        )

        model_artifact_path = task_dir / "models" / f"{cls.key.replace('.', '_')}.joblib"
        export_artifact_path = task_dir / "output" / "topic_assignments.csv"
        model_artifact_path.parent.mkdir(parents=True, exist_ok=True)
        export_artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact = {
            "model_key": cls.key,
            "text_column": text_column,
            "vectorizer": vectorizer,
            "model": model,
            "params": params.model_dump(mode="json"),
            "top_terms_by_topic": top_terms_by_topic,
        }
        joblib.dump(artifact, model_artifact_path)

        result_frame = dataframe.copy()
        result_frame["dominant_topic"] = pd.NA
        result_frame["topic_score"] = pd.NA
        result_frame.loc[non_empty_mask, "dominant_topic"] = [int(value) for value in dominant_topics]
        result_frame.loc[non_empty_mask, "topic_score"] = [float(value) for value in dominant_scores]
        result_frame.to_csv(export_artifact_path, index=False)

        return FitTaskResult(
            task_id=request.task_id,
            evaluation_kind=request.evaluation_kind,
            evaluation_policy=request.evaluation_policy,
            model_key=cls.key,
            params=params.model_dump(mode="json"),
            model_artifact_path=str(model_artifact_path),
            export_artifact_path=str(export_artifact_path),
            result_summary={
                "topic_count": int(params.topic_count),
                "trained_row_count": int(non_empty_mask.sum()),
                "empty_text_row_count": int((~non_empty_mask).sum()),
                "text_column": text_column,
                "top_terms_by_topic": top_terms_by_topic,
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
        text_column = str(artifact.get("text_column") or (request.feature_columns[0] if request.feature_columns else ""))
        vectorizer = artifact["vectorizer"]
        model = artifact["model"]
        result_frames: list[pd.DataFrame] = []
        for input_file in request.input_files:
            dataframe = load_dataset(Path(input_file.absolute_path))
            if text_column not in dataframe.columns:
                raise ValidationError(f"Apply input '{input_file.file_name}' is missing required column: {text_column}.")
            texts = _normalize_token_text_series(dataframe[text_column])
            non_empty_mask = texts.ne("")
            result_frame = dataframe.copy()
            result_frame["dominant_topic"] = pd.NA
            result_frame["topic_score"] = pd.NA
            if non_empty_mask.any():
                topic_matrix = model.transform(vectorizer.transform(texts.loc[non_empty_mask]))
                result_frame.loc[non_empty_mask, "dominant_topic"] = [int(value) for value in topic_matrix.argmax(axis=1)]
                result_frame.loc[non_empty_mask, "topic_score"] = [float(value) for value in topic_matrix.max(axis=1)]
            if len(request.input_files) > 1:
                result_frame["source_file"] = input_file.file_name
            result_frames.append(result_frame)

        output_path = _write_apply_output(task_dir, "topic_predictions.csv", result_frames)
        return ApplyTaskResult(
            task_id=request.task_id,
            trained_model_id=request.apply_model.trained_model_id,
            model_key=cls.key,
            output_file_path=str(output_path),
            summary=ApplySummary(
                row_count=int(sum(len(frame.index) for frame in result_frames)),
                input_file_count=len(request.input_files),
                prediction_column_name="dominant_topic",
            ),
        )


class TokenizedTextSimilarityService(ModelServiceBase):
    key = "text.similarity.tfidf_cosine"
    display_name = "Tokenized Text Similarity Retrieval"
    evaluation_kind = EvaluationKind.SUMMARY
    summary_metric_name = "match_count"
    family = "Similarity retrieval"
    guidance = "Retrieves the most similar tokenized Chinese text rows using TF-IDF cosine similarity."
    recommendation_tier = 40
    model_family = ModelFamily.TEXT_ANALYSIS
    model_task_kind = ModelTaskKind.RECOMMENDER
    requires_target = False
    supports_hyperparameter_tuning = False
    params_model = TokenizedTextSimilarityParams
    train_role_schema = ModelRoleSchema(
        roles=[
            ModelRoleDefinition(
                name="text",
                kind=ColumnRoleKind.SINGLE_COLUMN,
                required=True,
                description="Pre-tokenized text column, typically token_text from data.tokenize.",
            ),
            ModelRoleDefinition(
                name="text_id",
                kind=ColumnRoleKind.SINGLE_COLUMN,
                required=False,
                description="Optional identifier column returned with similar matches.",
            ),
        ],
        additional_roles=False,
    )
    apply_role_schema = ModelRoleSchema(
        roles=[
            ModelRoleDefinition(
                name="text",
                kind=ColumnRoleKind.SINGLE_COLUMN,
                required=True,
                description="Pre-tokenized text column used as the similarity query.",
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
        text_column = _single_role_column(request.train_role_bindings, "text")
        text_id_column = _optional_role_column(request.train_role_bindings, "text_id")
        texts = _normalize_token_text_series(dataframe[text_column])
        non_empty_mask = texts.ne("")
        if not non_empty_mask.any():
            raise ValidationError("Similarity retrieval requires at least one non-empty tokenized text row.")

        vectorizer = _tfidf_vectorizer(max_features=params.max_features, ngram_max=params.ngram_max)
        indexed_texts = texts.loc[non_empty_mask]
        matrix = vectorizer.fit_transform(indexed_texts)
        index_frame = pd.DataFrame(
            {
                "source_row_number": dataframe.index[non_empty_mask].to_series(index=indexed_texts.index).add(1).tolist(),
                "text": indexed_texts.tolist(),
            },
            index=indexed_texts.index,
        )
        if text_id_column is not None:
            index_frame["text_id"] = dataframe.loc[non_empty_mask, text_id_column].tolist()

        model_artifact_path = task_dir / "models" / f"{cls.key.replace('.', '_')}.joblib"
        export_artifact_path = task_dir / "output" / "similarity_index.csv"
        model_artifact_path.parent.mkdir(parents=True, exist_ok=True)
        export_artifact_path.parent.mkdir(parents=True, exist_ok=True)
        index_frame.to_csv(export_artifact_path, index=False)
        joblib.dump(
            {
                "model_key": cls.key,
                "text_column": text_column,
                "text_id_column": text_id_column,
                "params": params.model_dump(mode="json"),
                "vectorizer": vectorizer,
                "matrix": matrix,
                "index_rows": index_frame.to_dict(orient="records"),
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
                "match_count": int(len(index_frame.index)),
                "indexed_row_count": int(len(index_frame.index)),
                "empty_text_row_count": int((~non_empty_mask).sum()),
                "text_column": text_column,
                "text_id_column": text_id_column,
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
        text_column = str(artifact.get("text_column") or (request.feature_columns[0] if request.feature_columns else ""))
        params = TokenizedTextSimilarityParams.model_validate(artifact.get("params") or {})
        vectorizer = artifact["vectorizer"]
        matrix = artifact["matrix"]
        index_rows = [dict(row) for row in artifact.get("index_rows") or []]
        result_rows: list[dict[str, Any]] = []

        for input_file in request.input_files:
            dataframe = load_dataset(Path(input_file.absolute_path))
            if text_column not in dataframe.columns:
                raise ValidationError(f"Apply input '{input_file.file_name}' is missing required column: {text_column}.")
            texts = _normalize_token_text_series(dataframe[text_column])
            for row_number, query_text in enumerate(texts.tolist(), start=1):
                if not query_text:
                    continue
                scores = cosine_similarity(vectorizer.transform([query_text]), matrix).ravel()
                ranked_indexes = np.argsort(scores)[::-1]
                rank = 0
                for match_index in ranked_indexes:
                    similarity = float(scores[match_index])
                    if similarity < params.min_similarity:
                        continue
                    rank += 1
                    record = index_rows[int(match_index)]
                    result_rows.append(
                        {
                            "source_file": input_file.file_name,
                            "input_row_number": row_number,
                            "query_text": query_text,
                            "rank": rank,
                            "matched_source_row_number": int(record.get("source_row_number") or 0),
                            "matched_text_id": record.get("text_id"),
                            "matched_text": str(record.get("text") or ""),
                            "similarity": similarity,
                        }
                    )
                    if rank >= params.top_k:
                        break

        output_dir = task_dir / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "text_similarity_matches.csv"
        pd.DataFrame(
            result_rows,
            columns=[
                "source_file",
                "input_row_number",
                "query_text",
                "rank",
                "matched_source_row_number",
                "matched_text_id",
                "matched_text",
                "similarity",
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
                prediction_column_name="matched_text",
            ),
        )


class _TextVectorizerClassifier:
    def __init__(self, *, vectorizer: TfidfVectorizer, model: LogisticRegression) -> None:
        self.vectorizer = vectorizer
        self.model = model
        self.text_column: str | None = None

    def fit(self, texts: pd.Series, labels: pd.Series):
        matrix = self.vectorizer.fit_transform(texts.tolist())
        self.model.fit(matrix, labels)
        return self

    def predict(self, texts: pd.Series):
        return self.model.predict(self.vectorizer.transform(texts.tolist()))

    def predict_proba(self, texts: pd.Series):
        return self.model.predict_proba(self.vectorizer.transform(texts.tolist()))

    @property
    def classes_(self):
        return self.model.classes_

    def get_params(self, deep: bool = True) -> dict[str, Any]:
        return {"vectorizer": self.vectorizer, "model": self.model}

    def set_params(self, **params):
        for key, value in params.items():
            if key == "vectorizer":
                self.vectorizer = value
                continue
            if key == "model":
                self.model = value
                continue
            if key.startswith("vectorizer__"):
                self.vectorizer.set_params(**{key.split("__", 1)[1]: value})
                continue
            if key.startswith("model__"):
                self.model.set_params(**{key.split("__", 1)[1]: value})
                continue
            raise ValueError(f"Unsupported parameter '{key}'.")
        return self


def _single_role_column(role_bindings: list[dict[str, Any]], role: str) -> str:
    for binding in role_bindings:
        if binding.get("role") == role and isinstance(binding.get("columns"), list):
            columns = [str(column) for column in binding["columns"]]
            if len(columns) == 1:
                return columns[0]
    raise ValidationError(f"Text analysis model requires exactly one '{role}' column.")


def _optional_role_column(role_bindings: list[dict[str, Any]], role: str) -> str | None:
    for binding in role_bindings:
        if binding.get("role") == role and isinstance(binding.get("columns"), list):
            columns = [str(column) for column in binding["columns"]]
            if len(columns) == 1:
                return columns[0]
    return None


def _normalize_token_text_series(series: pd.Series) -> pd.Series:
    return (
        series.astype("string")
        .fillna("")
        .map(lambda value: " ".join(str(value).split()))
        .astype("string")
    )


def _prepare_supervised_text(
    dataframe: pd.DataFrame,
    *,
    text_column: str,
    target_column: str,
) -> tuple[pd.Series, pd.Series]:
    if text_column not in dataframe.columns:
        raise ValidationError(f"Text column '{text_column}' is missing.")
    if target_column not in dataframe.columns:
        raise ValidationError(f"Target column '{target_column}' is missing.")
    texts = _normalize_token_text_series(dataframe[text_column])
    labels = dataframe[target_column].copy()
    mask = texts.ne("") & labels.notna()
    if not mask.any():
        raise ValidationError("Text classification requires non-empty tokenized text rows with target labels.")
    filtered_texts = texts.loc[mask].reset_index(drop=True)
    filtered_labels = labels.loc[mask].reset_index(drop=True)
    if filtered_labels.nunique(dropna=True) < 2:
        raise ValidationError("Text classification requires at least two target classes.")
    return filtered_texts, filtered_labels


def _text_train_test_split(
    texts: pd.Series,
    labels: pd.Series,
    request: FitTaskRequest | HyperparameterTuningTaskRequest,
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    try:
        return train_test_split(
            texts,
            labels,
            test_size=request.evaluation_policy.test_size,
            random_state=request.evaluation_policy.random_state,
            stratify=labels,
        )
    except ValueError:
        return train_test_split(
            texts,
            labels,
            test_size=request.evaluation_policy.test_size,
            random_state=request.evaluation_policy.random_state,
            stratify=None,
        )


def _save_text_holdout(
    texts: pd.Series,
    labels: pd.Series,
    *,
    text_column: str,
    target_column: str,
    path: Path,
) -> None:
    holdout = pd.DataFrame({text_column: texts.tolist(), target_column: labels.tolist()})
    holdout.to_pickle(path)


def _serialize_search_best_params(best_params: dict[str, Any]) -> dict[str, Any]:
    serialized: dict[str, Any] = {}
    for key, value in best_params.items():
        simple_key = str(key).split("__", 1)[-1]
        if simple_key == "ngram_range" and isinstance(value, tuple) and len(value) == 2:
            serialized["ngram_max"] = int(value[1])
        else:
            serialized[simple_key] = value
    return serialized


def _single_role_column_from_artifact(estimator: Any, fallback_columns: list[str]) -> str:
    text_column = getattr(estimator, "text_column", None)
    if isinstance(text_column, str) and text_column.strip():
        return text_column
    if fallback_columns:
        return str(fallback_columns[0])
    raise ValidationError("The trained text model does not expose its required text column.")


def _write_apply_output(task_dir: Path, file_name: str, frames: list[pd.DataFrame]) -> Path:
    output_dir = task_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / file_name
    pd.concat(frames, ignore_index=True).to_csv(output_path, index=False)
    return output_path


def _tfidf_vectorizer(*, max_features: int, ngram_max: int) -> TfidfVectorizer:
    return TfidfVectorizer(
        tokenizer=str.split,
        preprocessor=None,
        token_pattern=None,
        lowercase=False,
        max_features=max_features,
        ngram_range=(1, ngram_max),
    )


def _top_terms_from_centers(
    centers: np.ndarray,
    feature_names: Any,
    *,
    top_n: int,
    label_prefix: str,
) -> list[dict[str, Any]]:
    terms = list(feature_names)
    rows: list[dict[str, Any]] = []
    for group_index, weights in enumerate(np.asarray(centers)):
        ranked_indexes = np.argsort(weights)[::-1][:top_n]
        rows.append(
            {
                f"{label_prefix}_id": int(group_index),
                "terms": [str(terms[index]) for index in ranked_indexes],
            }
        )
    return rows
