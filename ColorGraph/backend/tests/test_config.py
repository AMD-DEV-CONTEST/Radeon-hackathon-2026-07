from __future__ import annotations

from pathlib import Path

from colorgraph.config import Settings


def test_huggingface_cache_can_use_local_redirect(
    tmp_path: Path,
    monkeypatch,
) -> None:
    models = tmp_path / "models"
    models.mkdir()
    redirected = tmp_path / "large-model-cache"
    (models / "huggingface.redirect").write_text(
        str(redirected),
        encoding="utf-8",
    )
    monkeypatch.setenv("COLORGRAPH_MODELS_DIR", str(models))
    monkeypatch.delenv(
        "COLORGRAPH_HUGGINGFACE_CACHE_DIR",
        raising=False,
    )

    loaded = Settings.from_environment()

    assert loaded.models_dir == models.resolve()
    assert loaded.huggingface_cache_dir == redirected.resolve()


def test_huggingface_cache_environment_overrides_redirect(
    tmp_path: Path,
    monkeypatch,
) -> None:
    models = tmp_path / "models"
    models.mkdir()
    redirected = tmp_path / "redirected"
    explicit = tmp_path / "explicit"
    (models / "huggingface.redirect").write_text(
        str(redirected),
        encoding="utf-8",
    )
    monkeypatch.setenv("COLORGRAPH_MODELS_DIR", str(models))
    monkeypatch.setenv(
        "COLORGRAPH_HUGGINGFACE_CACHE_DIR",
        str(explicit),
    )

    loaded = Settings.from_environment()

    assert loaded.huggingface_cache_dir == explicit.resolve()
