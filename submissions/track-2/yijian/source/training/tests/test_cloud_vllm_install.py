# -*- coding: utf-8 -*-

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_vllm_installer_is_pinned_to_rocm721_and_existing_model() -> None:
    source = (ROOT / "deploy" / "cloud" / "install_qwen3_14b_vllm.sh").read_text(
        encoding="utf-8"
    )
    assert "python3.12 -m venv" in source
    assert "rocm721" in source
    assert "321fa2d6d1644629ac39d173f6393f37e14bf7b4" in source
    assert "ROCM_BOOTSTRAP_WHEELS" in source
    assert "flash_attn-2.8.3" in source
    assert "torch-2.10.0%2Bgit8514f05" in source
    assert "qwen3-14b-bf16" in source
    assert "--index-strategy unsafe-best-match" in source
    assert "torch.version.hip" in source
    assert "nvidia-" in source


def test_vllm_runtime_defaults_match_competition_profile() -> None:
    source = (ROOT / "deploy" / "cloud" / "start_qwen3_14b_agent.sh").read_text(
        encoding="utf-8"
    )
    assert "qwen3-14b-bf16" in source
    assert "models/yijian-lora-v3-frozen/adapter" in source
    assert 'YIJIAN_VLLM_GPU_MEMORY_UTILIZATION:-0.72' in source
    assert 'YIJIAN_VLLM_MAX_MODEL_LEN:-8192' in source
    assert 'YIJIAN_VLLM_MAX_NUM_SEQS:-2' in source
    assert "YIJIAN_VLLM_ENABLE_PREFIX_CACHING" in source
