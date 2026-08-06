"""
安全相关工具
"""
from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import JWTError, jwt
import bcrypt
from cryptography.fernet import Fernet

from app.core.config import settings

# 加密工具
cipher_suite = Fernet(settings.ENCRYPTION_KEY if isinstance(settings.ENCRYPTION_KEY, bytes) else settings.ENCRYPTION_KEY.encode())


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    if not plain_password or not hashed_password:
        return False

    password_bytes = plain_password.encode('utf-8')
    # bcrypt限制：密码最多72字节，超过则拒绝（与get_password_hash保持一致）
    if len(password_bytes) > 72:
        return False

    return bcrypt.checkpw(password_bytes, hashed_password.encode('utf-8'))


def get_password_hash(password: str) -> str:
    """生成密码哈希"""
    if not password:
        raise ValueError("Password cannot be empty")

    password_bytes = password.encode('utf-8')
    # bcrypt限制：密码最多72字节，超过则拒绝
    if len(password_bytes) > 72:
        raise ValueError("Password exceeds maximum length of 72 bytes")

    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode('utf-8')


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """创建JWT token"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM
    )
    return encoded_jwt


def decode_access_token(token: str) -> Optional[dict]:
    """解码JWT token"""
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
        )
        return payload
    except JWTError:
        return None


def encrypt_token(token: str) -> str:
    """加密token（用于存储HF Token等敏感信息）"""
    return cipher_suite.encrypt(token.encode()).decode()


def decrypt_token(encrypted_token: str) -> str:
    """解密token"""
    return cipher_suite.decrypt(encrypted_token.encode()).decode()
