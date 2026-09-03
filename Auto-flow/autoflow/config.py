"""AutoFlow 配置管理。

MVP 阶段优先通过环境变量注入，避免硬编码。
- 路径: 数据目录 (bundles / recordings / registry)
- LLM:  OpenAI 兼容接口 (base_url + api_key + model)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


class Settings:
    """集中管理 AutoFlow 配置。

    所有可配置项均支持环境变量覆盖，便于在不同环境切换。
    """

    def __init__(self) -> None:
        # 数据根目录
        root = os.environ.get("AUTOFLOW_HOME", str(Path.home() / ".autoflow"))
        self.data_dir = Path(root)

        # LLM 配置 (OpenAI 兼容接口)
        self.llm_base_url = os.environ.get("AUTOFLOW_LLM_BASE_URL", "https://api.openai.com/v1")
        self.llm_api_key = os.environ.get("AUTOFLOW_LLM_API_KEY", "")
        self.llm_model = os.environ.get("AUTOFLOW_LLM_MODEL", "gpt-4o-mini")

        # 首次执行策略
        self.computer_use_enabled = (
            os.environ.get("AUTOFLOW_COMPUTER_USE", "0") == "1"
        )
        # 录制 backend
        self.default_backend = os.environ.get("AUTOFLOW_BACKEND", "web")

        self.ensure_dirs()

    @property
    def bundles_dir(self) -> Path:
        return self.data_dir / "bundles"

    @property
    def recordings_dir(self) -> Path:
        return self.data_dir / "recordings"

    @property
    def registry_db(self) -> Path:
        return self.data_dir / "registry.json"

    @property
    def workflows_dir(self) -> Path:
        return self.data_dir / "workflows"

    def ensure_dirs(self) -> None:
        for d in (self.bundles_dir, self.recordings_dir, self.workflows_dir):
            d.mkdir(parents=True, exist_ok=True)


_settings: Settings | None = None


def get_settings() -> Settings:
    """全局单例设置。"""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
