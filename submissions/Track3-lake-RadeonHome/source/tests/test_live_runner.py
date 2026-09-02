from pathlib import Path

import pytest

from radeon_home import live_runner


def test_unknown_run_is_explicit() -> None:
    with pytest.raises(KeyError):
        live_runner.describe_run("missing")


def test_physical_instruction_selects_semantically_matching_seed() -> None:
    backend = {
        "backend": "local_qwen_validated_plan",
        "task_plan": {
            "instruction": "请把床头柜上需要丢弃的包装收进右侧的废物容器",
            "steps": [{
                "action": "pick_and_place",
                "object_id": "trash",
                "target_id": "trash_bin",
                "reference_id": None,
                "constraints": [],
            }],
        },
    }
    original = live_runner.plan_with_local_qwen
    live_runner.plan_with_local_qwen = lambda instruction: backend
    try:
        seed, object_id, selected_backend = live_runner.physical_task_for_instruction(
            "请把床头柜上需要丢弃的包装收进右侧的废物容器"
        )
    finally:
        live_runner.plan_with_local_qwen = original
    assert seed == live_runner.PHYSICAL_SEED_BY_OBJECT["trash"]
    assert object_id == "trash"
    assert selected_backend["backend"] == "local_qwen_validated_plan"


def test_artifact_rejects_path_traversal(monkeypatch, tmp_path: Path) -> None:
    run_dir = tmp_path / "run-a"
    run_dir.mkdir()
    (run_dir / "ok.txt").write_text("ok")
    monkeypatch.setattr(live_runner, "_runs", {"run-a": {"output_dir": run_dir}})
    assert live_runner.resolve_artifact("run-a", "ok.txt").read_text() == "ok"
    with pytest.raises(KeyError):
        live_runner.resolve_artifact("run-a", "../ok.txt")
