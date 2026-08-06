"""Tests for config loading."""

import pytest
from pathlib import Path

from src.config import Config, get_config, reset_config, Config as ConfigType


class TestConfig:
    def test_default_config(self):
        config = Config()
        assert config.server.host == "127.0.0.1"
        assert config.server.port == 8080
        assert config.llm.backend == "vllm"
        assert config.llm.max_model_len == 16384
        assert config.embedding.device == "cpu"
        assert config.reranker.device == "cuda"
        assert config.security.run_tests_enabled is False

    def test_from_yaml(self, tmp_path):
        yaml_content = """
server:
  host: "0.0.0.0"
  port: 9090
llm:
  backend: "llamacpp"
  max_model_len: 32768
"""
        config_path = tmp_path / "test_config.yaml"
        config_path.write_text(yaml_content)

        config = Config.from_yaml(config_path)
        assert config.server.host == "0.0.0.0"
        assert config.server.port == 9090
        assert config.llm.backend == "llamacpp"
        assert config.llm.max_model_len == 32768

    def test_missing_file_returns_defaults(self):
        config = Config.from_yaml("/nonexistent/path/config.yaml")
        assert config.server.host == "127.0.0.1"

    def test_get_config_singleton(self):
        reset_config()
        c1 = get_config()
        c2 = get_config()
        assert c1 is c2

    def test_apply_rocm_env(self):
        import os
        config = Config()
        config.apply_rocm_env()
        assert os.environ.get("PYTORCH_ROCM_ARCH") == "gfx1100"
        assert os.environ.get("HSA_ENABLE_SDMA") == "0"

    def test_repo_root_setter(self):
        config = Config()
        config.repo_root = "/some/path"
        assert str(config.repo_root) == "/some/path"
