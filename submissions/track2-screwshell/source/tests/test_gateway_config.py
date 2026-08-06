"""Gateway config-generation tests (no GPU required)."""
from __future__ import annotations

from unittest import mock

from screwshell.gateway.config import ServerConfig


def test_argv_contains_jinja():
    cfg = ServerConfig(model_path="/m/Qwen.gguf",
                       lora_paths=["/l/btl3.gguf"], vram_total_gb=48.0)
    argv = cfg.to_argv()
    assert "--jinja" in argv


def test_ngl_uses_fit_output_not_hardcoded_999():
    # When fit is available, argv must carry the fit ngl (53), never 999.
    with mock.patch("screwshell.gateway.config.fit_params",
                    return_value={"ctx": 131072, "ngl": 53}):
        cfg = ServerConfig(model_path="/m/Qwen.gguf", vram_total_gb=48.0)
        argv = cfg.to_argv(fit_binary="/opt/fit")  # triggers lazy fit call
    i = argv.index("--n-gpu-layers")
    assert argv[i + 1] == "53"
    assert argv[i + 1] != "999"


def test_ngl_uses_cached_fit_result_once():
    # The orchestrator resolves fit once and caches it; to_argv must reuse it
    # (and never re-run the slow fit subprocess) even with fit_binary=None.
    cfg = ServerConfig(model_path="/m/Qwen.gguf", vram_total_gb=48.0,
                       fit_result={"ctx": 131072, "ngl": 53})
    argv = cfg.to_argv()  # no fit_binary -> must use cached result, not 999
    i = argv.index("--n-gpu-layers")
    assert argv[i + 1] == "53"


def test_ngl_fallback_when_fit_unavailable_and_no_cache():
    # No cached result and no fit_binary -> roomy fallback, not the 999 that
    # bypasses --fit (DEFAULT_GPU_LAYERS is the documented fallback).
    from screwshell.gateway.config import DEFAULT_GPU_LAYERS
    cfg = ServerConfig(model_path="/m/Qwen.gguf", vram_total_gb=48.0)
    argv = cfg.to_argv()  # fit_binary=None, fit_result=None -> fallback
    i = argv.index("--n-gpu-layers")
    assert argv[i + 1] == str(DEFAULT_GPU_LAYERS)


def test_ngl_explicit_override_honored():
    cfg = ServerConfig(model_path="/m/Qwen.gguf", n_gpu_layers=40,
                       vram_total_gb=48.0)
    argv = cfg.to_argv()
    i = argv.index("--n-gpu-layers")
    assert argv[i + 1] == "40"


def test_ngl_fallback_is_room_default_not_999_when_fit_missing():
    # fit unavailable (returns None) -> roomy fallback, but NOT the value that
    # bypasses --fit. We mock fit to None and assert argv does not read 999
    # from a hardcoded path (DEFAULT_GPU_LAYERS is the documented fallback).
    from screwshell.gateway.config import DEFAULT_GPU_LAYERS
    with mock.patch("screwshell.gateway.config.fit_params", return_value=None):
        cfg = ServerConfig(model_path="/m/Qwen.gguf", vram_total_gb=48.0)
        argv = cfg.to_argv()
    i = argv.index("--n-gpu-layers")
    assert argv[i + 1] == str(DEFAULT_GPU_LAYERS)


def test_lora_is_single_comma_value():
    cfg = ServerConfig(model_path="/m/Qwen.gguf",
                       lora_paths=["/l/a.gguf", "/l/b.gguf", "/l/c.gguf"],
                       vram_total_gb=48.0)
    argv = cfg.to_argv()
    # exactly one --lora key, and its value is comma-joined
    assert argv.count("--lora") == 1
    i = argv.index("--lora")
    assert argv[i + 1] == "/l/a.gguf,/l/b.gguf,/l/c.gguf"


def test_reasoning_budget_never_minus_one():
    cfg = ServerConfig(model_path="/m/Qwen.gguf",
                       reasoning_budget=-1, vram_total_gb=48.0)
    argv = cfg.to_argv()
    i = argv.index("--reasoning-budget")
    assert argv[i + 1] != "-1"
    assert int(argv[i + 1]) > 0


def test_ctx_derived_from_capacity():
    cfg = ServerConfig(model_path="/m/Qwen.gguf", vram_total_gb=48.0)
    argv = cfg.to_argv()
    i = argv.index("--ctx-size")
    assert int(argv[i + 1]) >= 131072


def test_no_lora_when_none():
    cfg = ServerConfig(model_path="/m/Qwen.gguf", vram_total_gb=48.0)
    argv = cfg.to_argv()
    assert "--lora" not in argv


def test_required_flags_present():
    cfg = ServerConfig(model_path="/m/Qwen.gguf", vram_total_gb=48.0)
    argv = cfg.to_argv()
    for flag in ("--alias", "--host", "--port", "--n-gpu-layers",
                 "--threads", "--reasoning-budget"):
        assert flag in argv
