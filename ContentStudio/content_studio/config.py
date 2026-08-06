"""配置加载与持久化。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

DEFAULT_CONFIG_PATH = Path.home() / ".content_studio" / "config.json"


@dataclass
class ProviderConfig:
    name: str
    base_url: str
    api_key: str = ""
    model: str = ""
    vision: bool = False   # 模型是否支持视觉（看图）。文本模型为 False，否则会给它发图导致报错


@dataclass
class ImageConfig:
    watermark_text: str = "@我的账号"
    crop_strategy: str = "crop"   # "crop" | "pad"
    jpeg_quality: int = 85
    collage: bool = False


@dataclass
class WeChatConfig:
    app_id: str = ""
    app_secret: str = ""
    publish_enabled: bool = False


@dataclass
class ComfyConfig:
    base_url: str = "http://127.0.0.1:8188"
    enabled: bool = True
    style_transfer: bool = True
    t2i_count: int = 1
    timeout: int = 180


@dataclass
class AppConfig:
    providers: list[ProviderConfig] = field(default_factory=list)
    active_provider: str = ""
    image: ImageConfig = field(default_factory=ImageConfig)
    ocr_enabled: bool = False
    wechat: WeChatConfig = field(default_factory=WeChatConfig)
    comfy: ComfyConfig = field(default_factory=ComfyConfig)


def default_config() -> AppConfig:
    return AppConfig(
        providers=[
            ProviderConfig(name="radeon", base_url="https://developer.amd.com.cn/radeon/api/v1", model="Qwen3.6-35B-A3B"),
            ProviderConfig(name="qwen", base_url="https://dashscope.aliyuncs.com/compatible-mode/v1", model="qwen-plus"),
            ProviderConfig(name="deepseek", base_url="https://api.deepseek.com/v1", model="deepseek-chat"),
            ProviderConfig(name="glm", base_url="https://open.bigmodel.cn/api/paas/v4", model="glm-4"),
            ProviderConfig(name="kimi", base_url="https://api.moonshot.cn/v1", model="moonshot-v1-8k"),
        ],
        active_provider="radeon",
    )


def save_config(cfg: AppConfig, path: Path = DEFAULT_CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(cfg), ensure_ascii=False, indent=2), encoding="utf-8")


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> AppConfig:
    if not path.exists():
        cfg = default_config()
        save_config(cfg, path)
        return cfg
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        providers = [ProviderConfig(**p) for p in data.get("providers", [])]
        image = ImageConfig(**data.get("image", {}))
        wechat = WeChatConfig(**data.get("wechat", {}))
        comfy = ComfyConfig(**data.get("comfy", {}))
        return AppConfig(
            providers=providers,
            active_provider=data.get("active_provider", ""),
            image=image,
            ocr_enabled=data.get("ocr_enabled", False),
            wechat=wechat,
            comfy=comfy,
        )
    except Exception as e:
        # 配置损坏（坏字节/非法 JSON/字段缺失）时回退默认值，保证能启动；
        # 不覆盖损坏文件，仅在日志里提示。
        import logging
        logging.getLogger(__name__).warning("配置文件解析失败，已回退默认配置：%s", e)
        return default_config()


def get_active_provider(cfg: AppConfig) -> ProviderConfig:
    for p in cfg.providers:
        if p.name == cfg.active_provider:
            return p
    if cfg.providers:
        return cfg.providers[0]
    raise ValueError("没有配置任何 provider")
