from __future__ import annotations

from importlib import import_module


_EXPORTS = {
    "get_model_catalog_entry": ".registry",
    "get_model_service": ".registry",
    "list_model_catalog": ".registry",
    "list_model_keys": ".registry",
    "ColumnRoleBinding": ".types",
    "ColumnRoleKind": ".types",
    "EvaluationKind": ".types",
    "ModelCatalogEntry": ".types",
    "ModelFamily": ".types",
    "ModelResultContract": ".types",
    "ModelRoleDefinition": ".types",
    "ModelRoleSchema": ".types",
    "ModelServiceBase": ".types",
    "ModelTaskKind": ".types",
    "MLWorkerConfig": ".worker_settings",
    "MLWorkerKind": ".worker_settings",
    "MLWorkerPoolConfig": ".worker_settings",
    "MLWorkerSettings": ".worker_settings",
    "MLWorkerSettingsService": ".worker_settings",
    "MLWorkerSetupState": ".worker_settings",
    "MLWorkerValidationRecord": ".worker_settings",
    "MLWorkerValidationStatus": ".worker_settings",
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> object:
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_name, __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted([*globals(), *__all__])
