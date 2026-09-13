"""
Shared FastAPI dependencies: current-user resolution and role-based access gates.

`require_role` is a dependency *factory* — each endpoint declares the minimum
role it needs, and the check happens before the endpoint body runs at all,
so RBAC can never be forgotten inline in business logic.
"""
import uuid
from typing import Iterable

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthenticationError, AuthorizationError
from app.core.security import decode_access_token
from app.db.models.user import Role, User
from app.db.session import get_db

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)

# Roles are ordered by privilege so require_role(Role.SRE) also admits Role.ADMIN.
_ROLE_RANK = {Role.VIEWER: 0, Role.SRE: 1, Role.ADMIN: 2}


async def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if token is None:
        raise AuthenticationError("Missing authentication token")

    payload = decode_access_token(token)
    raw_user_id = payload.get("sub")
    if raw_user_id is None:
        raise AuthenticationError("Malformed authentication token")

    try:
        user_id = uuid.UUID(raw_user_id)
    except (ValueError, AttributeError):
        raise AuthenticationError("Malformed authentication token")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise AuthenticationError("User not found or inactive")
    return user


def require_role(minimum_role: Role):
    async def _dependency(user: User = Depends(get_current_user)) -> User:
        if _ROLE_RANK[user.role] < _ROLE_RANK[minimum_role]:
            raise AuthorizationError(
                f"This action requires at least '{minimum_role.value}' role",
                details={"user_role": user.role.value, "required_role": minimum_role.value},
            )
        return user
    return _dependency
