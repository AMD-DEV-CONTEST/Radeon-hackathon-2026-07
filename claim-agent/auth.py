# -*- coding: utf-8 -*-
"""
auth.py — 共享鉴权模块（JWT 签发与校验）

被理赔后端（backend/main.py, 8001）与核保后端（underwriting/backend.py, 8002）
共同复用。两个服务使用同一份 config.AUTH_SECRET_KEY 签发 token，因此单一账号
跨两个服务通用（统一鉴权）。

设计要点（demo 最小化）：
- 密码用 sha256(salt + password)（标准库 hashlib），不引入 passlib/bcrypt，
  零新编译依赖、Windows 无风险。答辩可主动说明"生产应换 bcrypt/argon2"。
- verify_token 内置 AUTH_DISABLED 短路：cfg.AUTH_DISABLED=True 时直接放行，
  作为最高优先级回退开关（答辩前可一行环境变量降级）。
- token payload: {sub: username, iat: now, exp: now + AUTH_TOKEN_EXPIRE_HOURS}。
"""

import hashlib
import hmac
import time

import jwt
from fastapi import Header, HTTPException

import config as cfg


# ---------------------------------------------------------------------------- #
# 密码哈希（sha256 + 固定 salt）
# ---------------------------------------------------------------------------- #
def _hash_password(password: str) -> str:
    """sha256(salt + password) → hex。salt 从 cfg.AUTH_PASSWORD_SALT 读。"""
    raw = (cfg.AUTH_PASSWORD_SALT + password).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def verify_password(plain: str, hashed: str) -> bool:
    """常量时间比较，避免计时侧信道。"""
    return hmac.compare_digest(_hash_password(plain), hashed)


# 启动时预计算配置密码的哈希，避免每次登录重复计算
_PASSWORD_HASH = _hash_password(cfg.AUTH_PASSWORD)


# ---------------------------------------------------------------------------- #
# JWT 签发与校验
# ---------------------------------------------------------------------------- #
def create_access_token(username: str):
    """签发 JWT，返回 (token, expires_in_seconds)。"""
    now = int(time.time())
    expires_in = cfg.AUTH_TOKEN_EXPIRE_HOURS * 3600
    payload = {
        "sub": username,
        "iat": now,
        "exp": now + expires_in,
    }
    token = jwt.encode(payload, cfg.AUTH_SECRET_KEY, algorithm="HS256")
    # PyJWT 2.x 已返回 str；兼容旧版返回 bytes 的情况
    if isinstance(token, bytes):
        token = token.decode("utf-8")
    return token, expires_in


def verify_token(authorization: str = Header(None, alias="Authorization")) -> str:
    """FastAPI 依赖：校验 ``Authorization: Bearer <jwt>``。

    - cfg.AUTH_DISABLED=True → 直接放行，返回 "demo"（回退开关）。
    - 成功 → 返回 username（payload.sub）。
    - 失败 → 抛 401（缺头 / 格式错 / 签名错 / 过期）。
    """
    # 回退开关：一键禁用全部鉴权
    if cfg.AUTH_DISABLED:
        return "demo"

    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    # 期望格式: Bearer <token>
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid Authorization header format, expected 'Bearer <token>'")

    token = parts[1]
    try:
        payload = jwt.decode(token, cfg.AUTH_SECRET_KEY, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired, please log in again")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

    username = payload.get("sub") or ""
    if not username:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    return username


def authenticate(username: str, password: str) -> bool:
    """校验用户名密码。demo 单一账号，对比 cfg.AUTH_USERNAME + 预计算哈希。"""
    if username != cfg.AUTH_USERNAME:
        return False
    return verify_password(password, _PASSWORD_HASH)
