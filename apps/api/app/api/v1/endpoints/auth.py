"""
认证相关API - 完整实现
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy.orm import Session
from datetime import datetime, timedelta, timezone
import uuid
import re
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.security import (
    verify_password,
    get_password_hash,
    create_access_token,
    decode_access_token,
)
from app.api.deps import get_db
from app.models.user import User
from app.models.audit import AuditLog
from app.services.entitlement_service import effective_tier, entitlements_for_user

router = APIRouter()
security = HTTPBearer()
limiter = Limiter(key_func=get_remote_address)


def make_aware(dt: datetime) -> datetime:
    """将naive datetime转换为aware datetime（UTC）"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


class LoginRequest(BaseModel):
    """登录请求"""
    email: str
    password: str


class RegisterRequest(BaseModel):
    """注册请求"""
    username: str
    email: EmailStr
    password: str

    @field_validator('password')
    @classmethod
    def validate_password(cls, v):
        """验证密码强度"""
        if len(v) < 8:
            raise ValueError('密码至少需要8个字符')
        if len(v.encode('utf-8')) > 72:
            raise ValueError('密码不能超过72字节')
        if not re.search(r'[A-Za-z]', v):
            raise ValueError('密码必须包含字母')
        if not re.search(r'\d', v):
            raise ValueError('密码必须包含数字')
        return v

    @field_validator('username')
    @classmethod
    def validate_username(cls, v):
        """验证用户名格式"""
        if not re.match(r'^[a-zA-Z0-9_]{3,20}$', v):
            raise ValueError('用户名只能包含字母、数字和下划线，长度3-20个字符')
        return v


class TokenResponse(BaseModel):
    """Token响应"""
    access_token: str
    token_type: str = "bearer"


class EntitlementsResponse(BaseModel):
    tier: str
    display_name: str
    tier_expires_at: str | None = None
    limits: dict


class UserResponse(BaseModel):
    """用户响应"""
    id: str
    username: str
    email: str
    role: str
    permissions: list
    is_active: bool
    subscription_tier: str = "free"
    tier_expires_at: str | None = None
    entitlements: EntitlementsResponse | None = None


def create_audit_log(
    db: Session,
    user_id: str | None,
    action: str,
    result: str,
    ip_address: str | None = None,
    error_message: str | None = None
):
    """创建审计日志"""
    audit_log = AuditLog(
        id=uuid.uuid4(),  # Generate UUID for SQLite compatibility
        user_id=uuid.UUID(user_id) if user_id else None,
        action=action,
        result=result,
        ip_address=ip_address,
        error_message=error_message,
    )
    db.add(audit_log)
    db.commit()


@router.post("/register", response_model=TokenResponse)
@limiter.limit("3/hour")  # 每小时最多3次注册尝试
async def register(
    reg_request: RegisterRequest,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    用户注册

    - **username**: 用户名（唯一）
    - **email**: 邮箱（唯一）
    - **password**: 密码（至少8位，包含字母和数字）
    """
    # 检查用户名是否已存在
    existing_user = db.query(User).filter(User.username == reg_request.username).first()
    if existing_user:
        create_audit_log(
            db, None, "auth:register", "failure",
            request.client.host if request.client else None, "用户名已存在"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="用户名已存在"
        )

    # 检查邮箱是否已存在
    existing_email = db.query(User).filter(User.email == reg_request.email).first()
    if existing_email:
        create_audit_log(
            db, None, "auth:register", "failure",
            request.client.host if request.client else None, "邮箱已被注册"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="邮箱已被注册"
        )

    # 创建新用户
    password_hash = get_password_hash(reg_request.password)
    new_user = User(
        id=uuid.uuid4(),  # Generate UUID for SQLite compatibility
        username=reg_request.username,
        email=reg_request.email,
        password_hash=password_hash,
        role="user",
        permissions=["robot:view", "data:read"],  # 默认权限
        is_active=True,
        subscription_tier="pro",  # beta: full access without payment flow
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    # 创建审计日志
    create_audit_log(
        db, str(new_user.id), "auth:register", "success",
        request.client.host if request.client else None
    )

    # 创建token
    access_token = create_access_token(
        data={
            "sub": str(new_user.id),
            "email": new_user.email,
            "permissions": new_user.permissions,
            "tier": effective_tier(new_user),
        }
    )

    return TokenResponse(access_token=access_token)


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")  # 每分钟最多5次登录尝试
async def login(
    login_request: LoginRequest,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    用户登录

    - **email**: 用户邮箱
    - **password**: 密码
    """
    identifier = login_request.email.strip()
    # 兼容「邮箱登录」和「用户名登录」：前端暂仍传 email 字段名
    if "@" in identifier:
        user = db.query(User).filter(User.email == identifier).first()
    else:
        user = db.query(User).filter(User.username == identifier).first()

    if not user:
        create_audit_log(
            db, None, "auth:login", "failure",
            request.client.host if request.client else None, "用户不存在"
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="邮箱或密码错误"
        )

    # 检查账户是否被锁定
    locked_until = make_aware(user.account_locked_until)
    if locked_until and locked_until > datetime.now(timezone.utc):
        create_audit_log(
            db, str(user.id), "auth:login", "denied",
            request.client.host if request.client else None, "账户已被锁定"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账户已被锁定，请稍后再试"
        )

    # 验证密码
    if not verify_password(login_request.password, user.password_hash):
        # 增加失败次数
        user.failed_login_attempts += 1

        # 如果失败次数超过5次，锁定账户30分钟
        if user.failed_login_attempts >= 5:
            from datetime import timedelta
            user.account_locked_until = datetime.now(timezone.utc) + timedelta(minutes=30)

        db.commit()

        create_audit_log(
            db, str(user.id), "auth:login", "failure",
            request.client.host if request.client else None, "密码错误"
        )

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="邮箱或密码错误"
        )

    # 检查账户是否激活
    if not user.is_active:
        create_audit_log(
            db, str(user.id), "auth:login", "denied",
            request.client.host if request.client else None, "账户未激活"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账户未激活"
        )

    # 登录成功，重置失败次数
    user.failed_login_attempts = 0
    user.last_login = datetime.now(timezone.utc)
    db.commit()

    # 创建审计日志
    create_audit_log(
        db, str(user.id), "auth:login", "success",
        request.client.host if request.client else None
    )

    # 创建token
    access_token = create_access_token(
        data={
            "sub": str(user.id),
            "email": user.email,
            "permissions": user.permissions,
            "tier": effective_tier(user),
        }
    )

    return TokenResponse(access_token=access_token)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    """获取当前用户（依赖注入）"""
    token = credentials.credentials
    payload = decode_access_token(token)

    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的认证凭证",
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的认证凭证",
        )

    # 从数据库获取用户
    user = db.query(User).filter(User.id == uuid.UUID(user_id)).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账户未激活",
        )

    return user


def _user_response(user: User) -> UserResponse:
    ent = entitlements_for_user(user)
    return UserResponse(
        id=str(user.id),
        username=user.username,
        email=user.email,
        role=user.role,
        permissions=user.permissions,
        is_active=user.is_active,
        subscription_tier=ent["tier"],
        tier_expires_at=ent.get("tier_expires_at"),
        entitlements=EntitlementsResponse(**ent),
    )


@router.get("/me", response_model=UserResponse)
async def get_my_info(current_user: User = Depends(get_current_user)):
    """
    获取当前用户信息（含订阅 tier 与 entitlements）
    """
    return _user_response(current_user)


@router.get("/plans")
async def list_plans() -> dict:
    """Public plan catalog for pricing UI."""
    from app.services.entitlement_service import get_plan_limits

    def _limits_dict(limits) -> dict:
        return {
            "storage_bytes": limits.storage_bytes,
            "training_local_monthly": limits.training_local_monthly,
            "training_qualia_monthly": limits.training_qualia_monthly,
            "training_concurrent_max": limits.training_concurrent_max,
            "skill_runs_monthly": limits.skill_runs_monthly,
            "inference_priority": limits.inference_priority,
            "qualia_max_hours": limits.qualia_max_hours,
            "workflow_nodes": sorted(limits.workflow_nodes),
            "verbs": sorted(limits.verbs),
            "can_publish_paid_skills": limits.can_publish_paid_skills,
            "commercial_license": limits.commercial_license,
            "batch_jobs": limits.batch_jobs,
            "show_legacy_workflow_nodes": limits.show_legacy_workflow_nodes,
        }

    tiers = ("free", "pro", "creator")
    return {
        "plans": [
            {
                "tier": t,
                "display_name": get_plan_limits(t).display_name,
                "limits": _limits_dict(get_plan_limits(t)),
            }
            for t in tiers
        ],
        "pricing": {
            "pro_usd_monthly": 9,
            "pro_cny_monthly": 68,
            "creator_cny_monthly": 128,
        },
    }
