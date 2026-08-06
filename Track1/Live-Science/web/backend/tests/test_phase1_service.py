"""Unit tests for the DeepSeek-backed Phase 1 service (mocked client + renderer)."""

import json
import types

import pytest

from app.services import phase1_service


class FakeClient:
    """OpenAI-compatible fake: client.chat.completions.create(...)."""

    def __init__(self, content: str):
        self._content = content

    @property
    def chat(self):
        return self

    @property
    def completions(self):
        return self

    def create(self, **kwargs):
        message = types.SimpleNamespace(content=self._content)
        choice = types.SimpleNamespace(message=message)
        return types.SimpleNamespace(choices=[choice])


class FakeRenderer:
    def __init__(self, manifest: dict):
        self.manifest = manifest

    def render(self, run_dir):
        (run_dir / "video.mp4").write_bytes(b"fake-mp4")
        (run_dir / "subtitles.srt").write_text("1\n00:00:00,000 --> 00:00:02,000\ntest\n")
        bridge = run_dir / "bridge"
        bridge.mkdir(exist_ok=True)
        (bridge / "manifest.json").write_text(json.dumps(self.manifest, ensure_ascii=False))
        return {
            "video": run_dir / "video.mp4",
            "poster": run_dir / "poster.png",
            "subtitles": run_dir / "subtitles.srt",
            "manifest": self.manifest,
            "run_dir": run_dir,
        }


def test_extract_json_strips_fences():
    data = phase1_service._extract_json('```json\n{"app": "x"}\n```')
    assert data == {"app": "x"}


def test_build_prompt_includes_request():
    system, user = phase1_service.build_prompt("How is an oxbow lake formed?")
    assert "How is an oxbow lake formed?" in user
    assert "LIVE_SCIENCE_BRIDGE" in user
    assert system.startswith("You are")


def test_phase1_run_returns_route(monkeypatch, tmp_path):
    monkeypatch.setattr(phase1_service, "DEEPSEEK_API_KEY", "test-key")
    payload = json.dumps({"app": "<html></html>", "subtitles": "1\n00:00:00,000 --> 00:00:02,000\nx"})
    manifest = {"route": "programmatic", "keyMoments": [], "events": []}
    svc = phase1_service.Phase1Service(
        client_factory=lambda: FakeClient(payload), renderer=FakeRenderer(manifest)
    )
    result = svc.run("testjob-1", "How is an oxbow lake formed?")
    assert result["manifest"]["route"] == "programmatic"
    assert result["video"].name == "video.mp4"
    assert result["run_dir"].exists()


def test_phase1_requires_api_key(monkeypatch, tmp_path):
    monkeypatch.setattr(phase1_service, "DEEPSEEK_API_KEY", "")
    svc = phase1_service.Phase1Service(
        client_factory=lambda: FakeClient("{}"), renderer=FakeRenderer({"route": "programmatic"})
    )
    with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY"):
        svc.run("testjob-2", "x")
