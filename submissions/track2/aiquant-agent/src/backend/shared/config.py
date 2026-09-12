"""
aiquant 全局配置 — 支持多模型统一管理
"""
import os
import json
from pathlib import Path
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """系统全局配置"""
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 项目路径
    project_root: Path = PROJECT_ROOT
    db_dir: Path = PROJECT_ROOT / "db" / "qlib_data"
    memory_dir: Path = PROJECT_ROOT / "db" / "memory"
    log_dir: Path = PROJECT_ROOT / "logs"
    config_dir: Path = PROJECT_ROOT / "config"

    # LLM 配置（主模型）
    llm_provider: str = "deepseek"
    llm_model: str = "deepseek-v4-flash"
    llm_api_key: str = Field(default="", validation_alias="OPENAI_API_KEY")
    llm_api_base: str = Field(default="https://api.deepseek.com/v1", validation_alias="OPENAI_API_BASE")

    # 多模型配置（JSON 文件存储）
    model_configs_file: Path = PROJECT_ROOT / "config" / "model_configs.json"

    # 服务端口
    api_port: int = 8010
    engine_port: int = 8001  # OpenBB 数据服务
    trade_port: int = 8002   # TradingAgents
    robot_port: int = 8003   # 对话机器人
    research_port: int = 8004  # RD-Agent

    # 数据库
    db_url: str = f"sqlite:///{PROJECT_ROOT}/db/aiquant.db"

    # A股市场配置
    market_start_date: str = "2015-01-01"
    market_benchmark: str = "000300.SH"  # 沪深300

    # 回测配置
    backtest_start: str = "2020-01-01"
    backtest_end: str = "2024-12-31"


settings = Settings()
os.makedirs(settings.log_dir, exist_ok=True)
os.makedirs(settings.db_dir, exist_ok=True)
os.makedirs(settings.memory_dir, exist_ok=True)
os.makedirs(settings.config_dir, exist_ok=True)


# ═══════════════════════════════════════════════════════════════
# 多模型配置管理
# ═══════════════════════════════════════════════════════════════

DEFAULT_MODEL_CONFIGS = {
    "deepseek": {
        "provider": "deepseek",
        "display_name": "DeepSeek",
        "api_key": "",
        "api_base": "https://api.deepseek.com/v1",
        "model": "deepseek-v4-flash",
        "temperature": 0.7,
        "max_context": 65536,
        "max_tokens": 4096,
        "enabled": True,
        "description": "DeepSeek 大模型，性价比高，中文能力强",
    },
    "openai": {
        "provider": "openai",
        "display_name": "OpenAI",
        "api_key": "",
        "api_base": "https://api.openai.com/v1",
        "model": "gpt-4o",
        "temperature": 0.7,
        "max_context": 128000,
        "max_tokens": 4096,
        "enabled": False,
        "description": "OpenAI GPT 系列模型（后期解锁）",
    },
    "qwen": {
        "provider": "qwen",
        "display_name": "通义千问",
        "api_key": "",
        "api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-max",
        "temperature": 0.7,
        "max_context": 32768,
        "max_tokens": 4096,
        "enabled": False,
        "description": "阿里通义千问模型（后期解锁）",
    },
}


def load_model_configs() -> dict:
    """加载多模型配置文件"""
    config_file = settings.model_configs_file
    if config_file.exists():
        try:
            with open(config_file, "r") as f:
                configs = json.load(f)
            # 合并默认配置（保证新字段存在）
            for key, default in DEFAULT_MODEL_CONFIGS.items():
                if key not in configs:
                    configs[key] = default
                else:
                    for k, v in default.items():
                        if k not in configs[key]:
                            configs[key][k] = v
            return configs
        except Exception:
            pass
    return dict(DEFAULT_MODEL_CONFIGS)


def save_model_configs(configs: dict):
    """保存多模型配置到文件"""
    config_file = settings.model_configs_file
    config_file.parent.mkdir(parents=True, exist_ok=True)
    with open(config_file, "w") as f:
        json.dump(configs, f, ensure_ascii=False, indent=2)


def get_active_model_config() -> dict:
    """获取当前激活的模型配置"""
    configs = load_model_configs()
    provider = settings.llm_provider
    if provider in configs and configs[provider].get("enabled", False):
        return configs[provider]
    # fallback 到 deepseek
    return configs.get("deepseek", DEFAULT_MODEL_CONFIGS["deepseek"])


def sync_config_to_services():
    """
    同步模型配置到各微服务的 .env 文件。
    RD-Agent、机器人服务读取各自 .env，无需手动修改。
    """
    configs = load_model_configs()
    active = get_active_model_config()

    # 写入机器人服务 .env
    robot_env = Path(os.path.expanduser("~/quant_system/robot_service/.env"))
    robot_env.parent.mkdir(parents=True, exist_ok=True)
    robot_content = f"""# env-robot 对话机器人配置（由 aiQuant 自动同步）
OPENAI_API_KEY={active.get('api_key', '')}
OPENAI_API_BASE={active.get('api_base', 'https://api.deepseek.com/v1')}
LLM_MODEL={active.get('model', 'deepseek-v4-flash')}
LLM_PROVIDER={active.get('provider', 'deepseek')}
ROBOT_PORT=8003
REDIS_HOST={os.environ.get("AIQUANT_REDIS_HOST", "127.0.0.1")}
REDIS_PORT=6379
"""
    with open(robot_env, "w") as f:
        f.write(robot_content)
    os.chmod(robot_env, 0o600)

    # 更新项目 .env 中的 LLM 配置
    project_env = settings.project_root / ".env"
    if project_env.exists():
        with open(project_env, "r") as f:
            content = f.read()
        import re
        content = re.sub(r'OPENAI_API_KEY=.*', f'OPENAI_API_KEY={active.get("api_key", "")}', content)
        content = re.sub(r'OPENAI_API_BASE=.*', f'OPENAI_API_BASE={active.get("api_base", "https://api.deepseek.com/v1")}', content)
        content = re.sub(r'LLM_MODEL=.*', f'LLM_MODEL={active.get("model", "deepseek-v4-flash")}', content)
        content = re.sub(r'LLM_PROVIDER=.*', f'LLM_PROVIDER={active.get("provider", "deepseek")}', content)
        with open(project_env, "w") as f:
            f.write(content)

    return {"robot_env": str(robot_env), "project_env": str(project_env)}

