"""Job-manager routing tests: engine -> phase1 / generative branches."""

from app.services import generative_service, job_manager, phase1_service
from app.storage import JobStore


def _make_store(tmp_path) -> JobStore:
    return JobStore(tmp_path / "jobs.db")


def _fake_phase1(video_name: str = "program.mp4", route: str = "programmatic"):
    def fake(job_id: str, text: str) -> dict:
        d = job_manager.JOBS_DIR / job_id
        d.mkdir(parents=True, exist_ok=True)
        video = d / video_name
        video.write_bytes(b"x")
        return {
            "video": video,
            "poster": d / "poster.png",
            "subtitles": None,
            "run_dir": d,
            "manifest": {"route": route, "reason": "test"},
        }

    return fake


def _fake_generative(job_id: str, manifest: dict, text: str, phase1_run_dir) -> dict:
    model_dir = job_manager.JOBS_DIR / job_id / "model"
    model_dir.mkdir(parents=True, exist_ok=True)
    video = model_dir / "final_video.mp4"
    video.write_bytes(b"y")
    return {"outputs": {"video": video}, "metrics": {"route": manifest.get("route")}}


def test_auto_programmatic_uses_program_video(tmp_path, monkeypatch):
    monkeypatch.setattr(phase1_service, "run_phase1", _fake_phase1(route="programmatic"))
    store = _make_store(tmp_path)
    mgr = job_manager.JobManager(store)
    job = job_manager.new_job("auto", "How is an oxbow lake formed?", {})
    store.create(job)
    mgr._run(job["id"])
    done = store.get(job["id"])
    assert done["status"] == "completed"
    assert done["manifest"]["route"] == "programmatic"
    assert done["artifacts"]["video"].endswith("/program.mp4")


def test_auto_realizable_routes_to_generative(tmp_path, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(phase1_service, "run_phase1", _fake_phase1(route="realizable"))

    def fake_gen(job_id, manifest, text, phase1_run_dir):
        calls.append("generative")
        return _fake_generative(job_id, manifest, text, phase1_run_dir)

    monkeypatch.setattr(generative_service, "run_generative", fake_gen)
    store = _make_store(tmp_path)
    mgr = job_manager.JobManager(store)
    job = job_manager.new_job("auto", "How is an oxbow lake formed?", {})
    store.create(job)
    mgr._run(job["id"])
    done = store.get(job["id"])
    assert done["status"] == "completed"
    assert calls == ["generative"]
    assert done["artifacts"]["video"].endswith("/final_video.mp4")


def test_deterministic_uses_program_video(tmp_path, monkeypatch):
    monkeypatch.setattr(phase1_service, "run_phase1", _fake_phase1(route="realizable"))
    store = _make_store(tmp_path)
    mgr = job_manager.JobManager(store)
    job = job_manager.new_job("deterministic", "x", {})
    store.create(job)
    mgr._run(job["id"])
    done = store.get(job["id"])
    assert done["status"] == "completed"
    assert done["artifacts"]["video"].endswith("/program.mp4")
