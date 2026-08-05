"""Regression test: stale job_id after server restart.

The client must be able to distinguish a dead job (server restarted,
JOBS is empty — answer 404, client goes idle) from a live one."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import serve_ui


def test_unknown_job_is_404():
    client = serve_ui.app.test_client()
    resp = client.get("/jobs/deadbeef1234")
    assert resp.status_code == 404
    assert resp.get_json()["exists"] is False


def test_live_job_reports_progress():
    job_id = serve_ui._new_job()
    serve_ui.emit(job_id, "text", "hello")
    client = serve_ui.app.test_client()
    resp = client.get(f"/jobs/{job_id}")
    body = resp.get_json()
    assert resp.status_code == 200
    assert body["exists"] is True and body["done"] is False
    assert body["events"] == 1


def test_finished_job_reports_done():
    job_id = serve_ui._new_job()
    serve_ui.JOBS[job_id]["done"] = True
    client = serve_ui.app.test_client()
    assert client.get(f"/jobs/{job_id}").get_json()["done"] is True
