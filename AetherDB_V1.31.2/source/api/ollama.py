"""Admin-only API for a separately installed local Ollama runtime."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.dependencies.auth import require_admin
from services.audit_log import log_event
from services.db import get_db
from services.ollama_management import (
    OllamaManagementError,
    cancel_operation,
    get_runtime_status,
    delete_model_file,
    get_operation,
    list_operations,
    retry_operation,
    set_model_loaded,
    start_pull_operation,
    start_existing_runtime,
    stop_managed_runtime,
    sync_ollama_model_profiles,
)
from services.ollama_observability import (
    list_model_observations,
    list_runtime_observations,
)
from services.ollama_execution import (
    cancel_ollama_execution,
    get_ollama_execution,
    list_ollama_executions,
)
from services.ollama_install_tasks import (
    OllamaInstallTaskError,
    cancel_install_operation,
    confirm_install_download,
    create_install_operation,
    get_install_operation,
    get_install_plan,
    launch_install_operation,
    list_install_operations,
)
from services.model_management import ModelDiagnosticError


router = APIRouter(prefix="/api/ollama", tags=["ollama_management"])


class OllamaRuntimeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_id: Optional[str] = Field(default=None, max_length=64)


class OllamaModelRequest(OllamaRuntimeRequest):
    model: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")


class OllamaDeleteRequest(OllamaModelRequest):
    confirm_model: str = Field(min_length=1, max_length=256)


class OllamaInstallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accelerator: Optional[str] = Field(default=None, pattern=r"^rocm$")


class OllamaInstallLaunchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")


def _audit(event_type: str, provider_id: str | None, success: bool):
    db = get_db()
    try:
        log_event(
            db,
            event_type,
            "Ollama runtime management action",
            target=provider_id or "local-default",
            success=success,
        )
    finally:
        db.close()


@router.get("/status")
def api_ollama_status(
    provider_id: str = None,
    _: None = Depends(require_admin),
):
    try:
        return get_runtime_status(provider_id)
    except KeyError:
        raise HTTPException(404, "Model provider not found")
    except OllamaManagementError as exc:
        raise HTTPException(400, {"code": exc.code, "message": exc.safe_message})


@router.post("/reconnect")
def api_ollama_reconnect(
    payload: OllamaRuntimeRequest,
    _: None = Depends(require_admin),
):
    try:
        result = get_runtime_status(payload.provider_id)
    except KeyError:
        raise HTTPException(404, "Model provider not found")
    if result["running"] and payload.provider_id:
        try:
            result["profile_sync"] = sync_ollama_model_profiles(payload.provider_id)
        except (ModelDiagnosticError, OllamaManagementError) as exc:
            result["profile_sync"] = {
                "status": "failed",
                "code": exc.code,
                "message": exc.safe_message,
            }
    _audit("ollama.reconnect", payload.provider_id, result["running"])
    return result


@router.post("/start")
def api_ollama_start(
    payload: OllamaRuntimeRequest,
    _: None = Depends(require_admin),
):
    try:
        result = start_existing_runtime(payload.provider_id)
    except KeyError:
        raise HTTPException(404, "Model provider not found")
    except OllamaManagementError as exc:
        _audit("ollama.start", payload.provider_id, False)
        raise HTTPException(409, {"code": exc.code, "message": exc.safe_message})
    _audit("ollama.start", payload.provider_id, True)
    return result


@router.post("/stop")
def api_ollama_stop(
    payload: OllamaRuntimeRequest,
    _: None = Depends(require_admin),
):
    try:
        result = stop_managed_runtime(payload.provider_id)
    except KeyError:
        raise HTTPException(404, "Model provider not found")
    except OllamaManagementError as exc:
        _audit("ollama.stop", payload.provider_id, False)
        raise HTTPException(409, {"code": exc.code, "message": exc.safe_message})
    _audit("ollama.stop", payload.provider_id, True)
    return result


@router.get("/observations")
def api_ollama_observations(
    provider_id: str = None,
    _: None = Depends(require_admin),
):
    return {
        "runtimes": list_runtime_observations(provider_id),
        "models": list_model_observations(provider_id),
    }


@router.get("/executions")
def api_ollama_executions(
    status: str = None,
    limit: int = 100,
    _: None = Depends(require_admin),
):
    return {
        "protocol_version": "1.0",
        "executions": list_ollama_executions(status=status, limit=limit),
    }


@router.get("/executions/{execution_id}")
def api_ollama_execution(
    execution_id: str,
    _: None = Depends(require_admin),
):
    try:
        execution = get_ollama_execution(execution_id)
    except KeyError:
        raise HTTPException(404, "Ollama execution not found")
    return {"protocol_version": "1.0", "execution": execution}


@router.post("/executions/{execution_id}/cancel")
def api_cancel_ollama_execution(
    execution_id: str,
    _: None = Depends(require_admin),
):
    try:
        execution = cancel_ollama_execution(execution_id)
    except KeyError:
        raise HTTPException(404, "Ollama execution not found")
    _audit("ollama.execution.cancel", execution.get("provider_id"), True)
    return {"protocol_version": "1.0", "execution": execution}


@router.get("/models")
def api_ollama_models(
    provider_id: str = None,
    _: None = Depends(require_admin),
):
    try:
        result = get_runtime_status(provider_id)
    except KeyError:
        raise HTTPException(404, "Model provider not found")
    if not result["running"]:
        raise HTTPException(503, result["error"])
    return {
        "provider_id": provider_id,
        "version": result["version"],
        "models": result["models"],
    }


@router.get("/install/plan")
def api_ollama_install_plan(
    accelerator: str = None,
    _: None = Depends(require_admin),
):
    try:
        return {"plan": get_install_plan(accelerator=accelerator)}
    except OllamaInstallTaskError as exc:
        raise HTTPException(400, {"code": exc.code, "message": exc.safe_message})


@router.post("/install/operations", status_code=201)
def api_create_ollama_install_operation(
    payload: OllamaInstallRequest,
    _: None = Depends(require_admin),
):
    try:
        result = create_install_operation(accelerator=payload.accelerator)
    except OllamaInstallTaskError as exc:
        raise HTTPException(400, {"code": exc.code, "message": exc.safe_message})
    _audit("ollama.install.plan", None, True)
    return {"operation": result}


@router.get("/install/operations")
def api_ollama_install_operations(
    limit: int = 20,
    _: None = Depends(require_admin),
):
    return {"operations": list_install_operations(limit)}


@router.get("/install/operations/{operation_id}")
def api_ollama_install_operation(
    operation_id: str,
    _: None = Depends(require_admin),
):
    result = get_install_operation(operation_id)
    if not result:
        raise HTTPException(404, "Ollama install operation not found")
    return {"operation": result}


@router.post("/install/operations/{operation_id}/confirm-download", status_code=202)
def api_confirm_ollama_install_download(
    operation_id: str,
    _: None = Depends(require_admin),
):
    try:
        result = confirm_install_download(operation_id)
    except KeyError:
        raise HTTPException(404, "Ollama install operation not found")
    except OllamaInstallTaskError as exc:
        raise HTTPException(409, {"code": exc.code, "message": exc.safe_message})
    _audit("ollama.install.download", None, True)
    return {"operation": result}


@router.post("/install/operations/{operation_id}/cancel")
def api_cancel_ollama_install_operation(
    operation_id: str,
    _: None = Depends(require_admin),
):
    try:
        result = cancel_install_operation(operation_id)
    except KeyError:
        raise HTTPException(404, "Ollama install operation not found")
    except OllamaInstallTaskError as exc:
        raise HTTPException(409, {"code": exc.code, "message": exc.safe_message})
    _audit("ollama.install.cancel", None, True)
    return {"operation": result}


@router.post("/install/operations/{operation_id}/launch", status_code=202)
def api_launch_ollama_install_operation(
    operation_id: str,
    payload: OllamaInstallLaunchRequest,
    _: None = Depends(require_admin),
):
    try:
        result = launch_install_operation(operation_id, payload.confirm_version)
    except KeyError:
        raise HTTPException(404, "Ollama install operation not found")
    except OllamaInstallTaskError as exc:
        raise HTTPException(409, {"code": exc.code, "message": exc.safe_message})
    _audit("ollama.install.launch", None, True)
    return {"operation": result}


@router.post("/models/pull", status_code=202)
def api_ollama_pull_model(
    payload: OllamaModelRequest,
    _: None = Depends(require_admin),
):
    try:
        result = start_pull_operation(payload.model, payload.provider_id)
    except KeyError:
        raise HTTPException(404, "Model provider not found")
    except OllamaManagementError as exc:
        raise HTTPException(400, {"code": exc.code, "message": exc.safe_message})
    _audit("ollama.model.pull", payload.provider_id, True)
    return {"operation": result}


@router.post("/models/sync")
def api_ollama_sync_models(
    payload: OllamaRuntimeRequest,
    _: None = Depends(require_admin),
):
    if not payload.provider_id:
        raise HTTPException(
            400,
            {"code": "PROVIDER_REQUIRED", "message": "A registered Ollama Provider is required"},
        )
    try:
        result = sync_ollama_model_profiles(payload.provider_id)
    except KeyError:
        raise HTTPException(404, "Model provider not found")
    except (ModelDiagnosticError, OllamaManagementError) as exc:
        raise HTTPException(409, {"code": exc.code, "message": exc.safe_message})
    _audit("ollama.model.sync", payload.provider_id, True)
    return result


@router.get("/operations")
def api_ollama_operations(limit: int = 20, _: None = Depends(require_admin)):
    return {"operations": list_operations(limit)}


@router.get("/operations/{operation_id}")
def api_ollama_operation(operation_id: str, _: None = Depends(require_admin)):
    result = get_operation(operation_id)
    if not result:
        raise HTTPException(404, "Ollama operation not found")
    return {"operation": result}


@router.post("/operations/{operation_id}/retry", status_code=202)
def api_ollama_retry_operation(operation_id: str, _: None = Depends(require_admin)):
    try:
        result = retry_operation(operation_id)
    except KeyError:
        raise HTTPException(404, "Ollama operation not found")
    except OllamaManagementError as exc:
        raise HTTPException(409, {"code": exc.code, "message": exc.safe_message})
    _audit("ollama.model.pull.retry", result.get("provider_id"), True)
    return {"operation": result}


@router.post("/operations/{operation_id}/cancel")
def api_ollama_cancel_operation(
    operation_id: str,
    _: None = Depends(require_admin),
):
    try:
        result = cancel_operation(operation_id)
    except KeyError:
        raise HTTPException(404, "Ollama operation not found")
    except OllamaManagementError as exc:
        raise HTTPException(409, {"code": exc.code, "message": exc.safe_message})
    _audit("ollama.model.pull.cancel", result.get("provider_id"), True)
    return {"operation": result}


@router.post("/models/load")
def api_ollama_load_model(payload: OllamaModelRequest, _: None = Depends(require_admin)):
    try:
        result = set_model_loaded(payload.model, True, payload.provider_id)
    except (ModelDiagnosticError, OllamaManagementError) as exc:
        raise HTTPException(409, {"code": exc.code, "message": exc.safe_message})
    _audit("ollama.model.load", payload.provider_id, True)
    return result


@router.post("/models/unload")
def api_ollama_unload_model(payload: OllamaModelRequest, _: None = Depends(require_admin)):
    try:
        result = set_model_loaded(payload.model, False, payload.provider_id)
    except (ModelDiagnosticError, OllamaManagementError) as exc:
        raise HTTPException(409, {"code": exc.code, "message": exc.safe_message})
    _audit("ollama.model.unload", payload.provider_id, True)
    return result


@router.post("/models/delete")
def api_ollama_delete_model(payload: OllamaDeleteRequest, _: None = Depends(require_admin)):
    try:
        result = delete_model_file(
            payload.model, payload.confirm_model, payload.provider_id
        )
    except KeyError:
        raise HTTPException(404, "Model provider not found")
    except (ModelDiagnosticError, OllamaManagementError) as exc:
        raise HTTPException(409, {"code": exc.code, "message": exc.safe_message})
    _audit("ollama.model.delete", payload.provider_id, True)
    return result
