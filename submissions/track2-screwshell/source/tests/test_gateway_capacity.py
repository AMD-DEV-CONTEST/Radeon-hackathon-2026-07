"""Gateway capacity + fit tests (no GPU / no real llama-fit-params required)."""
from __future__ import annotations

from unittest import mock

from screwshell.gateway.capacity import (
    CapacityResult, fit_params, max_ctx_tokens, plan, plan_fit, weight_gb,
)


def test_weight_gb_q4():
    assert round(weight_gb("Q4_K_M"), 2) == round(18.9 * 1.05, 2)


def test_48gb_yields_large_ctx():
    ctx = max_ctx_tokens(48.0, "Q4_K_M")
    assert ctx >= 131072
    res = plan(48.0, "Q4_K_M")
    used = res.weight_gb + res.kv_gb + res.overhead_gb
    assert used <= 48.0


def test_16gb_cannot_fit_q4_weight_safe_refusal():
    ctx = max_ctx_tokens(16.0, "Q4_K_M")
    assert ctx == 0
    res = plan(16.0, "Q4_K_M")
    assert res.ctx_tokens == 0
    assert any("不足以" in n for n in res.notes)


def test_small_ctx_fits_when_weight_allows():
    ctx = max_ctx_tokens(32.0, "Q4_K_M")
    assert 4096 <= ctx
    res = plan(32.0, "Q4_K_M")
    used = res.weight_gb + res.kv_gb + res.overhead_gb
    assert used <= 32.0


def test_insufficient_vram_returns_zero():
    assert max_ctx_tokens(8.0, "Q4_K_M") == 0


def test_plan_picks_quant_from_profile():
    from screwshell.autotune.hardware import HardwareProfile
    prof = HardwareProfile(vendor="amd", name="W7900", vram_total_gb=48.0)
    res = plan(48.0, profile=prof)
    assert isinstance(res, CapacityResult)
    assert res.ctx_tokens >= 131072


def test_fit_params_parses_dash_flags():
    # llama-fit-params prints "-c 131072 -ngl 53"
    fake = "-c 131072 -ngl 53\n"
    with mock.patch("screwshell.gateway.capacity.shutil.which", return_value="/bin/llama-fit-params"), \
         mock.patch("screwshell.gateway.capacity.subprocess.run") as run:
        run.return_value = mock.Mock(returncode=0, stdout=fake, stderr="")
        out = fit_params("/m/Qwen.gguf", binary="llama-fit-params")
    assert out == {"ctx": 131072, "ngl": 53}


def test_fit_params_none_when_binary_missing():
    with mock.patch("screwshell.gateway.capacity.shutil.which", return_value=None):
        assert fit_params("/m/Qwen.gguf") is None


def test_fit_params_none_on_nonzero_return():
    with mock.patch("screwshell.gateway.capacity.shutil.which", return_value="/bin/llama-fit-params"), \
         mock.patch("screwshell.gateway.capacity.subprocess.run") as run:
        run.return_value = mock.Mock(returncode=1, stdout="", stderr="boom")
        assert fit_params("/m/Qwen.gguf", binary="llama-fit-params") is None


def test_plan_fit_uses_fit_when_available():
    fake = "-c 131072 -ngl 53\n"
    with mock.patch("screwshell.gateway.capacity.shutil.which", return_value="/bin/llama-fit-params"), \
         mock.patch("screwshell.gateway.capacity.subprocess.run") as run:
        run.return_value = mock.Mock(returncode=0, stdout=fake, stderr="")
        res = plan_fit("/m/Qwen.gguf", 48.0)
    assert res.ctx_tokens == 131072
    assert any("llama-fit-params" in n for n in res.notes)


def test_plan_fit_fallback_caps_ctx_at_131072():
    # fit unavailable -> fallback formula, but ctx must not exceed 131072
    with mock.patch("screwshell.gateway.capacity.shutil.which", return_value=None):
        res = plan_fit("/m/Qwen.gguf", 48.0)
    assert res.ctx_tokens <= 131072
    assert any("回退" in n or "fit" in n.lower() for n in res.notes)
