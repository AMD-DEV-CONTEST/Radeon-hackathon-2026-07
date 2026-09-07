from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_latest_pretrained_model_selects_latest_numbered_checkpoint(tmp_path: Path) -> None:
    train_dir = tmp_path / "train"
    older = train_dir / "checkpoints" / "000100" / "pretrained_model"
    latest = train_dir / "checkpoints" / "010000" / "pretrained_model"
    older.mkdir(parents=True)
    latest.mkdir(parents=True)

    command = (
        f"source {ROOT / 'scripts' / 'lib.sh'}; "
        f"latest_pretrained_model {train_dir}"
    )
    result = subprocess.run(
        ["bash", "-c", command],
        check=True,
        text=True,
        capture_output=True,
        cwd=ROOT,
    )
    assert result.stdout.strip() == str(latest)


def test_latest_pretrained_model_prefers_legacy_last(tmp_path: Path) -> None:
    train_dir = tmp_path / "train"
    legacy = train_dir / "checkpoints" / "last" / "pretrained_model"
    numbered = train_dir / "checkpoints" / "020000" / "pretrained_model"
    legacy.mkdir(parents=True)
    numbered.mkdir(parents=True)

    command = (
        f"source {ROOT / 'scripts' / 'lib.sh'}; "
        f"latest_pretrained_model {train_dir}"
    )
    result = subprocess.run(
        ["bash", "-c", command],
        check=True,
        text=True,
        capture_output=True,
        cwd=ROOT,
    )
    assert result.stdout.strip() == str(legacy)


def test_physical_1k_pipeline_uses_held_out_seeds_and_remote_venv() -> None:
    remote = (ROOT / "scripts" / "run_full_remote.sh").read_text(encoding="utf-8")
    finish = (ROOT / "scripts" / "finish_physical_1k.sh").read_text(encoding="utf-8")
    assert 'EVAL_SEED_START="${EVAL_SEED_START:-50000}"' in remote
    assert 'INTERRUPT_SEED_START="${INTERRUPT_SEED_START:-60000}"' in remote
    assert 'PERTURB_SEED_START="${PERTURB_SEED_START:-60100}"' in remote
    assert 'PYTHON="$PYTHON_BIN"' in finish
