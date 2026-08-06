from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "3DGenerateFlow API"
    app_debug: bool = True

    database_url: str = "sqlite:///./data/dev.db"
    upload_dir: Path = Path("./uploads")
    result_dir: Path = Path("./results")

    celery_broker_url: str = "redis://redis:6379/0"
    celery_result_backend: str = "redis://redis:6379/0"

    # Model provider credentials / selectors
    threed_provider_priority: str = "tripo,meshy,rodin"
    tripo_api_key: str = ""
    meshy_api_key: str = ""
    rodin_api_key: str = ""
    replicate_api_token: str = ""
    stability_api_key: str = ""

    # LLM / Agent
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    llm_mock_mode: bool = False
    agent_max_steps: int = 10

    cors_origins: str = "http://localhost:5173,http://localhost:3000"


settings = Settings()
