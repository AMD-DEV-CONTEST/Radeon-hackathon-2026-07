from pathlib import Path

import pytest

from backend.config import Settings

pytestmark = [pytest.mark.rocm, pytest.mark.model_integration]


def test_test_media_manifest_schema_example_is_valid():
    import json

    manifest = json.loads(Path("tests/media/manifest.example.json").read_text())
    assert manifest["version"] == 1
    for item in manifest["samples"]:
        assert set(item) == {"path", "language", "expected_text", "license_source"}
        assert item["language"] in {"zh", "en"}


def test_real_command_mode_defaults_to_no_open_vocab_models():
    settings = Settings(command_backend="prototype")

    assert settings.command_backend == "prototype"
    assert not hasattr(settings, "minicpm_model_path")
