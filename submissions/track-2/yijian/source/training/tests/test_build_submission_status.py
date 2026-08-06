from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "build_submission_status.py"
SPEC = importlib.util.spec_from_file_location("build_submission_status", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_freeze_stage_accepts_content_addressed_frozen_adapter(tmp_path: Path) -> None:
    path = tmp_path / "freeze.json"
    path.write_text(
        '{"schemaVersion":"yijian-lora-adapter-freeze-v1","frozen":true,'
        '"adapterTreeSha256":"' + "a" * 64 + '",'
        '"baseRevision":"40c069824f4251a91eefaf281ebe4c544efd3e18"}',
        encoding="utf-8",
    )
    result = MODULE.artifact(path, MODULE.adapter_freeze_verified)
    assert result["available"] is True
    assert result["passed"] is True


def test_environment_stage_requires_pinned_w7900_stack(tmp_path: Path) -> None:
    path = tmp_path / "environment.json"
    path.write_text(
        '{"schemaVersion":"yijian-qwen3-14b-vllm-environment-v1",'
        '"model":"Qwen/Qwen3-14B",'
        '"modelRevision":"40c069824f4251a91eefaf281ebe4c544efd3e18",'
        '"vllm":"0.20.2","vllmCommit":"abc","torch":"2.10",'
        '"transformers":"5.14","gfxArch":"gfx1100"}',
        encoding="utf-8",
    )
    result = MODULE.artifact(path, MODULE.environment_verified)
    assert result["passed"] is True

    path.write_text(path.read_text(encoding="utf-8").replace("gfx1100", "gfx900"), encoding="utf-8")
    result = MODULE.artifact(path, MODULE.environment_verified)
    assert result["passed"] is False
