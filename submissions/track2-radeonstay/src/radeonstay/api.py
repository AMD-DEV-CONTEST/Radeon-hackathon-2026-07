from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from contextlib import asynccontextmanager
from typing import Annotated, Any, Protocol

from fastapi import FastAPI, Header, HTTPException, Path, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse

from .auth import IdentityError
from .contracts import (
    AgentResponse,
    AuditEvent,
    CancelActionRequest,
    ChatRequest,
    ConfirmRequest,
    JourneyView,
    SessionProjection,
    ToolReceipt,
)
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

_SENSITIVE_API_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "confirmation_token",
        "cookie",
        "identity_token",
        "password",
        "private_key",
        "refresh_token",
        "secret",
        "session_token",
        "set_cookie",
        "ssh_key",
        "token",
        "token_hash",
    }
)
_SAFE_TOKEN_METRIC_KEYS = frozenset(
    {
        "completion_tokens",
        "decode_tokens_per_second",
        "effective_output_tokens_per_second",
        "max_tokens",
        "prompt_tokens",
        "server_decode_tokens_per_second",
        "time_to_first_token_ms",
        "tokens_per_second",
        "total_tokens",
    }
)
_SENSITIVE_API_ASSIGNMENT_PATTERN = re.compile(
    r"\b([A-Za-z0-9_-]*(?:access[_-]?token|api[_-]?key|authorization|"
    r"confirmation[_-]?token|identity[_-]?token|password|refresh[_-]?token|"
    r"private[_-]?key|secret|session[_-]?token|ssh[_-]?key))"
    r"(\s*[:=]\s*)((?:bearer\s+)?[^\s,;&<>]+)",
    flags=re.IGNORECASE,
)
_BEARER_API_TOKEN_PATTERN = re.compile(
    r"\bbearer\s+[A-Za-z0-9._~+/=-]+",
    flags=re.IGNORECASE,
)
_STAY_BRIEF_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Disposition": 'attachment; filename="radeonstay-stay-brief.html"',
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; img-src data:; "
        "base-uri 'none'; form-action 'none'; frame-ancestors 'none'; sandbox"
    ),
    "X-Content-Type-Options": "nosniff",
}


def _is_sensitive_api_key(key: object) -> bool:
    normalized = str(key).casefold().replace("-", "_")
    if normalized in _SAFE_TOKEN_METRIC_KEYS:
        return False
    if normalized in _SENSITIVE_API_KEYS:
        return True
    if set(normalized.split("_")) & {
        "credential",
        "credentials",
        "password",
        "secret",
        "token",
    }:
        return True
    return any(
        marker in normalized
        for marker in (
            "_api_key",
            "_credential",
            "_password",
            "_private_key",
            "_secret",
            "_ssh_key",
            "_token",
            "private_key_",
            "ssh_key_",
            "token_",
        )
    )


def _redact_api_text(value: str) -> str:
    redacted = _SENSITIVE_API_ASSIGNMENT_PATTERN.sub(
        lambda match: (
            match.group(1)
            + match.group(2)
            + (
                "Bearer [REDACTED]"
                if match.group(3).casefold().startswith("bearer ")
                else "[REDACTED]"
            )
        ),
        value,
    )
    return _BEARER_API_TOKEN_PATTERN.sub("Bearer [REDACTED]", redacted)


def _redact_api_payload(value: Any) -> Any:
    """Recursively redact secret-bearing fields at the HTTP boundary."""

    model_fields = getattr(type(value), "model_fields", None)
    model_copy = getattr(value, "model_copy", None)
    if isinstance(model_fields, dict) and callable(model_copy):
        updates: dict[str, Any] = {}
        for field_name, field_info in model_fields.items():
            field_value = getattr(value, field_name)
            if field_name == "secret_retained" and type(field_value) is bool:
                # This typed PrivacyProof flag is evidence that no secret was
                # retained, not secret material. Only the boolean form is safe.
                updates[field_name] = field_value
                continue
            if _is_sensitive_api_key(field_name):
                if getattr(field_info, "exclude", False) is not True:
                    updates[field_name] = "[REDACTED]"
                continue
            updates[field_name] = _redact_api_payload(field_value)
        return model_copy(update=updates, deep=True)
    if isinstance(value, Mapping):
        return {
            str(key): (
                item
                if str(key).casefold().replace("-", "_") == "secret_retained"
                and type(item) is bool
                else "[REDACTED]"
                if _is_sensitive_api_key(key)
                else _redact_api_payload(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact_api_payload(item) for item in value]
    if isinstance(value, str):
        return _redact_api_text(value)
    return value


def _safe_request_validation_errors(
    exc: RequestValidationError,
) -> list[dict[str, Any]]:
    """Expose only bounded location, type, and redacted message metadata."""

    safe_errors: list[dict[str, Any]] = []
    for error in exc.errors():
        raw_location = error.get("loc")
        location = (
            [
                item
                if isinstance(item, int)
                else (
                    "[sensitive]"
                    if _is_sensitive_api_key(item)
                    else _redact_api_text(str(item))[:120]
                )
                for item in raw_location
            ]
            if isinstance(raw_location, (list, tuple))
            else []
        )
        safe_errors.append(
            {
                "loc": location,
                "type": str(error.get("type") or "value_error")[:120],
                "msg": "Invalid request value",
            }
        )
    return safe_errors


class ServiceProtocol(Protocol):
    def chat(
        self,
        request: ChatRequest,
        *,
        stage_callback: Callable[[str, str], None] | None = None,
    ) -> AgentResponse: ...

    def confirm(self, request: ConfirmRequest) -> ToolReceipt: ...

    def cancel_action(self, request: CancelActionRequest) -> ToolReceipt: ...

    def reset_session(
        self,
        session_id: str,
        identity_token: str,
    ) -> JourneyView: ...

    def session_snapshot(self, session_id: str, identity_token: str) -> JourneyView: ...

    def session_projection(
        self,
        session_id: str,
        identity_token: str,
    ) -> SessionProjection: ...

    def stay_brief(self, session_id: str, identity_token: str) -> str: ...

    def health(self) -> dict[str, Any]: ...

    def audit_events(self, session_id: str, identity_token: str) -> list[AuditEvent]: ...

    def close(self) -> None: ...


def readiness_report(
    service: ServiceProtocol,
    *,
    startup_preflight: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Normalize readiness without exposing dependency exception details."""
    try:
        report = dict(service.health())
    except Exception as exc:
        report = {
            "ok": False,
            "error": {"type": type(exc).__name__},
        }
    static_preflight_ok = startup_security_checks_ok(startup_preflight)
    report["ok"] = bool(report.get("ok") is True and static_preflight_ok)
    report["status"] = "ready" if report["ok"] else "not_ready"
    if startup_preflight is not None:
        report["startup_preflight"] = startup_preflight
    return _redact_api_payload(report)


def startup_security_checks_ok(
    startup_preflight: dict[str, Any] | None,
) -> bool:
    """Keep immutable safety gates separate from transient model readiness."""

    if startup_preflight is None:
        return True
    checks = startup_preflight.get("checks")
    if not isinstance(checks, dict):
        return False
    return all(
        isinstance(checks.get(name), dict)
        and checks[name].get("ok") is True
        for name in (
            "environment_file",
            "runtime_permissions",
            "inventory",
            "policies",
            "tools",
            "runtime_proof",
            "demo_isolation",
        )
    )


def create_api(
    service: ServiceProtocol,
    *,
    startup_preflight: dict[str, Any] | None = None,
    operations_enabled: bool = True,
) -> FastAPI:
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

    @app.middleware("http")
    async def prevent_v1_response_caching(
        request: Request,
        call_next: Callable[[Request], Any],
    ) -> Any:
        if (
            not operations_enabled
            and (request.url.path == "/v1" or request.url.path.startswith("/v1/"))
        ):
            return JSONResponse(
                status_code=503,
                content={
                    "detail": (
                        "Isolated demo operations are disabled until readiness passes"
                    )
                },
                headers={"Cache-Control": "no-store"},
            )
        response = await call_next(request)
        if request.url.path == "/v1" or request.url.path.startswith("/v1/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(RequestValidationError)
    async def request_validation_error(
        _: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"detail": _safe_request_validation_errors(exc)},
        )

    def readiness_response() -> JSONResponse:
        report = readiness_report(service, startup_preflight=startup_preflight)
        return JSONResponse(status_code=200 if report["ok"] else 503, content=report)

    @app.get("/health/live")
    def health_live() -> dict[str, Any]:
        return {
            "ok": True,
            "status": "live",
            "service": "radeonstay",
        }

    @app.get("/health/ready")
    def health_ready() -> JSONResponse:
        return readiness_response()

    @app.get("/health")
    def health() -> JSONResponse:
        """Backward-compatible readiness endpoint."""
        return readiness_response()

    @app.post("/v1/chat", response_model=AgentResponse)
    def chat(request: ChatRequest) -> AgentResponse:
        try:
            return _redact_api_payload(service.chat(request))
        except IdentityError as exc:
            raise HTTPException(
                status_code=401,
                detail=_redact_api_text(str(exc)),
            ) from exc
        except PermissionDenied as exc:
            raise HTTPException(
                status_code=403,
                detail=_redact_api_text(str(exc)),
            ) from exc
        except NotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail=_redact_api_text(str(exc)),
            ) from exc
        except (ConflictError, ConsentRequired) as exc:
            raise HTTPException(
                status_code=409,
                detail=_redact_api_text(str(exc)),
            ) from exc
        except (DomainValidationError, ValueError) as exc:
            raise HTTPException(
                status_code=422,
                detail=_redact_api_text(str(exc)),
            ) from exc
        except ModelClientError as exc:
            raise HTTPException(status_code=503, detail="Local model is unavailable") from exc
        except DomainError as exc:
            raise HTTPException(
                status_code=400,
                detail=_redact_api_text(str(exc)),
            ) from exc

    @app.post("/v1/confirm", response_model=ToolReceipt)
    def confirm(request: ConfirmRequest) -> ToolReceipt:
        try:
            return _redact_api_payload(service.confirm(request))
        except IdentityError as exc:
            raise HTTPException(
                status_code=401,
                detail=_redact_api_text(str(exc)),
            ) from exc
        except PermissionDenied as exc:
            raise HTTPException(
                status_code=403,
                detail=_redact_api_text(str(exc)),
            ) from exc
        except NotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail=_redact_api_text(str(exc)),
            ) from exc
        except (ConflictError, ConsentRequired) as exc:
            raise HTTPException(
                status_code=409,
                detail=_redact_api_text(str(exc)),
            ) from exc
        except (DomainValidationError, ValueError) as exc:
            raise HTTPException(
                status_code=422,
                detail=_redact_api_text(str(exc)),
            ) from exc
        except DomainError as exc:
            raise HTTPException(
                status_code=400,
                detail=_redact_api_text(str(exc)),
            ) from exc

    @app.post("/v1/actions/cancel", response_model=ToolReceipt)
    def cancel_action(request: CancelActionRequest) -> ToolReceipt:
        try:
            return _redact_api_payload(service.cancel_action(request))
        except IdentityError as exc:
            raise HTTPException(
                status_code=401,
                detail=_redact_api_text(str(exc)),
            ) from exc
        except PermissionDenied as exc:
            raise HTTPException(
                status_code=403,
                detail=_redact_api_text(str(exc)),
            ) from exc
        except NotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail=_redact_api_text(str(exc)),
            ) from exc
        except (ConflictError, ConsentRequired) as exc:
            raise HTTPException(
                status_code=409,
                detail=_redact_api_text(str(exc)),
            ) from exc
        except (DomainValidationError, ValueError) as exc:
            raise HTTPException(
                status_code=422,
                detail=_redact_api_text(str(exc)),
            ) from exc
        except DomainError as exc:
            raise HTTPException(
                status_code=400,
                detail=_redact_api_text(str(exc)),
            ) from exc

    @app.get("/v1/sessions/{session_id}", response_model=JourneyView)
    def session_snapshot(
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
    ) -> JourneyView:
        try:
            return _redact_api_payload(
                service.session_snapshot(session_id, identity_token)
            )
        except IdentityError as exc:
            raise HTTPException(
                status_code=401,
                detail=_redact_api_text(str(exc)),
            ) from exc
        except PermissionDenied as exc:
            raise HTTPException(
                status_code=403,
                detail=_redact_api_text(str(exc)),
            ) from exc
        except NotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail=_redact_api_text(str(exc)),
            ) from exc

    @app.get("/v1/sessions/{session_id}/brief", response_class=HTMLResponse)
    def stay_brief(
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
    ) -> HTMLResponse:
        try:
            return HTMLResponse(
                service.stay_brief(session_id, identity_token),
                headers=_STAY_BRIEF_HEADERS,
            )
        except IdentityError as exc:
            raise HTTPException(
                status_code=401,
                detail=_redact_api_text(str(exc)),
            ) from exc
        except PermissionDenied as exc:
            raise HTTPException(
                status_code=403,
                detail=_redact_api_text(str(exc)),
            ) from exc
        except NotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail=_redact_api_text(str(exc)),
            ) from exc
        except DomainValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail=_redact_api_text(str(exc)),
            ) from exc

    @app.get(
        "/v1/sessions/{session_id}/projection",
        response_model=SessionProjection,
    )
    def session_projection(
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
    ) -> SessionProjection:
        try:
            return _redact_api_payload(
                service.session_projection(session_id, identity_token)
            )
        except IdentityError as exc:
            raise HTTPException(
                status_code=401,
                detail=_redact_api_text(str(exc)),
            ) from exc
        except PermissionDenied as exc:
            raise HTTPException(
                status_code=403,
                detail=_redact_api_text(str(exc)),
            ) from exc
        except NotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail=_redact_api_text(str(exc)),
            ) from exc

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
            return [
                _redact_api_payload(event)
                for event in service.audit_events(session_id, identity_token)
            ]
        except IdentityError as exc:
            raise HTTPException(
                status_code=401,
                detail=_redact_api_text(str(exc)),
            ) from exc
        except PermissionDenied as exc:
            raise HTTPException(
                status_code=403,
                detail=_redact_api_text(str(exc)),
            ) from exc

    return app
