from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_defaults_are_valid() -> None:
    settings = Settings(_env_file=None)

    assert str(settings.llm_base_url).rstrip("/").endswith("/v1")
    assert str(settings.embedding_base_url).rstrip("/").endswith("/v1")
    assert settings.agent_max_steps == 8
    assert settings.llm_timeout_seconds == 90
    assert settings.llm_max_tokens == 384


def test_rejects_invalid_api_port() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, api_port=70000)


def test_rejects_embedding_url_without_v1_suffix() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, embedding_base_url="http://127.0.0.1:8080")


def test_rejects_empty_model_name() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, llm_model="")


def test_collects_required_directories() -> None:
    settings = Settings(
        _env_file=None,
        project_root=Path("/tmp/projects"),
        vector_db_root=Path("/tmp/vector-db"),
        sqlite_path=Path("/tmp/sqlite/projectpack.db"),
        output_root=Path("/tmp/outputs"),
        log_root=Path("/tmp/logs"),
    )

    assert Path("/tmp/sqlite") in settings.required_directories()
