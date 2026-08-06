# character-workshop/tests/test_model_paths.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.model_paths import (
    has_local_image,
    has_local_llm,
    local_image_dir,
    local_llm_dir,
)
from src.paths import MODELS


def test_local_dirs_under_models():
    assert local_llm_dir() == MODELS / "llm"
    assert local_image_dir() == MODELS / "image"


def test_has_local_returns_bool():
    assert isinstance(has_local_llm(), bool)
    assert isinstance(has_local_image(), bool)


def test_false_when_dir_absent(tmp_path, monkeypatch):
    monkeypatch.setattr("src.model_paths.MODELS", tmp_path / "models")
    assert has_local_llm() is False
    assert has_local_image() is False
