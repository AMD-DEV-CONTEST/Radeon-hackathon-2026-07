"""Tests for the audit builder (policycut/audit/builder.py).

Contract (CONTRACTS.md section 11): audit.json contains counts and per-event
metadata but NEVER text_preview / raw PII / transcripts / absolute host paths.
"""

from __future__ import annotations

import inspect
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from policycut.core.models import Project, RedactionEvent

SECRET = "SECRET_PREVIEW_PHONE_9138"


def _events() -> list[RedactionEvent]:
    return [
        RedactionEvent(
            id="e_aud0000001",
            kind="audio",
            category="phone",
            status="confirmed",
            source="auto",
            start_s=1.0,
            end_s=2.0,
            action={"type": "mute"},
            confidence=0.9,
            text_preview=SECRET,  # must never surface in audit.json
        ),
        RedactionEvent(
            id="e_aud0000002",
            kind="visual",
            category="face",
            status="ignored",
            source="auto",
            start_s=0.5,
            end_s=3.0,
            action={"type": "pixelate", "strength": 65},
            confidence=0.7,
            track_id="t_aud0000001",
            warnings=["rect_fallback"],
        ),
        RedactionEvent(
            id="e_aud0000003",
            kind="visual",
            category="manual",
            status="confirmed",
            source="manual",
            start_s=2.0,
            end_s=4.0,
            action={"type": "solid", "strength": 100},
            manual_fixed_region=True,
        ),
    ]


def _project(pid: str) -> Project:
    now = datetime.now(timezone.utc).isoformat()
    return Project(id=pid, name="Audit Demo", status="rendering",
                   created_at=now, updated_at=now, policy_text="blur faces, mute phones",
                   revision=5)


@pytest.fixture()
def audit(store, sample_policy, tmp_path):
    """Build an audit dict through build_audit with signature-tolerant binding."""
    from policycut.audit import builder as builder_mod

    fn = getattr(builder_mod, "build_audit", None)
    assert callable(fn), "policycut.audit.builder must expose build_audit"

    project = store.create_project("Audit Demo")
    pid = project.id
    project.policy_text = "blur faces, mute phones"
    project.revision = 5
    store.save_project(project)
    events = _events()
    store.save_events(pid, events)
    store.save_policy(pid, sample_policy)
    store.append_review_history(pid, {"action": "confirm", "event_id": "e_aud0000001"})
    # fake media files so sha256 computation has something to hash
    for parts in (("source", "original.mp4"), ("working", "normalized.mp4"),
                  ("exports", "redacted.mp4")):
        p = store.path(pid, *parts)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"fake-video-bytes-" + parts[-1].encode())

    stage_metrics = {
        "DETECTING_VISUAL": {"wall_s": 1.5, "peak_vram_mb": 900, "frames": 20,
                             "effective_fps": 13.3, "precision": "fp16", "fallbacks": []},
        "TRACKING": {"wall_s": 2.0, "peak_vram_mb": 1100, "frames": 120,
                     "effective_fps": 60.0, "precision": "fp16",
                     "fallbacks": ["rect_fallback"]},
    }
    pool = {
        "project": project, "proj": project,
        "project_id": pid, "pid": pid,
        "store": store,
        "events": events,
        "policy": sample_policy, "spec": sample_policy, "policy_spec": sample_policy,
        "stage_metrics": stage_metrics, "metrics": stage_metrics,
        "input_info": {"sha256": "a" * 64, "duration_s": 5.0, "resolution": "640x360"},
        "output_info": {"sha256": "b" * 64, "duration_s": 5.0, "resolution": "640x360"},
        "input": {"sha256": "a" * 64, "duration_s": 5.0, "resolution": "640x360"},
        "output": {"sha256": "b" * 64, "duration_s": 5.0, "resolution": "640x360"},
        "input_path": store.path(pid, "source", "original.mp4"),
        "output_path": store.path(pid, "exports", "redacted.mp4"),
        "models": [{"stage": "DETECTING_VISUAL", "model_id": "IDEA-Research/grounding-dino-tiny",
                    "precision": "fp16", "device": "cpu"}],
        "environment": {"gpu_name": "cpu", "rocm_version": None,
                        "torch_version": "n/a", "python": "3.12"},
        "env": {"gpu_name": "cpu", "rocm_version": None,
                "torch_version": "n/a", "python": "3.12"},
        "review_history_count": 1,
        "warnings": ["whisper_unavailable"],
    }
    try:
        from policycut.config import get_settings

        pool["settings"] = get_settings()
    except Exception:
        pool["settings"] = None
    sig = inspect.signature(fn)
    kwargs = {}
    missing = []
    for name, param in sig.parameters.items():
        if name in pool:
            kwargs[name] = pool[name]
        elif param.default is inspect.Parameter.empty and param.kind in (
            param.POSITIONAL_OR_KEYWORD, param.KEYWORD_ONLY,
        ):
            missing.append(name)
    assert not missing, f"build_audit has unrecognized required params: {missing}"
    result = fn(**kwargs)
    if result is None:
        audit_path = store.path(pid, "exports", "audit.json")
        assert Path(audit_path).exists(), "build_audit returned None and wrote no audit.json"
        result = json.loads(Path(audit_path).read_text())
    if hasattr(result, "model_dump"):
        result = result.model_dump()
    assert isinstance(result, dict)
    return result, tmp_path


class TestAuditContent:
    def test_counts(self, audit):
        data, _ = audit
        assert "counts" in data
        counts = data["counts"]
        assert counts["auto"] == 2
        assert counts["manual"] == 1
        assert counts["confirmed"] == 2
        assert counts["ignored"] == 1

    def test_events_present_with_metadata(self, audit):
        data, _ = audit
        events = data["events"]
        assert len(events) == 3
        ids = {e["id"] for e in events}
        assert ids == {"e_aud0000001", "e_aud0000002", "e_aud0000003"}
        for e in events:
            assert "kind" in e and "category" in e
            assert "start_s" in e and "end_s" in e
            assert "action" in e and "status" in e

    def test_schema_version_present(self, audit):
        data, _ = audit
        assert data.get("schema_version")


class TestAuditPrivacy:
    def test_text_preview_excluded(self, audit):
        data, _ = audit
        for e in data["events"]:
            assert "text_preview" not in e, "audit events must not carry text_preview"

    def test_no_pii_text_anywhere(self, audit):
        data, _ = audit
        dump = json.dumps(data)
        assert SECRET not in dump, "raw preview text leaked into audit.json"

    def test_no_absolute_paths(self, audit):
        data, tmp_path = audit
        dump = json.dumps(data)
        assert str(tmp_path) not in dump, "temp data dir path leaked into audit.json"
        assert str(Path.home()) not in dump, "home directory leaked into audit.json"
        assert "/Users/" not in dump and "C:\\\\Users" not in dump

    def test_no_raw_transcript_key(self, audit):
        data, _ = audit
        assert "transcript" not in {k.lower() for k in data.keys()}
