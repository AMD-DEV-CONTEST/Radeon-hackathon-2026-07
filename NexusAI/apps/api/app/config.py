from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    nexus_env: str = "development"
    nexus_allowed_origins: str = "http://localhost:3000"
    database_url: str = "sqlite:///./nexusai.db"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def allowed_origins(self) -> list[str]:
        return [x.strip() for x in self.nexus_allowed_origins.split(",") if x.strip()]

settings = Settings()
