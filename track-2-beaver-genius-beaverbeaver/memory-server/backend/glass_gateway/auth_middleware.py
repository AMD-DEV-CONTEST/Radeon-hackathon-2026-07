from __future__ import annotations

from urllib.parse import quote

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse
from starlette.responses import JSONResponse

from glass_gateway.auth import auth_registry


_PROTECTED_PAGES = {
    "/memory",
    "/memory/capsules",
    "/memory/search",
    "/memory/corrections",
    "/commitments",
    "/daily",
    "/objects/search",
    "/people",
    "/integrations",
}


class UserContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        cookie_principal = auth_registry.authenticate_cookie(
            request.cookies.get(auth_registry.settings.auth_cookie_name)
        )
        header_principal = auth_registry.authenticate_authorization(
            request.headers.get("authorization")
        )
        if request.url.path.startswith("/api/v1/media/"):
            principal = header_principal
        else:
            principal = cookie_principal or header_principal
        context_token = auth_registry.bind(principal) if principal else None
        try:
            if (
                request.url.path in _PROTECTED_PAGES
                and principal is None
                and auth_registry.multi_user_enabled
            ):
                destination = quote(request.url.path, safe="/")
                return RedirectResponse(f"/login?next={destination}", status_code=303)
            if request.url.path.startswith("/v1/preview/") and principal is None:
                return JSONResponse({"detail": "unauthorized"}, status_code=401)
            request.state.user = principal
            return await call_next(request)
        finally:
            if context_token is not None:
                auth_registry.reset(context_token)
