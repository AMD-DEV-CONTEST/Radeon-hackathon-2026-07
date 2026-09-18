import pytest

from radeon_sentinel.config import Settings


def test_openai_mode_requires_base_url() -> None:
    with pytest.raises(ValueError, match="MODEL_BASE_URL"):
        Settings(model_mode="openai", model_name="qwen").validate()


def test_mock_mode_needs_no_secret() -> None:
    Settings(model_mode="mock", model_api_key="").validate()
