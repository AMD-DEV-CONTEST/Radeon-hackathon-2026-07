from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Annotated, Any, Protocol

from fastapi import FastAPI, Header, HTTPException, Path

from .auth import IdentityError
from .contracts import AgentResponse, AuditEvent, ChatRequest, ConfirmRequest, ToolReceipt
from .domain import (
    ConflictError,
    ConsentRequired,
    DomainError,
    NotFoundError,
    PermissionDenied,
)
from .domain import (
    ValidationError as DomainValidationError,
)
from .model_client import ModelClientError


class ServiceProtocol(Protocol):
    def chat(self, request: ChatRequest) -> AgentResponse: ...

    def confirm(self, request: ConfirmRequest) -> ToolReceipt: ...

    def health(self) -> dict[str, Any]: ...

    def audit_events(self, session_id: str, identity_token: str) -> list[AuditEvent]: ...

    def close(self) -> None: ...


def create_api(service: ServiceProtocol) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        try:
            yield
        finally:
            service.close()

    app = FastAPI(
        title="RadeonStay",
        version="0.1.0",
        description="Private, auditable hotel guest-journey agent on AMD Radeon/ROCm",
        lifespan=lifespan,
    )

    @app.get("/health")
    def health() -> dict[str, Any]:
        return service.health()

    @app.post("/v1/chat", response_model=AgentResponse)
    def chat(request: ChatRequest) -> AgentResponse:
        try:
            return service.chat(request)
        except IdentityError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        except PermissionDenied as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ConflictError, ConsentRequired) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (DomainValidationError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except ModelClientError as exc:
            raise HTTPException(status_code=503, detail="Local model is unavailable") from exc
        except DomainError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/v1/confirm", response_model=ToolReceipt)
    def confirm(request: ConfirmRequest) -> ToolReceipt:
        try:
            return service.confirm(request)
        except IdentityError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        except PermissionDenied as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ConflictError, ConsentRequired) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (DomainValidationError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except DomainError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/v1/audit/{session_id}", response_model=list[AuditEvent])
    def audit(
        session_id: Annotated[
            str,
            Path(
                min_length=1,
                max_length=120,
                pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
            ),
        ],
        identity_token: Annotated[
            str,
            Header(alias="X-Identity-Token", min_length=20, max_length=2000),
        ],
    ) -> list[AuditEvent]:
        try:
            return service.audit_events(session_id, identity_token)
        except IdentityError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        except PermissionDenied as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    return app
