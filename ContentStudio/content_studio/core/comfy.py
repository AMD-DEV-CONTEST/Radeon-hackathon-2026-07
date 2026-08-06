"""ComfyUI HTTP 客户端：排队 workflow / 轮询 / 取图。"""
from __future__ import annotations

import copy
import random
import time
from io import BytesIO
from pathlib import Path
from typing import Any, Callable

import httpx
from PIL import Image

from content_studio.styles.registry import StylePreset, load_workflow


class ComfyError(Exception):
    pass


def _walk_replace(obj: Any, positive: str | None, input_image: str | None) -> Any:
    if isinstance(obj, dict):
        return {k: _walk_replace(v, positive, input_image) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_walk_replace(v, positive, input_image) for v in obj]
    if isinstance(obj, str):
        if positive is not None:
            obj = obj.replace("{positive}", positive)
        if input_image is not None:
            obj = obj.replace("{input_image}", input_image)
        return obj
    return obj


class ComfyClient:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8188",
        http: Any = None,
        timeout: float = 180,
        sleeper: Callable[[float], None] = time.sleep,
        poll_interval: float = 1.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._sleep = sleeper
        self._poll = poll_interval
        self._http = http if http is not None else httpx.Client(timeout=timeout)

    _NET_ERRORS = (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError, httpx.ProtocolError)

    def _post(self, url, **kw):
        try:
            return self._http.post(url, **kw)
        except self._NET_ERRORS as e:
            raise ComfyError(f"ComfyUI 网络错误（连不上/超时）: {e}") from e

    def _get(self, url, **kw):
        try:
            return self._http.get(url, **kw)
        except self._NET_ERRORS as e:
            raise ComfyError(f"ComfyUI 网络错误（连不上/超时）: {e}") from e

    def upload_image(self, path: str | Path) -> str:
        p = Path(path)
        # 大图先压缩到 ≤1MB（隧道/网络有大小限制）
        import io
        raw = p.read_bytes()
        if len(raw) > 1_000_000:
            im = Image.open(io.BytesIO(raw)).convert("RGB")
            if max(im.size) > 1024:
                im.thumbnail((1024, 1024))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=85)
            raw = buf.getvalue()
        files = {"image": (p.name, raw, "application/octet-stream")}
        r = self._post(f"{self.base_url}/upload/image", files=files)
        if r.status_code != 200:
            raise ComfyError(f"upload_image 失败: HTTP {r.status_code}")
        data = r.json()
        name = data.get("name") or data.get("filename")
        if not name:
            raise ComfyError(f"upload_image 无 filename: {data}")
        return name

    def submit(self, graph: dict) -> str:
        r = self._post(f"{self.base_url}/prompt", json={"prompt": graph})
        if r.status_code != 200:
            raise ComfyError(f"submit 失败: HTTP {r.status_code} {getattr(r, 'text', '')}")
        data = r.json()
        pid = data.get("prompt_id")
        if not pid:
            raise ComfyError(f"submit 无 prompt_id: {data}")
        return pid

    def wait_result(self, prompt_id: str) -> dict:
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            r = self._get(f"{self.base_url}/history/{prompt_id}")
            if r.status_code != 200:
                raise ComfyError(f"history 失败: HTTP {r.status_code}")
            data = r.json()
            if prompt_id in data:
                outputs = data[prompt_id].get("outputs", {}) or {}
                if outputs:
                    return outputs
            self._sleep(self._poll)
        raise ComfyError(f"等待 {prompt_id} 超时")

    def fetch_image(self, filename: str, subfolder: str = "", type: str = "output") -> Image.Image:
        params = {"filename": filename, "subfolder": subfolder, "type": type}
        r = self._get(f"{self.base_url}/view", params=params)
        if r.status_code != 200:
            raise ComfyError(f"view 失败: HTTP {r.status_code}")
        return Image.open(BytesIO(r.content)).convert("RGB")

    def _outputs_to_images(self, outputs: dict) -> list[Image.Image]:
        images: list[Image.Image] = []
        for node in outputs.values():
            for img in (node.get("images") or []):
                images.append(self.fetch_image(img.get("filename", ""), img.get("subfolder", ""), img.get("type", "output")))
        return images

    def run_workflow(self, graph: dict) -> list[Image.Image]:
        pid = self.submit(graph)
        outputs = self.wait_result(pid)
        imgs = self._outputs_to_images(outputs)
        if not imgs:
            raise ComfyError("workflow 未产出图片")
        return imgs

    @staticmethod
    def _inject(graph: dict, positive: str | None = None, input_image: str | None = None, seed: int | None = None) -> dict:
        g = _walk_replace(copy.deepcopy(graph), positive, input_image)
        if seed is not None:
            for node in g.values():
                if isinstance(node, dict) and node.get("class_type") == "KSampler":
                    node.setdefault("inputs", {})["seed"] = seed
        return g

    def style_transfer(self, image_path: str | Path, style: StylePreset) -> Image.Image:
        graph = load_workflow(style.workflow_style)
        fname = self.upload_image(image_path)
        g = self._inject(graph, positive=style.visual_keywords, input_image=fname, seed=random.randint(1, 10**9))
        return self.run_workflow(g)[0]

    def text_to_image(self, prompt: str, style: StylePreset) -> Image.Image:
        graph = load_workflow(style.workflow_t2i)
        full = f"{prompt}, {style.visual_keywords}"
        g = self._inject(graph, positive=full, seed=random.randint(1, 10**9))
        return self.run_workflow(g)[0]
