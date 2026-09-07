import json

from radeonvla.artifact_io import sha256_path, write_evaluation_bundle


def test_sha256_path_is_stable_for_directory(tmp_path) -> None:
    model = tmp_path / "model"
    model.mkdir()
    (model / "b.bin").write_bytes(b"two")
    (model / "a.bin").write_bytes(b"one")
    first = sha256_path(model)
    second = sha256_path(model)
    assert first == second
    assert len(first) == 64
    (model / "a.bin").write_bytes(b"changed")
    assert sha256_path(model) != first


def test_write_evaluation_bundle_creates_json_csv_and_summary(tmp_path) -> None:
    payload = {
        "experiment_id": "eval_test",
        "git_commit": "a" * 40,
        "environment": {"gpu": "AMD", "rocm": "7.2.1"},
        "checkpoint": {"sha256": "b" * 64},
        "summary": {
            "num_episodes": 1,
            "final_success": 1.0,
            "first_attempt_success": 1.0,
            "recovery_success": 0.0,
            "safe_interrupt_rate": 1.0,
            "p50_inference_latency_ms": 10.0,
            "p95_inference_latency_ms": 12.0,
            "success_by_task": {"banana_white_left": 1.0},
        },
        "episodes": [
            {
                "episode_id": "banana_white_left_1",
                "task_id": "banana_white_left",
                "seed": 1,
                "success": True,
                "inference_latency_ms": [10.0, 12.0],
            }
        ],
    }
    paths = write_evaluation_bundle(payload, tmp_path / "evaluation.json")
    assert set(paths) == {"json", "csv", "summary"}
    assert json.loads(paths["json"].read_text())["experiment_id"] == "eval_test"
    assert "banana_white_left" in paths["csv"].read_text()
    assert "Safe interrupt rate" in paths["summary"].read_text()
