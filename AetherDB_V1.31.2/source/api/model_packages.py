"""Admin-only lifecycle API for trusted local model packages."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.dependencies.auth import require_admin
from services.audit_log import log_event
from services.db import get_db
from services.model_packages.installer import (
    ModelPackageOperationError,
    cancel_operation,
    retry_operation,
    set_package_enabled,
    start_install_operation,
    start_verify_operation,
    uninstall_package,
)
from services.model_packages.registry import (
    ModelPackageRegistryError,
    accept_license,
    check_distribution_eligibility,
    get_operation,
    get_package,
    list_operations,
    list_packages,
    sync_catalog,
)


router = APIRouter(prefix="/api/model-packages", tags=["model_packages"])


class LicenseAcceptanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    package_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[a-z0-9.-]+)?$")
    manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    license_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9+._-]{0,63}$")
    accepted: Literal[True]


class InstallPackageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    package_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[a-z0-9.-]+)?$")
    source_kind: Literal["catalog", "offline_cache"] = "catalog"
    source_ref: str | None = Field(default=None, max_length=160)


class PackageVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    package_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[a-z0-9.-]+)?$")


class UninstallPackageRequest(PackageVersionRequest):
    confirm_package_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,95}$")


class DistributionPackageRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    package_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,95}$")
    package_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[a-z0-9.-]+)?$")


class DistributionCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    packages: list[DistributionPackageRef] = Field(min_length=1, max_length=32)


def _audit(event_type: str, package_id: str, success: bool) -> None:
    db = get_db()
    try:
        log_event(
            db,
            event_type,
            "Model package lifecycle action",
            target=package_id,
            success=success,
        )
    finally:
        db.close()


def _raise_package_error(exc) -> None:
    raise HTTPException(409, {"code": exc.code, "message": exc.safe_message})


@router.get("")
def api_list_model_packages(_: None = Depends(require_admin)):
    try:
        packages = list_packages()
    except ModelPackageRegistryError as exc:
        _raise_package_error(exc)
    return {"packages": packages}


@router.get("/operations")
def api_list_model_package_operations(
    limit: int = 20,
    _: None = Depends(require_admin),
):
    return {"operations": list_operations(limit)}


@router.post("/distribution-check")
def api_check_model_package_distribution(
    payload: DistributionCheckRequest,
    _: None = Depends(require_admin),
):
    result = check_distribution_eligibility(
        [(item.package_id, item.package_version) for item in payload.packages]
    )
    _audit("model_package.distribution.check", "release-candidate", result["eligible"])
    return result


@router.get("/operations/{operation_id}")
def api_get_model_package_operation(
    operation_id: str,
    _: None = Depends(require_admin),
):
    operation = get_operation(operation_id)
    if operation is None:
        raise HTTPException(404, "Model package operation not found")
    return {"operation": operation}


@router.post("/operations/{operation_id}/cancel")
def api_cancel_model_package_operation(
    operation_id: str,
    _: None = Depends(require_admin),
):
    try:
        operation = cancel_operation(operation_id)
    except KeyError:
        raise HTTPException(404, "Model package operation not found")
    _audit("model_package.operation.cancel", operation["package_id"], True)
    return {"operation": operation}


@router.post("/operations/{operation_id}/retry", status_code=202)
def api_retry_model_package_operation(
    operation_id: str,
    _: None = Depends(require_admin),
):
    try:
        operation = retry_operation(operation_id)
    except KeyError:
        raise HTTPException(404, "Model package operation not found")
    except (ModelPackageOperationError, ModelPackageRegistryError) as exc:
        _raise_package_error(exc)
    _audit("model_package.operation.retry", operation["package_id"], True)
    return {"operation": operation}


@router.get("/{package_id}")
def api_get_model_package(
    package_id: str,
    _: None = Depends(require_admin),
):
    try:
        package = get_package(package_id)
    except ModelPackageRegistryError as exc:
        _raise_package_error(exc)
    if package is None:
        raise HTTPException(404, "Model package not found")
    return {"package": package}


@router.post("/{package_id}/license-acceptance")
def api_accept_model_package_license(
    package_id: str,
    payload: LicenseAcceptanceRequest,
    _: None = Depends(require_admin),
):
    try:
        sync_catalog()
        result = accept_license(
            package_id,
            payload.package_version,
            manifest_digest=payload.manifest_digest,
            license_id=payload.license_id,
            accepted_by="local-admin",
        )
    except KeyError:
        raise HTTPException(404, "Model package not found")
    except ModelPackageRegistryError as exc:
        _raise_package_error(exc)
    _audit("model_package.license.accept", package_id, True)
    return result


@router.post("/{package_id}/install", status_code=202)
def api_install_model_package(
    package_id: str,
    payload: InstallPackageRequest,
    _: None = Depends(require_admin),
):
    try:
        operation = start_install_operation(
            package_id,
            package_version=payload.package_version,
            source_kind=payload.source_kind,
            source_ref=payload.source_ref,
        )
    except KeyError:
        raise HTTPException(404, "Model package not found")
    except (ModelPackageOperationError, ModelPackageRegistryError) as exc:
        _raise_package_error(exc)
    _audit("model_package.install.start", package_id, True)
    return {"operation": operation}


@router.post("/{package_id}/repair", status_code=202)
def api_repair_model_package(
    package_id: str,
    payload: InstallPackageRequest,
    _: None = Depends(require_admin),
):
    try:
        operation = start_install_operation(
            package_id,
            package_version=payload.package_version,
            source_kind=payload.source_kind,
            source_ref=payload.source_ref,
            repair=True,
        )
    except KeyError:
        raise HTTPException(404, "Model package not found")
    except (ModelPackageOperationError, ModelPackageRegistryError) as exc:
        _raise_package_error(exc)
    _audit("model_package.repair.start", package_id, True)
    return {"operation": operation}


@router.post("/{package_id}/verify", status_code=202)
def api_verify_model_package(
    package_id: str,
    payload: PackageVersionRequest,
    _: None = Depends(require_admin),
):
    try:
        operation = start_verify_operation(
            package_id,
            package_version=payload.package_version,
        )
    except KeyError:
        raise HTTPException(404, "Model package not found")
    except (ModelPackageOperationError, ModelPackageRegistryError) as exc:
        _raise_package_error(exc)
    _audit("model_package.verify.start", package_id, True)
    return {"operation": operation}


@router.post("/{package_id}/uninstall")
def api_uninstall_model_package(
    package_id: str,
    payload: UninstallPackageRequest,
    _: None = Depends(require_admin),
):
    try:
        installation = uninstall_package(
            package_id,
            confirm_package_id=payload.confirm_package_id,
            confirm_package_version=payload.package_version,
        )
    except KeyError:
        raise HTTPException(404, "Model package not found")
    except (ModelPackageOperationError, ModelPackageRegistryError) as exc:
        _raise_package_error(exc)
    _audit("model_package.uninstall", package_id, True)
    return {"installation": installation}


@router.post("/{package_id}/disable")
def api_disable_model_package(
    package_id: str,
    _: None = Depends(require_admin),
):
    try:
        installation = set_package_enabled(package_id, False)
    except KeyError:
        raise HTTPException(404, "Model package not found")
    except (ModelPackageOperationError, ModelPackageRegistryError) as exc:
        _raise_package_error(exc)
    _audit("model_package.disable", package_id, True)
    return {"installation": installation}


@router.post("/{package_id}/enable")
def api_enable_model_package(
    package_id: str,
    _: None = Depends(require_admin),
):
    try:
        installation = set_package_enabled(package_id, True)
    except KeyError:
        raise HTTPException(404, "Model package not found")
    except (ModelPackageOperationError, ModelPackageRegistryError) as exc:
        _raise_package_error(exc)
    _audit("model_package.enable", package_id, True)
    return {"installation": installation}
