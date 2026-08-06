"""
数据库连接和会话管理 (M0 精简版)

M0 默认 sqlite, 不启用 Timescale. `get_timescale_db` 保留接口签名以便后续恢复.
"""
import uuid as _uuid
from sqlalchemy import create_engine, CHAR
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.types import TypeDecorator

from app.core.config import settings


class UUIDType(TypeDecorator):
    """跨方言 UUID 类型.

    - sqlite: 底层 CHAR(36), 透明转 uuid.UUID <-> str
    - M2 恢复 postgres: 可直接换回 postgresql.UUID 或用 UUID(as_uuid=True)
    """

    impl = CHAR(36)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, _uuid.UUID):
            return str(value)
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, _uuid.UUID):
            return value
        return _uuid.UUID(value)


def _make_engine(url: str):
    """根据 URL 生成 engine. sqlite 需要禁用线程检查."""
    connect_args = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        return create_engine(url, connect_args=connect_args)
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )


engine = _make_engine(settings.DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# M0 不启 Timescale, 复用主 engine 避免 import 错
timescale_engine = engine
TimescaleSessionLocal = SessionLocal

Base = declarative_base()


def get_db():
    """获取数据库会话（依赖注入）"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_timescale_db():
    """M0 stub — 与主 DB 同源, M2 恢复 Timescale."""
    db = TimescaleSessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """在应用启动时创建缺失的表 (M0 sqlite 友好)."""
    # 显式 import 所有模型, 确保被 Base.metadata 捕获
    from app.models import user as _user  # noqa: F401
    from app.models import audit as _audit  # noqa: F401
    from app.models import dataset as _dataset  # noqa: F401
    from app.models import training as _training  # noqa: F401
    from app.models import skill as _skill  # noqa: F401
    from app.models import usage_counter as _usage  # noqa: F401
    from app.models import skill_listing as _listing  # noqa: F401
    from app.models import subscription as _sub  # noqa: F401
    from app.models import copilot_playbook as _copilot_pb  # noqa: F401

    Base.metadata.create_all(bind=engine)

    # Seed Copilot playbooks on first boot.
    from app.services.copilot_playbook_service import seed_playbooks

    db_seed = SessionLocal()
    try:
        seed_playbooks(db_seed)
    finally:
        db_seed.close()

    # Production admin seed (created only if ethan does not exist).
    import uuid
    from app.core.security import get_password_hash
    from app.models.user import User

    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.username == "ethan").first()
        if not existing:
            user = User(
                id=uuid.uuid4(),
                username="ethan",
                email="yzc_2024@163.com",
                password_hash=get_password_hash("linux"),
                role="admin",
                permissions=["*"],
                is_active=True,
                subscription_tier="creator",
            )
            db.add(user)
            db.commit()

        # Temporary guest account for on-site demos (non-admin).
        guest = db.query(User).filter(User.username == "test").first()
        if not guest:
            db.add(
                User(
                    id=uuid.uuid4(),
                    username="test",
                    email="guest@botversex.dev",
                    password_hash=get_password_hash("test"),
                    role="user",
                    permissions=["robot:view", "data:read"],
                    is_active=True,
                    subscription_tier="pro",
                )
            )
            db.commit()
    finally:
        db.close()
