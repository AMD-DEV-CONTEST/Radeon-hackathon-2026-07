import io
import pytest
from PIL import Image

from content_studio.core.comfy import ComfyClient, ComfyError
from content_studio.styles.registry import get_preset


def _png_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (1, 2, 3)).save(buf, "PNG")
    return buf.getvalue()


class FakeResp:
    def __init__(self, status_code=200, json_data=None, content=b""):
        self.status_code = status_code
        self._json = json_data
        self.content = content
        self.text = ""
    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


class FakeHttp:
    """按 (method, url 片段) 路由到预设响应。"""
    def __init__(self):
        self.calls = []
        self.routes = {}
    def add(self, method, frag, resp):
        self.routes[(method, frag)] = resp
    def _match(self, method, url, **kw):
        self.calls.append((method, url))
        for (m, frag), resp in self.routes.items():
            if m == method and frag in url:
                return resp
        return FakeResp(404)
    def post(self, url, **kw):
        return self._match("post", url)
    def get(self, url, **kw):
        return self._match("get", url)


def test_style_transfer_returns_image(tmp_path):
    dummy = tmp_path / "dummy.png"
    dummy.write_bytes(_png_bytes())
    http = FakeHttp()
    http.add("post", "/upload/image", FakeResp(json_data={"name": "up.png"}))
    http.add("post", "/prompt", FakeResp(json_data={"prompt_id": "p1"}))
    http.add("get", "/history/p1", FakeResp(json_data={
        "p1": {"outputs": {"9": {"images": [{"filename": "out.png", "subfolder": "", "type": "output"}]}}}}))
    http.add("get", "/view", FakeResp(content=_png_bytes()))
    c = ComfyClient("http://x:8188", http=http, sleeper=lambda _s: None)
    img = c.style_transfer(dummy, get_preset("anime"))
    assert img.size == (8, 8)


def test_text_to_image_returns_image():
    http = FakeHttp()
    http.add("post", "/prompt", FakeResp(json_data={"prompt_id": "p2"}))
    http.add("get", "/history/p2", FakeResp(json_data={
        "p2": {"outputs": {"9": {"images": [{"filename": "o2.png"}]}}}}))
    http.add("get", "/view", FakeResp(content=_png_bytes()))
    c = ComfyClient("http://x:8188", http=http, sleeper=lambda _s: None)
    img = c.text_to_image("a cat in tokyo", get_preset("cyberpunk"))
    assert img.size == (8, 8)


def test_submit_failure_raises():
    http = FakeHttp()
    http.add("post", "/prompt", FakeResp(500))
    c = ComfyClient("http://x:8188", http=http, sleeper=lambda _s: None)
    with pytest.raises(ComfyError):
        c.run_workflow({"3": {"class_type": "KSampler", "inputs": {"seed": 0}}})


def test_timeout_raises():
    http = FakeHttp()
    http.add("post", "/prompt", FakeResp(json_data={"prompt_id": "p3"}))
    http.add("get", "/history/p3", FakeResp(json_data={}))  # 永远空
    c = ComfyClient("http://x:8188", http=http, timeout=0.05, sleeper=lambda _s: None, poll_interval=0.01)
    with pytest.raises(ComfyError):
        c.run_workflow({"3": {"class_type": "KSampler", "inputs": {"seed": 0}}})


import httpx


def test_network_error_becomes_comfyerror(tmp_path):
    class NetErrHttp:
        def post(self, url, **kw):
            raise httpx.ConnectError("connection refused")
        def get(self, url, **kw):
            raise httpx.ConnectError("connection refused")
    p = tmp_path / "a.png"
    Image.new("RGB", (8, 8)).save(p, "PNG")
    c = ComfyClient("http://127.0.0.1:8188", http=NetErrHttp())
    with pytest.raises(ComfyError):  # 而不是 httpx.ConnectError
        c.style_transfer(str(p), get_preset("anime"))
