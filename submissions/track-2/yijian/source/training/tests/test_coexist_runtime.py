# -*- coding: utf-8 -*-

from pathlib import Path
import sys


TRAINING_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TRAINING_ROOT))

import summarize_inference_ablations as ablations  # noqa: E402


ROOT = Path(__file__).resolve().parents[2]


def test_coexistence_uses_actual_overlap_and_gpu_telemetry() -> None:
    source = (ROOT / "deploy" / "cloud" / "stress_qwen3_katago_coexist.py").read_text(
        encoding="utf-8"
    )
    assert "ThreadPoolExecutor(max_workers=2)" in source
    assert '"workloadsOverlapped": True' in source
    assert "GpuSampler" in source
    assert '"oomCount"' in source
    assert '"peakVramUsedGiB"' in source


def test_matrix_embeds_full_profile_reports() -> None:
    source = (ROOT / "deploy" / "cloud" / "run_qwen3_14b_coexist_matrix.sh").read_text(
        encoding="utf-8"
    )
    assert 'UTILIZATIONS=(0.72 0.75 0.78)' in source
    assert '"profileReports"' in source
    assert "--vllm-log" in source


def test_runtime_v3_matrix_binds_frozen_adapter_and_restores_services() -> None:
    source = (
        ROOT / "training" / "remote" / "run_vllm_lora_v3_coexist_matrix.sh"
    ).read_text(encoding="utf-8")
    assert "UTILIZATIONS=(0.72 0.75 0.78)" in source
    assert "/persistent/yijian/models/yijian-lora-v3-frozen/adapter" in source
    assert "--cycles 30 --p95-limit 12" in source
    assert "trap restore_services EXIT" in source
    assert "RESTORE_14B=" in source and "RESTORE_27B=" in source
    assert "YIJIAN-Qwen3-14B-LoRA-gold-runtime-v3-BF16" in source


def test_ablation_summary_requires_real_thirty_cycle_profiles(tmp_path: Path) -> None:
    def report(prefix: str) -> dict:
        return {
            "passed": True,
            "cycles": 30,
            "oomCount": 0,
            "combined": {"p95Seconds": 3.5},
            "llm": {"p95FirstTokenSeconds": .2, "p95TotalSeconds": 3.4},
            "telemetry": {"peakVramUsedGiB": 38.0},
            "rows": [
                {"llm": {"totalSeconds": 2.0, "chars": 100, "usage": {"completion_tokens": 40}, "textHash": f"{prefix}-{index}"}}
                for index in range(30)
            ],
        }

    paths = []
    for name in ("baseline", "prefix-off", "context"):
        path = tmp_path / f"{name}.json"
        path.write_text(__import__("json").dumps(report(name)), encoding="utf-8")
        paths.append(path)
    result = ablations.build_summary(
        baseline_path=paths[0], prefix_off_path=paths[1], context_16384_path=paths[2]
    )
    assert result["passed"] is True
    assert result["profiles"]["prefixOnContext8192"]["completionTokensPerSecond"] == 20.0
    assert result["comparisons"]["prefixCacheOnVsOff"]["exactTextHashAgreementDiagnostic"] == 0
    assert result["comparisons"]["prefixCacheOnVsOff"]["responseShapeConsistency"] == 1


def test_ablation_runner_restores_27b_on_every_exit() -> None:
    source = (ROOT / "deploy" / "cloud" / "run_qwen3_14b_ablation_profile.sh").read_text(
        encoding="utf-8"
    )
    assert "trap restore_services EXIT" in source
    assert "pgrep -x llama-server" in source
    assert "--cycles 30 --p95-limit 12" in source
    assert 'YIJIAN_VLLM_ENABLE_PREFIX_CACHING="$PREFIX_CACHE"' in source
    assert 'YIJIAN_VLLM_MAX_MODEL_LEN="$MAX_MODEL_LEN"' in source
