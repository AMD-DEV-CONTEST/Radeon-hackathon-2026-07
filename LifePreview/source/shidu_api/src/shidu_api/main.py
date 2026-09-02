"""Application factory for the independent Shidu consumer API."""

from __future__ import annotations

import importlib
import os
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from creative_hub.artifact_proxy import ArtifactGateway

from .routes import create_artifact_router, create_public_router
from .security import ArtifactTokenSigner
from .services import ApiServiceError, ShiduApiService


def _error(status_code: int, error_code: str, message: str, retryable: bool) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error_code": error_code,
            "message": message,
            "retryable": retryable,
        },
    )


def create_app(
    *,
    service: ShiduApiService,
    signer: ArtifactTokenSigner,
    artifact_gateway: ArtifactGateway,
    project_id: UUID,
) -> FastAPI:
    if not isinstance(project_id, UUID):
        raise ValueError("project_id is required")
    app = FastAPI(
        title="Shidu API",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
    )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_: Request, __: RequestValidationError) -> JSONResponse:
        return _error(422, "invalid_request", "请求参数无效", False)

    @app.exception_handler(ApiServiceError)
    async def service_error(_: Request, exc: ApiServiceError) -> JSONResponse:
        return _error(exc.status_code, exc.error_code, exc.public_message, exc.retryable)

    @app.exception_handler(Exception)
    async def internal_error(_: Request, __: Exception) -> JSONResponse:
        return _error(500, "internal_error", "服务内部错误", False)

    @app.get("/health/live", include_in_schema=False)
    async def liveness() -> dict[str, str]:
        return {"status": "live"}

    @app.get("/health/ready", include_in_schema=False)
    async def readiness() -> Any:
        probe = getattr(service, "is_ready", None)
        try:
            ready = True if probe is None else probe()
        except Exception:
            ready = False
        if ready is not True:
            return JSONResponse(
                status_code=503,
                content={"status": "not_ready"},
            )
        return {"status": "ready"}

    app.include_router(
        create_public_router(service=service, signer=signer, project_id=project_id)
    )
    app.include_router(create_artifact_router(signer=signer, gateway=artifact_gateway))
    return app


def _factory(spec: str) -> Any:
    if ":" not in spec:
        raise RuntimeError("factory must use module:callable syntax")
    module_name, name = spec.split(":", 1)
    factory = getattr(importlib.import_module(module_name), name)
    return factory()


def _secret_from_file(environment_name: str, *, optional: bool = False) -> str:
    location = os.environ.get(environment_name, "")
    if not location:
        if optional:
            return ""
        raise RuntimeError(f"{environment_name} is required")
    try:
        path = Path(location)
        if not path.is_file() or path.stat().st_size > 65_536:
            raise OSError
        value = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        raise RuntimeError(f"{environment_name} is unreadable") from None
    if not value and not optional:
        raise RuntimeError(f"{environment_name} is empty")
    return value


def configured_app() -> FastAPI:
    """Fail-closed environment wiring; deployment supplies real adapters."""

    secret = _secret_from_file("SHIDU_SIGNING_SECRET_FILE").encode("utf-8")
    previous_secrets = tuple(
        item.encode("utf-8")
        for item in _secret_from_file(
            "SHIDU_PREVIOUS_SIGNING_SECRETS_FILE", optional=True
        ).splitlines()
        if item
    )
    project = os.environ.get("SHIDU_PROJECT_ID", "")
    service_factory = os.environ.get("SHIDU_SERVICE_FACTORY", "")
    gateway_factory = os.environ.get("SHIDU_ARTIFACT_GATEWAY_FACTORY", "")
    if not project or not service_factory or not gateway_factory:
        raise RuntimeError("Shidu production adapters are not configured")
    return create_app(
        service=_factory(service_factory),
        signer=ArtifactTokenSigner(
            secret,
            previous_secrets=previous_secrets,
        ),
        artifact_gateway=_factory(gateway_factory),
        project_id=UUID(project),
    )


def _server_bindings() -> tuple[str, int]:
    host = os.environ.get("SHIDU_API_HOST", "0.0.0.0")
    port_text = os.environ.get("SHIDU_API_PORT", "8082")
    if not port_text.isascii() or not port_text.isdecimal():
        raise RuntimeError("SHIDU_API_PORT must be an integer from 1 to 65535")
    port = int(port_text)
    if not 1 <= port <= 65_535:
        raise RuntimeError("SHIDU_API_PORT must be an integer from 1 to 65535")
    return host, port


def main() -> None:
    import uvicorn

    host, port = _server_bindings()
    uvicorn.run(configured_app(), host=host, port=port)


__all__ = ["configured_app", "create_app", "main"]
