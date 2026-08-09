"""Authentication router — JSON login (not form-data)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from passlib.hash import pbkdf2_sha256 as hasher
from pydantic import BaseModel
from ..database import get_db
from ..models import User
from ..security.jwt import create_token

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == body.username).first()
    if not user or not hasher.verify(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    token = create_token(user.username, user.role, user.display_name or user.username)
    return {
        "token": token,
        "username": user.username,
        "displayName": user.display_name or user.username,
        "role": user.role,
    }
