from pathlib import Path

import safetensors.torch
import torch

from smolvla_qvgm_rlinf.models.checkpoint import _native_processor_stats


def test_native_processor_stats_loads_state_and_action_mean_std(tmp_path: Path):
    state_path = tmp_path / "policy_preprocessor_step_5_normalizer_processor.safetensors"
    safetensors.torch.save_file(
        {
            "observation.state.mean": torch.arange(8, dtype=torch.float32),
            "observation.state.std": torch.arange(1, 9, dtype=torch.float32),
            "action.mean": torch.arange(7, dtype=torch.float32),
            "action.std": torch.arange(1, 8, dtype=torch.float32),
            "timestamp.mean": torch.zeros(1),
        },
        state_path,
    )

    stats = _native_processor_stats(tmp_path)

    torch.testing.assert_close(stats["observation.state"]["mean"], torch.arange(8).float())
    torch.testing.assert_close(stats["observation.state"]["std"], torch.arange(1, 9).float())
    torch.testing.assert_close(stats["action"]["mean"], torch.arange(7).float())
    torch.testing.assert_close(stats["action"]["std"], torch.arange(1, 8).float())


def test_native_processor_stats_returns_none_for_legacy_checkpoint(tmp_path: Path):
    assert _native_processor_stats(tmp_path) is None
