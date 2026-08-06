from pathlib import Path
from content_studio.config import (
    AppConfig, ProviderConfig, ImageConfig, WeChatConfig,
    load_config, save_config, get_active_provider, default_config,
)


def test_default_config_has_two_providers_and_active():
    cfg = default_config()
    names = [p.name for p in cfg.providers]
    assert "radeon" in names and "qwen" in names and "deepseek" in names and "glm" in names and "kimi" in names
    assert cfg.active_provider == "radeon"
    assert isinstance(cfg.image, ImageConfig)
    assert isinstance(cfg.wechat, WeChatConfig)


def test_save_then_load_round_trip(tmp_path: Path):
    path = tmp_path / "config.json"
    cfg = default_config()
    cfg.active_provider = "glm"
    cfg.image.watermark_text = "@me"
    cfg.ocr_enabled = True
    save_config(cfg, path)
    loaded = load_config(path)
    assert loaded.active_provider == "glm"
    assert loaded.image.watermark_text == "@me"
    assert loaded.ocr_enabled is True
    assert len(loaded.providers) == 5


def test_get_active_provider_resolves(tmp_path: Path):
    cfg = default_config()
    p = get_active_provider(cfg)
    assert p.name == "radeon"
    cfg.active_provider = "glm"
    assert get_active_provider(cfg).name == "glm"


def test_load_missing_file_creates_default(tmp_path: Path):
    path = tmp_path / "config.json"
    cfg = load_config(path)
    assert path.exists()
    assert cfg.active_provider == "radeon"


def test_load_corrupt_file_returns_default_without_raising(tmp_path: Path):
    path = tmp_path / "config.json"
    garbage = b"\xff\xfe not valid json \x00 garbage"
    path.write_bytes(garbage)
    cfg = load_config(path)
    assert isinstance(cfg, AppConfig)
    assert cfg.active_provider == "radeon"
    # 损坏文件不应被覆盖
    assert path.read_bytes() == garbage


from content_studio.config import ComfyConfig


def test_comfy_config_defaults():
    c = ComfyConfig()
    assert c.base_url == "http://127.0.0.1:8188"
    assert c.enabled is True
    assert c.style_transfer is True
    assert c.t2i_count == 1
    assert c.timeout == 180


def test_default_config_has_comfy():
    cfg = default_config()
    assert isinstance(cfg.comfy, ComfyConfig)
    assert cfg.comfy.base_url.startswith("http")


def test_comfy_round_trip(tmp_path: Path):
    path = tmp_path / "config.json"
    cfg = default_config()
    cfg.comfy.t2i_count = 3
    cfg.comfy.base_url = "http://gpu:8188"
    save_config(cfg, path)
    loaded = load_config(path)
    assert loaded.comfy.t2i_count == 3
    assert loaded.comfy.base_url == "http://gpu:8188"
