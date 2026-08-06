import pytest

from backend.config import Settings
from backend.main import create_app


@pytest.fixture
def settings() -> Settings:
    return Settings(command_backend="fake")


@pytest.fixture
def app(settings: Settings):
    return create_app(settings)
