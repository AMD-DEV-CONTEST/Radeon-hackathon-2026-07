"""
用户模型 (M0 sqlite 兼容版)

- UUIDType: 跨方言 UUID (见 database.UUIDType), app 代码仍可传 uuid.UUID 对象
- JSONB -> JSON (通用)
- TODO(M2): 切 postgres 时 UUIDType 可以保留 (向后兼容) 或换为 postgresql.UUID
"""
from sqlalchemy import Column, String, Boolean, Integer, TIMESTAMP, JSON
from datetime import datetime

from app.models.database import Base, UUIDType


class User(Base):
    """用户表"""
    __tablename__ = "users"

    id = Column(UUIDType, primary_key=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(100), unique=True, nullable=False, index=True)

    # 安全字段
    password_hash = Column(String(255), nullable=False)
    hf_token_encrypted = Column(String, nullable=True)
    mfa_secret = Column(String(32), nullable=True)

    # 权限和状态
    role = Column(String(20), default="user", nullable=False)
    permissions = Column(JSON, default=list, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    # Subscription (Phase 1+)
    subscription_tier = Column(String(32), default="free", nullable=False)
    tier_expires_at = Column(TIMESTAMP(timezone=True), nullable=True)
    stripe_customer_id = Column(String(128), nullable=True)

    # 安全审计
    failed_login_attempts = Column(Integer, default=0, nullable=False)
    account_locked_until = Column(TIMESTAMP(timezone=True), nullable=True)
    last_login = Column(TIMESTAMP(timezone=True), nullable=True)
    last_password_change = Column(TIMESTAMP(timezone=True), default=datetime.utcnow, nullable=False)

    created_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<User(id={self.id}, username={self.username}, email={self.email})>"
