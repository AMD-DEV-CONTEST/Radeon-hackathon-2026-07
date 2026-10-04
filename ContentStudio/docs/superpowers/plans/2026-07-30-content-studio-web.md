# Content Studio · Web 版实现计划（AMD 赛道一）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把现有桌面 MVP 演进为 FastAPI Web 应用：网页输入「主题+照片+文字+预设风格」→ 云端 LLM 出公众号长文 → 本地 AMD GPU 的 ComfyUI 做风格迁移/文生图 → 真调公众号 API 发草稿箱。

**Architecture:** 复用 UI 无关的 `core/`；新增 `core/comfy.py`(ComfyUI 客户端)、`core/pipeline.py`(编排)、`publish/wechat.py`(草稿箱)、`styles/`(风格注册表+workflow 模板)、`web/`(FastAPI+Jinja2+内存任务表)。风格预设三合一驱动(ComfyUI 出图 + LLM 文风 + 文生图提示词)。ComfyUI 不可达时降级为原图。

**Tech Stack:** Python 3.12(`.venv-paddle`)、FastAPI、uvicorn、Jinja2、python-multipart、httpx、Pillow、openai、pytest。

## Global Constraints

- **Python 解释器固定为** `.\.venv-paddle\Scripts\python.exe`（已含 pip 25.0.1、httpx 0.28.1、requests、openai 2.50.0、PIL、cv2、paddleocr）。
- **所有命令在仓库根目录** `C:\Users\VPX01\Documents\Default Project` 下执行。
- **测试命令**：`.\.venv-paddle\Scripts\python.exe -m pytest -q`（现有 41 个测试必须始终通过）。
- **配置文件**：`~/.content_studio/config.json`（`Path.home()/.content_studio/config.json`）。
- **`core/`、`publish/`、`styles/` 不得 import 任何 UI 库**（fastapi/tkinter/customtkinter）。Web 依赖只在 `web/` 内 import。
- **ComfyUI 走 HTTP**（默认 `http://127.0.0.1:8188`），`comfy.py` 与部署方式解耦。
- **公众号**：草稿箱用 `/media/uploadimg`(正文图)、`/material/add_material`(封面)、`/draft/add`(建草稿)；token 过期前 5 分钟刷新；`40001` 刷新重试一次。
- **图片尺寸常量**（沿用现有 `image_pipeline`）：公众号封面 2.35:1=`900×383`；正文图最大宽 `900px`。
- **git 当前未安装**：Task 1 用 winget 安装并 `git init`；装完需**新终端**刷新 PATH。提交若提示缺少身份，按 Task 1 Step 4 设置**本地**身份。
- **不删**桌面 `gui/` 与 `main.py`；Web 入口为 `python -m content_studio.web.app`。
- **不主动 `git push`**。

---

## File Structure

| 文件 | 职责 |
|---|---|
| `requirements.txt` | 修改：追加 fastapi、uvicorn、jinja2、python-multipart |
| `content_studio/config.py` | 修改：新增 `ComfyConfig`，加入 `AppConfig` |
| `content_studio/styles/__init__.py` | 新建：包标记 |
| `content_studio/styles/registry.py` | 新建：`StylePreset` 注册表 + 加载 workflow |
| `content_studio/styles/workflows/anime.json` | 新建：风格迁移 workflow 模板(占位) |
| `content_studio/styles/workflows/anime_t2i.json` | 新建：文生图 workflow 模板(占位) |
| `content_studio/styles/workflows/cyberpunk.json` | 新建：风格迁移模板(占位) |
| `content_studio/styles/workflows/cyberpunk_t2i.json` | 新建：文生图模板(占位) |
| `content_studio/core/comfy.py` | 新建：ComfyUI HTTP 客户端 |
| `content_studio/core/prompts.py` | 修改：`build_wechat_prompt(material, style)` |
| `content_studio/core/generator.py` | 修改：`WeChatContent` 加 `image_prompts`；`generate_wechat(material, style)` |
| `content_studio/core/pipeline.py` | 新建：编排 LLM+ComfyUI+image_pipeline+降级 |
| `content_studio/publish/__init__.py` | 新建：包标记 |
| `content_studio/publish/wechat.py` | 新建：公众号草稿箱 |
| `content_studio/web/__init__.py` | 新建：包标记 |
| `content_studio/web/app.py` | 新建：FastAPI 实例 + uvicorn 入口 |
| `content_studio/web/jobs.py` | 新建：内存任务表 + 进度 |
| `content_studio/web/routes.py` | 新建：路由 |
| `content_studio/web/templates/index.html` | 新建：表单页 |
| `content_studio/web/templates/preview.html` | 新建：预览页 |
| `content_studio/web/templates/settings.html` | 新建：设置页 |
| `tests/test_config.py` | 修改：增 ComfyConfig 用例 |
| `tests/test_styles.py` | 新建 |
| `tests/test_comfy.py` | 新建 |
| `tests/test_prompts.py` | 修改：增 style 用例 |
| `tests/test_generator.py` | 修改：增 style + image_prompts 用例 |
| `tests/test_pipeline.py` | 新建 |
| `tests/test_publish_wechat.py` | 新建 |
| `tests/test_web_routes.py` | 新建 |

---

## Task 1: 环境与依赖

**Files:**
- Modify: `requirements.txt`
- Test: 无单测（验证 import + pytest 可用）

**Interfaces:**
- Produces: 可用 git 仓库；venv 内含 fastapi/uvicorn/jinja2/python-multipart；可 `import fastapi` 且现有 41 测试通过。

- [ ] **Step 1: 安装 git（winget）**

```powershell
winget install --id Git.Git -e --accept-source-agreements --accept-package-agreements
```
Expected: 安装成功或提示已安装。

- [ ] **Step 2: 在新终端验证 git**

Run: `git --version`
Expected: 输出 `git version ...`。若报找不到，**开新终端**重试（winget 装完需新进程刷新 PATH）。

- [ ] **Step 3: 初始化仓库**

Run: `git init`
Expected: `Initialized empty Git repository in ...`

- [ ] **Step 4: 配置本地 git 身份（仅在提交报错时）**

仅当后续提交提示缺少 user.name/user.email 时执行（仓库本地，不动全局）：
```powershell
git config user.name "Content Studio"
git config user.email "dev@content-studio.local"
```

- [ ] **Step 5: 安装 Web 依赖**

Run: `.\.venv-paddle\Scripts\python.exe -m pip install fastapi "uvicorn[standard]" jinja2 python-multipart`
Expected: `Successfully installed fastapi-... uvicorn-... jinja2-... python-multipart-...`

- [ ] **Step 6: 更新 requirements.txt**

在 `requirements.txt` 末尾追加：
```
fastapi
uvicorn[standard]
jinja2
python-multipart
```

- [ ] **Step 7: 验证 import 与现有测试**

Run: `.\.venv-paddle\Scripts\python.exe -c "import fastapi, uvicorn, jinja2, multipart; print('web deps ok')"`
Expected: `web deps ok`

Run: `.\.venv-paddle\Scripts\python.exe -m pytest -q`
Expected: `41 passed`

- [ ] **Step 8: 提交基线**

```bash
git add -A
git commit -m "chore: baseline desktop MVP + web dependencies"
```
Expected: 提交成功（若提示缺身份，回到 Step 4）。

---

## Task 2: 配置扩展 ComfyConfig

**Files:**
- Modify: `content_studio/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces:
  - `ComfyConfig(base_url="http://127.0.0.1:8188", enabled=True, style_transfer=True, t2i_count=1, timeout=180)`
  - `AppConfig` 新增字段 `comfy: ComfyConfig`
  - `default_config()` 含默认 `comfy`
  - `load_config`/`save_config` 正确读写 `comfy` 段（往返一致）

- [ ] **Step 1: 追加失败测试**

在 `tests/test_config.py` 末尾追加：
```python
from content_studio.config import ComfyConfig


def test_comfy_config_defaults():
    c = ComfyConfig()
    assert c.base_url == "http://127.0.0.1:8188"
    assert c.enabled is True
    assert c.style_transfer is True
    assert c.t2i_count == 1
    assert c.timeout == 180


def test_default_config_has_comfy():
    cfg = default_config()
    assert isinstance(cfg.comfy, ComfyConfig)
    assert cfg.comfy.base_url.startswith("http")


def test_comfy_round_trip(tmp_path: Path):
    path = tmp_path / "config.json"
    cfg = default_config()
    cfg.comfy.t2i_count = 3
    cfg.comfy.base_url = "http://gpu:8188"
    save_config(cfg, path)
    loaded = load_config(path)
    assert loaded.comfy.t2i_count == 3
    assert loaded.comfy.base_url == "http://gpu:8188"
```

- [ ] **Step 2: 运行验证失败**

Run: `.\.venv-paddle\Scripts\python.exe -m pytest tests/test_config.py -q`
Expected: FAIL（`AttributeError: ... has no attribute 'comfy'` 或导入失败）。

- [ ] **Step 3: 实现**

在 `content_studio/config.py` 中：
(a) 在 `WeChatConfig` 之后新增 dataclass：
```python
@dataclass
class ComfyConfig:
    base_url: str = "http://127.0.0.1:8188"
    enabled: bool = True
    style_transfer: bool = True
    t2i_count: int = 1
    timeout: int = 180
```
(b) 给 `AppConfig` 加字段（加在 `wechat` 之后）：
```python
    wechat: WeChatConfig = field(default_factory=WeChatConfig)
    comfy: ComfyConfig = field(default_factory=ComfyConfig)
```
(c) 在 `load_config` 的 `return AppConfig(...)` 前加解析，并在构造参数加 `comfy`：
```python
        comfy = ComfyConfig(**data.get("comfy", {}))
        return AppConfig(
            providers=providers,
            active_provider=data.get("active_provider", ""),
            image=image,
            ocr_enabled=data.get("ocr_enabled", False),
            wechat=wechat,
            comfy=comfy,
        )
```

- [ ] **Step 4: 运行验证通过**

Run: `.\.venv-paddle\Scripts\python.exe -m pytest tests/test_config.py -q`
Expected: `7 passed`（原 4 + 新 3）。

- [ ] **Step 5: 提交**

```bash
git add content_studio/config.py tests/test_config.py
git commit -m "feat(config): add ComfyConfig for ComfyUI endpoint and options"
```

---

## Task 3: 风格预设注册表 + workflow 模板

**Files:**
- Create: `content_studio/styles/__init__.py`, `content_studio/styles/registry.py`, 四个 workflow JSON
- Test: `tests/test_styles.py`

**Interfaces:**
- Produces:
  - `StylePreset(id, name, workflow_style, workflow_t2i, llm_tone, visual_keywords)`
  - `list_presets() -> list[StylePreset]`
  - `get_preset(style_id: str) -> StylePreset`（未找到抛 `ValueError`）
  - `load_workflow(filename: str) -> dict`（从 `styles/workflows/` 读 JSON）
  - 内置至少 2 个预设：`anime`、`cyberpunk`

- [ ] **Step 1: 写失败测试**

Create `tests/test_styles.py`:
```python
import pytest
from content_studio.styles.registry import (
    StylePreset, list_presets, get_preset, load_workflow,
)


def test_list_presets_has_at_least_two():
    ids = [p.id for p in list_presets()]
    assert "anime" in ids and "cyberpunk" in ids


def test_get_preset_returns_matching():
    p = get_preset("anime")
    assert isinstance(p, StylePreset)
    assert p.id == "anime"
    assert p.llm_tone and p.visual_keywords


def test_get_preset_unknown_raises():
    with pytest.raises(ValueError):
        get_preset("nope")


def test_load_workflow_has_placeholders():
    g = load_workflow("anime.json")
    assert isinstance(g, dict)
    assert any("{positive}" in str(v) for v in g.values())


def test_load_workflow_t2i_has_positive():
    g = load_workflow("anime_t2i.json")
    assert any("{positive}" in str(v) for v in g.values())
```

- [ ] **Step 2: 运行验证失败**

Run: `.\.venv-paddle\Scripts\python.exe -m pytest tests/test_styles.py -q`
Expected: FAIL（`ModuleNotFoundError: ... styles.registry`）。

- [ ] **Step 3: 实现注册表**

Create `content_studio/styles/__init__.py`:
```python
"""Style presets and ComfyUI workflow templates."""
```

Create `content_studio/styles/registry.py`:
```python
"""风格预设注册表 + workflow 加载。"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

WORKFLOWS_DIR = Path(__file__).resolve().parent / "workflows"


@dataclass
class StylePreset:
    id: str
    name: str
    workflow_style: str   # 文件名, 如 "anime.json"     风格迁移
    workflow_t2i: str     # 文件名, 如 "anime_t2i.json"  文生图
    llm_tone: str         # 喂给 LLM 的文风指令
    visual_keywords: str  # 拼进文生图正向提示的视觉关键词


_BUILTIN: list[StylePreset] = [
    StylePreset(
        id="anime", name="动漫风",
        workflow_style="anime.json", workflow_t2i="anime_t2i.json",
        llm_tone="活泼、有二次元感、多用感叹和短句",
        visual_keywords="anime style, vibrant colors, cel shading, detailed",
    ),
    StylePreset(
        id="cyberpunk", name="赛博朋克",
        workflow_style="cyberpunk.json", workflow_t2i="cyberpunk_t2i.json",
        llm_tone="酷炫、未来感、节奏紧凑",
        visual_keywords="cyberpunk, neon lights, futuristic, blade runner style",
    ),
]


def list_presets() -> list[StylePreset]:
    return list(_BUILTIN)


def get_preset(style_id: str) -> StylePreset:
    for p in _BUILTIN:
        if p.id == style_id:
            return p
    raise ValueError(f"未知风格: {style_id}")


def load_workflow(filename: str) -> dict:
    path = WORKFLOWS_DIR / filename
    return json.loads(path.read_text(encoding="utf-8"))
```

- [ ] **Step 4: 写 workflow 模板（占位，真实模型后续替换）**

Create `content_studio/styles/workflows/anime.json`:
```json
{
  "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "{model}"}},
  "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "{positive}", "clip": ["4", 0]}},
  "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "bad, blurry, lowres", "clip": ["4", 0]}},
  "10": {"class_type": "LoadImage", "inputs": {"image": "{input_image}"}},
  "3": {"class_type": "KSampler", "inputs": {"seed": 0, "steps": 25, "cfg": 7, "sampler_name": "euler", "scheduler": "normal", "denoise": 0.6, "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["10", 0]}},
  "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
  "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0]}}
}
```
Create `content_studio/styles/workflows/anime_t2i.json`（无 LoadImage，用 EmptyLatentImage）:
```json
{
  "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "{model}"}},
  "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "{positive}", "clip": ["4", 0]}},
  "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "bad, blurry, lowres", "clip": ["4", 0]}},
  "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 1024, "height": 1024, "batch_size": 1}},
  "3": {"class_type": "KSampler", "inputs": {"seed": 0, "steps": 30, "cfg": 7, "sampler_name": "euler", "scheduler": "normal", "denoise": 1.0, "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0]}},
  "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
  "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0]}}
}
```
Create `content_studio/styles/workflows/cyberpunk.json`：内容与 `anime.json` 相同（占位，后续换 LoRA/workflow）。
Create `content_studio/styles/workflows/cyberpunk_t2i.json`：内容与 `anime_t2i.json` 相同。

- [ ] **Step 5: 运行验证通过**

Run: `.\.venv-paddle\Scripts\python.exe -m pytest tests/test_styles.py -q`
Expected: `5 passed`

- [ ] **Step 6: 提交**

```bash
git add content_studio/styles tests/test_styles.py
git commit -m "feat(styles): style preset registry with placeholder ComfyUI workflows"
```

---

## Task 4: ComfyUI 客户端（core/comfy.py）

**Files:**
- Create: `content_studio/core/comfy.py`
- Test: `tests/test_comfy.py`

**Interfaces:**
- Consumes: `content_studio.styles.registry.StylePreset`、`load_workflow`
- Produces:
  - `ComfyError(Exception)`
  - `ComfyClient(base_url, http=None, timeout=180, sleeper=time.sleep, poll_interval=1.0)`
  - `ComfyClient.upload_image(path)->str`
  - `ComfyClient.submit(graph)->str`
  - `ComfyClient.wait_result(prompt_id)->dict`
  - `ComfyClient.fetch_image(filename, subfolder="", type="output")->PIL.Image`
  - `ComfyClient.run_workflow(graph)->list[PIL.Image]`
  - `ComfyClient.style_transfer(image_path, style)->PIL.Image`
  - `ComfyClient.text_to_image(prompt, style)->PIL.Image`
  - 注入用占位符：`{positive}` `{input_image}` `{seed}`；`{model}` 原样保留（部署期在模板里替换）

- [ ] **Step 1: 写失败测试**

Create `tests/test_comfy.py`:
```python
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


def test_style_transfer_returns_image():
    http = FakeHttp()
    http.add("post", "/upload/image", FakeResp(json_data={"name": "up.png"}))
    http.add("post", "/prompt", FakeResp(json_data={"prompt_id": "p1"}))
    http.add("get", "/history/p1", FakeResp(json_data={
        "p1": {"outputs": {"9": {"images": [{"filename": "out.png", "subfolder": "", "type": "output"}]}}}}))
    http.add("get", "/view", FakeResp(content=_png_bytes()))
    c = ComfyClient("http://x:8188", http=http, sleeper=lambda _s: None)
    img = c.style_transfer("dummy.png", get_preset("anime"))
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
```

- [ ] **Step 2: 运行验证失败**

Run: `.\.venv-paddle\Scripts\python.exe -m pytest tests/test_comfy.py -q`
Expected: FAIL（`ModuleNotFoundError: ... comfy`）。

- [ ] **Step 3: 实现 comfy.py**

Create `content_studio/core/comfy.py`:
```python
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

    def upload_image(self, path: str | Path) -> str:
        p = Path(path)
        with p.open("rb") as f:
            files = {"image": (p.name, f, "application/octet-stream")}
            r = self._http.post(f"{self.base_url}/upload/image", files=files)
        if r.status_code != 200:
            raise ComfyError(f"upload_image 失败: HTTP {r.status_code}")
        data = r.json()
        name = data.get("name") or data.get("filename")
        if not name:
            raise ComfyError(f"upload_image 无 filename: {data}")
        return name

    def submit(self, graph: dict) -> str:
        r = self._http.post(f"{self.base_url}/prompt", json={"prompt": graph})
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
            r = self._http.get(f"{self.base_url}/history/{prompt_id}")
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
        r = self._http.get(f"{self.base_url}/view", params=params)
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
```

- [ ] **Step 4: 运行验证通过**

Run: `.\.venv-paddle\Scripts\python.exe -m pytest tests/test_comfy.py -q`
Expected: `4 passed`

- [ ] **Step 5: 提交**

```bash
git add content_studio/core/comfy.py tests/test_comfy.py
git commit -m "feat(comfy): ComfyUI HTTP client with workflow injection and polling"
```

---

## Task 5: 扩展 prompts + generator（风格 + image_prompts）

**Files:**
- Modify: `content_studio/core/prompts.py`, `content_studio/core/generator.py`
- Test: `tests/test_prompts.py`, `tests/test_generator.py`

**Interfaces:**
- Produces:
  - `build_wechat_prompt(material: str, style: StylePreset | None = None) -> tuple[str, str]`
  - `WeChatContent` 新增字段 `image_prompts: list[str]`
  - `Generator.generate_wechat(self, material, style=None) -> WeChatContent`
  - 兼容：旧的无 style 调用与无 image_prompts 的 JSON 仍可用

- [ ] **Step 1: 追加失败测试**

在 `tests/test_prompts.py` 末尾追加：
```python
from content_studio.styles.registry import get_preset


def test_wechat_prompt_with_style_includes_tone():
    style = get_preset("anime")
    system, user = build_wechat_prompt("我的素材", style)
    assert style.llm_tone in system
    assert "image_prompts" in system
    assert "我的素材" in user
```

在 `tests/test_generator.py` 末尾追加：
```python
from content_studio.styles.registry import get_preset


def test_generate_wechat_with_style_and_image_prompts():
    c = FakeClient(['{"title":"T","summary":"S","body_html":"<p>x</p>",'
                    '"image_captions":["c1"],"image_prompts":["a cat","a robot"]}'])
    r = Generator(c).generate_wechat("素材", get_preset("anime"))
    assert r.title == "T"
    assert r.image_prompts == ["a cat", "a robot"]


def test_generate_wechat_without_image_prompts_is_empty_list():
    c = FakeClient(['{"title":"T"}'])
    r = Generator(c).generate_wechat("素材")
    assert r.image_prompts == []
```

- [ ] **Step 2: 运行验证失败**

Run: `.\.venv-paddle\Scripts\python.exe -m pytest tests/test_prompts.py tests/test_generator.py -q`
Expected: FAIL（断言失败：system 不含 `image_prompts`/`llm_tone`；`WeChatContent` 无 `image_prompts`）。

- [ ] **Step 3: 实现 prompts.py**

把 `content_studio/core/prompts.py` 的 `WECHAT_SYSTEM` 与 `build_wechat_prompt` 改为：
```python
"""公众号 / 小红书 的 prompt 构造。"""
from __future__ import annotations

from content_studio.styles.registry import StylePreset

WECHAT_SYSTEM = """你是一位资深微信公众号编辑。根据用户给的素材，写出公众号长文。
严格输出 JSON，键如下：
- title：标题
- summary：摘要，30 字以内
- body_html：正文，HTML 字符串，可用 <p> <h2> <strong> <br> 等标签，但不要 <html>/<body>
- image_captions：数组，为每张配图给的图注文字，可为空数组
- image_prompts：数组，为正文配图给出 1~3 条画面描述（英文，用于 AI 绘图），可为空数组
只输出 JSON，不要多余解释。"""

XHS_SYSTEM = """你是一位小红书爆款笔记写手。根据用户给的素材，写出小红书笔记。
严格输出 JSON，键如下：
- title：15 字以内的吸睛标题
- body：正文，多用 emoji 和换行，口语化
- hashtags：数组，形如 "#话题"
- cover_text：封面主标题，6 字以内
只输出 JSON，不要多余解释。"""


def build_wechat_prompt(material: str, style: StylePreset | None = None) -> tuple[str, str]:
    system = WECHAT_SYSTEM
    if style is not None:
        system = f"{WECHAT_SYSTEM}\n文风要求：{style.llm_tone}"
    return system, f"素材：\n{material}\n\n请生成公众号文章 JSON。"


def build_xhs_prompt(material: str) -> tuple[str, str]:
    return XHS_SYSTEM, f"素材：\n{material}\n\n请生成小红书笔记 JSON。"
```

- [ ] **Step 4: 实现 generator.py**

在 `content_studio/core/generator.py` 的 `WeChatContent` dataclass 加字段：
```python
    image_prompts: list[str] = field(default_factory=list)
```
（加在 `image_captions` 之后、`raw` 之前）

把 `generate_wechat` 改为接受可选 `style`，并解析 `image_prompts`：
```python
    def generate_wechat(self, material: str, style=None) -> WeChatContent:
        system, user = prompts.build_wechat_prompt(material, style)
        parsed, raw = self._complete_and_parse(system, user)
        if parsed is None:
            return WeChatContent(title="(解析失败)", body_html=raw, raw=raw, fell_back=True)
        return WeChatContent(
            title=parsed.get("title", ""),
            summary=parsed.get("summary", ""),
            body_html=parsed.get("body_html", ""),
            image_captions=list(parsed.get("image_captions") or []),
            image_prompts=list(parsed.get("image_prompts") or []),
            raw=raw,
        )
```

- [ ] **Step 5: 运行验证通过**

Run: `.\.venv-paddle\Scripts\python.exe -m pytest tests/test_prompts.py tests/test_generator.py -q`
Expected: prompts `4 passed`、generator `8 passed`（原 6 + 新 2）。

再跑全量回归：
Run: `.\.venv-paddle\Scripts\python.exe -m pytest -q`
Expected: 全部通过（无回归）。

- [ ] **Step 6: 提交**

```bash
git add content_studio/core/prompts.py content_studio/core/generator.py tests/test_prompts.py tests/test_generator.py
git commit -m "feat(generator): style-driven tone and image_prompts in wechat generation"
```

---

## Task 6: 生成管线编排（core/pipeline.py）

**Files:**
- Create: `content_studio/core/pipeline.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `Generator.generate_wechat`、`ComfyClient`（可 None）、`image_pipeline.build_wechat_images`、`AppConfig`、`StylePreset`
- Produces:
  - `BuiltArticle(title, summary, body_html, image_captions, images: list[PIL.Image])`
  - `PipelineResult(article: BuiltArticle, image_prompts: list[str], used_comfyui: bool, warnings: list[str])`
  - `run_pipeline(material, image_paths, style, cfg, generator, comfy=None, progress=lambda s,p:None) -> PipelineResult`
  - ComfyUI 失败 → 降级为原图（`used_comfyui=False`，`warnings` 记原因），不抛异常

- [ ] **Step 1: 写失败测试**

Create `tests/test_pipeline.py`:
```python
from PIL import Image

from content_studio.config import AppConfig, ComfyConfig, ImageConfig
from content_studio.core.comfy import ComfyError
from content_studio.core.generator import WeChatContent
from content_studio.core.pipeline import run_pipeline, PipelineResult, BuiltArticle
from content_studio.styles.registry import get_preset


def _cfg():
    cfg = AppConfig()
    cfg.comfy = ComfyConfig(enabled=True, t2i_count=1)
    cfg.image = ImageConfig()
    return cfg


class FakeGen:
    def __init__(self, content: WeChatContent):
        self._c = content
    def generate_wechat(self, material, style=None):
        return self._c


def _img_file(tmp_path, name="a.png"):
    p = tmp_path / name
    Image.new("RGB", (900, 900), (5, 6, 7)).save(p, "PNG")
    return str(p)


def test_pipeline_uses_comfy_when_available(tmp_path):
    wc = WeChatContent(title="T", summary="S", body_html="<p>x</p>",
                       image_captions=["c"], image_prompts=["a cat"])
    class FakeComfy:
        def style_transfer(self, path, style):
            return Image.new("RGB", (1000, 700), (1, 1, 1))
        def text_to_image(self, prompt, style):
            return Image.new("RGB", (1024, 1024), (2, 2, 2))
    stages = []
    res = run_pipeline("m", [_img_file(tmp_path)], get_preset("anime"), _cfg(),
                       FakeGen(wc), FakeComfy(), progress=lambda s, p: stages.append(s))
    assert isinstance(res, PipelineResult)
    assert res.used_comfyui is True
    assert len(res.article.images) == 2          # 1 风格迁移 + 1 文生图
    assert res.article.images[0].size == (900, 383)  # 首图=公众号封面
    assert "images" in stages


def test_pipeline_degrades_to_original_on_comfy_error(tmp_path):
    wc = WeChatContent(title="T", image_prompts=["x"])
    class BrokenComfy:
        def style_transfer(self, path, style):
            raise ComfyError("down")
        def text_to_image(self, prompt, style):
            raise ComfyError("down")
    res = run_pipeline("m", [_img_file(tmp_path)], get_preset("anime"), _cfg(),
                       FakeGen(wc), BrokenComfy())
    assert res.used_comfyui is False
    assert any("ComfyUI" in w for w in res.warnings)
    assert len(res.article.images) == 1          # 退回原图


def test_pipeline_no_comfy_client_uses_original(tmp_path):
    wc = WeChatContent(title="T")
    res = run_pipeline("m", [_img_file(tmp_path)], get_preset("anime"), _cfg(),
                       FakeGen(wc), comfy=None)
    assert res.used_comfyui is False
    assert len(res.article.images) == 1
```

- [ ] **Step 2: 运行验证失败**

Run: `.\.venv-paddle\Scripts\python.exe -m pytest tests/test_pipeline.py -q`
Expected: FAIL（`ModuleNotFoundError: ... pipeline`）。

- [ ] **Step 3: 实现 pipeline.py**

Create `content_studio/core/pipeline.py`:
```python
"""端到端生成编排：LLM 出文 -> ComfyUI 出图(可降级) -> image_pipeline 后处理。"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from PIL import Image

from content_studio.config import AppConfig
from content_studio.core import image_pipeline
from content_studio.core.comfy import ComfyClient, ComfyError
from content_studio.core.generator import Generator
from content_studio.styles.registry import StylePreset


@dataclass
class BuiltArticle:
    title: str = ""
    summary: str = ""
    body_html: str = ""
    image_captions: list[str] = field(default_factory=list)
    images: list[Image.Image] = field(default_factory=list)


@dataclass
class PipelineResult:
    article: BuiltArticle
    image_prompts: list[str] = field(default_factory=list)
    used_comfyui: bool = False
    warnings: list[str] = field(default_factory=list)


def _load_originals(image_paths: list[str]) -> list[Image.Image]:
    return [image_pipeline.load_image(p) for p in image_paths]


def run_pipeline(
    material: str,
    image_paths: list[str],
    style: StylePreset | None,
    cfg: AppConfig,
    generator: Generator,
    comfy: ComfyClient | None = None,
    progress: Callable[[str, float], None] = lambda _s, _p: None,
) -> PipelineResult:
    progress("llm", 0.1)
    wc = generator.generate_wechat(material, style)
    progress("llm", 0.4)

    originals = _load_originals(image_paths)
    styled: list[Image.Image] = []
    used = False
    warnings: list[str] = []

    if cfg.comfy.enabled and comfy is not None and originals:
        try:
            for p in image_paths:
                styled.append(comfy.style_transfer(p, style))
            for prompt in (wc.image_prompts or [])[: cfg.comfy.t2i_count]:
                styled.append(comfy.text_to_image(prompt, style))
            used = True
            progress("images", 0.7)
        except ComfyError as e:
            warnings.append(f"ComfyUI 不可用，改用原图：{e}")
            styled = list(originals)
    else:
        styled = list(originals)
        if originals and cfg.comfy.enabled and comfy is not None:
            warnings.append("ComfyUI 已启用但无输入图片，使用原图")

    processed = image_pipeline.build_wechat_images(styled, cfg.image)
    progress("images", 0.9)

    return PipelineResult(
        article=BuiltArticle(
            title=wc.title,
            summary=wc.summary,
            body_html=wc.body_html,
            image_captions=list(wc.image_captions),
            images=processed,
        ),
        image_prompts=list(wc.image_prompts or []),
        used_comfyui=used,
        warnings=warnings,
    )
```

- [ ] **Step 4: 运行验证通过**

Run: `.\.venv-paddle\Scripts\python.exe -m pytest tests/test_pipeline.py -q`
Expected: `3 passed`

- [ ] **Step 5: 提交**

```bash
git add content_studio/core/pipeline.py tests/test_pipeline.py
git commit -m "feat(pipeline): orchestrate LLM + ComfyUI + image processing with fallback"
```

---

## Task 7: 公众号草稿箱（publish/wechat.py）

**Files:**
- Create: `content_studio/publish/__init__.py`, `content_studio/publish/wechat.py`
- Test: `tests/test_publish_wechat.py`

**Interfaces:**
- Produces:
  - `WeChatError(Exception)`
  - `WeChatPublisher(app_id, app_secret, http=None, sleeper=time.sleep)`
  - `get_access_token()->str`（缓存，过期前 5 分钟刷新）
  - `upload_body_image(path)->str`（返回文章内 URL）
  - `upload_cover_material(path)->str`（返回 `media_id`）
  - `create_draft(article: dict)->str`（返回草稿 `media_id`）
  - `publish_article(title, digest, body_html, cover_path, body_image_paths=None)->str`
  - `40001` → 失效 token 重试一次

- [ ] **Step 1: 写失败测试**

Create `tests/test_publish_wechat.py`:
```python
from pathlib import Path

from content_studio.publish.wechat import WeChatPublisher, WeChatError


class FakeResp:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data or {}
    def json(self):
        return self._json


class FakeHttp:
    def __init__(self):
        self.posts = []
        self.gets = []
        self._seq_post = []
        self._seq_get = []
    def queue_post(self, resp):
        self._seq_post.append(resp)
    def queue_get(self, resp):
        self._seq_get.append(resp)
    def post(self, url, **kw):
        self.posts.append((url, kw))
        return self._seq_post.pop(0) if self._seq_post else FakeResp(200, {})
    def get(self, url, **kw):
        self.gets.append((url, kw))
        return self._seq_get.pop(0) if self._seq_get else FakeResp(200, {})


def _img(path: Path):
    path.write_bytes(b"\xff\xd8\xff\xe0" + b"0" * 16)  # 假 JPEG
    return str(path)


def test_token_cached_between_calls(tmp_path):
    h = FakeHttp()
    h.queue_get(FakeResp(200, {"access_token": "TOK", "expires_in": 7200}))
    pub = WeChatPublisher("id", "secret", http=h)
    assert pub.get_access_token() == "TOK"
    assert pub.get_access_token() == "TOK"      # 第二次不重新请求
    assert len(h.gets) == 1


def test_token_refreshed_after_expiry():
    h = FakeHttp()
    h.queue_get(FakeResp(200, {"access_token": "T1", "expires_in": 0}))
    h.queue_get(FakeResp(200, {"access_token": "T2", "expires_in": 7200}))
    pub = WeChatPublisher("id", "secret", http=h)
    assert pub.get_access_token() == "T1"
    assert pub.get_access_token() == "T2"
    assert len(h.gets) == 2


def test_publish_article_full_flow(tmp_path):
    h = FakeHttp()
    h.queue_get(FakeResp(200, {"access_token": "TOK", "expires_in": 7200}))   # token
    h.queue_post(FakeResp(200, {"url": "http://img/1"}))                       # body img
    h.queue_post(FakeResp(200, {"media_id": "COVER"}))                         # cover
    h.queue_post(FakeResp(200, {"media_id": "DRAFT"}))                         # draft
    pub = WeChatPublisher("id", "secret", http=h)
    cover = _img(tmp_path / "c.jpg")
    body = [_img(tmp_path / "b.jpg")]
    media_id = pub.publish_article("标题", "摘要", "<p>正文</p>", cover, body)
    assert media_id == "DRAFT"
    # draft/add 的 body 含正文与图片 url
    draft_call = [c for c in h.posts if "draft/add" in c[0]][0]
    article = draft_call[1]["json"]["articles"][0]
    assert article["title"] == "标题"
    assert article["thumb_media_id"] == "COVER"
    assert "http://img/1" in article["content"]


def test_errcode_raises():
    h = FakeHttp()
    h.queue_get(FakeResp(200, {"errcode": 40013, "errmsg": "invalid appid"}))
    pub = WeChatPublisher("id", "secret", http=h)
    try:
        pub.get_access_token()
        assert False, "应抛错"
    except WeChatError as e:
        assert "40013" in str(e)


def test_40001_refreshes_and_retries(tmp_path):
    h = FakeHttp()
    h.queue_get(FakeResp(200, {"access_token": "BAD", "expires_in": 7200}))   # 首 token
    h.queue_post(FakeResp(200, {"errcode": 40001, "errmsg": "invalid credential"}))  # body img 失败
    h.queue_get(FakeResp(200, {"access_token": "GOOD", "expires_in": 7200}))  # 刷新
    h.queue_post(FakeResp(200, {"url": "http://img/1"}))                       # body img 重试成功
    h.queue_post(FakeResp(200, {"media_id": "COVER"}))
    h.queue_post(FakeResp(200, {"media_id": "DRAFT"}))
    pub = WeChatPublisher("id", "secret", http=h)
    cover = _img(tmp_path / "c.jpg")
    body = [_img(tmp_path / "b.jpg")]
    assert pub.publish_article("T", "S", "<p>x</p>", cover, body) == "DRAFT"
```

- [ ] **Step 2: 运行验证失败**

Run: `.\.venv-paddle\Scripts\python.exe -m pytest tests/test_publish_wechat.py -q`
Expected: FAIL（`ModuleNotFoundError: ... publish.wechat`）。

- [ ] **Step 3: 实现**

Create `content_studio/publish/__init__.py`:
```python
"""Publishing layer (WeChat draft box)."""
```

Create `content_studio/publish/wechat.py`:
```python
"""公众号草稿箱：token / 正文图 / 封面素材 / 建草稿。"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

import httpx


class WeChatError(Exception):
    pass


class WeChatPublisher:
    BASE = "https://api.weixin.qq.com/cgi-bin"

    def __init__(self, app_id: str, app_secret: str, http: Any = None, sleeper: Callable[[float], None] = time.sleep):
        self.app_id = app_id
        self.app_secret = app_secret
        self._sleep = sleeper
        self._http = http if http is not None else httpx.Client(timeout=30)
        self._token: str | None = None
        self._token_expires = 0.0

    @staticmethod
    def _check(r) -> dict:
        if r.status_code != 200:
            raise WeChatError(f"HTTP {r.status_code}")
        data = r.json()
        if data.get("errcode"):
            raise WeChatError(f"{data.get('errcode')} {data.get('errmsg')}")
        return data

    def _invalidate(self) -> None:
        self._token = None
        self._token_expires = 0.0

    def get_access_token(self) -> str:
        if self._token and time.time() < self._token_expires - 300:
            return self._token
        r = self._http.get(f"{self.BASE}/token", params={
            "grant_type": "client_credential",
            "appid": self.app_id,
            "secret": self.app_secret,
        })
        data = self._check(r)
        if "access_token" not in data:
            raise WeChatError(f"无 access_token: {data}")
        self._token = data["access_token"]
        self._token_expires = time.time() + int(data.get("expires_in", 7200))
        return self._token

    def _tokened(self, path: str) -> tuple[str, dict]:
        return f"{self.BASE}/{path}", {"access_token": self.get_access_token()}

    def _retry(self, fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except WeChatError as e:
            if "40001" in str(e):
                self._invalidate()
                return fn()
            raise

    def upload_body_image(self, path: str | Path) -> str:
        p = Path(path)
        def do():
            url, params = self._tokened("media/uploadimg")
            with p.open("rb") as f:
                files = {"media": (p.name, f, "image/jpeg")}
                return self._check(self._http.post(url, params=params, files=files))["url"]
        return self._retry(do)

    def upload_cover_material(self, path: str | Path) -> str:
        p = Path(path)
        def do():
            url, params = self._tokened("material/add_material")
            params = dict(params); params["type"] = "image"
            with p.open("rb") as f:
                files = {"media": (p.name, f, "image/jpeg")}
                return self._check(self._http.post(url, params=params, files=files))["media_id"]
        return self._retry(do)

    def create_draft(self, article: dict) -> str:
        def do():
            url, params = self._tokened("draft/add")
            return self._check(self._http.post(url, params=params, json={"articles": [article]}))["media_id"]
        return self._retry(do)

    def publish_article(self, title: str, digest: str, body_html: str,
                        cover_path: str | Path, body_image_paths: list[str] | None = None) -> str:
        body_image_paths = body_image_paths or []
        urls = [self.upload_body_image(p) for p in body_image_paths]
        thumb = self.upload_cover_material(cover_path)
        content = body_html or ""
        for u in urls:
            content += f'\n<p><img src="{u}"></p>'
        article = {
            "title": title,
            "author": "Content Studio",
            "digest": digest or "",
            "content": content,
            "thumb_media_id": thumb,
            "need_open_comment": 0,
            "only_fans_can_comment": 0,
        }
        return self.create_draft(article)
```

- [ ] **Step 4: 运行验证通过**

Run: `.\.venv-paddle\Scripts\python.exe -m pytest tests/test_publish_wechat.py -q`
Expected: `5 passed`

- [ ] **Step 5: 提交**

```bash
git add content_studio/publish tests/test_publish_wechat.py
git commit -m "feat(publish): WeChat draft box publisher with token cache and retry"
```

---

## Task 8: Web 骨架（app.py + jobs.py + 首页路由 + 模板）

**Files:**
- Create: `content_studio/web/__init__.py`, `content_studio/web/app.py`, `content_studio/web/jobs.py`, `content_studio/web/routes.py`（仅本任务的首页部分），`content_studio/web/templates/index.html`, `content_studio/web/templates/settings.html`
- Test: `tests/test_web_routes.py`

**Interfaces:**
- Produces:
  - `web.app.create_app() -> FastAPI`、模块级 `app`、`main()`
  - `web.jobs.create_job() -> Job`、`get_job(jid) -> Job | None`、`update_job(jid, **kw)`
  - `Job(id, stage, progress, result, error)`
  - 路由 `GET /`（渲染 index）、`GET /styles`（JSON 风格列表）

- [ ] **Step 1: 写失败测试**

Create `tests/test_web_routes.py`:
```python
import time
from fastapi.testclient import TestClient
from content_studio.web.app import create_app


def _client():
    return TestClient(create_app())


def test_index_returns_form():
    c = _client()
    r = c.get("/")
    assert r.status_code == 200
    assert "一键生成" in r.text
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
```

- [ ] **Step 2: 运行验证失败**

Run: `.\.venv-paddle\Scripts\python.exe -m pytest tests/test_web_routes.py -q`
Expected: FAIL（`ModuleNotFoundError: ... web.app`）。

- [ ] **Step 3: 实现 jobs.py**

Create `content_studio/web/__init__.py`:
```python
"""FastAPI web layer."""
```

Create `content_studio/web/jobs.py`:
```python
"""内存任务表 + 进度。单进程有效，重启清空。"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Job:
    id: str
    stage: str = "queued"
    progress: float = 0.0
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None


_jobs: dict[str, Job] = {}
_lock = threading.Lock()


def create_job() -> Job:
    jid = uuid.uuid4().hex[:12]
    job = Job(id=jid)
    with _lock:
        _jobs[jid] = job
    return job


def get_job(jid: str) -> Optional[Job]:
    with _lock:
        return _jobs.get(jid)


def update_job(jid: str, **kw: Any) -> None:
    with _lock:
        j = _jobs.get(jid)
        if j is None:
            return
        for k, v in kw.items():
            setattr(j, k, v)
```

- [ ] **Step 4: 实现 routes.py（首页 + 风格）**

Create `content_studio/web/routes.py`:
```python
"""FastAPI 路由。"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from content_studio.styles.registry import list_presets

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).resolve().parent / "templates")


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {"presets": list_presets()})


@router.get("/styles")
def styles():
    return [{"id": p.id, "name": p.name} for p in list_presets()]
```

- [ ] **Step 5: 实现 app.py**

Create `content_studio/web/app.py`:
```python
"""FastAPI 应用入口。"""
from __future__ import annotations

from fastapi import FastAPI

from content_studio.web.routes import router


def create_app() -> FastAPI:
    app = FastAPI(title="Content Studio")
    app.include_router(router)
    return app


app = create_app()


def main():
    import uvicorn
    uvicorn.run("content_studio.web.app:app", host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: 写模板**

Create `content_studio/web/templates/index.html`:
```html
<!doctype html>
<html lang="zh">
<head>
  <meta charset="utf-8">
  <title>Content Studio · 公众号一键生成</title>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 880px; margin: 24px auto; padding: 0 16px; }
    textarea { width: 100%; height: 120px; }
    .row { margin: 10px 0; }
    button { padding: 8px 16px; }
  </style>
</head>
<body>
  <h1>Content Studio</h1>
  <p>主题 + 照片 + 文字 → 一键生成公众号文章并发到草稿箱</p>
  <form id="f" enctype="multipart/form-data">
    <div class="row"><label>主题</label><br><input name="theme" style="width:100%" placeholder="例如：秋日京都漫步"></div>
    <div class="row"><label>素材文字</label><br><textarea name="text"></textarea></div>
    <div class="row"><label>照片</label><br><input name="images" type="file" multiple accept="image/*"></div>
    <div class="row"><label>风格</label>
      <select name="style_id">
        {% for p in presets %}<option value="{{ p.id }}">{{ p.name }}</option>{% endfor %}
      </select>
    </div>
    <div class="row"><label><input type="checkbox" name="ocr"> 从图片提取文字 (OCR)</label></div>
    <div class="row"><button type="submit">一键生成</button> <a href="/settings">设置</a></div>
  </form>
  <pre id="status"></pre>
  <script>
    const f = document.getElementById('f');
    const status = document.getElementById('status');
    f.addEventListener('submit', async (e) => {
      e.preventDefault();
      status.textContent = '提交中…';
      const fd = new FormData(f);
      if (!fd.get('images').length) { status.textContent = '请选择至少一张照片'; return; }
      const r = await fetch('/generate', { method: 'POST', body: fd });
      const { job_id } = await r.json();
      poll(job_id);
    });
    function poll(jobId) {
      const t = setInterval(async () => {
        const j = await (await fetch('/job/' + jobId)).json();
        status.textContent = (j.stage || '') + ' ' + Math.round((j.progress||0)*100) + '%';
        if (j.stage === 'done') { clearInterval(t); location.href = '/job/' + jobId + '/preview'; }
        if (j.stage === 'error') { clearInterval(t); status.textContent = '错误：' + (j.error||''); }
      }, 1500);
    }
  </script>
</body>
</html>
```

- [ ] **Step 7: 运行验证通过**

Run: `.\.venv-paddle\Scripts\python.exe -m pytest tests/test_web_routes.py -q`
Expected: `3 passed`

- [ ] **Step 8: 提交**

```bash
git add content_studio/web tests/test_web_routes.py
git commit -m "feat(web): FastAPI scaffold with index page, styles, and in-memory jobs"
```

---

## Task 9: 生成 / 进度 / 预览路由

**Files:**
- Modify: `content_studio/web/routes.py`
- Create: `content_studio/web/templates/preview.html`
- Test: `tests/test_web_routes.py`（追加用例）

**Interfaces:**
- Consumes: `core.pipeline.run_pipeline`、`core.models.LLMClient`、`core.generator.Generator`、`core.comfy.ComfyClient`、`config.load_config`/`get_active_provider`、`web.jobs`
- Produces:
  - `POST /generate`（form: theme/text/images/style_id/ocr）→ `{"job_id": ...}`，后台线程跑管线
  - `GET /job/{id}` → `{"stage","progress","error"}`
  - `GET /job/{id}/image/{n}` → JPEG
  - `GET /job/{id}/preview` → 预览页
  - 模块内辅助：`_build_services(cfg)`、`_save_upload(data, suffix)`、`_to_jpeg(img)`

- [ ] **Step 1: 追加失败测试**

在 `tests/test_web_routes.py` 末尾追加：
```python
import io
from PIL import Image
from content_studio.web import routes


def _png():
    buf = io.BytesIO(); Image.new("RGB", (50, 50), (9, 9, 9)).save(buf, "PNG"); return buf.getvalue()


def _fake_pipeline_factory(result):
    def fake(material, image_paths, style, cfg, generator, comfy=None, progress=lambda s, p: None):
        progress("llm", 0.5); progress("done", 1.0)
        return result
    return fake


def test_generate_creates_job_and_completes(monkeypatch):
    from content_studio.core.pipeline import PipelineResult, BuiltArticle
    art = BuiltArticle(title="标题", summary="摘要", body_html="<p>正文</p>",
                       image_captions=["c1"], images=[Image.new("RGB", (40, 40))])
    result = PipelineResult(article=art, image_prompts=["a cat"], used_comfyui=True, warnings=[])
    monkeypatch.setattr(routes, "run_pipeline", _fake_pipeline_factory(result))

    c = _client()
    r = c.post("/generate", data={"theme": "t", "text": "x", "style_id": "anime"},
               files={"images": ("a.png", _png(), "image/png")})
    assert r.status_code == 200
    job_id = r.json()["job_id"]

    done = False
    for _ in range(40):
        j = c.get(f"/job/{job_id}").json()
        if j["stage"] == "done":
            done = True; break
        time.sleep(0.02)
    assert done

    img = c.get(f"/job/{job_id}/image/0")
    assert img.status_code == 200
    assert img.headers["content-type"].startswith("image/")

    prev = c.get(f"/job/{job_id}/preview")
    assert prev.status_code == 200
    assert "标题" in prev.text


def test_generate_missing_images_returns_400():
    c = _client()
    r = c.post("/generate", data={"theme": "t", "style_id": "anime"}, files=[])
    assert r.status_code == 400


def test_job_not_found():
    c = _client()
    assert c.get("/job/does-not-exist").status_code == 404
```

- [ ] **Step 2: 运行验证失败**

Run: `.\.venv-paddle\Scripts\python.exe -m pytest tests/test_web_routes.py -q`
Expected: FAIL（`/generate` 404 或断言失败）。

- [ ] **Step 3: 扩展 routes.py**

在 `content_studio/web/routes.py` 顶部追加 import：
```python
import os
import tempfile
import threading
from io import BytesIO

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from PIL import Image

from content_studio.config import get_active_provider, load_config
from content_studio.core.comfy import ComfyClient
from content_studio.core.generator import Generator, build_material
from content_studio.core.models import LLMClient
from content_studio.core.pipeline import run_pipeline
from content_studio.styles.registry import get_preset
from content_studio.web import jobs
```
（替换原 import 块；保留 `router`、`templates`、`/`、`/styles`）

在文件末尾追加辅助与路由：
```python
UPLOAD_DIR = Path(tempfile.gettempdir()) / "content_studio_uploads"


def _save_upload(data: bytes, suffix: str) -> str:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(suffix=suffix, dir=str(UPLOAD_DIR))
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return name


def _to_jpeg(img: Image.Image, quality: int = 85) -> bytes:
    buf = BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def _build_services(cfg):
    generator = Generator(LLMClient(get_active_provider(cfg)))
    comfy = ComfyClient(cfg.comfy.base_url, timeout=cfg.comfy.timeout) if cfg.comfy.enabled else None
    return generator, comfy


@router.post("/generate")
async def generate(
    theme: str = Form(...),
    text: str = Form(""),
    style_id: str = Form(...),
    ocr: bool = Form(False),
    images: list[UploadFile] | None = File(default=None),
):
    if not images:
        raise HTTPException(400, "请至少上传一张照片")
    cfg = load_config()
    style = get_preset(style_id)
    saved: list[str] = []
    ocr_text = ""
    for up in images:
        data = await up.read()
        suffix = Path(up.filename or "img.png").suffix or ".png"
        saved.append(_save_upload(data, suffix))
    if ocr and saved:
        from content_studio.core import ocr as ocr_mod
        ocr_text = ocr_mod.extract_text(saved)
    material = build_material((theme + "\n" + text).strip(), ocr_text=ocr_text, image_count=len(saved))

    job = jobs.create_job()

    def worker():
        try:
            generator, comfy = _build_services(cfg)

            def progress(stage, p):
                jobs.update_job(job.id, stage=stage, progress=p)

            res = run_pipeline(material, saved, style, cfg, generator, comfy, progress)
            jobs.update_job(
                job.id, stage="done", progress=1.0,
                result={
                    "title": res.article.title,
                    "summary": res.article.summary,
                    "body_html": res.article.body_html,
                    "image_captions": res.article.image_captions,
                    "images": [_to_jpeg(im) for im in res.article.images],
                    "image_prompts": res.image_prompts,
                    "used_comfyui": res.used_comfyui,
                    "warnings": res.warnings,
                },
            )
        except Exception as e:
            jobs.update_job(job.id, stage="error", error=str(e))

    threading.Thread(target=worker, daemon=True).start()
    return {"job_id": job.id}


@router.get("/job/{jid}")
def job_status(jid: str):
    j = jobs.get_job(jid)
    if j is None:
        raise HTTPException(404)
    return {"stage": j.stage, "progress": j.progress, "error": j.error}


@router.get("/job/{jid}/image/{n}")
def job_image(jid: str, n: int):
    j = jobs.get_job(jid)
    if j is None or not j.result or n < 0 or n >= len(j.result["images"]):
        raise HTTPException(404)
    return Response(content=j.result["images"][n], media_type="image/jpeg")


@router.get("/job/{jid}/preview", response_class=HTMLResponse)
def job_preview(jid: str, request: Request):
    j = jobs.get_job(jid)
    if j is None or not j.result:
        raise HTTPException(404)
    return templates.TemplateResponse(request, "preview.html", {"job": j, "jid": jid})
```

- [ ] **Step 4: 写预览模板**

Create `content_studio/web/templates/preview.html`:
```html
<!doctype html>
<html lang="zh">
<head>
  <meta charset="utf-8">
  <title>预览 · {{ job.result.title }}</title>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 760px; margin: 24px auto; padding: 0 16px; }
    img.art { max-width: 100%; display:block; margin: 8px 0; }
    .meta { color: #666; font-size: 14px; }
  </style>
</head>
<body>
  <h1>{{ job.result.title }}</h1>
  <div class="meta">摘要：{{ job.result.summary }}</div>
  {% if job.result.used_comfyui %}<div class="meta">✅ 已用 AMD GPU (ComfyUI) 出图</div>{% endif %}
  {% for w in job.result.warnings %}<div class="meta" style="color:#b00">⚠ {{ w }}</div>{% endfor %}
  <hr>
  <div>{{ job.result.body_html | safe }}</div>
  {% for n in range(job.result.images | length) %}
    <img class="art" src="/job/{{ jid }}/image/{{ n }}">
  {% endfor %}
  <form method="post" action="/job/{{ jid }}/publish">
    <button type="submit">发到公众号草稿箱</button>
  </form>
  <p class="meta"><a href="/">← 再来一篇</a></p>
</body>
</html>
```

- [ ] **Step 5: 运行验证通过**

Run: `.\.venv-paddle\Scripts\python.exe -m pytest tests/test_web_routes.py -q`
Expected: `6 passed`（原 3 + 新 3）

- [ ] **Step 6: 提交**

```bash
git add content_studio/web/routes.py content_studio/web/templates/preview.html tests/test_web_routes.py
git commit -m "feat(web): generate/job/preview routes with async pipeline and image serving"
```

---

## Task 10: 发布 + 设置路由

**Files:**
- Modify: `content_studio/web/routes.py`
- Create: `content_studio/web/templates/settings.html`
- Test: `tests/test_web_routes.py`（追加用例）

**Interfaces:**
- Consumes: `publish.wechat.WeChatPublisher`、`config`
- Produces：
  - `POST /job/{id}/publish` → `{"media_id": ...}`
  - `GET /settings` → 设置页（读当前配置）
  - `POST /settings` → 保存 provider key/model、ComfyUI base_url、公众号凭证

- [ ] **Step 1: 追加失败测试**

在 `tests/test_web_routes.py` 末尾追加：
```python
def test_publish_calls_publisher(monkeypatch):
    from content_studio.core.pipeline import PipelineResult, BuiltArticle
    import io
    from PIL import Image
    art = BuiltArticle(title="T", summary="S", body_html="<p>x</p>", images=[Image.new("RGB",(20,20))])
    monkeypatch.setattr(routes, "run_pipeline", _fake_pipeline_factory(
        PipelineResult(article=art, image_prompts=[], used_comfyui=False, warnings=[])))

    class FakePub:
        def __init__(self, *a, **k): pass
        def publish_article(self, title, digest, body_html, cover_path, body_image_paths=None):
            assert title == "T"
            return "MEDIA123"
    monkeypatch.setattr(routes, "WeChatPublisher", FakePub)
    monkeypatch.setattr(routes, "load_config", lambda: load_config_for_settings("id", "secret"))

    c = _client()
    r = c.post("/generate", data={"theme": "t", "text": "x", "style_id": "anime"},
               files={"images": ("a.png", _png(), "image/png")})
    jid = r.json()["job_id"]
    for _ in range(40):
        if c.get(f"/job/{jid}").json()["stage"] == "done":
            break
        time.sleep(0.02)
    pub = c.post(f"/job/{jid}/publish")
    assert pub.status_code == 200
    assert pub.json()["media_id"] == "MEDIA123"


def test_publish_without_credentials_returns_400(monkeypatch):
    from content_studio.core.pipeline import PipelineResult, BuiltArticle
    from PIL import Image
    art = BuiltArticle(title="T", images=[Image.new("RGB", (20, 20))])
    monkeypatch.setattr(routes, "run_pipeline", _fake_pipeline_factory(
        PipelineResult(article=art, image_prompts=[], used_comfyui=False, warnings=[])))
    monkeypatch.setattr(routes, "load_config", lambda: load_config_for_settings(app_id="", app_secret=""))

    c = _client()
    r = c.post("/generate", data={"theme": "t", "text": "x", "style_id": "anime"},
               files={"images": ("a.png", _png(), "image/png")})
    jid = r.json()["job_id"]
    for _ in range(40):
        if c.get(f"/job/{jid}").json()["stage"] == "done":
            break
        time.sleep(0.02)
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
```

- [ ] **Step 2: 运行验证失败**

Run: `.\.venv-paddle\Scripts\python.exe -m pytest tests/test_web_routes.py -q`
Expected: FAIL（`/job/{id}/publish` 404、`/settings` 404）。

- [ ] **Step 3: 扩展 routes.py**

在 `content_studio/web/routes.py` 顶部 import 区追加：
```python
from content_studio.publish.wechat import WeChatPublisher
from content_studio.config import save_config
```
（`load_config`/`get_active_provider` 已在 Task 9 import；此处只补 `save_config` 与 `WeChatPublisher`。）
在文件末尾追加路由：
```python
def _bytes_to_tmp(data: bytes, suffix: str = ".jpg") -> str:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(suffix=suffix, dir=str(UPLOAD_DIR))
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return name


@router.post("/job/{jid}/publish")
def publish(jid: str):
    j = jobs.get_job(jid)
    if j is None or not j.result:
        raise HTTPException(404)
    cfg = load_config()
    if not cfg.wechat.app_id or not cfg.wechat.app_secret:
        raise HTTPException(400, "未配置公众号 AppID/AppSecret，请到设置页填写")
    pub = WeChatPublisher(cfg.wechat.app_id, cfg.wechat.app_secret)
    r = j.result
    imgs = r["images"]
    cover = _bytes_to_tmp(imgs[0])
    body = [_bytes_to_tmp(b) for b in imgs[1:]]
    media_id = pub.publish_article(r["title"], r["summary"], r["body_html"], cover, body)
    r["draft_media_id"] = media_id
    return {"media_id": media_id}


@router.get("/settings", response_class=HTMLResponse)
def settings_form(request: Request):
    cfg = load_config()
    return templates.TemplateResponse(request, "settings.html", {"cfg": cfg})


@router.post("/settings")
async def settings_save(request: Request):
    form = await request.form()
    cfg = load_config()
    active = form.get("active_provider") or (cfg.providers[0].name if cfg.providers else "")
    for p in cfg.providers:
        key = (form.get(f"key_{p.name}") or "").strip()
        model = (form.get(f"model_{p.name}") or "").strip()
        if key:
            p.api_key = key
        if model:
            p.model = model
    cfg.active_provider = active
    cfg.comfy.base_url = (form.get("comfy_url") or cfg.comfy.base_url).strip()
    cfg.wechat.app_id = (form.get("app_id") or "").strip()
    cfg.wechat.app_secret = (form.get("app_secret") or "").strip()
    save_config(cfg)
    return JSONResponse({"ok": True})
```

- [ ] **Step 4: 写设置模板**

Create `content_studio/web/templates/settings.html`:
```html
<!doctype html>
<html lang="zh">
<head>
  <meta charset="utf-8"><title>设置 · Content Studio</title>
  <style>body{font-family:system-ui,sans-serif;max-width:640px;margin:24px auto;padding:0 16px} input{width:100%} .row{margin:10px 0}</style>
</head>
<body>
  <h1>设置</h1>
  <form id="f">
    <h3>文本 LLM (OpenAI 兼容)</h3>
    <div class="row"><label>当前 Provider</label>
      <select name="active_provider">
        {% for p in cfg.providers %}<option value="{{ p.name }}" {% if p.name==cfg.active_provider %}selected{% endif %}>{{ p.name }}</option>{% endfor %}
      </select>
    </div>
    {% for p in cfg.providers %}
    <div class="row"><label>{{ p.name }} · API Key</label><input name="key_{{ p.name }}" value="{{ p.api_key }}" type="password"></div>
    <div class="row"><label>{{ p.name }} · 模型</label><input name="model_{{ p.name }}" value="{{ p.model }}"></div>
    {% endfor %}
    <h3>ComfyUI (本地 AMD GPU)</h3>
    <div class="row"><label>Base URL</label><input name="comfy_url" value="{{ cfg.comfy.base_url }}"></div>
    <h3>公众号草稿箱</h3>
    <div class="row"><label>AppID</label><input name="app_id" value="{{ cfg.wechat.app_id }}"></div>
    <div class="row"><label>AppSecret</label><input name="app_secret" value="{{ cfg.wechat.app_secret }}" type="password"></div>
    <div class="row"><button type="submit">保存</button> <a href="/">返回</a></div>
  </form>
  <pre id="msg"></pre>
  <script>
    document.getElementById('f').addEventListener('submit', async (e) => {
      e.preventDefault();
      const fd = new FormData(e.target);
      const r = await fetch('/settings', { method: 'POST', body: fd });
      document.getElementById('msg').textContent = r.ok ? '已保存' : '保存失败';
    });
  </script>
</body>
</html>
```

- [ ] **Step 5: 运行验证通过**

Run: `.\.venv-paddle\Scripts\python.exe -m pytest tests/test_web_routes.py -q`
Expected: `9 passed`

再跑全量回归：
Run: `.\.venv-paddle\Scripts\python.exe -m pytest -q`
Expected: 全部通过。

- [ ] **Step 6: 提交**

```bash
git add content_studio/web/routes.py content_studio/web/templates/settings.html tests/test_web_routes.py
git commit -m "feat(web): publish-to-draft route and settings page"
```

---

## Task 11: 手动端到端验收

**Files:** 无（运行 + 验收）

**说明：** 真实 LLM / ComfyUI / 公众号 API 不进单测，手动验收。

- [ ] **Step 1: 启动 Web 服务**

Run: `.\.venv-paddle\Scripts\python.exe -m content_studio.web.app`
Expected: 浏览器打开 `http://127.0.0.1:8000`，看到表单页含「一键生成」与两个风格。

- [ ] **Step 2: 填设置**

打开 `/settings`，填一个 provider 的 API Key + 模型（如千问 DashScope 的 OpenAI 兼容端点），填公众号 AppID/AppSecret，保存。

- [ ] **Step 3: 验收「无 GPU 降级」路径**

在 `设置` 临时把 ComfyUI base_url 改成不可达地址（或先不启动 ComfyUI）。首页上传 1–2 张照片 + 文字，选「动漫风」，点「一键生成」。
Expected: 进度走到 done；预览页出现标题/摘要/正文 + 原图（带 ⚠ ComfyUI 不可用告警）。

- [ ] **Step 4: 验收「ComfyUI 出图」路径（需 GPU）**

本地启动 ComfyUI（AMD GPU 走 `--directml`）并放入真实 workflow/模型。重复 Step 3。
Expected: 预览页配图为风格化图 + 文生图（预览页显示「✅ 已用 AMD GPU 出图」）。

- [ ] **Step 5: 验收草稿箱**

预览页点「发到公众号草稿箱」。
Expected: 返回 `media_id`；登录公众号后台 → 草稿箱，出现新草稿（标题/摘要/封面/正文图正确）。

- [ ] **Step 6: 验收清单（对照 spec §2 MVP 标准）**

逐条核对：上传图/填表/选风格 ✓；LLM 出结构化字段 ✓；ComfyUI 风格迁移+文生图 ✓；`image_pipeline` 封面(900×383)+压缩 ✓；预览+进度 ✓；草稿箱真调 ✓；≥2 风格 ✓。

- [ ] **Step 7: 提交收尾（如有改动）**

```bash
git add -A
git commit -m "chore: end-to-end acceptance verified" --allow-empty
```
Expected: 提交成功（无改动则空提交留痕）。
