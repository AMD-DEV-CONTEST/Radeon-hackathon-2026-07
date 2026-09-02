"""Authentication and authorization FastAPI dependencies.

Kept under ``api.auth`` so ``core`` does not import the API layer (avoids
``core ↔ api`` circular dependencies).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from api.auth.repository import AuthRepository
from core.exceptions import ForbiddenError, UnauthorizedError
from core.security import decode_access_token
from db.database import get_db
from models.enums import UserRole
from models.user import User

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    """Resolve the authenticated user from a Bearer access token."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise UnauthorizedError(
            "Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_access_token(credentials.credentials)
    if payload is None:
        raise UnauthorizedError(
            "Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    subject = payload.get("sub")
    if subject is None:
        raise UnauthorizedError(
            "Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_id = UUID(str(subject))
    except ValueError as exc:
        raise UnauthorizedError(
            "Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user = AuthRepository(db).get_user_by_id(user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError(
            "Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def get_current_active_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Ensure the authenticated user is active."""
    if not current_user.is_active:
        raise ForbiddenError("Inactive user")
    return current_user


def require_roles(*roles: UserRole) -> Callable[[User], User]:
    """Dependency factory that enforces one of the allowed roles."""

    allowed = set(roles)

    def _checker(
        current_user: Annotated[User, Depends(get_current_active_user)],
    ) -> User:
        user_role = (
            current_user.role
            if isinstance(current_user.role, UserRole)
            else UserRole(str(current_user.role))
        )
        if user_role not in allowed:
            raise ForbiddenError("Insufficient permissions")
        return current_user

    return _checker


CurrentUser = Annotated[User, Depends(get_current_active_user)]
AdminUser = Annotated[User, Depends(require_roles(UserRole.ADMIN))]
RecruiterUser = Annotated[
    User,
    Depends(require_roles(UserRole.ADMIN, UserRole.RECRUITER)),
]
