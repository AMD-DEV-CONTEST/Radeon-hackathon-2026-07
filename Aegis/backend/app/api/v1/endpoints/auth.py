from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.auth import Token, UserCreate, UserLogin, UserOut
from app.services.auth_service import authenticate_user, issue_token_for_user, register_user

router = APIRouter()


@router.post("/register", response_model=UserOut, status_code=201)
async def register(payload: UserCreate, db: AsyncSession = Depends(get_db)) -> UserOut:
    user = await register_user(db, payload)
    return UserOut.model_validate(user)


@router.post("/login", response_model=Token)
async def login(payload: UserLogin, db: AsyncSession = Depends(get_db)) -> Token:
    user = await authenticate_user(db, payload.email, payload.password)
    return issue_token_for_user(user)


@router.get("/me", response_model=UserOut)
async def me(current_user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(current_user)
