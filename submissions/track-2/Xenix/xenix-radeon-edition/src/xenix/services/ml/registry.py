from __future__ import annotations

from ...exceptions import NotFoundError
from .models.association import ApyoriAssociationRulesService, MlxtendAssociationRulesService
from .models.anomaly import IsolationForestAnomalyService, LocalOutlierFactorAnomalyService
from .models.classification import (
    AdaBoostClassificationService,
    CalibratedLinearSVCClassificationService,
    DecisionTreeClassificationService,
    ExtraTreesClassificationService,
    GradientBoostingClassificationService,
    HistGradientBoostingClassificationService,
    KNeighborsClassificationService,
    LabelPropagationClassificationService,
    LabelSpreadingClassificationService,
    LightGBMClassificationService,
    LogisticRegressionService,
    MLPClassificationService,
    MultinomialNBClassificationService,
    NaiveBayesClassificationService,
    RandomForestClassificationService,
    SelfTrainingClassificationService,
    SVCClassificationService,
    XGBoostClassificationService,
)
from .models.clustering import (
    BirchClusteringService,
    DBSCANClusteringService,
    GaussianMixtureClusteringService,
    KMeansClusteringService,
    MiniBatchKMeansClusteringService,
)
from .models.recommendation import ItemSimilarityRecommendationService
from .models.regression import (
    AdaBoostRegressionService,
    BayesianRidgeRegressionService,
    DecisionTreeRegressionService,
    ElasticNetRegressionService,
    GradientBoostingRegressionService,
    HistGradientBoostingRegressionService,
    KNeighborsRegressionService,
    LassoRegressionService,
    LightGBMRegressionService,
    LinearRegressionService,
    MLPRegressionService,
    PolynomialRegressionService,
    RandomForestRegressionService,
    RidgeRegressionService,
    SVRRegressionService,
    XGBoostRegressionService,
)
from .models.text_analysis import (
    TokenizedTextClassificationService,
    TokenizedTextClusteringService,
    TokenizedTextSimilarityService,
    TokenizedTextTopicModelingService,
)
from .types import ModelCatalogEntry, ModelServiceBase, parse_model_key


def _build_model_service_registry(
    services: tuple[type[ModelServiceBase], ...],
) -> dict[str, type[ModelServiceBase]]:
    if not services:
        raise ValueError("The model service registry must contain at least one service.")

    registry: dict[str, type[ModelServiceBase]] = {}
    for service in services:
        if not isinstance(service, type) or not issubclass(service, ModelServiceBase):
            raise TypeError(f"Invalid model service registration: {service!r}.")
        model_key = service.key
        parse_model_key(model_key)
        if model_key in registry:
            first_service = registry[model_key]
            raise ValueError(
                f"Duplicate model key {model_key!r} for "
                f"{first_service.__name__} and {service.__name__}."
            )
        catalog_entry = service.catalog_entry()
        if not isinstance(catalog_entry, ModelCatalogEntry):
            raise TypeError(
                f"Model service {service.__name__} returned an invalid catalog entry."
            )
        if catalog_entry.model_key != model_key:
            raise ValueError(
                f"Model service {service.__name__} catalog key "
                f"{catalog_entry.model_key!r} does not match {model_key!r}."
            )
        expected_param_schema = service.params_model.model_json_schema()
        if catalog_entry.param_schema != expected_param_schema:
            raise ValueError(
                f"Model service {service.__name__} catalog parameter schema "
                "must be derived from params_model."
            )
        expected_grid_schema = (
            service.param_grid_model.model_json_schema()
            if service.param_grid_model is not None
            else None
        )
        if catalog_entry.param_grid_schema != expected_grid_schema:
            raise ValueError(
                f"Model service {service.__name__} catalog grid schema "
                "must be derived from param_grid_model."
            )
        registry[model_key] = service
    return registry


_MODEL_SERVICE_TYPES: tuple[type[ModelServiceBase], ...] = (
    LinearRegressionService,
    LassoRegressionService,
    ElasticNetRegressionService,
    RidgeRegressionService,
    BayesianRidgeRegressionService,
    KNeighborsRegressionService,
    DecisionTreeRegressionService,
    GradientBoostingRegressionService,
    HistGradientBoostingRegressionService,
    AdaBoostRegressionService,
    XGBoostRegressionService,
    LightGBMRegressionService,
    SVRRegressionService,
    MLPRegressionService,
    PolynomialRegressionService,
    RandomForestRegressionService,
    LogisticRegressionService,
    NaiveBayesClassificationService,
    MultinomialNBClassificationService,
    KNeighborsClassificationService,
    DecisionTreeClassificationService,
    GradientBoostingClassificationService,
    HistGradientBoostingClassificationService,
    AdaBoostClassificationService,
    XGBoostClassificationService,
    LightGBMClassificationService,
    RandomForestClassificationService,
    ExtraTreesClassificationService,
    SVCClassificationService,
    CalibratedLinearSVCClassificationService,
    MLPClassificationService,
    LabelPropagationClassificationService,
    LabelSpreadingClassificationService,
    SelfTrainingClassificationService,
    BirchClusteringService,
    GaussianMixtureClusteringService,
    KMeansClusteringService,
    MiniBatchKMeansClusteringService,
    DBSCANClusteringService,
    IsolationForestAnomalyService,
    LocalOutlierFactorAnomalyService,
    ApyoriAssociationRulesService,
    MlxtendAssociationRulesService,
    ItemSimilarityRecommendationService,
    TokenizedTextClassificationService,
    TokenizedTextClusteringService,
    TokenizedTextTopicModelingService,
    TokenizedTextSimilarityService,
)

_MODEL_SERVICES = _build_model_service_registry(_MODEL_SERVICE_TYPES)


def get_model_service(model_key: str) -> type[ModelServiceBase]:
    try:
        return _MODEL_SERVICES[model_key]
    except KeyError as exc:
        raise NotFoundError(f"Model '{model_key}' was not found.") from exc


def list_model_keys() -> list[str]:
    return sorted(_MODEL_SERVICES)


def list_model_catalog() -> list[ModelCatalogEntry]:
    return [get_model_service(model_key).catalog_entry() for model_key in list_model_keys()]


def get_model_catalog_entry(model_key: str) -> ModelCatalogEntry:
    return get_model_service(model_key).catalog_entry()
