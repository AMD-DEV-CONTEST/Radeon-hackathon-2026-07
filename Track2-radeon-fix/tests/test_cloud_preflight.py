from __future__ import annotations

import json

from scripts.cloud_preflight import parse_rocminfo
from scripts import cloud_preflight


def test_parse_rocminfo_ignores_cpu_and_finds_gpu_marketing_name() -> None:
    text = """
  Name:                    AMD EPYC 9334 32-Core Processor
  Marketing Name:          AMD EPYC 9334 32-Core Processor
  Vendor Name:             CPU
  Name:                    gfx1100
  Marketing Name:          AMD Radeon Graphics
  Vendor Name:             AMD
"""
    assert parse_rocminfo(text) == {
        "gpu_arch": "gfx1100",
        "marketing_name": "AMD Radeon Graphics",
        "has_gpu_agent": True,
    }


def test_parse_rocminfo_reports_missing_gpu() -> None:
    assert parse_rocminfo("Name: CPU\nVendor Name: CPU\n") == {
        "gpu_arch": None,
        "marketing_name": None,
        "has_gpu_agent": False,
    }


def test_bf16_preflight_accepts_qwen3_gfx1100(tmp_path, monkeypatch) -> None:
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / "config.json").write_text(
        json.dumps({"model_type": "qwen3", "architectures": ["Qwen3ForCausalLM"]})
    )
    monkeypatch.setattr(
        cloud_preflight,
        "read_gpu_info",
        lambda: {
            "gpu_arch": "gfx1100",
            "marketing_name": "AMD Radeon Graphics",
            "has_gpu_agent": True,
        },
    )
    monkeypatch.setattr(
        cloud_preflight,
        "runtime_capability",
        lambda: {"bf16_supported": True, "vllm_version": "0.25.1"},
    )
    report, accepted = cloud_preflight.run_preflight(model_dir)
    assert accepted is True
    assert report["model"]["model_type"] == "qwen3"


def test_bf16_preflight_rejects_wrong_gpu(tmp_path, monkeypatch) -> None:
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / "config.json").write_text(json.dumps({"model_type": "qwen3"}))
    monkeypatch.setattr(
        cloud_preflight,
        "read_gpu_info",
        lambda: {"gpu_arch": "gfx942", "has_gpu_agent": True},
    )
    monkeypatch.setattr(
        cloud_preflight,
        "runtime_capability",
        lambda: {"bf16_supported": True},
    )
    _, accepted = cloud_preflight.run_preflight(model_dir)
    assert accepted is False
