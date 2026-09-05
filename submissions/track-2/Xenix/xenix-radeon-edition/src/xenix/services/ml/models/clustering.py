from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field
from sklearn.cluster import DBSCAN, Birch, KMeans, MiniBatchKMeans
from sklearn.mixture import GaussianMixture

from ...storage.models import ProblemKind
from .base import UnsupervisedClusteringModelService


class KMeansParams(BaseModel):
    n_clusters: int = Field(default=4, ge=2, le=20)
    n_init: int = Field(default=10, ge=1, le=50)
    max_iter: int = Field(default=300, ge=50, le=1000)


class DBSCANParams(BaseModel):
    eps: float = Field(default=0.5, gt=0.0, le=10.0)
    min_samples: int = Field(default=5, ge=1, le=100)


class MiniBatchKMeansParams(BaseModel):
    n_clusters: int = Field(default=4, ge=2, le=20)
    batch_size: int = Field(default=256, ge=10, le=10000)
    n_init: int = Field(default=10, ge=1, le=50)
    max_iter: int = Field(default=300, ge=50, le=1000)


class BirchParams(BaseModel):
    n_clusters: int | None = Field(default=4, ge=2, le=20)
    threshold: float = Field(default=0.5, gt=0.0, le=10.0)
    branching_factor: int = Field(default=50, ge=2, le=500)


class GaussianMixtureParams(BaseModel):
    n_components: int = Field(default=4, ge=1, le=20)
    covariance_type: Literal["full", "tied", "diag", "spherical"] = Field(default="full")
    n_init: int = Field(default=1, ge=1, le=20)
    max_iter: int = Field(default=100, ge=50, le=1000)
    reg_covar: float = Field(default=1e-6, ge=0.0, le=1.0)


class KMeansClusteringService(UnsupervisedClusteringModelService):
    key = "clustering.kmeans"
    display_name = "KMeans Clustering"
    problem_kind = ProblemKind.CLUSTERING
    family = "Centroid clustering"
    guidance = "Creates a chosen number of compact segments around representative centers."
    recommendation_tier = 10
    params_model = KMeansParams

    @classmethod
    def _build_estimator(cls, **estimator_kwargs: object) -> KMeans:
        kwargs = dict(estimator_kwargs)
        kwargs.setdefault("random_state", 42)
        return KMeans(**kwargs)


class MiniBatchKMeansClusteringService(UnsupervisedClusteringModelService):
    key = "clustering.minibatch_kmeans"
    display_name = "MiniBatch KMeans Clustering"
    problem_kind = ProblemKind.CLUSTERING
    family = "Centroid clustering"
    guidance = "Creates compact segments with a faster mini-batch KMeans fit for larger datasets."
    recommendation_tier = 12
    params_model = MiniBatchKMeansParams

    @classmethod
    def _build_estimator(cls, **estimator_kwargs: object) -> MiniBatchKMeans:
        kwargs = dict(estimator_kwargs)
        kwargs.setdefault("random_state", 42)
        return MiniBatchKMeans(**kwargs)


class BirchClusteringService(UnsupervisedClusteringModelService):
    key = "clustering.birch"
    display_name = "BIRCH Clustering"
    problem_kind = ProblemKind.CLUSTERING
    family = "Hierarchical clustering"
    guidance = "Builds scalable customer segments through compact clustering feature summaries."
    recommendation_tier = 15
    params_model = BirchParams

    @classmethod
    def _build_estimator(cls, **estimator_kwargs: object) -> Birch:
        return Birch(**estimator_kwargs)


class GaussianMixtureClusteringService(UnsupervisedClusteringModelService):
    key = "clustering.gaussian_mixture"
    display_name = "Gaussian Mixture Clustering"
    problem_kind = ProblemKind.CLUSTERING
    family = "Probabilistic clustering"
    guidance = "Groups rows into probabilistic mixture components for less rigid segment shapes."
    recommendation_tier = 18
    params_model = GaussianMixtureParams

    @classmethod
    def _build_estimator(cls, **estimator_kwargs: object) -> GaussianMixture:
        kwargs = dict(estimator_kwargs)
        kwargs.setdefault("random_state", 42)
        return GaussianMixture(**kwargs)


class DBSCANClusteringService(UnsupervisedClusteringModelService):
    key = "clustering.dbscan"
    display_name = "DBSCAN Clustering"
    problem_kind = ProblemKind.CLUSTERING
    family = "Density clustering"
    guidance = "Finds dense natural groups and marks sparse rows as noise."
    recommendation_tier = 25
    params_model = DBSCANParams

    @classmethod
    def _build_estimator(cls, **estimator_kwargs: object) -> DBSCAN:
        return DBSCAN(**estimator_kwargs)
