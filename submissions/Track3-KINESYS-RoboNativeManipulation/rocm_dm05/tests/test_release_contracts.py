from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_pinned_upstream_revisions() -> None:
    setup = (ROOT / "scripts" / "setup_sources.sh").read_text(encoding="utf-8")
    assert "89474e8d4e39a4b48458fcb2e119685a8118d5cc" in setup
    assert "f66b9150ca7cfd48746147dfa8326a2657ab309e" in setup
    assert "agent/amd-gfx1100-reconstruction" not in setup


def test_bigym_overlay_is_self_contained() -> None:
    installer = (ROOT / "scripts" / "install_bigym_amd_overlay.sh").read_text()
    for relative in (
        "overlays/bigym/bigym/utils/visual_shell.py",
        "overlays/bigym/bigym/utils/visual_shell_assets.py",
    ):
        assert (ROOT / relative).is_file()
        assert relative.replace("overlays/bigym/", "") in installer


def test_safe_evaluation_protocol_is_frozen() -> None:
    runner = (ROOT / "scripts" / "run_eval.py").read_text(encoding="utf-8")
    for value in (
        'parser.add_argument("--diffusion-steps", type=int, default=10)',
        '"--diffusion-steps",\n            str(args.diffusion_steps)',
        '"--chunk-size",\n            "16"',
        '"--execute-actions",\n            "8"',
        '"--no-lora-wrapper"',
        '"--reuse-kv-workspace"',
        'env["ROCM_HOME"]',
        'env["TORCH_EXTENSIONS_DIR"]',
    ):
        assert value in runner

    for relative in (
        "eval/eval_cutlery_native.py",
        "eval/eval_cutlery_3dgs.py",
        "inference/http_provider.py",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8")
        expected = 'parser.add_argument("--diffusion-steps", type=int, default=10)'
        assert expected in source


def test_release_patch_excludes_rejected_experiments() -> None:
    runtime_patch = (ROOT / "patches" / "opendm-runtime.patch").read_text()
    for rejected in (
        "benchmark_steps",
        "save_final_model",
        "torch_compile",
        "language_gradient_checkpointing",
        "vision_gradient_checkpointing",
    ):
        assert rejected not in runtime_patch


def test_machine_readable_result_scope() -> None:
    result = json.loads((ROOT / "results" / "benchmark.json").read_text())
    assert result["amd_runtime"]["architecture"] == "gfx1100"
    assert result["quality_protocol"]["diffusion_steps"] == 10
    assert result["quality_results"]["native_50"]["successes"] == 25
    assert result["quality_results"]["three_dgs_50"]["successes"] == 20
    assert result["training_software_benchmark"]["claim_scope"] == (
        "controlled_dm05_throughput_benchmark"
    )


def test_public_shell_source_is_pinned() -> None:
    downloader = (ROOT / "scripts" / "download_3dgs_shell.py").read_text()
    assert 'DEFAULT_REPO = "eustance/amd-bigym-3dgs-kitchen-shell"' in downloader
    assert 'DEFAULT_REVISION = "amd-rocm-w7900d-20260804"' in downloader
    assert "resolved_commit" in downloader


def test_shell_profile_contract_validation(tmp_path: Path) -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    from download_3dgs_shell import validate_profile

    payload = b"ply\nvalidated-shell\n"
    ply = tmp_path / "shell.ply"
    ply.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    profile = tmp_path / "scene-shell-profile.json"
    profile.write_text(
        json.dumps(
            {
                "layer_files": {"combined": ply.name},
                "ground_visual": {"mode": "gaussian_combined"},
                "asset": {
                    "path": ply.name,
                    "bytes": len(payload),
                    "sha256": digest,
                },
            }
        ),
        encoding="utf-8",
    )
    result = validate_profile(profile)
    assert result["mode"] == "combined"
    assert result["assets"]["combined"]["sha256"] == digest

    bad = json.loads(profile.read_text())
    bad["asset"]["sha256"] = "0" * 64
    profile.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ValueError, match="SHA-256"):
        validate_profile(profile)


def test_private_and_large_artifacts_are_ignored() -> None:
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for pattern in ("*.ply", "*.safetensors", "*.mp4", "checkpoints/", "data/"):
        assert pattern in ignore


def test_single_seed_shard_merge(tmp_path: Path) -> None:
    shard = {
        "model_path": "/model",
        "task": "DishwasherUnloadCutleryLong",
        "prompt": "Unload cutlery from dishwasher to drawer task.",
        "control_frequency": 20,
        "policy_frequency": 20,
        "chunk_size": 16,
        "diffusion_steps": 10,
        "execute_actions": 8,
        "max_policy_steps": 800,
        "model_max_length": 896,
        "use_lora_wrapper": False,
        "reuse_kv_workspace": True,
        "state_definition": "state16",
        "episodes": [
            {
                "seed": 200009,
                "success": True,
                "policy_steps": 560,
                "inference_calls": 70,
                "inference_seconds": 32.2,
            }
        ],
    }
    shard_path = tmp_path / "shard.json"
    output_path = tmp_path / "summary.json"
    shard_path.write_text(json.dumps(shard), encoding="utf-8")
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "eval" / "merge_shards.py"),
            "--expected-seeds",
            "200009",
            "--output",
            str(output_path),
            str(shard_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(output_path.read_text(encoding="utf-8"))
    assert result["successes"] == 1
    assert result["expected_seeds"] == [200009]


def test_unvalidated_domain_mix_is_not_in_release() -> None:
    assert not (ROOT / "scripts" / "train_domain_mix.sh").exists()
    assert not (ROOT / "train" / "dm05_domain_mix.py").exists()


def test_public_text_is_amd_only() -> None:
    forbidden = re.compile(r"\b(?:nvidia|geforce|rtx|a800|5090d?)\b", re.IGNORECASE)
    suffixes = {".md", ".py", ".sh", ".txt", ".toml", ".yaml", ".yml"}
    violations: list[str] = []
    for path in ROOT.rglob("*"):
        if (
            not path.is_file()
            or path == Path(__file__).resolve()
            or path.suffix not in suffixes
            or ".git" in path.parts
            or "third_party" in path.parts
        ):
            continue
        if forbidden.search(path.read_text(encoding="utf-8")):
            violations.append(str(path.relative_to(ROOT)))
    assert not violations
