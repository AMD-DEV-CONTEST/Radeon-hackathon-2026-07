"""API tests for the PolicyCut FastAPI app (contract section 8).

Runs against create_app() with a temporary data dir and POLICYCUT_NO_LLM=1.
Must pass without torch/ffmpeg: the upload test monkeypatches the ffprobe
wrapper to return a fake MediaInfo and stubs out any subprocess calls.
"""

from __future__ import annotations

import importlib
import inspect
import subprocess
import sys
from types import SimpleNamespace

import pytest

# The upload endpoint declares multipart File params, which makes FastAPI
# require python-multipart at route-registration time (create_app raises
# without it). It is a runtime dependency of the app (in pyproject), not a
# test-only extra: skip cleanly on machines that lack it.
try:  # pragma: no cover - import probe
    import multipart  # noqa: F401  (python-multipart < 0.0.13)
except ImportError:
    try:
        import python_multipart  # noqa: F401  (python-multipart >= 0.0.13)
    except ImportError:
        pytest.skip(
            "python-multipart not installed (required by the upload API)",
            allow_module_level=True,
        )

API = "/api/v1"


def _purge_policycut_modules():
    for name in [m for m in list(sys.modules) if m == "policycut" or m.startswith("policycut.")]:
        del sys.modules[name]


@pytest.fixture()
def client(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setenv("POLICYCUT_DATA_DIR", str(data_dir))
    monkeypatch.setenv("POLICYCUT_NO_LLM", "1")
    monkeypatch.setenv("POLICYCUT_REQUIRE_ROCM", "0")
    # fresh import so the Settings singleton picks up the temp data dir
    _purge_policycut_modules()

    from policycut.api.app import create_app

    sig = inspect.signature(create_app)
    kwargs = {}
    for name in sig.parameters:
        if name in ("data_dir",):
            kwargs[name] = data_dir
        elif name == "settings":
            try:
                from policycut.config import get_settings

                s = get_settings()
                s.data_dir = data_dir
                kwargs[name] = s
            except Exception:
                pass
    app = create_app(**kwargs)

    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c


def _make_project(client, name="Test Project") -> dict:
    r = client.post(f"{API}/projects", json={"name": name})
    assert r.status_code in (200, 201), r.text
    return r.json()


class TestHealthAndSystem:
    def test_health(self, client):
        r = client.get(f"{API}/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert "version" in body

    def test_system(self, client):
        r = client.get(f"{API}/system")
        assert r.status_code == 200
        body = r.json()
        assert "gpu" in body
        assert "models" in body
        assert "ffmpeg" in body


class TestProjectCrud:
    def test_create_and_get(self, client):
        p = _make_project(client, "My Clip")
        assert p["id"].startswith("p_")
        assert p["name"] == "My Clip"
        assert p["status"] == "draft"
        r = client.get(f"{API}/projects/{p['id']}")
        assert r.status_code == 200
        assert r.json()["id"] == p["id"]

    def test_list(self, client):
        p = _make_project(client)
        r = client.get(f"{API}/projects")
        assert r.status_code == 200
        ids = [x["id"] for x in r.json()["projects"]]
        assert p["id"] in ids

    def test_patch_rename(self, client):
        p = _make_project(client, "Before")
        r = client.patch(f"{API}/projects/{p['id']}", json={"name": "After"})
        assert r.status_code == 200
        assert r.json()["name"] == "After"

    def test_delete(self, client):
        p = _make_project(client)
        r = client.delete(f"{API}/projects/{p['id']}")
        assert r.status_code == 204
        assert client.get(f"{API}/projects/{p['id']}").status_code == 404

    def test_get_missing_404(self, client):
        assert client.get(f"{API}/projects/p_nope1234567").status_code == 404


class TestPolicy:
    def test_parse_keyword_fallback(self, client):
        p = _make_project(client)
        r = client.post(
            f"{API}/projects/{p['id']}/policy/parse",
            json={"text": "Blur all faces. Mute phone numbers."},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["source"] == "keyword_fallback"
        spec = body["spec"]
        vcats = {t["category"] for t in spec["visual_targets"]}
        acats = {t["category"] for t in spec["audio_targets"]}
        assert "face" in vcats
        assert "phone" in acats

    def test_parse_negation(self, client):
        p = _make_project(client)
        r = client.post(
            f"{API}/projects/{p['id']}/policy/parse",
            json={"text": "Blur faces and screens. Do not blur screens."},
        )
        assert r.status_code == 200
        vcats = {t["category"] for t in r.json()["spec"]["visual_targets"]}
        assert "face" in vcats and "screen" not in vcats

    def test_put_policy(self, client):
        p = _make_project(client)
        parsed = client.post(
            f"{API}/projects/{p['id']}/policy/parse",
            json={"text": "Pixelate faces, beep emails."},
        ).json()["spec"]
        r = client.put(f"{API}/projects/{p['id']}/policy", json=parsed)
        assert r.status_code == 200, r.text
        saved = r.json()
        saved_spec = saved.get("spec", saved)
        assert {t["category"] for t in saved_spec["visual_targets"]} == \
               {t["category"] for t in parsed["visual_targets"]}

    def test_put_invalid_policy_rejected(self, client):
        p = _make_project(client)
        r = client.put(
            f"{API}/projects/{p['id']}/policy",
            json={"schema_version": "1.0", "visual_targets": [{"category": "alien"}]},
        )
        assert r.status_code in (400, 422)


def _manual_event_payload(expected_revision: int) -> dict:
    return {
        "kind": "visual",
        "category": "manual",
        "start_s": 1.0,
        "end_s": 2.0,
        "action": {"type": "blur", "strength": 50},
        "boxes": [
            {"t": 1.0, "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2},
            {"t": 2.0, "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2},
        ],
        "expected_revision": expected_revision,
    }


def _event_from_response(body: dict) -> dict:
    return body.get("event", body)


class TestEvents:
    def test_initial_events_empty(self, client):
        p = _make_project(client)
        r = client.get(f"{API}/projects/{p['id']}/events")
        assert r.status_code == 200
        body = r.json()
        assert body["events"] == []
        assert body["revision"] == 0

    def test_create_manual_event(self, client):
        p = _make_project(client)
        r = client.post(f"{API}/projects/{p['id']}/events", json=_manual_event_payload(0))
        assert r.status_code in (200, 201), r.text
        ev = _event_from_response(r.json())
        assert ev["id"].startswith("e_")
        assert ev["source"] == "manual"
        body = client.get(f"{API}/projects/{p['id']}/events").json()
        assert len(body["events"]) == 1
        assert body["revision"] >= 1

    def test_patch_event_revision_conflict_409(self, client):
        p = _make_project(client)
        r = client.post(f"{API}/projects/{p['id']}/events", json=_manual_event_payload(0))
        ev = _event_from_response(r.json())
        # revision advanced to 1 by the create; stale expected_revision=0 must 409
        r2 = client.patch(
            f"{API}/projects/{p['id']}/events/{ev['id']}",
            json={"status": "confirmed", "expected_revision": 0},
        )
        assert r2.status_code == 409, r2.text

    def test_patch_event_with_correct_revision(self, client):
        p = _make_project(client)
        client.post(f"{API}/projects/{p['id']}/events", json=_manual_event_payload(0))
        body = client.get(f"{API}/projects/{p['id']}/events").json()
        rev = body["revision"]
        eid = body["events"][0]["id"]
        r = client.patch(
            f"{API}/projects/{p['id']}/events/{eid}",
            json={"status": "confirmed", "expected_revision": rev},
        )
        assert r.status_code == 200, r.text
        assert _event_from_response(r.json())["status"] == "confirmed"
        assert client.get(f"{API}/projects/{p['id']}/events").json()["revision"] > rev

    def test_delete_manual_event(self, client):
        p = _make_project(client)
        client.post(f"{API}/projects/{p['id']}/events", json=_manual_event_payload(0))
        body = client.get(f"{API}/projects/{p['id']}/events").json()
        eid = body["events"][0]["id"]
        rev = body["revision"]
        r = client.delete(
            f"{API}/projects/{p['id']}/events/{eid}?expected_revision={rev}"
        )
        assert r.status_code == 204, r.text
        assert client.get(f"{API}/projects/{p['id']}/events").json()["events"] == []

    def test_confirm_all(self, client):
        p = _make_project(client)
        client.post(f"{API}/projects/{p['id']}/events", json=_manual_event_payload(0))
        body = client.get(f"{API}/projects/{p['id']}/events").json()
        rev = body["revision"]
        client.post(
            f"{API}/projects/{p['id']}/events",
            json={**_manual_event_payload(rev), "start_s": 3.0, "end_s": 4.0},
        )
        body = client.get(f"{API}/projects/{p['id']}/events").json()
        pending_before = sum(1 for e in body["events"] if e["status"] == "pending")
        r = client.post(
            f"{API}/projects/{p['id']}/review/confirm-all",
            json={"expected_revision": body["revision"]},
        )
        assert r.status_code == 200, r.text
        out = r.json()
        assert out["confirmed"] == pending_before
        assert "revision" in out
        after = client.get(f"{API}/projects/{p['id']}/events").json()
        assert all(e["status"] != "pending" for e in after["events"])


class TestUpload:
    @pytest.fixture()
    def fake_probe(self, monkeypatch):
        """Monkeypatch the ffprobe wrapper to return a fake MediaInfo."""
        from policycut.core.models import MediaInfo

        fake = MediaInfo(
            filename="clip.mp4",
            duration_s=5.0,
            width=640,
            height=360,
            fps=25.0,
            codec="h264",
            has_audio=False,
            audio_codec=None,
            size_bytes=64,
            rotation=0,
        )

        def fake_probe_fn(*args, **kwargs):
            return fake

        patched = 0
        for mod_name in ("policycut.media.probe", "policycut.api.projects",
                         "policycut.media.normalize"):
            try:
                mod = importlib.import_module(mod_name)
            except Exception:
                continue
            for attr in dir(mod):
                if attr.startswith("_"):
                    continue
                obj = getattr(mod, attr)
                if callable(obj) and not inspect.isclass(obj) and "probe" in attr.lower():
                    monkeypatch.setattr(mod, attr, fake_probe_fn)
                    patched += 1
                if callable(obj) and not inspect.isclass(obj) and "thumbnail" in attr.lower():
                    monkeypatch.setattr(mod, attr, lambda *a, **k: None)
        assert patched >= 1, "no probe function found to monkeypatch"

        # never let the upload path shell out (no ffmpeg in unit tests)
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **k: SimpleNamespace(returncode=0, stdout=b"", stderr=b""),
        )
        return fake

    def test_upload_source(self, client, fake_probe):
        p = _make_project(client)
        payload = b"\x00\x00\x00\x18ftypmp42-fake-tiny-video-bytes"
        r = client.post(
            f"{API}/projects/{p['id']}/source",
            files={"file": ("clip.mp4", payload, "video/mp4")},
        )
        assert r.status_code in (200, 201), r.text
        proj = r.json()
        assert proj["media"] is not None
        assert proj["media"]["duration_s"] == pytest.approx(5.0)
        assert proj["media"]["width"] == 640

    def test_media_endpoint_after_upload(self, client, fake_probe):
        p = _make_project(client)
        client.post(
            f"{API}/projects/{p['id']}/source",
            files={"file": ("clip.mp4", b"fake-bytes", "video/mp4")},
        )
        r = client.get(f"{API}/projects/{p['id']}/media")
        assert r.status_code == 200
        assert r.json()["fps"] == pytest.approx(25.0)
