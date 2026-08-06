"""
审计日志模型 (M0 sqlite 兼容版)

- UUIDType 透明桥接 uuid.UUID <-> 存储字符串
- INET -> String(45) (IPv6 足够)
- JSONB -> JSON (通用)
- TODO(M2): 切 postgres 时仍兼容
"""
from sqlalchemy import Column, String, TIMESTAMP, JSON
from datetime import datetime

from app.models.database import Base, UUIDType


class AuditLog(Base):
    """审计日志表（不可篡改）"""
    __tablename__ = "audit_logs"

    id = Column(UUIDType, primary_key=True)
    timestamp = Column(TIMESTAMP(timezone=True), default=datetime.utcnow, nullable=False, index=True)

    user_id = Column(UUIDType, nullable=True, index=True)
    username = Column(String(50), nullable=True)
    ip_address = Column(String(45), nullable=True)

    action = Column(String(100), nullable=False, index=True)
    resource_type = Column(String(50), nullable=True)
    resource_id = Column(UUIDType, nullable=True)

    result = Column(String(20), nullable=True)
    error_message = Column(String, nullable=True)

    extra_data = Column(JSON, nullable=True)

    def __repr__(self):
        return f"<AuditLog(id={self.id}, action={self.action}, result={self.result})>"
