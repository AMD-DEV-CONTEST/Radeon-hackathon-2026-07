from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field

from glass_gateway.auth import auth_registry


router = APIRouter(prefix="/v1/auth")


class LoginRequest(BaseModel):
    token: str = Field(min_length=1, max_length=512)


@router.post("/login")
async def login(request: LoginRequest, response: Response) -> dict[str, object]:
    principal = auth_registry.authenticate_token(request.token)
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="token 无效",
        )
    response.set_cookie(
        key=auth_registry.settings.auth_cookie_name,
        value=principal.token_digest,
        max_age=30 * 24 * 60 * 60,
        httponly=True,
        secure=auth_registry.settings.auth_cookie_secure,
        samesite="lax",
        path="/",
    )
    return {
        "status": "ok",
        "user": {
            "user_id": principal.user_id,
            "display_name": principal.display_name,
        },
    }


@router.post("/logout")
async def logout(response: Response) -> dict[str, str]:
    response.delete_cookie(
        auth_registry.settings.auth_cookie_name,
        path="/",
        samesite="lax",
    )
    return {"status": "ok"}


@router.get("/me")
async def me() -> dict[str, object]:
    principal = auth_registry.current_principal()
    if principal is None:
        raise HTTPException(status_code=401, detail="not logged in")
    return {
        "user": {
            "user_id": principal.user_id,
            "display_name": principal.display_name,
        }
    }
