from __future__ import annotations

from app.schemas.project import ProjectCreate
from app.services.store import ProjectStore


def _payload(name: str) -> ProjectCreate:
    return ProjectCreate(
        product_name=name,
        product_category="Skincare",
        campaign_goal="Launch a local campaign",
        target_audience="Adults",
        key_benefits="Rights-safe example product",
        brand_tone="Premium",
        brand_colors=["#112233"],
        creative_styles=["Luxury"],
        output_formats=["Instagram Square"],
    )


def test_startup_marks_only_active_jobs_interrupted_and_preserves_results(tmp_path):
    store = ProjectStore(tmp_path / "storage")
    interrupted = store.create(_payload("Interrupted"))
    interrupted["status"] = "generating"
    interrupted["generation_state"] = "generating"
    interrupted["active_rocm_job_id"] = "ephemeral-job-id"
    interrupted["results"] = [
        {
            "result_id": "completed-result",
            "human_review_status": "approved",
        }
    ]
    interrupted["review_state"] = "in_progress"
    store.save(interrupted)

    completed = store.create(_payload("Completed"))
    completed["status"] = "completed"
    completed["generation_state"] = "completed"
    completed["results"] = [{"result_id": "kept"}]
    store.save(completed)

    failed = store.create(_payload("Failed"))
    failed["status"] = "failed"
    failed["generation_state"] = "failed"
    failed["last_generation_failure"] = "previous safe failure"
    store.save(failed)

    assert store.recover_interrupted_jobs() == 1

    recovered = store.get(interrupted["project_id"])
    assert recovered["status"] == "interrupted"
    assert recovered["generation_state"] == "interrupted"
    assert recovered["active_rocm_job_id"] is None
    assert "backend restart" in recovered["last_generation_failure"]
    assert recovered["results"][0]["result_id"] == "completed-result"
    assert recovered["results"][0]["human_review_status"] == "approved"
    assert recovered["review_state"] == "in_progress"

    assert store.get(completed["project_id"])["generation_state"] == "completed"
    assert store.get(completed["project_id"])["results"] == [{"result_id": "kept"}]
    assert store.get(failed["project_id"])["last_generation_failure"] == (
        "previous safe failure"
    )
    assert store.recover_interrupted_jobs() == 0


def test_pending_mock_project_is_not_changed_by_recovery(tmp_path):
    store = ProjectStore(tmp_path / "storage")
    project = store.create(_payload("Mock"))
    assert store.recover_interrupted_jobs() == 0
    assert store.get(project["project_id"])["generation_state"] == "pending"
