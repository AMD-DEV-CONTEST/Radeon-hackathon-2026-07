import importlib.util
import json
import math
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "render_match_log_video.py"
SPEC = importlib.util.spec_from_file_location("render_match_log_video", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def match_data():
    identities = {
        "worker_alpha": {"team": "A", "role": "attacker", "controller": "ONNX", "model_sha": "a" * 64},
        "worker_beta": {"team": "B", "role": "keeper", "controller": "Rule", "model_sha": "b" * 64},
    }
    return {
        "duration": 99.0,
        "sync_hz": 2.0,
        "identities": identities,
        "log": [
            {"t": 0.0, "ball": {"x": 0.0, "y": 0.0}, "robots": {
                "worker_alpha": {"x": -1.0, "y": 0.0}, "worker_beta": {"x": 1.0, "y": 0.0}},
             "events": {"worker_alpha": {"fallen": False, "scored": False}, "worker_beta": {"fallen": False, "scored": False}}},
            {"t": 1.25, "ball": {"x": 0.5, "y": 0.25}, "robots": {
                "worker_alpha": {"x": 0.0, "y": 0.5}, "worker_beta": {"x": 0.5, "y": -0.5}},
             "events": {"worker_alpha": {"fallen": False, "scored": True}, "worker_beta": {"fallen": False, "scored": False}}},
        ],
    }


def write_match(tmp_path, data=None):
    path = tmp_path / "match.json"
    path.write_text(json.dumps(data or match_data()))
    return path


def test_role_mapping_comes_from_same_log_and_not_client_order(tmp_path):
    loaded = MODULE.load_match(write_match(tmp_path))
    assert loaded["identities"]["worker_alpha"]["role"] == "attacker"
    sample = MODULE.interpolate_sample(loaded["log"], 0.625, loaded["identities"])
    assert sample["robots"]["worker_alpha"]["x"] == pytest.approx(-0.5)


@pytest.mark.parametrize("mutation", ["missing_identities", "robot_mismatch", "nan_time", "inf_position"])
def test_malformed_or_nonfinite_log_is_rejected(tmp_path, mutation):
    data = match_data()
    if mutation == "missing_identities":
        data.pop("identities")
    elif mutation == "robot_mismatch":
        data["log"][0]["robots"].pop("worker_beta")
    elif mutation == "nan_time":
        data["log"][1]["t"] = math.nan
    else:
        data["log"][1]["ball"]["x"] = math.inf
    with pytest.raises(ValueError):
        MODULE.load_match(write_match(tmp_path, data))


def test_real_render_decodes_and_ends_at_last_sample(tmp_path):
    imageio = pytest.importorskip("imageio.v2")
    pytest.importorskip("matplotlib")
    pytest.importorskip("imageio_ffmpeg")
    source = write_match(tmp_path)
    model = tmp_path / "model.onnx"
    model.write_bytes(b"test model")
    stdout = tmp_path / "match.log"
    stdout.write_text("same run stdout")
    video = tmp_path / "match.mp4"
    metadata_path = tmp_path / "match.metadata.json"
    metadata = MODULE.render_video(source, video, metadata_path, model, stdout, fps=4, width=320, height=240)

    reader = imageio.get_reader(video)
    decoded = sum(1 for _ in reader)
    video_meta = reader.get_meta_data()
    reader.close()
    assert decoded == 6
    assert video_meta["size"] == (320, 240)
    assert metadata["frame_count"] == decoded
    assert metadata["duration_seconds"] == 1.25  # top-level duration=99 is deliberately ignored
    assert metadata["last_sample_t"] == 1.25
    assert metadata["role_mapping"] == match_data()["identities"]
    assert metadata["video_sha256"] == MODULE.sha256_file(video)
    assert metadata["source_stdout_sha256"] == MODULE.sha256_file(stdout)
    assert metadata["renderer_sha256"] == MODULE.sha256_file(SCRIPT)
    assert metadata["command"].startswith("python3 scripts/render_match_log_video.py ")
    assert set(metadata["tool_versions"]) == {"python", "imageio", "matplotlib", "ffmpeg"}


def test_final_metadata_is_bound_to_final_same_run_sources():
    metadata_path = ROOT / "acceptance/demo/track3_3v3_20260804.metadata.json"
    if not metadata_path.exists():
        pytest.skip("final artifact has not been rendered yet")
    metadata = json.loads(metadata_path.read_text())
    source = ROOT / "acceptance/remote/match_20260804_115349.json"
    stdout = ROOT / "acceptance/remote/codex_3v3_acceptance.log"
    assert metadata["source_log_sha256"] == MODULE.sha256_file(source)
    assert metadata["source_stdout_sha256"] == MODULE.sha256_file(stdout)
    assert metadata["duration_seconds"] == MODULE.load_match(source)["log"][-1]["t"]
    assert metadata["role_mapping"] == MODULE.load_match(source)["identities"]
    assert metadata["identity_source"] == MODULE.load_match(source)["identity_source"]
    assert metadata["role_mapping"]["client_0"]["ball_authority"] is True
    assert metadata["event_summary"]["fallen"] == ["client_0"]
