"""Tests for ProjectStore (policycut/core/storage.py).

Contract (CONTRACTS.md section 5): atomic JSON persistence under
data/projects/<project_id>/, tolerant reads, jobs index maintenance.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from policycut.core.models import Job, RedactionEvent
from policycut.core.storage import ProjectStore


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TestProjectCrud:
    def test_create_project(self, store):
        p = store.create_project("Demo")
        assert p.id.startswith("p_") and len(p.id) == 12
        assert p.name == "Demo"
        assert p.status == "draft"
        assert p.revision == 0
        # ISO timestamps parse
        datetime.fromisoformat(p.created_at.replace("Z", "+00:00"))

    def test_list_and_get(self, store):
        a = store.create_project("A")
        b = store.create_project("B")
        ids = {p.id for p in store.list_projects()}
        assert {a.id, b.id} <= ids
        got = store.get_project(a.id)
        assert got is not None and got.name == "A"

    def test_get_missing_returns_none(self, store):
        assert store.get_project("p_doesnotexis") is None

    def test_save_roundtrip(self, store):
        p = store.create_project("Old Name")
        p.name = "New Name"
        p.policy_text = "blur faces"
        p.exports_stale = True
        store.save_project(p)
        got = store.get_project(p.id)
        assert got.name == "New Name"
        assert got.policy_text == "blur faces"
        assert got.exports_stale is True

    def test_delete_project(self, store):
        p = store.create_project("Doomed")
        pdir = store.project_dir(p.id)
        assert pdir.exists()
        store.delete_project(p.id)
        assert not pdir.exists()
        assert store.get_project(p.id) is None
        assert all(x.id != p.id for x in store.list_projects())

    def test_path_helper(self, store):
        p = store.create_project("Paths")
        f = store.path(p.id, "working", "normalized.mp4")
        assert str(f).endswith("normalized.mp4")
        assert store.project_dir(p.id) in f.parents


class TestRevision:
    def test_revision_persists(self, store):
        p = store.create_project("Rev")
        p.revision = 3
        store.save_project(p)
        assert store.get_project(p.id).revision == 3

    def test_revision_survives_new_store_instance(self, store, tmp_path):
        p = store.create_project("Rev2")
        p.revision = 7
        store.save_project(p)
        fresh = ProjectStore(tmp_path / "data")  # same dir as the `store` fixture
        assert fresh.get_project(p.id).revision == 7


def _make_events() -> list[RedactionEvent]:
    return [
        RedactionEvent(
            id="e_aaaaaaaaaa",
            kind="visual",
            category="face",
            status="pending",
            source="auto",
            start_s=1.0,
            end_s=2.5,
            action={"type": "pixelate", "strength": 65},
            confidence=0.83,
            track_id="t_bbbbbbbbbb",
            boxes=[
                {"t": 1.0, "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.3},
                {"t": 2.5, "x": 0.15, "y": 0.12, "w": 0.2, "h": 0.3},
            ],
            warnings=["rect_fallback"],
        ),
        RedactionEvent(
            id="e_cccccccccc",
            kind="audio",
            category="phone",
            status="confirmed",
            source="auto",
            start_s=3.2,
            end_s=4.1,
            action={"type": "beep"},
            confidence=0.95,
            text_preview="PHONE (last 2 digits hidden)",
        ),
    ]


class TestEvents:
    def test_events_roundtrip(self, store):
        p = store.create_project("Ev")
        events = _make_events()
        store.save_events(p.id, events)
        loaded = store.load_events(p.id)
        assert [e.id for e in loaded] == [e.id for e in events]
        vis = loaded[0]
        assert vis.kind == "visual"
        assert vis.track_id == "t_bbbbbbbbbb"
        assert len(vis.boxes) == 2
        assert vis.boxes[0].t == pytest.approx(1.0)
        assert vis.boxes[0].w == pytest.approx(0.2)
        assert vis.warnings == ["rect_fallback"]
        aud = loaded[1]
        assert aud.kind == "audio"
        assert aud.action == {"type": "beep"}
        assert aud.text_preview == "PHONE (last 2 digits hidden)"

    def test_load_events_missing_file(self, store):
        p = store.create_project("NoEvents")
        assert store.load_events(p.id) == []

    def test_save_overwrites(self, store):
        p = store.create_project("Overwrite")
        store.save_events(p.id, _make_events())
        store.save_events(p.id, _make_events()[:1])
        assert len(store.load_events(p.id)) == 1


class TestPolicy:
    def test_policy_roundtrip(self, store, sample_policy):
        p = store.create_project("Pol")
        store.save_policy(p.id, sample_policy)
        loaded = store.load_policy(p.id)
        assert loaded is not None
        assert {t.category for t in loaded.visual_targets} == {"face", "license_plate"}
        assert {t.category for t in loaded.audio_targets} == {"phone", "email", "address"}

    def test_load_policy_missing(self, store):
        p = store.create_project("NoPol")
        assert store.load_policy(p.id) is None


class TestJobsIndex:
    def _job(self, pid: str, jid: str = "j_0123456789") -> Job:
        return Job(
            id=jid,
            project_id=pid,
            type="analysis",
            status="queued",
            created_at=_iso_now(),
        )

    def test_save_and_get_job(self, store):
        p = store.create_project("Jobs")
        job = self._job(p.id)
        store.save_job(job)
        got = store.get_job(job.id)
        assert got is not None
        assert got.project_id == p.id
        assert got.type == "analysis"

    def test_jobs_listed_per_project(self, store):
        p = store.create_project("Jobs2")
        store.save_job(self._job(p.id, "j_aaaaaaaaaa"))
        store.save_job(self._job(p.id, "j_bbbbbbbbbb"))
        jobs = store.load_jobs(p.id)
        assert {j.id for j in jobs} >= {"j_aaaaaaaaaa", "j_bbbbbbbbbb"}

    def test_jobs_index_survives_new_instance(self, store, tmp_path):
        p = store.create_project("Jobs3")
        job = self._job(p.id, "j_cccccccccc")
        store.save_job(job)
        fresh = ProjectStore(tmp_path / "data")
        got = fresh.get_job("j_cccccccccc")
        assert got is not None and got.project_id == p.id

    def test_job_update_roundtrip(self, store):
        p = store.create_project("Jobs4")
        job = self._job(p.id, "j_dddddddddd")
        store.save_job(job)
        job.status = "running"
        job.progress = 0.5
        job.stage = "DETECTING_VISUAL"
        job.metrics = {"DETECTING_VISUAL": {"wall_s": 1.5, "peak_vram_mb": 900}}
        store.save_job(job)
        got = store.get_job(job.id)
        assert got.status == "running"
        assert got.progress == pytest.approx(0.5)
        assert got.metrics["DETECTING_VISUAL"]["peak_vram_mb"] == 900

    def test_get_missing_job(self, store):
        assert store.get_job("j_nosuchjob00") is None


class TestReviewHistory:
    def test_append_review_history(self, store):
        p = store.create_project("Hist")
        store.append_review_history(p.id, {"action": "confirm", "event_id": "e_x"})
        store.append_review_history(p.id, {"action": "ignore", "event_id": "e_y"})
        hist_file = store.project_dir(p.id) / "review_history.jsonl"
        assert hist_file.exists()
        lines = [ln for ln in hist_file.read_text().splitlines() if ln.strip()]
        assert len(lines) == 2
