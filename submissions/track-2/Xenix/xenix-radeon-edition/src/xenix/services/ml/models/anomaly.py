from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field
from sklearn.ensemble import IsolationForest
from sklearn.neighbors import LocalOutlierFactor

from ...storage.models import ProblemKind
from .base import UnsupervisedAnomalyModelService


class IsolationForestParams(BaseModel):
    n_estimators: int = Field(default=100, ge=10, le=1000)
    contamination: float | Literal["auto"] = Field(default="auto")
    max_samples: float | Literal["auto"] = Field(default="auto")


class LocalOutlierFactorParams(BaseModel):
    n_neighbors: int = Field(default=20, ge=2, le=200)
    contamination: float | Literal["auto"] = Field(default="auto")
    metric: Literal["minkowski", "euclidean", "manhattan"] = Field(default="minkowski")


class IsolationForestAnomalyService(UnsupervisedAnomalyModelService):
    key = "anomaly.isolation_forest"
    display_name = "Isolation Forest"
    problem_kind = ProblemKind.ANOMALY_DETECTION
    family = "Tree anomaly detector"
    guidance = "Finds rows that become isolated quickly across random trees."
    recommendation_tier = 10
    params_model = IsolationForestParams

    @classmethod
    def _build_estimator(cls, **estimator_kwargs: object) -> IsolationForest:
        kwargs = dict(estimator_kwargs)
        kwargs.setdefault("random_state", 42)
        kwargs.setdefault("n_jobs", 1)
        return IsolationForest(**kwargs)


class LocalOutlierFactorAnomalyService(UnsupervisedAnomalyModelService):
    key = "anomaly.local_outlier_factor"
    display_name = "Local Outlier Factor"
    problem_kind = ProblemKind.ANOMALY_DETECTION
    family = "Density anomaly detector"
    guidance = "Finds rows that look sparse compared with their nearest neighbors."
    recommendation_tier = 25
    params_model = LocalOutlierFactorParams

    @classmethod
    def _build_estimator(cls, **estimator_kwargs: object) -> LocalOutlierFactor:
        return LocalOutlierFactor(**estimator_kwargs)
