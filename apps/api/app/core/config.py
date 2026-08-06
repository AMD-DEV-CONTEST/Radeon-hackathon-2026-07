"""
核心配置模块 (M0 精简版)

M0 阶段 — 所有外部服务 URL 可选, 默认本地 sqlite.
M2 阶段恢复 Postgres / Timescale / Redis / MinIO 时, 移除默认值即可.
"""
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置"""

    # 项目信息
    PROJECT_NAME: str = "BotverseX Platform API"
    API_V1_PREFIX: str = "/api/v1"

    # 数据库配置 — M0 默认 sqlite, M2 切 Postgres
    DATABASE_URL: str = "sqlite:///./botversex_dev.db"
    TIMESCALE_URL: str = "sqlite:///./botversex_timeseries_dev.db"  # M0 stub, 不实际使用

    # Redis / MinIO — M0 阶段不启外部服务, 给空壳默认值避免 pydantic 校验失败
    # TODO(M2): 切换到真实 URL 并恢复 startup 健康检查
    REDIS_URL: str = "redis://localhost:6379/0"
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_SECURE: bool = False

    # 安全配置 — M0 用开发用固定值, 部署前替换
    ENCRYPTION_KEY: str = "8Be4BbRe8qpLdzb9MtNziKBSsvrModgEPr9LqktiA9A="  # dev Fernet key, 必须合法 base64
    JWT_SECRET: str = "dev-jwt-secret-change-in-production-min-32-chars"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 1440

    # CORS — 允许 Vite dev (:5173) 和生产前端
    BACKEND_CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://botversex.feispace.me",
        "https://botversex.feispace.me",
        "http://botversex.achao.xin",
        "https://botversex.achao.xin",
    ]

    # apps/realtime 地址, M1.6 的 record proxy 会用
    REALTIME_SERVICE_URL: str = "http://127.0.0.1:8002"

    # M2: 数据集 parquet 存储根. 默认指向 apps/realtime/datasets/
    # 开发机跨仓路径按 __file__ 推导, 方便无 env 直接跑.
    DATASETS_STORAGE_ROOT: str = ""  # 空串时由 models/dataset_service.py 推导默认值

    # M3: 模型 checkpoint 存储根. 默认 apps/realtime/models/
    MODELS_STORAGE_ROOT: str = ""
    TRAINING_LOGS_ROOT: str = ""

    # BotverseX Copilot LLM provider
    COPILOT_PROVIDER: str = "disabled"
    COPILOT_MODEL: str = ""
    COPILOT_API_KEY: str = ""
    COPILOT_BASE_URL: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()
