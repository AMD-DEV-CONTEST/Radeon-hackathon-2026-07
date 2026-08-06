from __future__ import annotations

from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, Field
from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.calibration import CalibratedClassifierCV
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import AdaBoostClassifier, ExtraTreesClassifier, GradientBoostingClassifier, HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.naive_bayes import GaussianNB, MultinomialNB
from sklearn.neural_network import MLPClassifier
from sklearn.neighbors import KNeighborsClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import LabelEncoder, MinMaxScaler, OneHotEncoder
from sklearn.svm import LinearSVC, SVC
from sklearn.tree import DecisionTreeClassifier

from ...storage.models import ProblemKind
from .base import EncodedSemiSupervisedClassifier, NumericAndCategoricalModelService, SemiSupervisedClassificationModelService


class LogisticRegressionParams(BaseModel):
    c: float = Field(default=1.0, gt=0.0, alias="C", serialization_alias="C")
    max_iter: int = Field(default=2000, ge=100, le=10000)


class LogisticRegressionParamGrid(BaseModel):
    c: list[float] = Field(
        default=[0.01, 0.1, 1.0, 10.0, 100.0],
        min_length=1,
        alias="C",
        serialization_alias="C",
    )
    max_iter: list[int] = Field(default=[2000, 5000, 8000], min_length=1)


class NaiveBayesClassificationParams(BaseModel):
    var_smoothing: float = Field(default=1e-9, gt=0.0)


class NaiveBayesClassificationParamGrid(BaseModel):
    var_smoothing: list[float] = Field(default=[1e-12, 1e-10, 1e-9, 1e-8, 1e-6], min_length=1)


class KNeighborsClassificationParams(BaseModel):
    n_neighbors: int = Field(default=5, ge=1, le=100)
    weights: Literal["uniform", "distance"] = Field(default="uniform")
    p: Literal[1, 2] = Field(default=2)


class KNeighborsClassificationParamGrid(BaseModel):
    n_neighbors: list[int] = Field(default=[3, 5, 7], min_length=1)
    weights: list[Literal["uniform", "distance"]] = Field(default=["uniform", "distance"], min_length=1)
    p: list[Literal[1, 2]] = Field(default=[1, 2], min_length=1)


class RandomForestClassificationParams(BaseModel):
    n_estimators: int = Field(default=200, ge=10, le=1000)
    max_depth: int | None = Field(default=None, ge=1)
    max_features: Literal["all", "sqrt", "log2"] = Field(default="sqrt")


class RandomForestClassificationParamGrid(BaseModel):
    n_estimators: list[int] = Field(default=[100, 200, 300], min_length=1)
    max_depth: list[int] = Field(default=[0, 5, 10, 15], min_length=1)
    max_features: list[Literal["all", "sqrt", "log2"]] = Field(
        default=["all", "sqrt", "log2"],
        min_length=1,
    )


class DecisionTreeClassificationParams(BaseModel):
    max_depth: int | None = Field(default=None, ge=1)
    min_samples_split: int = Field(default=2, ge=2, le=50)
    min_samples_leaf: int = Field(default=1, ge=1, le=50)
    max_features: Literal["all", "sqrt", "log2"] = Field(default="all")


class DecisionTreeClassificationParamGrid(BaseModel):
    max_depth: list[int] = Field(default=[0, 5, 10, 15], min_length=1)
    min_samples_split: list[int] = Field(default=[2, 5, 10], min_length=1)
    min_samples_leaf: list[int] = Field(default=[1, 2, 4], min_length=1)
    max_features: list[Literal["all", "sqrt", "log2"]] = Field(
        default=["all", "sqrt", "log2"],
        min_length=1,
    )


class GradientBoostingClassificationParams(BaseModel):
    n_estimators: int = Field(default=100, ge=10, le=1000)
    learning_rate: float = Field(default=0.1, gt=0.0, le=1.0)
    max_depth: int = Field(default=3, ge=1, le=20)
    min_samples_split: int = Field(default=2, ge=2, le=50)
    min_samples_leaf: int = Field(default=1, ge=1, le=50)
    subsample: float = Field(default=1.0, gt=0.0, le=1.0)
    max_features: Literal["all", "sqrt", "log2"] = Field(default="all")


class GradientBoostingClassificationParamGrid(BaseModel):
    n_estimators: list[int] = Field(default=[50, 100, 200], min_length=1)
    learning_rate: list[float] = Field(default=[0.01, 0.05, 0.1, 0.2], min_length=1)
    max_depth: list[int] = Field(default=[2, 3, 5], min_length=1)
    min_samples_split: list[int] = Field(default=[2, 5, 10], min_length=1)
    min_samples_leaf: list[int] = Field(default=[1, 2, 4], min_length=1)
    subsample: list[float] = Field(default=[0.8, 1.0], min_length=1)
    max_features: list[Literal["all", "sqrt", "log2"]] = Field(
        default=["all", "sqrt", "log2"],
        min_length=1,
    )


class AdaBoostClassificationParams(BaseModel):
    n_estimators: int = Field(default=100, ge=10, le=1000)
    learning_rate: float = Field(default=0.1, gt=0.0, le=2.0)
    estimator_max_depth: int = Field(default=1, ge=1, le=20)


class AdaBoostClassificationParamGrid(BaseModel):
    n_estimators: list[int] = Field(default=[50, 100, 200], min_length=1)
    learning_rate: list[float] = Field(default=[0.01, 0.1, 0.5, 1.0], min_length=1)
    estimator_max_depth: list[int] = Field(default=[1, 2, 3], min_length=1)


class XGBoostClassificationParams(BaseModel):
    n_estimators: int = Field(default=200, ge=10, le=1000)
    learning_rate: float = Field(default=0.1, gt=0.0, le=1.0)
    max_depth: int = Field(default=3, ge=1, le=20)
    min_child_weight: float = Field(default=1.0, ge=0.0)
    subsample: float = Field(default=1.0, gt=0.0, le=1.0)
    colsample_bytree: float = Field(default=1.0, gt=0.0, le=1.0)
    reg_lambda: float = Field(default=1.0, ge=0.0)


class XGBoostClassificationParamGrid(BaseModel):
    n_estimators: list[int] = Field(default=[100, 200], min_length=1)
    learning_rate: list[float] = Field(default=[0.05, 0.1], min_length=1)
    max_depth: list[int] = Field(default=[3, 5], min_length=1)
    min_child_weight: list[float] = Field(default=[1.0, 3.0], min_length=1)
    subsample: list[float] = Field(default=[0.8, 1.0], min_length=1)
    colsample_bytree: list[float] = Field(default=[0.8, 1.0], min_length=1)
    reg_lambda: list[float] = Field(default=[1.0, 2.0], min_length=1)


class LightGBMClassificationParams(BaseModel):
    n_estimators: int = Field(default=200, ge=10, le=1000)
    learning_rate: float = Field(default=0.1, gt=0.0, le=1.0)
    max_depth: int = Field(default=-1, ge=-1, le=20)
    num_leaves: int = Field(default=31, ge=2, le=255)
    min_child_samples: int = Field(default=20, ge=1, le=200)
    subsample: float = Field(default=1.0, gt=0.0, le=1.0)
    colsample_bytree: float = Field(default=1.0, gt=0.0, le=1.0)


class LightGBMClassificationParamGrid(BaseModel):
    n_estimators: list[int] = Field(default=[100, 200], min_length=1)
    max_depth: list[int] = Field(default=[-1, 5, 10], min_length=1)


class ExtraTreesClassificationParams(BaseModel):
    n_estimators: int = Field(default=200, ge=10, le=1000)
    max_depth: int | None = Field(default=None, ge=1)
    min_samples_split: int = Field(default=2, ge=2, le=50)
    min_samples_leaf: int = Field(default=1, ge=1, le=50)
    max_features: Literal["all", "sqrt", "log2"] = Field(default="sqrt")


class ExtraTreesClassificationParamGrid(BaseModel):
    n_estimators: list[int] = Field(default=[100, 200, 300], min_length=1)
    max_depth: list[int] = Field(default=[0, 5, 10, 15], min_length=1)
    min_samples_split: list[int] = Field(default=[2, 5, 10], min_length=1)
    min_samples_leaf: list[int] = Field(default=[1, 2, 4], min_length=1)
    max_features: list[Literal["all", "sqrt", "log2"]] = Field(default=["all", "sqrt", "log2"], min_length=1)


class HistGradientBoostingClassificationParams(BaseModel):
    max_iter: int = Field(default=100, ge=10, le=1000)
    learning_rate: float = Field(default=0.1, gt=0.0, le=1.0)
    max_leaf_nodes: int = Field(default=31, ge=2, le=255)
    max_depth: int | None = Field(default=None, ge=1)
    min_samples_leaf: int = Field(default=20, ge=1, le=200)
    l2_regularization: float = Field(default=0.0, ge=0.0)


class HistGradientBoostingClassificationParamGrid(BaseModel):
    max_iter: list[int] = Field(default=[100, 200], min_length=1)
    learning_rate: list[float] = Field(default=[0.05, 0.1], min_length=1)
    max_leaf_nodes: list[int] = Field(default=[15, 31, 63], min_length=1)
    max_depth: list[int] = Field(default=[0, 5, 10], min_length=1)
    min_samples_leaf: list[int] = Field(default=[10, 20, 40], min_length=1)
    l2_regularization: list[float] = Field(default=[0.0, 0.1], min_length=1)


class SVCClassificationParams(BaseModel):
    c: float = Field(default=1.0, gt=0.0, alias="C", serialization_alias="C")
    kernel: Literal["rbf", "linear", "poly", "sigmoid"] = Field(default="rbf")
    gamma: Literal["scale", "auto"] = Field(default="scale")
    degree: int = Field(default=3, ge=2, le=5)
    max_iter: int = Field(default=-1, ge=-1, le=100000)


class SVCClassificationParamGrid(BaseModel):
    c: list[float] = Field(default=[0.1, 1.0, 10.0], min_length=1, alias="C", serialization_alias="C")
    kernel: list[Literal["rbf", "linear"]] = Field(default=["rbf", "linear"], min_length=1)
    gamma: list[Literal["scale", "auto"]] = Field(default=["scale"], min_length=1)


class CalibratedLinearSVCClassificationParams(BaseModel):
    c: float = Field(default=1.0, gt=0.0, alias="C", serialization_alias="C")
    max_iter: int = Field(default=5000, ge=100, le=100000)
    cv: int = Field(default=2, ge=2, le=5)


class CalibratedLinearSVCClassificationParamGrid(BaseModel):
    c: list[float] = Field(default=[0.1, 1.0, 10.0], min_length=1, alias="C", serialization_alias="C")
    max_iter: list[int] = Field(default=[3000, 5000], min_length=1)


class MLPClassificationParams(BaseModel):
    hidden_layer_size: int = Field(default=64, ge=4, le=512)
    activation: Literal["relu", "tanh", "logistic"] = Field(default="relu")
    alpha: float = Field(default=0.0001, ge=0.0)
    learning_rate_init: float = Field(default=0.001, gt=0.0, le=1.0)
    max_iter: int = Field(default=500, ge=100, le=5000)


class MLPClassificationParamGrid(BaseModel):
    hidden_layer_size: list[int] = Field(default=[32, 64, 128], min_length=1)
    activation: list[Literal["relu", "tanh"]] = Field(default=["relu", "tanh"], min_length=1)
    alpha: list[float] = Field(default=[0.0001, 0.001], min_length=1)
    learning_rate_init: list[float] = Field(default=[0.001, 0.01], min_length=1)


class MultinomialNBClassificationParams(BaseModel):
    alpha: float = Field(default=1.0, ge=0.0)
    fit_prior: bool = Field(default=True)


class MultinomialNBClassificationParamGrid(BaseModel):
    alpha: list[float] = Field(default=[0.1, 1.0, 10.0], min_length=1)
    fit_prior: list[bool] = Field(default=[True, False], min_length=1)


class LabelPropagationParams(BaseModel):
    kernel: Literal["rbf", "knn"] = Field(default="rbf")
    gamma: float = Field(default=20.0, gt=0.0)
    n_neighbors: int = Field(default=7, ge=1, le=100)
    max_iter: int = Field(default=1000, ge=10, le=10000)
    tol: float = Field(default=0.001, gt=0.0)


class LabelSpreadingParams(BaseModel):
    kernel: Literal["rbf", "knn"] = Field(default="rbf")
    gamma: float = Field(default=20.0, gt=0.0)
    n_neighbors: int = Field(default=7, ge=1, le=100)
    alpha: float = Field(default=0.2, gt=0.0, lt=1.0)
    max_iter: int = Field(default=1000, ge=10, le=10000)
    tol: float = Field(default=0.001, gt=0.0)


class SelfTrainingClassificationParams(BaseModel):
    threshold: float = Field(default=0.75, gt=0.0, lt=1.0)
    criterion: Literal["threshold", "k_best"] = Field(default="threshold")
    k_best: int = Field(default=10, ge=1, le=10000)
    max_iter: int = Field(default=10, ge=1, le=1000)
    c: float = Field(default=1.0, gt=0.0, alias="C", serialization_alias="C")
    estimator_max_iter: int = Field(default=2000, ge=100, le=10000)


class LabelEncodedXGBClassifier(BaseEstimator, ClassifierMixin):
    def __init__(
        self,
        n_estimators: int = 200,
        learning_rate: float = 0.1,
        max_depth: int = 3,
        min_child_weight: float = 1.0,
        subsample: float = 1.0,
        colsample_bytree: float = 1.0,
        reg_lambda: float = 1.0,
        eval_metric: str = "logloss",
        random_state: int = 42,
        n_jobs: int = 1,
    ) -> None:
        self.n_estimators = n_estimators
        self.learning_rate = learning_rate
        self.max_depth = max_depth
        self.min_child_weight = min_child_weight
        self.subsample = subsample
        self.colsample_bytree = colsample_bytree
        self.reg_lambda = reg_lambda
        self.eval_metric = eval_metric
        self.random_state = random_state
        self.n_jobs = n_jobs

    def fit(self, X: Any, y: Any) -> "LabelEncodedXGBClassifier":
        from xgboost import XGBClassifier

        self.label_encoder_ = LabelEncoder()
        encoded_y = self.label_encoder_.fit_transform(y)
        self.classes_ = self.label_encoder_.classes_
        self.estimator_ = XGBClassifier(
            n_estimators=self.n_estimators,
            learning_rate=self.learning_rate,
            max_depth=self.max_depth,
            min_child_weight=self.min_child_weight,
            subsample=self.subsample,
            colsample_bytree=self.colsample_bytree,
            reg_lambda=self.reg_lambda,
            eval_metric=self.eval_metric,
            random_state=self.random_state,
            n_jobs=self.n_jobs,
        )
        self.estimator_.fit(X, encoded_y)
        return self

    def predict(self, X: Any) -> np.ndarray:
        encoded = np.asarray(self.estimator_.predict(X), dtype=int)
        return self.label_encoder_.inverse_transform(encoded)

    def predict_proba(self, X: Any) -> np.ndarray:
        return self.estimator_.predict_proba(X)

    @property
    def feature_importances_(self) -> np.ndarray:
        return np.asarray(self.estimator_.feature_importances_, dtype=float)


class LabelPropagationClassifier(EncodedSemiSupervisedClassifier):
    def __init__(
        self,
        kernel: str = "rbf",
        gamma: float = 20.0,
        n_neighbors: int = 7,
        max_iter: int = 1000,
        tol: float = 0.001,
        n_jobs: int | None = 1,
    ) -> None:
        self.kernel = kernel
        self.gamma = gamma
        self.n_neighbors = n_neighbors
        self.max_iter = max_iter
        self.tol = tol
        self.n_jobs = n_jobs

    def _build_semisupervised_estimator(self) -> Any:
        from sklearn.semi_supervised import LabelPropagation

        return LabelPropagation(
            kernel=self.kernel,
            gamma=self.gamma,
            n_neighbors=self.n_neighbors,
            max_iter=self.max_iter,
            tol=self.tol,
            n_jobs=self.n_jobs,
        )


class LabelSpreadingClassifier(EncodedSemiSupervisedClassifier):
    def __init__(
        self,
        kernel: str = "rbf",
        gamma: float = 20.0,
        n_neighbors: int = 7,
        alpha: float = 0.2,
        max_iter: int = 1000,
        tol: float = 0.001,
        n_jobs: int | None = 1,
    ) -> None:
        self.kernel = kernel
        self.gamma = gamma
        self.n_neighbors = n_neighbors
        self.alpha = alpha
        self.max_iter = max_iter
        self.tol = tol
        self.n_jobs = n_jobs

    def _build_semisupervised_estimator(self) -> Any:
        from sklearn.semi_supervised import LabelSpreading

        return LabelSpreading(
            kernel=self.kernel,
            gamma=self.gamma,
            n_neighbors=self.n_neighbors,
            alpha=self.alpha,
            max_iter=self.max_iter,
            tol=self.tol,
            n_jobs=self.n_jobs,
        )


class SelfTrainingLogisticClassifier(EncodedSemiSupervisedClassifier):
    def __init__(
        self,
        threshold: float = 0.75,
        criterion: str = "threshold",
        k_best: int = 10,
        max_iter: int = 10,
        C: float = 1.0,
        estimator_max_iter: int = 2000,
    ) -> None:
        self.threshold = threshold
        self.criterion = criterion
        self.k_best = k_best
        self.max_iter = max_iter
        self.C = C
        self.estimator_max_iter = estimator_max_iter

    def _build_semisupervised_estimator(self) -> Any:
        from sklearn.semi_supervised import SelfTrainingClassifier

        estimator = LogisticRegression(
            C=self.C,
            max_iter=self.estimator_max_iter,
            random_state=42,
            solver="lbfgs",
        )
        return SelfTrainingClassifier(
            estimator=estimator,
            threshold=self.threshold,
            criterion=self.criterion,
            k_best=self.k_best,
            max_iter=self.max_iter,
        )


class LogisticRegressionService(NumericAndCategoricalModelService):
    key = "classification.logistic_regression"
    display_name = "Logistic Regression"
    problem_kind = ProblemKind.CLASSIFICATION
    family = "Linear baseline"
    guidance = "Fast baseline for customer outcome classification with clear probability scores."
    recommendation_tier = 10
    params_model = LogisticRegressionParams
    param_grid_model = LogisticRegressionParamGrid
    scaler_for_numeric = True

    @classmethod
    def _build_estimator(cls, **estimator_kwargs: object) -> LogisticRegression:
        kwargs = dict(estimator_kwargs)
        kwargs.setdefault("random_state", 42)
        kwargs.setdefault("solver", "lbfgs")
        return LogisticRegression(**kwargs)


class NaiveBayesClassificationService(NumericAndCategoricalModelService):
    key = "classification.naive_bayes"
    display_name = "Naive Bayes Classifier"
    problem_kind = ProblemKind.CLASSIFICATION
    family = "Probabilistic baseline"
    guidance = "Simple probabilistic model that is useful as a quick classification benchmark."
    recommendation_tier = 20
    params_model = NaiveBayesClassificationParams
    param_grid_model = NaiveBayesClassificationParamGrid
    scaler_for_numeric = True
    dense_preprocessing = True

    @classmethod
    def _build_estimator(cls, **estimator_kwargs: object) -> GaussianNB:
        return GaussianNB(**estimator_kwargs)


class RandomForestClassificationService(NumericAndCategoricalModelService):
    key = "classification.random_forest"
    display_name = "Random Forest Classifier"
    problem_kind = ProblemKind.CLASSIFICATION
    family = "Tree ensemble"
    guidance = "Robust nonlinear benchmark for mixed customer and operations data."
    recommendation_tier = 35
    params_model = RandomForestClassificationParams
    param_grid_model = RandomForestClassificationParamGrid

    @classmethod
    def _build_estimator(cls, **estimator_kwargs: object) -> RandomForestClassifier:
        kwargs = dict(estimator_kwargs)
        if kwargs.get("max_depth") == 0:
            kwargs["max_depth"] = None
        if kwargs.get("max_features") == "all":
            kwargs["max_features"] = 1.0
        kwargs.setdefault("random_state", 42)
        kwargs.setdefault("n_jobs", 1)
        return RandomForestClassifier(**kwargs)


class KNeighborsClassificationService(NumericAndCategoricalModelService):
    key = "classification.knn"
    display_name = "K-Nearest Neighbors Classifier"
    problem_kind = ProblemKind.CLASSIFICATION
    family = "Similarity based"
    guidance = "Classifies by nearby examples; works best when similar rows should share outcomes."
    recommendation_tier = 60
    params_model = KNeighborsClassificationParams
    param_grid_model = KNeighborsClassificationParamGrid
    scaler_for_numeric = True

    @classmethod
    def _build_estimator(cls, **estimator_kwargs: object) -> KNeighborsClassifier:
        return KNeighborsClassifier(**estimator_kwargs)


class DecisionTreeClassificationService(NumericAndCategoricalModelService):
    key = "classification.decision_tree"
    display_name = "Decision Tree Classifier"
    problem_kind = ProblemKind.CLASSIFICATION
    family = "Tree model"
    guidance = "Explainable nonlinear baseline for simple branching business rules."
    recommendation_tier = 50
    params_model = DecisionTreeClassificationParams
    param_grid_model = DecisionTreeClassificationParamGrid

    @classmethod
    def _build_estimator(cls, **estimator_kwargs: object) -> DecisionTreeClassifier:
        kwargs = dict(estimator_kwargs)
        if kwargs.get("max_depth") == 0:
            kwargs["max_depth"] = None
        if kwargs.get("max_features") == "all":
            kwargs["max_features"] = 1.0
        kwargs.setdefault("random_state", 42)
        return DecisionTreeClassifier(**kwargs)


class GradientBoostingClassificationService(NumericAndCategoricalModelService):
    key = "classification.gradient_boosting"
    display_name = "Gradient Boosting Classifier"
    problem_kind = ProblemKind.CLASSIFICATION
    family = "Boosted trees"
    guidance = "Strong nonlinear candidate for churn, conversion, and other tabular outcomes."
    recommendation_tier = 25
    params_model = GradientBoostingClassificationParams
    param_grid_model = GradientBoostingClassificationParamGrid

    @classmethod
    def _build_estimator(cls, **estimator_kwargs: object) -> GradientBoostingClassifier:
        kwargs = dict(estimator_kwargs)
        if kwargs.get("max_features") == "all":
            kwargs["max_features"] = 1.0
        kwargs.setdefault("random_state", 42)
        return GradientBoostingClassifier(**kwargs)


class AdaBoostClassificationService(NumericAndCategoricalModelService):
    key = "classification.ada_boost"
    display_name = "AdaBoost Classifier"
    problem_kind = ProblemKind.CLASSIFICATION
    family = "Boosted trees"
    guidance = "Combines small trees to focus on rows previous trees misclassified."
    recommendation_tier = 45
    params_model = AdaBoostClassificationParams
    param_grid_model = AdaBoostClassificationParamGrid

    @classmethod
    def _build_estimator(cls, **estimator_kwargs: object) -> AdaBoostClassifier:
        kwargs = dict(estimator_kwargs)
        estimator_max_depth = int(kwargs.pop("estimator_max_depth", 1))
        kwargs.setdefault(
            "estimator",
            DecisionTreeClassifier(max_depth=estimator_max_depth, random_state=42),
        )
        kwargs.setdefault("random_state", 42)
        return AdaBoostClassifier(**kwargs)

    @classmethod
    def _build_param_grid(cls, param_grid_model: BaseModel) -> dict[str, list[Any]]:
        payload = param_grid_model.model_dump(mode="json", by_alias=True)
        grid: dict[str, list[Any]] = {}
        for key, values in payload.items():
            if key == "estimator_max_depth":
                grid["model__estimator__max_depth"] = list(values)
            else:
                grid[f"model__{key}"] = list(values)
        return grid


class XGBoostClassificationService(NumericAndCategoricalModelService):
    key = "classification.xgboost"
    display_name = "XGBoost Classifier"
    problem_kind = ProblemKind.CLASSIFICATION
    family = "Boosted trees"
    guidance = "High-capacity boosted tree classifier for nonlinear churn and conversion patterns."
    recommendation_tier = 28
    params_model = XGBoostClassificationParams
    param_grid_model = XGBoostClassificationParamGrid

    @classmethod
    def _build_estimator(cls, **estimator_kwargs: object) -> Any:
        kwargs = dict(estimator_kwargs)
        kwargs.setdefault("eval_metric", "logloss")
        kwargs.setdefault("random_state", 42)
        kwargs.setdefault("n_jobs", 1)
        return LabelEncodedXGBClassifier(**kwargs)


class LightGBMClassificationService(NumericAndCategoricalModelService):
    key = "classification.lightgbm"
    display_name = "LightGBM Classifier"
    problem_kind = ProblemKind.CLASSIFICATION
    family = "Boosted trees"
    guidance = "Fast boosted tree classifier for larger tabular classification datasets."
    recommendation_tier = 27
    params_model = LightGBMClassificationParams
    param_grid_model = LightGBMClassificationParamGrid

    @classmethod
    def _build_estimator(cls, **estimator_kwargs: object) -> Any:
        from lightgbm import LGBMClassifier

        kwargs = dict(estimator_kwargs)
        kwargs.setdefault("random_state", 42)
        kwargs.setdefault("n_jobs", 1)
        kwargs.setdefault("verbose", -1)
        kwargs.setdefault("verbosity", -1)
        return LGBMClassifier(**kwargs)


class ExtraTreesClassificationService(NumericAndCategoricalModelService):
    key = "classification.extra_trees"
    display_name = "Extra Trees Classifier"
    problem_kind = ProblemKind.CLASSIFICATION
    family = "Tree ensemble"
    guidance = "Randomized tree ensemble for robust nonlinear classification with less tuning pressure."
    recommendation_tier = 36
    params_model = ExtraTreesClassificationParams
    param_grid_model = ExtraTreesClassificationParamGrid

    @classmethod
    def _build_estimator(cls, **estimator_kwargs: object) -> ExtraTreesClassifier:
        kwargs = dict(estimator_kwargs)
        if kwargs.get("max_depth") == 0:
            kwargs["max_depth"] = None
        if kwargs.get("max_features") == "all":
            kwargs["max_features"] = 1.0
        kwargs.setdefault("random_state", 42)
        kwargs.setdefault("n_jobs", 1)
        return ExtraTreesClassifier(**kwargs)


class HistGradientBoostingClassificationService(NumericAndCategoricalModelService):
    key = "classification.hist_gradient_boosting"
    display_name = "Histogram Gradient Boosting Classifier"
    problem_kind = ProblemKind.CLASSIFICATION
    family = "Boosted trees"
    guidance = "Efficient boosted tree classifier for larger tabular datasets."
    recommendation_tier = 29
    params_model = HistGradientBoostingClassificationParams
    param_grid_model = HistGradientBoostingClassificationParamGrid
    dense_preprocessing = True

    @classmethod
    def _build_estimator(cls, **estimator_kwargs: object) -> HistGradientBoostingClassifier:
        kwargs = dict(estimator_kwargs)
        if kwargs.get("max_depth") == 0:
            kwargs["max_depth"] = None
        kwargs.setdefault("random_state", 42)
        return HistGradientBoostingClassifier(**kwargs)


class SVCClassificationService(NumericAndCategoricalModelService):
    key = "classification.svc"
    display_name = "Support Vector Classifier"
    problem_kind = ProblemKind.CLASSIFICATION
    family = "Margin based"
    guidance = "Flexible classifier for smaller datasets where class boundaries may be curved."
    recommendation_tier = 65
    params_model = SVCClassificationParams
    param_grid_model = SVCClassificationParamGrid
    scaler_for_numeric = True

    @classmethod
    def _build_estimator(cls, **estimator_kwargs: object) -> SVC:
        kwargs = dict(estimator_kwargs)
        kwargs.setdefault("probability", True)
        kwargs.setdefault("random_state", 42)
        return SVC(**kwargs)


class CalibratedLinearSVCClassificationService(NumericAndCategoricalModelService):
    key = "classification.linear_svc_calibrated"
    display_name = "Calibrated Linear SVC"
    problem_kind = ProblemKind.CLASSIFICATION
    family = "Margin based"
    guidance = "Linear support-vector classifier with calibrated probabilities for metric evidence."
    recommendation_tier = 55
    params_model = CalibratedLinearSVCClassificationParams
    param_grid_model = CalibratedLinearSVCClassificationParamGrid
    scaler_for_numeric = True

    @classmethod
    def _build_estimator(cls, **estimator_kwargs: object) -> CalibratedClassifierCV:
        kwargs = dict(estimator_kwargs)
        cv = int(kwargs.pop("cv", 2))
        estimator = LinearSVC(
            **kwargs,
            random_state=42,
        )
        return CalibratedClassifierCV(estimator=estimator, cv=cv)


class MLPClassificationService(NumericAndCategoricalModelService):
    key = "classification.mlp"
    display_name = "MLP Classifier"
    problem_kind = ProblemKind.CLASSIFICATION
    family = "Neural network"
    guidance = "Neural-network classifier for nonlinear patterns after simpler baselines are checked."
    recommendation_tier = 75
    params_model = MLPClassificationParams
    param_grid_model = MLPClassificationParamGrid
    scaler_for_numeric = True
    dense_preprocessing = True

    @classmethod
    def _build_estimator(cls, **estimator_kwargs: object) -> MLPClassifier:
        kwargs = dict(estimator_kwargs)
        hidden_layer_size = int(kwargs.pop("hidden_layer_size", 64))
        kwargs.setdefault("hidden_layer_sizes", (hidden_layer_size,))
        kwargs.setdefault("random_state", 42)
        return MLPClassifier(**kwargs)

    @classmethod
    def _build_param_grid(cls, param_grid_model: BaseModel) -> dict[str, list[Any]]:
        payload = param_grid_model.model_dump(mode="json", by_alias=True)
        grid: dict[str, list[Any]] = {}
        for key, values in payload.items():
            if key == "hidden_layer_size":
                grid["model__hidden_layer_sizes"] = [(int(value),) for value in values]
            else:
                grid[f"model__{key}"] = list(values)
        return grid


class MultinomialNBClassificationService(NumericAndCategoricalModelService):
    key = "classification.multinomial_naive_bayes"
    display_name = "Multinomial Naive Bayes"
    problem_kind = ProblemKind.CLASSIFICATION
    family = "Probabilistic baseline"
    guidance = "Fast probabilistic classifier for count-like or non-negative feature tables."
    recommendation_tier = 68
    params_model = MultinomialNBClassificationParams
    param_grid_model = MultinomialNBClassificationParamGrid

    @classmethod
    def _build_estimator(cls, **estimator_kwargs: object) -> MultinomialNB:
        return MultinomialNB(**estimator_kwargs)

    @classmethod
    def _build_preprocessor(cls) -> ColumnTransformer:
        numeric_transformer = Pipeline(
            steps=[
                ("imputer", SimpleImputer(strategy="median")),
                ("scaler", MinMaxScaler()),
            ]
        )
        categorical_transformer = Pipeline(
            steps=[
                ("imputer", SimpleImputer(strategy="most_frequent")),
                ("encoder", OneHotEncoder(handle_unknown="ignore")),
            ]
        )
        return ColumnTransformer(
            transformers=[
                ("numeric", numeric_transformer, cls._numeric_selector),
                ("categorical", categorical_transformer, cls._categorical_selector),
            ],
        )


class LabelPropagationClassificationService(SemiSupervisedClassificationModelService):
    key = "classification.label_propagation"
    display_name = "Label Propagation Classifier"
    problem_kind = ProblemKind.CLASSIFICATION
    guidance = "Uses unlabeled rows to propagate labels across similar examples; useful when only part of the table is labeled."
    recommendation_tier = 85
    params_model = LabelPropagationParams
    param_grid_model = None

    @classmethod
    def _build_estimator(cls, **estimator_kwargs: object) -> LabelPropagationClassifier:
        kwargs = dict(estimator_kwargs)
        kwargs.setdefault("n_jobs", 1)
        return LabelPropagationClassifier(**kwargs)


class LabelSpreadingClassificationService(SemiSupervisedClassificationModelService):
    key = "classification.label_spreading"
    display_name = "Label Spreading Classifier"
    problem_kind = ProblemKind.CLASSIFICATION
    guidance = "Smooths labels across similar rows while using unlabeled examples as supporting evidence."
    recommendation_tier = 86
    params_model = LabelSpreadingParams
    param_grid_model = None

    @classmethod
    def _build_estimator(cls, **estimator_kwargs: object) -> LabelSpreadingClassifier:
        kwargs = dict(estimator_kwargs)
        kwargs.setdefault("n_jobs", 1)
        return LabelSpreadingClassifier(**kwargs)


class SelfTrainingClassificationService(SemiSupervisedClassificationModelService):
    key = "classification.self_training"
    display_name = "Self-Training Classifier"
    problem_kind = ProblemKind.CLASSIFICATION
    guidance = "Starts from labeled rows, then cautiously adds high-confidence unlabeled rows to improve coverage."
    recommendation_tier = 87
    params_model = SelfTrainingClassificationParams
    param_grid_model = None

    @classmethod
    def _build_estimator(cls, **estimator_kwargs: object) -> SelfTrainingLogisticClassifier:
        return SelfTrainingLogisticClassifier(**estimator_kwargs)
