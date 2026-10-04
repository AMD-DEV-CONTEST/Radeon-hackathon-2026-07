import time
from fastapi.testclient import TestClient
from content_studio.web.app import create_app


def _client():
    return TestClient(create_app())


def test_index_returns_form():
    c = _client()
    r = c.get("/")
    assert r.status_code == 200
    assert "Generate" in r.text
    assert "动漫风" in r.text or "anime" in r.text   # 风格出现在页面


def test_styles_endpoint():
    c = _client()
    r = c.get("/styles")
    assert r.status_code == 200
    ids = [s["id"] for s in r.json()]
    assert "anime" in ids and "cyberpunk" in ids


def test_job_lifecycle():
    from content_studio.web import jobs
    j = jobs.create_job()
    assert jobs.get_job(j.id) is not None
    jobs.update_job(j.id, stage="done", progress=1.0)
    assert jobs.get_job(j.id).stage == "done"


import io
from PIL import Image
from content_studio.web import routes


def _png():
    buf = io.BytesIO(); Image.new("RGB", (50, 50), (9, 9, 9)).save(buf, "PNG"); return buf.getvalue()


def _fake_pipeline_factory(result):
    def fake(material, image_paths, styles, cfg, generator, comfy=None, target="wechat", t2i_count=0, t2i_prompt="", progress=lambda s, p: None):
        progress("llm", 0.5); progress("done", 1.0)
        return result
    return fake


def test_generate_creates_job_and_completes(monkeypatch):
    from content_studio.core.pipeline import PipelineResult, BuiltArticle, BuiltXHS
    art = BuiltArticle(title="标题", summary="摘要", body_html="<p>正文</p>",
                       image_captions=["c1"], images=[Image.new("RGB", (40, 40))])
    result = PipelineResult(wechat=art, xhs=BuiltXHS(title="X", body="b", images=[Image.new("RGB", (40, 40))]), used_comfyui=True, warnings=[])
    monkeypatch.setattr(routes, "run_pipeline", _fake_pipeline_factory(result))

    c = _client()
    r = c.post("/generate", data={"theme": "t", "text": "x", "styles": "none"},
               files={"images": ("a.png", _png(), "image/png")})
    assert r.status_code == 200
    job_id = r.json()["job_id"]

    done = False
    for _ in range(100):
        j = c.get(f"/job/{job_id}").json()
        if j["stage"] == "done":
            done = True; break
        time.sleep(0.05)
    assert done

    img = c.get(f"/job/{job_id}/image/0")
    assert img.status_code == 200
    assert img.headers["content-type"].startswith("image/")

    prev = c.get(f"/job/{job_id}/preview")
    assert prev.status_code == 200
    assert "标题" in prev.text


def test_generate_missing_images_returns_400():
    c = _client()
    r = c.post("/generate", data={"theme": "t"}, files=[])
    assert r.status_code == 400


def test_job_not_found():
    c = _client()
    assert c.get("/job/does-not-exist").status_code == 404


def test_publish_calls_publisher(monkeypatch):
    from content_studio.core.pipeline import PipelineResult, BuiltArticle, BuiltXHS
    import io
    from PIL import Image
    art = BuiltArticle(title="T", summary="S", body_html="<p>x</p>", images=[Image.new("RGB",(20,20))])
    monkeypatch.setattr(routes, "run_pipeline", _fake_pipeline_factory(
        PipelineResult(wechat=art, xhs=BuiltXHS(), used_comfyui=False, warnings=[])))

    class FakePub:
        def __init__(self, *a, **k): pass
        def upload_cover_material(self, path): return "COVER"
        def upload_body_image(self, path): return "http://img/1"
        def create_draft(self, article):
            assert article["title"] == "T"
            assert article["thumb_media_id"] == "COVER"
            return "MEDIA123"
    monkeypatch.setattr(routes, "WeChatPublisher", FakePub)
    monkeypatch.setattr(routes, "load_config", lambda: load_config_for_settings("id", "secret"))

    c = _client()
    r = c.post("/generate", data={"theme": "t", "text": "x", "styles": "none"},
               files={"images": ("a.png", _png(), "image/png")})
    jid = r.json()["job_id"]
    for _ in range(100):
        if c.get(f"/job/{jid}").json()["stage"] == "done":
            break
        time.sleep(0.05)
    pub = c.post(f"/job/{jid}/publish", json={"body_html": "<p>x</p>"})
    assert pub.status_code == 200
    assert pub.json()["media_id"] == "MEDIA123"


def test_publish_without_credentials_returns_400(monkeypatch):
    from content_studio.core.pipeline import PipelineResult, BuiltArticle, BuiltXHS
    from PIL import Image
    art = BuiltArticle(title="T", images=[Image.new("RGB", (20, 20))])
    monkeypatch.setattr(routes, "run_pipeline", _fake_pipeline_factory(
        PipelineResult(wechat=art, xhs=BuiltXHS(), used_comfyui=False, warnings=[])))
    monkeypatch.setattr(routes, "load_config", lambda: load_config_for_settings(app_id="", app_secret=""))

    c = _client()
    r = c.post("/generate", data={"theme": "t", "text": "x", "styles": "none"},
               files={"images": ("a.png", _png(), "image/png")})
    jid = r.json()["job_id"]
    for _ in range(100):
        if c.get(f"/job/{jid}").json()["stage"] == "done":
            break
        time.sleep(0.05)
    pub = c.post(f"/job/{jid}/publish")
    assert pub.status_code == 400


def load_config_for_settings(app_id, app_secret):
    from content_studio.config import default_config, WeChatConfig
    cfg = default_config()
    cfg.wechat = WeChatConfig(app_id=app_id, app_secret=app_secret)
    return cfg


def test_settings_get_and_post():
    c = _client()
    g = c.get("/settings")
    assert g.status_code == 200
    assert "API" in g.text or "api" in g.text


def test_regenerate_creates_new_job_from_same_inputs(monkeypatch):
    from content_studio.core.pipeline import PipelineResult, BuiltArticle, BuiltXHS
    monkeypatch.setattr(routes, "run_pipeline", _fake_pipeline_factory(
        PipelineResult(wechat=BuiltArticle(title="T1"), xhs=BuiltXHS(), target="wechat")))
    c = _client()
    r = c.post("/generate", data={"theme": "t", "text": "x", "styles": "none"},
               files={"images": ("a.png", _png(), "image/png")})
    jid = r.json()["job_id"]
    for _ in range(100):
        if c.get(f"/job/{jid}").json()["stage"] == "done":
            break
        time.sleep(0.05)

    regen = c.post(f"/job/{jid}/regenerate")
    assert regen.status_code == 200
    nid = regen.json()["job_id"]
    assert nid != jid
    for _ in range(100):
        if c.get(f"/job/{nid}").json()["stage"] == "done":
            break
        time.sleep(0.05)
    # 新任务也带了 inputs（可再次重新生成）
    assert c.post(f"/job/{nid}/regenerate").status_code == 200
