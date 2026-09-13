"""
Auth service — the only place password verification, user lookup, and token
issuance are wired together. Endpoints call this; they never touch the DB
or JWT logic directly, keeping the API layer thin and testable.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthenticationError, ConflictError
from app.core.security import create_access_token, hash_password, verify_password
from app.db.models.user import User
from app.schemas.auth import Token, UserCreate, UserOut


async def register_user(db: AsyncSession, payload: UserCreate) -> User:
    existing = await db.execute(select(User).where(User.email == payload.email))
    if existing.scalar_one_or_none() is not None:
        raise ConflictError(f"A user with email {payload.email} already exists")

    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        role=payload.role,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


async def authenticate_user(db: AsyncSession, email: str, password: str) -> User:
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(password, user.hashed_password):
        raise AuthenticationError("Incorrect email or password")
    if not user.is_active:
        raise AuthenticationError("This account has been deactivated")
    return user


def issue_token_for_user(user: User) -> Token:
    access_token = create_access_token(subject=str(user.id), extra_claims={"role": user.role.value})
    return Token(access_token=access_token, user=UserOut.model_validate(user))
