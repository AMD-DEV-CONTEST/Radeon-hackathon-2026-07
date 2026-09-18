from pathlib import Path

import pytest

from buildguard.config import load_settings
from buildguard.exceptions import ConfigurationError


def test_yaml_loading(config_tree: Path) -> None:
    settings = load_settings(config_tree)
    assert settings.app.name == "TestGuard"
    assert settings.llm.model == "test-model"
    assert settings.safe_dump()["llm"]["api_key"] == "********"


def test_environment_override(config_tree: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BUILDGUARD_APP__SEED", "99")
    monkeypatch.setenv("BUILDGUARD_LLM__MODE", "local")
    monkeypatch.setenv("BUILDGUARD_APP__RETENTION__AUDIT_LOGS_DAYS", "12")
    settings = load_settings(config_tree)
    assert settings.app.seed == 99
    assert settings.llm.mode == "local"
    assert settings.app.retention.audit_logs_days == 12


def test_validation_error_is_clear(config_tree: Path) -> None:
    llm = config_tree.parent / "llm.yaml"
    llm.write_text("llm:\n  mode: invalid\n  endpoint: not-a-url\n", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="Invalid configuration"):
        load_settings(config_tree)


def test_competition_config_enforces_offline_rocm_and_real_models() -> None:
    settings = load_settings(Path("configs/competition/app.yaml"))

    assert settings.app.environment == "competition"
    assert settings.competition.offline_only is True
    assert settings.competition.require_rocm is True
    assert settings.llm.mode == "local"
    assert settings.rag.embedding_mode == "transformers"
    assert settings.rag.embedding_local_files_only is True
    assert settings.rag.reranker_mode == "transformers"
    assert settings.rag.reranker_local_files_only is True
    assert settings.monitoring.scheduler.allow_cpu_fallback is False
    assert all(model.backend != "mock" for model in settings.vision.models)
