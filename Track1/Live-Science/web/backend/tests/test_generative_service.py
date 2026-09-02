"""Unit tests for the local ComfyUI Phase 2/3 pipeline (mocked tool runner)."""

from pathlib import Path

from app.services import generative_service


def fake_runner(cmd: list[str], cwd: Path) -> None:
    """Simulate the Re_0 tools producing their expected output files."""
    if "--output" in cmd:
        out = Path(cmd[cmd.index("--output") + 1])
        out.write_bytes(b"fake-png")
        return
    if "--segment-id" in cmd:
        run_dir = Path(cmd[2])
        seg = cmd[cmd.index("--segment-id") + 1]
        video = run_dir / "segments" / seg / "video.mp4"
        video.parent.mkdir(parents=True, exist_ok=True)
        video.write_bytes(b"fake-mp4")


def _make_phase1_run(tmp_path: Path, moment_ids: list[str]) -> Path:
    phase1_run = tmp_path / "phase1"
    bridge = phase1_run / "bridge" / "clean"
    bridge.mkdir(parents=True)
    for mid in moment_ids:
        (bridge / f"{mid}.png").write_bytes(b"png")
    return phase1_run


def test_pipeline_runs_phase2_phase3(tmp_path):
    manifest = {
        "route": "realizable",
        "worldContinuity": ["river", "oxbow lake"],
        "meta": {"width": 1536, "height": 864, "fps": 30},
        "keyMoments": [
            {"id": "m1", "time": 0.0, "description": "initial bending", "realizable": True,
             "assets": {"clean": "clean/m1.png"}},
            {"id": "m2", "time": 5.0, "description": "neck cutoff", "realizable": True,
             "assets": {"clean": "clean/m2.png"}},
        ],
    }
    phase1_run = _make_phase1_run(tmp_path, ["m1", "m2"])
    pipe = generative_service.LocalModelPipeline(runner=fake_runner)
    result = pipe.run_model("testjob-g", manifest, "oxbow lake", phase1_run)
    assert result["outputs"]["video"].name == "final_video.mp4"
    assert result["metrics"]["route"] == "realizable"
    assert "keyframe_m1" in result["outputs"]


def test_pipeline_skips_non_realizable_moments(tmp_path):
    manifest = {
        "route": "hybrid",
        "worldContinuity": [],
        "meta": {"width": 1536, "height": 864, "fps": 30},
        "keyMoments": [
            {"id": "m1", "time": 0.0, "description": "abstract formula", "realizable": False,
             "assets": {"clean": "clean/m1.png"}},
            {"id": "m2", "time": 3.0, "description": "realistic scene 1", "realizable": True,
             "assets": {"clean": "clean/m2.png"}},
            {"id": "m3", "time": 6.0, "description": "realistic scene 2", "realizable": True,
             "assets": {"clean": "clean/m3.png"}},
        ],
    }
    phase1_run = _make_phase1_run(tmp_path, ["m1", "m2", "m3"])
    pipe = generative_service.LocalModelPipeline(runner=fake_runner)
    result = pipe.run_model("testjob-h", manifest, "x", phase1_run)
    # m1 (not realizable) is skipped; m2/m3 generate keyframes + a video
    assert "keyframe_m1" not in result["outputs"]
    assert "keyframe_m2" in result["outputs"]
    assert "keyframe_m3" in result["outputs"]
    assert result["outputs"]["video"].name == "final_video.mp4"
