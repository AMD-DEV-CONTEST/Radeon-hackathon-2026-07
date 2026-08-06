# Content Studio 实现计划（第一阶段 MVP）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个 Windows 桌面 GUI 程序，投入「图片+文字」后一键用 AI 生成公众号长文和小红书笔记，并自动处理图片。

**Architecture:** 模块化的 Python 包 `content_studio`，核心逻辑全部在 `core/`（不依赖 GUI，可单测）；GUI 用 CustomTkinter 套壳；LLM 走 OpenAI 兼容客户端（可切换 DeepSeek/GLM/Kimi）；图片走 Pillow。生成与图片两条并行管线，公众号/小红书各自独立输出。

**Tech Stack:** Python 3.12（`.venv-paddle`）、CustomTkinter、openai（兼容客户端）、Pillow、OpenCV、PaddleOCR（可选）、pytest

## Global Constraints

- **Python 解释器固定为** `.\.venv-paddle\Scripts\python.exe`（已含 PIL/cv2/httpx/paddleocr；缺 pip，用 `ensurepip` 引导）。
- **所有命令在仓库根目录** `C:\Users\VPX01\Documents\Default Project` 下执行。
- **新增依赖**：`openai`、`customtkinter`、`pytest`（pytest 仅开发用）。
- **LLM 调用统一用 OpenAI 兼容格式**，强制 `response_format={"type":"json_object"}`；切换 provider 只改 `~/.content_studio/config.json`。
- **图片尺寸常量**：小红书封面 3:4 = `1242×1656`；公众号封面 2.35:1 = `900×383`；正文图最大宽 `900px`。
- **配置文件路径**：`~/.content_studio/config.json`（`Path.home()/.content_studio/config.json`）。
- **第一阶段不含**公众号 API 发布（`publish/wechat.py` 仅预留，GUI 入口灰置）。
- **`core/` 不得 import 任何 GUI 库**（customtkinter/tkinter）。
- **git 当前未安装**：Task 1 会用 winget 安装并 `git init`；若某次提交步骤提示找不到 git，开一个新终端再继续（winget 装完需要新进程刷新 PATH）。

---

## File Structure

| 文件 | 职责 |
|---|---|
| `requirements.txt` | 修改：追加 openai、customtkinter；备注 pytest |
| `.gitignore` | 忽略 `.venv-paddle/`、`reports/`、输出目录、敏感配置 |
| `conftest.py` | 空文件，让 pytest 把根目录加入 sys.path |
| `content_studio/__init__.py` | 包标记 |
| `content_studio/config.py` | 配置 dataclass + 加载/保存/解析 active provider |
| `content_studio/core/__init__.py` | 包标记 |
| `content_studio/core/models.py` | LLM 客户端（OpenAI 兼容，带重试） |
| `content_studio/core/prompts.py` | 公众号/小红书 prompt 构造器 |
| `content_studio/core/generator.py` | 编排生成 + JSON 解析 + 降级 |
| `content_studio/core/image_pipeline.py` | 图片原子操作 + 按平台组合 |
| `content_studio/core/exporter.py` | 打包文本+图片产出 |
| `content_studio/core/ocr.py` | PaddleOCR 可选封装（优雅降级） |
| `content_studio/gui/__init__.py` | 包标记 |
| `content_studio/gui/app.py` | CustomTkinter 主窗口 + 一键生成流程 |
| `content_studio/main.py` | 入口 |
| `tests/test_*.py` | 每个 core 模块一个测试文件 |

---

## Task 1: 环境与项目骨架

**Files:**
- Create: `.gitignore`, `conftest.py`, `content_studio/__init__.py`, `content_studio/core/__init__.py`, `content_studio/gui/__init__.py`
- Modify: `requirements.txt`
- Test: 无（验证导入可用即可）

**Interfaces:**
- Produces: 可 import 的空包 `content_studio`、`content_studio.core`、`content_studio.gui`；可用的 git 仓库；装好 openai/customtkinter/pytest 的 venv。

- [ ] **Step 1: 安装 git（winget）**

```powershell
winget install --id Git.Git -e --accept-source-agreements --accept-package-agreements
```
Expected: 安装成功。若已装会提示已安装。

- [ ] **Step 2: 在新终端验证 git 可用**

Run: `git --version`
Expected: 输出 `git version ...`（若报找不到，开新终端重试；PATH 需新进程刷新）。

- [ ] **Step 3: 初始化 git 仓库**

Run: `git init`
Expected: `Initialized empty Git repository in ...`

- [ ] **Step 4: 写 `.gitignore`**

Create `.gitignore`:
```
.venv-paddle/
reports/
output/
__pycache__/
*.pyc
.pytest_cache/
~/.content_studio/
```

- [ ] **Step 5: 给 venv 引导 pip**

Run: `.\.venv-paddle\Scripts\python.exe -m ensurepip --upgrade`
Expected: 输出 `Successfully installed pip-...` 或提示已存在。

- [ ] **Step 6: 安装缺失依赖**

Run: `.\.venv-paddle\Scripts\python.exe -m pip install openai customtkinter pytest`
Expected: `Successfully installed openai-... customtkinter-... pytest-...`

- [ ] **Step 7: 更新 requirements.txt**

在 `requirements.txt` 末尾追加：
```
openai
customtkinter
# dev only:
# pytest
```

- [ ] **Step 8: 创建包骨架文件**

Create `content_studio/__init__.py`（内容为空字符串 `"""Content Studio."""`）:
```python
"""Content Studio."""
```
Create `content_studio/core/__init__.py`:
```python
"""Core logic (no GUI dependencies)."""
```
Create `content_studio/gui/__init__.py`:
```python
"""GUI layer."""
```
Create `conftest.py`（空，用于 pytest sys.path）:
```python
# 让 pytest 把仓库根加入 sys.path
```

- [ ] **Step 9: 验证导入与 pytest 可用**

Run: `.\.venv-paddle\Scripts\python.exe -c "import openai, customtkinter, PIL, cv2; from content_studio.core import models, prompts, generator, image_pipeline, exporter, ocr; print('ok')"`
Expected: 报 `ModuleNotFoundError: No module named 'content_studio.core.models'`（因为还没创建这些模块，属正常——只要 `openai/customtkinter/PIL/cv2` 不报错即可）。若第三方库报错则回到 Step 6。

Run: `.\.venv-paddle\Scripts\python.exe -m pytest -q`
Expected: `no tests ran`（无测试，不报错）。

- [ ] **Step 10: 提交**

```bash
git add .gitignore conftest.py requirements.txt content_studio
git commit -m "chore: project skeleton and dependencies"
```
Expected: 提交成功。

---

## Task 2: 配置模块（config.py）

**Files:**
- Create: `content_studio/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces:
  - `ProviderConfig(name, base_url, api_key="", model="")`
  - `ImageConfig(watermark_text="@我的账号", crop_strategy="crop", jpeg_quality=85, collage=False)`
  - `WeChatConfig(app_id="", app_secret="", publish_enabled=False)`
  - `AppConfig(providers, active_provider, image, ocr_enabled, wechat)`
  - `load_config(path=DEFAULT_CONFIG_PATH) -> AppConfig`
  - `save_config(cfg, path=DEFAULT_CONFIG_PATH) -> None`
  - `get_active_provider(cfg) -> ProviderConfig`
  - 常量 `DEFAULT_CONFIG_PATH = Path.home() / ".content_studio" / "config.json"`

- [ ] **Step 1: 写失败测试**

Create `tests/test_config.py`:
```python
from pathlib import Path
from content_studio.config import (
    AppConfig, ProviderConfig, ImageConfig, WeChatConfig,
    load_config, save_config, get_active_provider, default_config,
)


def test_default_config_has_two_providers_and_active():
    cfg = default_config()
    names = [p.name for p in cfg.providers]
    assert "deepseek" in names and "glm" in names
    assert cfg.active_provider == "deepseek"
    assert isinstance(cfg.image, ImageConfig)
    assert isinstance(cfg.wechat, WeChatConfig)


def test_save_then_load_round_trip(tmp_path: Path):
    path = tmp_path / "config.json"
    cfg = default_config()
    cfg.active_provider = "glm"
    cfg.image.watermark_text = "@me"
    cfg.ocr_enabled = True
    save_config(cfg, path)
    loaded = load_config(path)
    assert loaded.active_provider == "glm"
    assert loaded.image.watermark_text == "@me"
    assert loaded.ocr_enabled is True
    assert len(loaded.providers) == 2


def test_get_active_provider_resolves(tmp_path: Path):
    cfg = default_config()
    p = get_active_provider(cfg)
    assert p.name == "deepseek"
    cfg.active_provider = "glm"
    assert get_active_provider(cfg).name == "glm"


def test_load_missing_file_creates_default(tmp_path: Path):
    path = tmp_path / "config.json"
    cfg = load_config(path)
    assert path.exists()
    assert cfg.active_provider == "deepseek"
```

- [ ] **Step 2: 运行测试验证失败**

Run: `.\.venv-paddle\Scripts\python.exe -m pytest tests/test_config.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'content_studio.config'`）。

- [ ] **Step 3: 实现 config.py**

Create `content_studio/config.py`:
```python
"""配置加载与持久化。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

DEFAULT_CONFIG_PATH = Path.home() / ".content_studio" / "config.json"


@dataclass
class ProviderConfig:
    name: str
    base_url: str
    api_key: str = ""
    model: str = ""


@dataclass
class ImageConfig:
    watermark_text: str = "@我的账号"
    crop_strategy: str = "crop"   # "crop" | "pad"
    jpeg_quality: int = 85
    collage: bool = False


@dataclass
class WeChatConfig:
    app_id: str = ""
    app_secret: str = ""
    publish_enabled: bool = False


@dataclass
class AppConfig:
    providers: list[ProviderConfig] = field(default_factory=list)
    active_provider: str = ""
    image: ImageConfig = field(default_factory=ImageConfig)
    ocr_enabled: bool = False
    wechat: WeChatConfig = field(default_factory=WeChatConfig)


def default_config() -> AppConfig:
    return AppConfig(
        providers=[
            ProviderConfig(name="deepseek", base_url="https://api.deepseek.com/v1", model="deepseek-chat"),
            ProviderConfig(name="glm", base_url="https://open.bigmodel.cn/api/paas/v4", model="glm-4"),
        ],
        active_provider="deepseek",
    )


def save_config(cfg: AppConfig, path: Path = DEFAULT_CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(cfg), ensure_ascii=False, indent=2), encoding="utf-8")


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> AppConfig:
    if not path.exists():
        cfg = default_config()
        save_config(cfg, path)
        return cfg
    data = json.loads(path.read_text(encoding="utf-8"))
    providers = [ProviderConfig(**p) for p in data.get("providers", [])]
    image = ImageConfig(**data.get("image", {}))
    wechat = WeChatConfig(**data.get("wechat", {}))
    return AppConfig(
        providers=providers,
        active_provider=data.get("active_provider", ""),
        image=image,
        ocr_enabled=data.get("ocr_enabled", False),
        wechat=wechat,
    )


def get_active_provider(cfg: AppConfig) -> ProviderConfig:
    for p in cfg.providers:
        if p.name == cfg.active_provider:
            return p
    if cfg.providers:
        return cfg.providers[0]
    raise ValueError("没有配置任何 provider")
```

- [ ] **Step 4: 运行测试验证通过**

Run: `.\.venv-paddle\Scripts\python.exe -m pytest tests/test_config.py -q`
Expected: `4 passed`

- [ ] **Step 5: 提交**

```bash
git add content_studio/config.py tests/test_config.py
git commit -m "feat(config): config dataclass with load/save and active provider"
```

---

## Task 3: LLM 客户端（core/models.py）

**Files:**
- Create: `content_studio/core/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: `content_studio.config.ProviderConfig`
- Produces:
  - `LLMError(Exception)`
  - `LLMClient(provider: ProviderConfig, client=None, max_retries=3, sleeper=time.sleep)`
  - `LLMClient.complete_json(system: str, user: str) -> str`：返回模型内容字符串；可重试错误重试后仍失败抛 `LLMError`。

- [ ] **Step 1: 写失败测试**

Create `tests/test_models.py`:
```python
import openai
import pytest
from content_studio.config import ProviderConfig
from content_studio.core.models import LLMClient, LLMError


def _provider():
    return ProviderConfig(name="deepseek", base_url="http://x", api_key="sk-x", model="m")


class FakeMessage:
    def __init__(self, content): self.content = content

class FakeChoice:
    def __init__(self, content): self.message = FakeMessage(content)

class FakeResp:
    def __init__(self, content): self.choices = [FakeChoice(content)]

class FakeCompletions:
    def __init__(self, outputs): self.outputs = list(outputs); self.calls = 0
    def create(self, **kw):
        self.calls += 1
        out = self.outputs.pop(0)
        if isinstance(out, Exception): raise out
        return FakeResp(out)

class FakeChat:
    def __init__(self, completions): self.completions = completions
class FakeClient:
    def __init__(self, completions): self.chat = FakeChat(completions)


def test_complete_json_returns_content():
    comp = FakeCompletions(['{"a":1}'])
    c = LLMClient(_provider(), client=FakeClient(comp))
    assert c.complete_json("sys", "usr") == '{"a":1}'
    assert comp.calls == 1


def test_retry_on_rate_limit_then_success():
    comp = FakeCompletions([openai.RateLimitError("boom", response=None, body=None), '{"a":1}'])
    c = LLMClient(_provider(), client=FakeClient(comp), sleeper=lambda _s: None)
    assert c.complete_json("sys", "usr") == '{"a":1}'
    assert comp.calls == 2


def test_retry_exhausted_raises_llm_error():
    err = openai.RateLimitError("boom", response=None, body=None)
    comp = FakeCompletions([err, err, err])
    c = LLMClient(_provider(), client=FakeClient(comp), sleeper=lambda _s: None)
    with pytest.raises(LLMError):
        c.complete_json("sys", "usr")
    assert comp.calls == 3


def test_non_retryable_error_wrapped_immediately():
    comp = FakeCompletions([ValueError("bad")])
    c = LLMClient(_provider(), client=FakeClient(comp))
    with pytest.raises(LLMError):
        c.complete_json("sys", "usr")
    assert comp.calls == 1
```

- [ ] **Step 2: 运行测试验证失败**

Run: `.\.venv-paddle\Scripts\python.exe -m pytest tests/test_models.py -q`
Expected: FAIL（`ModuleNotFoundError: ... models`）。

- [ ] **Step 3: 实现 models.py**

Create `content_studio/core/models.py`:
```python
"""LLM 客户端（OpenAI 兼容，带重试）。"""
from __future__ import annotations

import time
from typing import Any, Callable

import openai
from openai import OpenAI

from content_studio.config import ProviderConfig


class LLMError(Exception):
    pass


class LLMClient:
    RETRYABLE = (
        getattr(openai, "APITimeoutError", Exception),
        getattr(openai, "APIConnectionError", Exception),
        getattr(openai, "RateLimitError", Exception),
        getattr(openai, "InternalServerError", Exception),
    )

    def __init__(
        self,
        provider: ProviderConfig,
        client: Any = None,
        max_retries: int = 3,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        self.provider = provider
        self.max_retries = max_retries
        self._sleep = sleeper
        self._client = client if client is not None else OpenAI(
            base_url=provider.base_url, api_key=provider.api_key or "missing-key"
        )

    def complete_json(self, system: str, user: str) -> str:
        last_err: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                resp = self._client.chat.completions.create(
                    model=self.provider.model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.8,
                )
                return resp.choices[0].message.content
            except self.RETRYABLE as e:
                last_err = e
                self._sleep(0.5 * (2 ** attempt))
            except Exception as e:
                raise LLMError(str(e)) from e
        raise LLMError(f"重试 {self.max_retries} 次后仍失败: {last_err}")
```

- [ ] **Step 4: 运行测试验证通过**

Run: `.\.venv-paddle\Scripts\python.exe -m pytest tests/test_models.py -q`
Expected: `4 passed`

- [ ] **Step 5: 提交**

```bash
git add content_studio/core/models.py tests/test_models.py
git commit -m "feat(models): OpenAI-compatible LLM client with retry"
```

---

## Task 4: Prompt 构造（core/prompts.py）

**Files:**
- Create: `content_studio/core/prompts.py`
- Test: `tests/test_prompts.py`

**Interfaces:**
- Produces:
  - `build_wechat_prompt(material: str) -> tuple[str, str]`：返回 (system, user)
  - `build_xhs_prompt(material: str) -> tuple[str, str]`

- [ ] **Step 1: 写失败测试**

Create `tests/test_prompts.py`:
```python
from content_studio.core.prompts import build_wechat_prompt, build_xhs_prompt


def test_wechat_prompt_contains_material():
    system, user = build_wechat_prompt("我的素材")
    assert "公众号" in system
    assert "json" in system.lower()
    assert "我的素材" in user


def test_xhs_prompt_contains_material():
    system, user = build_xhs_prompt("我的素材")
    assert "小红书" in system
    assert "json" in system.lower()
    assert "我的素材" in user


def test_prompts_return_two_strings():
    for fn in (build_wechat_prompt, build_xhs_prompt):
        system, user = fn("x")
        assert isinstance(system, str) and isinstance(user, str)
```

- [ ] **Step 2: 运行测试验证失败**

Run: `.\.venv-paddle\Scripts\python.exe -m pytest tests/test_prompts.py -q`
Expected: FAIL（`ModuleNotFoundError: ... prompts`）。

- [ ] **Step 3: 实现 prompts.py**

Create `content_studio/core/prompts.py`:
```python
"""公众号 / 小红书 的 prompt 构造。"""
from __future__ import annotations

WECHAT_SYSTEM = """你是一位资深微信公众号编辑。根据用户给的素材，写出公众号长文。
严格输出 JSON，键如下：
- title：标题
- summary：摘要，30 字以内
- body_html：正文，HTML 字符串，可用 <p> <h2> <strong> <br> 等标签，但不要 <html>/<body>
- image_captions：数组，为每张配图给的图注文字，可为空数组
只输出 JSON，不要多余解释。"""

XHS_SYSTEM = """你是一位小红书爆款笔记写手。根据用户给的素材，写出小红书笔记。
严格输出 JSON，键如下：
- title：15 字以内的吸睛标题
- body：正文，多用 emoji 和换行，口语化
- hashtags：数组，形如 "#话题"
- cover_text：封面主标题，6 字以内
只输出 JSON，不要多余解释。"""


def build_wechat_prompt(material: str) -> tuple[str, str]:
    return WECHAT_SYSTEM, f"素材：\n{material}\n\n请生成公众号文章 JSON。"


def build_xhs_prompt(material: str) -> tuple[str, str]:
    return XHS_SYSTEM, f"素材：\n{material}\n\n请生成小红书笔记 JSON。"
```

- [ ] **Step 4: 运行测试验证通过**

Run: `.\.venv-paddle\Scripts\python.exe -m pytest tests/test_prompts.py -q`
Expected: `3 passed`

- [ ] **Step 5: 提交**

```bash
git add content_studio/core/prompts.py tests/test_prompts.py
git commit -m "feat(prompts): wechat and xiaohongshu prompt builders"
```

---

## Task 5: 生成编排（core/generator.py）

**Files:**
- Create: `content_studio/core/generator.py`
- Test: `tests/test_generator.py`

**Interfaces:**
- Consumes: `content_studio.core.models.LLMClient`、`content_studio.core.prompts`
- Produces:
  - `WeChatContent(title, summary, body_html, image_captions, raw, fell_back)`
  - `XHSContent(title, body, hashtags, cover_text, raw, fell_back)`
  - `build_material(user_text, ocr_text="", image_count=0) -> str`
  - `Generator(client: LLMClient)`
  - `Generator.generate_wechat(material) -> WeChatContent`
  - `Generator.generate_xhs(material) -> XHSContent`
  - 解析失败时「修复式重发一次」，仍失败则 `fell_back=True`、字段降级为原文。

- [ ] **Step 1: 写失败测试**

Create `tests/test_generator.py`:
```python
from content_studio.core.generator import (
    Generator, WeChatContent, XHSContent, build_material,
)


class FakeClient:
    def __init__(self, outputs): self.outputs = list(outputs); self.calls = 0
    def complete_json(self, system, user):
        self.calls += 1
        out = self.outputs.pop(0)
        return out


def test_build_material_combines_text_ocr_images():
    m = build_material("正文", "图里文字", image_count=2)
    assert "正文" in m and "图里文字" in m and "2" in m


def test_build_material_empty():
    assert build_material("") != ""


def test_generate_wechat_parses_json():
    c = FakeClient(['{"title":"T","summary":"S","body_html":"<p>x</p>","image_captions":["c1"]}'])
    g = Generator(c)
    r = g.generate_wechat("素材")
    assert isinstance(r, WeChatContent)
    assert r.title == "T" and r.summary == "S" and r.body_html == "<p>x</p>"
    assert r.image_captions == ["c1"]
    assert r.fell_back is False
    assert c.calls == 1


def test_generate_wechat_recovers_on_second_try():
    c = FakeClient(["not json", '{"title":"T2"}'])
    r = Generator(c).generate_wechat("素材")
    assert r.title == "T2"
    assert c.calls == 2


def test_generate_wechat_falls_back_when_both_bad():
    c = FakeClient(["not json", "still not json"])
    r = Generator(c).generate_wechat("素材")
    assert r.fell_back is True
    assert "still not json" in r.body_html
    assert c.calls == 2


def test_generate_xhs_parses_json():
    c = FakeClient(['{"title":"T","body":"b","hashtags":["#a"],"cover_text":"封面"}'])
    r = Generator(c).generate_xhs("素材")
    assert isinstance(r, XHSContent)
    assert r.title == "T" and r.body == "b"
    assert r.hashtags == ["#a"] and r.cover_text == "封面"
```

- [ ] **Step 2: 运行测试验证失败**

Run: `.\.venv-paddle\Scripts\python.exe -m pytest tests/test_generator.py -q`
Expected: FAIL（`ModuleNotFoundError: ... generator`）。

- [ ] **Step 3: 实现 generator.py**

Create `content_studio/core/generator.py`:
```python
"""生成编排：调 LLM + JSON 解析 + 降级。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

from content_studio.core import models, prompts


@dataclass
class WeChatContent:
    title: str = ""
    summary: str = ""
    body_html: str = ""
    image_captions: list[str] = field(default_factory=list)
    raw: str = ""
    fell_back: bool = False


@dataclass
class XHSContent:
    title: str = ""
    body: str = ""
    hashtags: list[str] = field(default_factory=list)
    cover_text: str = ""
    raw: str = ""
    fell_back: bool = False


def build_material(user_text: str, ocr_text: str = "", image_count: int = 0) -> str:
    parts: list[str] = []
    if user_text.strip():
        parts.append(user_text.strip())
    if ocr_text.strip():
        parts.append(f"[图片中识别的文字]\n{ocr_text.strip()}")
    if image_count:
        parts.append(f"[附图 {image_count} 张]")
    return "\n\n".join(parts) if parts else "(无素材)"


def _parse_json(content: str) -> Optional[dict]:
    try:
        return json.loads(content)
    except Exception:
        return None


class Generator:
    def __init__(self, client: models.LLMClient):
        self.client = client

    def _complete_and_parse(self, system: str, user: str) -> tuple[Optional[dict], str]:
        content = self.client.complete_json(system, user)
        parsed = _parse_json(content)
        if parsed is None:
            fix_user = "上一次返回不是合法 JSON，请只输出合法 JSON。\n\n" + user
            content = self.client.complete_json(system, fix_user)
            parsed = _parse_json(content)
        return parsed, content

    def generate_wechat(self, material: str) -> WeChatContent:
        system, user = prompts.build_wechat_prompt(material)
        parsed, raw = self._complete_and_parse(system, user)
        if parsed is None:
            return WeChatContent(title="(解析失败)", body_html=raw, raw=raw, fell_back=True)
        return WeChatContent(
            title=parsed.get("title", ""),
            summary=parsed.get("summary", ""),
            body_html=parsed.get("body_html", ""),
            image_captions=list(parsed.get("image_captions") or []),
            raw=raw,
        )

    def generate_xhs(self, material: str) -> XHSContent:
        system, user = prompts.build_xhs_prompt(material)
        parsed, raw = self._complete_and_parse(system, user)
        if parsed is None:
            return XHSContent(title="(解析失败)", body=raw, raw=raw, fell_back=True)
        return XHSContent(
            title=parsed.get("title", ""),
            body=parsed.get("body", ""),
            hashtags=list(parsed.get("hashtags") or []),
            cover_text=parsed.get("cover_text", ""),
            raw=raw,
        )
```

- [ ] **Step 4: 运行测试验证通过**

Run: `.\.venv-paddle\Scripts\python.exe -m pytest tests/test_generator.py -q`
Expected: `6 passed`

- [ ] **Step 5: 提交**

```bash
git add content_studio/core/generator.py tests/test_generator.py
git commit -m "feat(generator): orchestrate generation with JSON parsing and fallback"
```

---

## Task 6: 图片处理（core/image_pipeline.py）

**Files:**
- Create: `content_studio/core/image_pipeline.py`
- Test: `tests/test_image_pipeline.py`

**Interfaces:**
- Consumes: `content_studio.config.ImageConfig`
- Produces（原子 + 组合）:
  - 常量 `XHS_COVER_SIZE=(1242,1656)`、`WECHAT_COVER_SIZE=(900,383)`、`WECHAT_ARTICLE_MAX_W=900`
  - `load_image(path) -> PIL.Image`
  - `to_cover_3_4(img, strategy="crop") -> Image`
  - `add_watermark(img, text, position="br", opacity=128) -> Image`
  - `add_title_overlay(img, title) -> Image`
  - `stitch_grid(imgs, cols=2) -> Image`
  - `to_wechat_cover(img) -> Image`
  - `resize_for_article(img, max_w=900) -> Image`
  - `save_jpeg(img, path, quality=85) -> Path`
  - `build_xhs_images(images, cfg, cover_text="") -> list[Image]`
  - `build_wechat_images(images, cfg) -> list[Image]`

- [ ] **Step 1: 写失败测试**

Create `tests/test_image_pipeline.py`:
```python
from PIL import Image

from content_studio.config import ImageConfig
from content_studio.core import image_pipeline as ip


def _img(w, h, color=(200, 50, 50)):
    return Image.new("RGB", (w, h), color)


def test_to_cover_3_4_size():
    out = ip.to_cover_3_4(_img(1000, 500))
    assert out.size == ip.XHS_COVER_SIZE


def test_to_cover_3_4_pad_keeps_size():
    out = ip.to_cover_3_4(_img(1000, 500), strategy="pad")
    assert out.size == ip.XHS_COVER_SIZE


def test_to_wechat_cover_size():
    out = ip.to_wechat_cover(_img(1000, 500))
    assert out.size == ip.WECHAT_COVER_SIZE


def test_resize_for_article_caps_width():
    out = ip.resize_for_article(_img(2000, 1000))
    assert out.width == 900
    out2 = ip.resize_for_article(_img(500, 300))
    assert out2.width == 500   # 不放大


def test_watermark_changes_pixels():
    src = _img(800, 600)
    out = ip.add_watermark(src, "@me")
    assert out.size == src.size
    assert list(out.getdata()) != list(src.getdata())


def test_watermark_empty_text_returns_same_pixels():
    src = _img(800, 600)
    out = ip.add_watermark(src, "")
    assert list(out.getdata()) == list(src.getdata())


def test_title_overlay_changes_pixels():
    src = _img(800, 600)
    out = ip.add_title_overlay(src, "主标题")
    assert out.size == src.size
    assert list(out.getdata()) != list(src.getdata())


def test_stitch_grid_dimensions():
    imgs = [_img(400, 300), _img(400, 300), _img(400, 300)]
    out = ip.stitch_grid(imgs, cols=2)
    assert out.size == (800, 600)   # 2 列 2 行，单元 400x300


def test_build_xhs_images_first_is_cover_with_overlay_and_watermark():
    cfg = ImageConfig(watermark_text="@me", crop_strategy="crop", collage=False)
    imgs = [Image.new("RGB", (900, 900), (10, 10, 10))]
    out = ip.build_xhs_images(imgs, cfg, cover_text="封面")
    assert len(out) == 1
    assert out[0].size == ip.XHS_COVER_SIZE


def test_build_xhs_images_collage_when_enabled():
    cfg = ImageConfig(watermark_text="@me", collage=True)
    imgs = [Image.new("RGB", (900, 900)), Image.new("RGB", (900, 900))]
    out = ip.build_xhs_images(imgs, cfg)
    assert len(out) == 1   # collage 只出一张
    assert out[0].size == ip.XHS_COVER_SIZE


def test_build_wechat_images_cover_plus_body():
    cfg = ImageConfig()
    imgs = [Image.new("RGB", (1200, 800)), Image.new("RGB", (2000, 1000))]
    out = ip.build_wechat_images(imgs, cfg)
    assert out[0].size == ip.WECHAT_COVER_SIZE
    assert out[1].width <= ip.WECHAT_ARTICLE_MAX_W


def test_build_empty_returns_empty():
    assert ip.build_xhs_images([], ImageConfig()) == []
    assert ip.build_wechat_images([], ImageConfig()) == []


def test_save_jpeg_writes_file(tmp_path):
    p = ip.save_jpeg(_img(100, 100), tmp_path / "out" / "x.jpg")
    assert p.exists() and p.suffix == ".jpg"
```

- [ ] **Step 2: 运行测试验证失败**

Run: `.\.venv-paddle\Scripts\python.exe -m pytest tests/test_image_pipeline.py -q`
Expected: FAIL（`ModuleNotFoundError: ... image_pipeline`）。

- [ ] **Step 3: 实现 image_pipeline.py**

Create `content_studio/core/image_pipeline.py`:
```python
"""图片原子操作与按平台组合。"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from content_studio.config import ImageConfig

XHS_COVER_SIZE = (1242, 1656)        # 3:4
WECHAT_COVER_SIZE = (900, 383)       # 2.35:1
WECHAT_ARTICLE_MAX_W = 900


def load_image(path: str | Path) -> Image.Image:
    return Image.open(path).convert("RGB")


def _fit_font(size: int) -> ImageFont.FreeTypeFont:
    for name in ("msyh.ttc", "simhei.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _contain(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    target_ratio = target_w / target_h
    src_ratio = img.width / img.height
    if src_ratio > target_ratio:
        new_w = target_w
        new_h = int(target_w / src_ratio)
    else:
        new_h = target_h
        new_w = int(target_h * src_ratio)
    return img.resize((new_w, new_h), Image.LANCZOS)


def to_cover_3_4(img: Image.Image, strategy: str = "crop") -> Image.Image:
    target_w, target_h = XHS_COVER_SIZE
    if strategy == "pad":
        scaled = _contain(img, target_w, target_h)
        canvas = Image.new("RGB", (target_w, target_h), (255, 255, 255))
        canvas.paste(scaled, ((target_w - scaled.width) // 2, (target_h - scaled.height) // 2))
        return canvas
    target_ratio = target_w / target_h
    src_ratio = img.width / img.height
    if src_ratio > target_ratio:
        new_w = int(img.height * target_ratio)
        left = (img.width - new_w) // 2
        img = img.crop((left, 0, left + new_w, img.height))
    else:
        new_h = int(img.width / target_ratio)
        top = (img.height - new_h) // 2
        img = img.crop((0, top, img.width, top + new_h))
    return img.resize((target_w, target_h), Image.LANCZOS)


def add_watermark(img: Image.Image, text: str, position: str = "br", opacity: int = 128) -> Image.Image:
    if not text:
        return img
    layer = img.convert("RGBA")
    overlay = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    font = _fit_font(max(24, layer.height // 30))
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    margin = layer.height // 40
    pos = {
        "br": (layer.width - tw - margin, layer.height - th - margin),
        "bl": (margin, layer.height - th - margin),
        "tr": (layer.width - tw - margin, margin),
        "tl": (margin, margin),
    }[position]
    draw.text(pos, text, fill=(255, 255, 255, opacity), font=font,
              stroke_width=2, stroke_fill=(0, 0, 0, int(opacity * 0.6)))
    return Image.alpha_composite(layer, overlay).convert("RGB")


def add_title_overlay(img: Image.Image, title: str) -> Image.Image:
    if not title:
        return img
    layer = img.convert("RGBA")
    overlay = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    font = _fit_font(layer.height // 9)
    margin = layer.width // 15
    bbox = draw.textbbox((0, 0), title, font=font)
    th = bbox[3] - bbox[1]
    y = layer.height // 2 - th // 2
    draw.rectangle([0, y - margin, layer.width, y + th + margin], fill=(0, 0, 0, 140))
    draw.text((margin, y), title, fill=(255, 255, 255, 255), font=font)
    return Image.alpha_composite(layer, overlay).convert("RGB")


def stitch_grid(imgs: list[Image.Image], cols: int = 2) -> Image.Image:
    if not imgs:
        raise ValueError("无图可拼")
    rows = (len(imgs) + cols - 1) // cols
    cell_w = min(i.width for i in imgs)
    cell_h = min(i.height for i in imgs)
    canvas = Image.new("RGB", (cell_w * cols, cell_h * rows), (255, 255, 255))
    for idx, im in enumerate(imgs):
        r, c = divmod(idx, cols)
        canvas.paste(im.resize((cell_w, cell_h), Image.LANCZOS), (c * cell_w, r * cell_h))
    return canvas


def to_wechat_cover(img: Image.Image) -> Image.Image:
    tw, th = WECHAT_COVER_SIZE
    target_ratio = tw / th
    src_ratio = img.width / img.height
    if src_ratio > target_ratio:
        new_w = int(img.height * target_ratio)
        left = (img.width - new_w) // 2
        img = img.crop((left, 0, left + new_w, img.height))
    else:
        new_h = int(img.width / target_ratio)
        top = (img.height - new_h) // 2
        img = img.crop((0, top, img.width, top + new_h))
    return img.resize((tw, th), Image.LANCZOS)


def resize_for_article(img: Image.Image, max_w: int = WECHAT_ARTICLE_MAX_W) -> Image.Image:
    if img.width > max_w:
        new_h = int(img.height * max_w / img.width)
        img = img.resize((max_w, new_h), Image.LANCZOS)
    return img


def save_jpeg(img: Image.Image, path: str | Path, quality: int = 85) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "JPEG", quality=quality)
    return path


def build_xhs_images(images: list[Image.Image], cfg: ImageConfig, cover_text: str = "") -> list[Image.Image]:
    if not images:
        return []
    base = [to_cover_3_4(im, cfg.crop_strategy) for im in images]
    if cfg.collage and len(base) >= 2:
        cover = to_cover_3_4(stitch_grid(base, cols=2), "pad")
    else:
        cover = base[0]
        if cover_text:
            cover = add_title_overlay(cover, cover_text)
    cover = add_watermark(cover, cfg.watermark_text)
    rest = [add_watermark(im, cfg.watermark_text) for im in base[1:]]
    return [cover] + rest


def build_wechat_images(images: list[Image.Image], cfg: ImageConfig) -> list[Image.Image]:
    if not images:
        return []
    cover = to_wechat_cover(images[0])
    body = [resize_for_article(im) for im in images[1:]]
    return [cover] + body
```

- [ ] **Step 4: 运行测试验证通过**

Run: `.\.venv-paddle\Scripts\python.exe -m pytest tests/test_image_pipeline.py -q`
Expected: `12 passed`

- [ ] **Step 5: 提交**

```bash
git add content_studio/core/image_pipeline.py tests/test_image_pipeline.py
git commit -m "feat(image): pipeline ops and per-platform image builders"
```

---

## Task 7: 导出打包（core/exporter.py）

**Files:**
- Create: `content_studio/core/exporter.py`
- Test: `tests/test_exporter.py`

**Interfaces:**
- Consumes: `WeChatContent`、`XHSContent`、`ImageConfig`、`image_pipeline`
- Produces:
  - `ExportArtifacts(out_dir, wechat_text_path, xhs_text_path, wechat_images, xhs_images)`
  - `export(wechat, xhs, source_images, cfg, out_dir) -> ExportArtifacts`

- [ ] **Step 1: 写失败测试**

Create `tests/test_exporter.py`:
```python
from pathlib import Path
from PIL import Image

from content_studio.config import ImageConfig
from content_studio.core.exporter import export
from content_studio.core.generator import WeChatContent, XHSContent


def test_export_writes_text_and_images(tmp_path: Path):
    wc = WeChatContent(title="标题", summary="摘要", body_html="<p>正文</p>", image_captions=["c1"])
    xh = XHSContent(title="小红书标题", body="正文", hashtags=["#a"], cover_text="封面")
    imgs = [Image.new("RGB", (900, 900), (20, 20, 20))]
    art = export(wc, xh, imgs, ImageConfig(), tmp_path / "out")
    assert art.wechat_text_path.exists()
    assert art.xhs_text_path.exists()
    assert len(art.wechat_images) == 1
    assert len(art.xhs_images) == 1
    assert all(Path(p).exists() for p in art.wechat_images + art.xhs_images)
    assert "标题" in art.wechat_text_path.read_text(encoding="utf-8")
    assert "小红书标题" in art.xhs_text_path.read_text(encoding="utf-8")
    assert "#a" in art.xhs_text_path.read_text(encoding="utf-8")


def test_export_no_images_still_writes_text(tmp_path: Path):
    wc = WeChatContent(title="T")
    xh = XHSContent(title="X")
    art = export(wc, xh, [], ImageConfig(), tmp_path / "out")
    assert art.wechat_images == [] and art.xhs_images == []
    assert art.wechat_text_path.exists() and art.xhs_text_path.exists()
```

- [ ] **Step 2: 运行测试验证失败**

Run: `.\.venv-paddle\Scripts\python.exe -m pytest tests/test_exporter.py -q`
Expected: FAIL（`ModuleNotFoundError: ... exporter`）。

- [ ] **Step 3: 实现 exporter.py**

Create `content_studio/core/exporter.py`:
```python
"""把生成结果与处理后的图片打包到输出目录。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from content_studio.config import ImageConfig
from content_studio.core import image_pipeline
from content_studio.core.generator import WeChatContent, XHSContent


@dataclass
class ExportArtifacts:
    out_dir: Path
    wechat_text_path: Path
    xhs_text_path: Path
    wechat_images: list[Path]
    xhs_images: list[Path]


def _format_wechat(wc: WeChatContent) -> str:
    lines = [f"标题：{wc.title}"]
    if wc.summary:
        lines.append(f"摘要：{wc.summary}")
    lines.append("")
    lines.append(wc.body_html or "")
    if wc.image_captions:
        lines.append("")
        lines.append("图注：")
        lines.extend(f"- {c}" for c in wc.image_captions)
    if wc.fell_back:
        lines.insert(0, "（⚠ 解析失败，以下为原始返回）")
    return "\n".join(lines)


def _format_xhs(xh: XHSContent) -> str:
    lines = [f"标题：{xh.title}"]
    if xh.cover_text:
        lines.append(f"封面主标题：{xh.cover_text}")
    lines.append("")
    lines.append(xh.body or "")
    if xh.hashtags:
        lines.append("")
        lines.append(" ".join(xh.hashtags))
    if xh.fell_back:
        lines.insert(0, "（⚠ 解析失败，以下为原始返回）")
    return "\n".join(lines)


def export(
    wechat: WeChatContent,
    xhs: XHSContent,
    source_images: list[Image.Image],
    cfg: ImageConfig,
    out_dir: str | Path,
) -> ExportArtifacts:
    if wechat is None:
        wechat = WeChatContent()
    if xhs is None:
        xhs = XHSContent()
    out_dir = Path(out_dir)
    wechat_dir = out_dir / "wechat"
    xhs_dir = out_dir / "xiaohongshu"

    wechat_imgs = image_pipeline.build_wechat_images(source_images, cfg)
    xhs_imgs = image_pipeline.build_xhs_images(source_images, cfg, xhs.cover_text)

    wechat_paths = [
        image_pipeline.save_jpeg(im, wechat_dir / f"img_{i + 1}.jpg", cfg.jpeg_quality)
        for i, im in enumerate(wechat_imgs)
    ]
    xhs_paths = [
        image_pipeline.save_jpeg(im, xhs_dir / f"img_{i + 1}.jpg", cfg.jpeg_quality)
        for i, im in enumerate(xhs_imgs)
    ]

    wechat_text_path = out_dir / "wechat.txt"
    xhs_text_path = out_dir / "xiaohongshu.txt"
    wechat_text_path.write_text(_format_wechat(wechat), encoding="utf-8")
    xhs_text_path.write_text(_format_xhs(xhs), encoding="utf-8")

    return ExportArtifacts(out_dir, wechat_text_path, xhs_text_path, wechat_paths, xhs_paths)
```

- [ ] **Step 4: 运行测试验证通过**

Run: `.\.venv-paddle\Scripts\python.exe -m pytest tests/test_exporter.py -q`
Expected: `2 passed`

- [ ] **Step 5: 提交**

```bash
git add content_studio/core/exporter.py tests/test_exporter.py
git commit -m "feat(exporter): package text and processed images to output dir"
```

---

## Task 8: OCR 封装（core/ocr.py）

**Files:**
- Create: `content_studio/core/ocr.py`
- Test: `tests/test_ocr.py`

**Interfaces:**
- Produces:
  - `extract_text(image_paths, initializer=None) -> str`：成功返回拼接文本；初始化或单图失败时优雅返回（部分）字符串，不抛异常。

- [ ] **Step 1: 写失败测试**

Create `tests/test_ocr.py`:
```python
from content_studio.core import ocr


def test_extract_text_init_failure_returns_empty():
    def bad_init(): raise RuntimeError("no paddle")
    assert ocr.extract_text(["a.png"], initializer=bad_init) == ""


def test_extract_text_collects_lines_via_initializer():
    class FakeOCR:
        def ocr(self, path, cls=True):
            return [[[[0, 0], [1, 1]], ("识别的文字A", 0.9)]]
    def good_init(): return FakeOCR()
    out = ocr.extract_text(["a.png"], initializer=good_init)
    assert "识别的文字A" in out


def test_extract_text_skips_failing_image_but_keeps_good(monkeypatch):
    class FakeOCR:
        def __init__(self): self.first = True
        def ocr(self, path, cls=True):
            if self.first:
                self.first = False
                raise RuntimeError("boom")
            return [[[[0, 0], [1, 1]], ("好的文字", 0.9)]]
    def good_init(): return FakeOCR()
    out = ocr.extract_text(["a.png", "b.png"], initializer=good_init)
    assert "好的文字" in out
```

- [ ] **Step 2: 运行测试验证失败**

Run: `.\.venv-paddle\Scripts\python.exe -m pytest tests/test_ocr.py -q`
Expected: FAIL（`ModuleNotFoundError: ... ocr`）。

- [ ] **Step 3: 实现 ocr.py**

Create `content_studio/core/ocr.py`:
```python
"""可选的 PaddleOCR 封装；任何失败都优雅降级，不影响主流程。"""
from __future__ import annotations

import logging
from collections.abc import Callable, Iterable

log = logging.getLogger(__name__)


def extract_text(
    image_paths: Iterable[str],
    initializer: Callable[[], object] | None = None,
) -> str:
    paths = list(image_paths)
    try:
        if initializer is not None:
            ocr = initializer()
        else:
            from paddleocr import PaddleOCR
            ocr = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
    except Exception as e:
        log.warning("OCR 初始化失败，已禁用 OCR: %s", e)
        return ""

    lines: list[str] = []
    for p in paths:
        try:
            result = None
            if hasattr(ocr, "ocr"):
                result = ocr.ocr(str(p), cls=True)
            elif hasattr(ocr, "predict"):
                result = ocr.predict(str(p))
            for block in (result or []):
                # paddleocr 2.x: block = [ [box, (text, score)], ... ]
                if isinstance(block, list):
                    for line in block:
                        if line and len(line) >= 2 and line[1]:
                            lines.append(line[1][0])
                # paddleocr 3.x: block 可能是 dict，含 rec_texts
                elif isinstance(block, dict):
                    lines.extend(block.get("rec_texts", []) or [])
        except Exception as e:
            log.warning("OCR 处理 %s 失败: %s", p, e)
    return "\n".join(lines)
```

- [ ] **Step 4: 运行测试验证通过**

Run: `.\.venv-paddle\Scripts\python.exe -m pytest tests/test_ocr.py -q`
Expected: `3 passed`

- [ ] **Step 5: 提交**

```bash
git add content_studio/core/ocr.py tests/test_ocr.py
git commit -m "feat(ocr): optional PaddleOCR wrapper with graceful degradation"
```

---

## Task 9: GUI 主程序（gui/app.py + main.py）

**Files:**
- Create: `content_studio/gui/app.py`, `content_studio/main.py`
- Test: 无单元测试（手动冒烟）

**Interfaces:**
- Consumes: 全部 `core/*`、`config`
- Produces: `gui.app.run() -> None`（启动窗口）；`main.py` 入口。

**说明：** GUI 不做单元测试。验收 = 运行 `main.py` 能开窗口、能完成一次「一键生成」（需配置真实 provider 的 api_key）。

- [ ] **Step 1: 实现 gui/app.py**

Create `content_studio/gui/app.py`:
```python
"""CustomTkinter 主窗口 + 一键生成流程。"""
from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from content_studio.config import AppConfig, get_active_provider, load_config, save_config
from content_studio.core import exporter, image_pipeline, ocr
from content_studio.core.generator import Generator, build_material
from content_studio.core.models import LLMClient, LLMError

ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")


class SettingsDialog(ctk.CTkToplevel):
    def __init__(self, master, cfg: AppConfig, on_save):
        super().__init__(master)
        self.title("设置")
        self.geometry("520x560")
        self.cfg = cfg
        self.on_save = on_save
        self._build()

    def _build(self):
        ctk.CTkLabel(self, text="当前 Provider").pack(anchor="w", padx=16, pady=(16, 0))
        names = [p.name for p in self.cfg.providers]
        self.provider_var = ctk.StringVar(value=self.cfg.active_provider or (names[0] if names else ""))
        self.provider_menu = ctk.CTkOptionMenu(self, values=names, variable=self.provider_var)
        self.provider_menu.pack(fill="x", padx=16)

        ctk.CTkLabel(self, text="API Key").pack(anchor="w", padx=16, pady=(12, 0))
        self.key_entry = ctk.CTkEntry(self, show="*", width=480)
        self.key_entry.pack(fill="x", padx=16)
        cur = self._current_provider()
        if cur:
            self.key_entry.insert(0, cur.api_key)

        ctk.CTkLabel(self, text="模型名").pack(anchor="w", padx=16, pady=(12, 0))
        self.model_entry = ctk.CTkEntry(self, width=480)
        self.model_entry.pack(fill="x", padx=16)
        if cur:
            self.model_entry.insert(0, cur.model)

        ctk.CTkLabel(self, text="水印文字").pack(anchor="w", padx=16, pady=(12, 0))
        self.watermark_entry = ctk.CTkEntry(self, width=480)
        self.watermark_entry.pack(fill="x", padx=16)
        self.watermark_entry.insert(0, self.cfg.image.watermark_text)

        self.collage_var = ctk.BooleanVar(value=self.cfg.image.collage)
        ctk.CTkCheckBox(self, text="小红书封面用 collage 拼图", variable=self.collage_var).pack(anchor="w", padx=16, pady=(8, 0))

        self.ocr_var = ctk.BooleanVar(value=self.cfg.ocr_enabled)
        ctk.CTkCheckBox(self, text="启用 OCR（从图片提取文字）", variable=self.ocr_var).pack(anchor="w", padx=16)

        ctk.CTkButton(self, text="保存", command=self._save).pack(pady=16)

    def _current_provider(self):
        for p in self.cfg.providers:
            if p.name == self.provider_var.get():
                return p
        return self.cfg.providers[0] if self.cfg.providers else None

    def _save(self):
        p = self._current_provider()
        if p:
            p.api_key = self.key_entry.get()
            p.model = self.model_entry.get()
        self.cfg.active_provider = self.provider_var.get()
        self.cfg.image.watermark_text = self.watermark_entry.get()
        self.cfg.image.collage = self.collage_var.get()
        self.cfg.ocr_enabled = self.ocr_var.get()
        save_config(self.cfg)
        self.on_save(self.cfg)
        self.destroy()


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Content Studio")
        self.geometry("1100x720")
        self.cfg = load_config()
        self.image_paths: list[str] = []
        self._build()
        # 首次启动若没有任何 provider 配过 api_key，自动弹设置面板
        if not any(p.api_key for p in self.cfg.providers):
            self.after(100, self._open_settings)

    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=0, column=0, columnspan=2, sticky="ew", padx=12, pady=8)
        ctk.CTkLabel(top, text="Content Studio", font=ctk.CTkFont(size=22, weight="bold")).pack(side="left", padx=8)
        ctk.CTkButton(top, text="设置", width=80, command=self._open_settings).pack(side="right", padx=4)
        self.gen_btn = ctk.CTkButton(top, text="一键生成", width=120, command=self._on_generate)
        self.gen_btn.pack(side="right", padx=4)

        # 左：输入
        left = ctk.CTkFrame(self)
        left.grid(row=1, column=0, sticky="nsew", padx=(12, 6), pady=6)
        left.grid_rowconfigure(2, weight=1)
        ctk.CTkLabel(left, text="素材文字").grid(row=0, column=0, sticky="w", padx=10, pady=(10, 0))
        self.text_box = ctk.CTkTextbox(left)
        self.text_box.grid(row=2, column=0, sticky="nsew", padx=10, pady=6)
        btns = ctk.CTkFrame(left, fg_color="transparent")
        btns.grid(row=1, column=0, sticky="ew", padx=10)
        ctk.CTkButton(btns, text="添加图片", command=self._add_images).pack(side="left", padx=(0, 6))
        ctk.CTkButton(btns, text="清空图片", command=self._clear_images).pack(side="left")
        self.img_label = ctk.CTkLabel(left, text="未选择图片", anchor="w")
        self.img_label.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 10))

        # 右：输出（tab）
        right = ctk.CTkFrame(self)
        right.grid(row=1, column=1, sticky="nsew", padx=(6, 12), pady=6)
        right.grid_rowconfigure(1, weight=1)
        right.grid_columnconfigure(0, weight=1)
        self.tabs = ctk.CTkTabview(right)
        self.tabs.grid(row=1, column=0, sticky="nsew", padx=8, pady=8)
        self.tabs.add("公众号")
        self.tabs.add("小红书")
        self.wechat_box = ctk.CTkTextbox(self.tabs.tab("公众号"))
        self.wechat_box.pack(fill="both", expand=True, padx=6, pady=6)
        self.xhs_box = ctk.CTkTextbox(self.tabs.tab("小红书"))
        self.xhs_box.pack(fill="both", expand=True, padx=6, pady=6)

        bar = ctk.CTkFrame(right, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 0))
        self.status = ctk.CTkLabel(bar, text="就绪", anchor="w")
        self.status.pack(side="left")
        ctk.CTkButton(bar, text="复制公众号", width=110, command=lambda: self._copy(self.wechat_box)).pack(side="right", padx=4)
        ctk.CTkButton(bar, text="复制小红书", width=110, command=lambda: self._copy(self.xhs_box)).pack(side="right", padx=4)
        ctk.CTkButton(bar, text="打开输出目录", width=120, command=self._open_output).pack(side="right", padx=4)
        # 第二阶段入口：灰置
        self.pub_btn = ctk.CTkButton(bar, text="发布到公众号(未启用)", width=160, state="disabled")
        self.pub_btn.pack(side="right", padx=4)

    # ---- 输入 ----
    def _add_images(self):
        files = filedialog.askopenfilenames(filetypes=[("图片", "*.png *.jpg *.jpeg *.bmp *.webp")])
        if files:
            self.image_paths.extend(files)
            self._refresh_img_label()

    def _clear_images(self):
        self.image_paths = []
        self._refresh_img_label()

    def _refresh_img_label(self):
        self.img_label.configure(text=f"已选 {len(self.image_paths)} 张图片" if self.image_paths else "未选择图片")

    # ---- 设置 ----
    def _open_settings(self):
        SettingsDialog(self, self.cfg, on_save=lambda c: setattr(self, "cfg", c))

    # ---- 生成 ----
    def _on_generate(self):
        provider = get_active_provider(self.cfg)
        if not provider.api_key:
            messagebox.showwarning("缺少配置", "请先在「设置」里填写当前 provider 的 API Key。")
            return
        self.gen_btn.configure(state="disabled")
        self.status.configure(text="生成中…")
        threading.Thread(target=self._generate_thread, args=(provider,), daemon=True).start()

    def _generate_thread(self, provider):
        try:
            user_text = self.text_box.get("1.0", "end").strip()
            ocr_text = ""
            if self.cfg.ocr_enabled and self.image_paths:
                ocr_text = ocr.extract_text(self.image_paths)
            material = build_material(user_text, ocr_text, len(self.image_paths))

            client = LLMClient(provider)
            gen = Generator(client)
            wc_err = xh_err = None
            wechat = xhs = None
            try:
                wechat = gen.generate_wechat(material)
            except LLMError as e:
                wc_err = str(e)
            try:
                xhs = gen.generate_xhs(material)
            except LLMError as e:
                xh_err = str(e)

            # 逐张加载：坏图跳过并计数告警，不中断整批
            source_images = []
            skipped = 0
            for p in self.image_paths:
                try:
                    source_images.append(image_pipeline.load_image(p))
                except Exception:
                    skipped += 1

            out_dir = Path.cwd() / "output"
            art = exporter.export(wechat, xhs, source_images, self.cfg.image, out_dir)

            self._last_output_dir = art.out_dir
            self.after(0, lambda: self._render(wechat, xhs, wc_err, xh_err, skipped))
        except Exception as e:
            self.after(0, lambda: self._fail(str(e)))

    def _render(self, wechat, xhs, wc_err, xh_err, skipped=0):
        self.wechat_box.delete("1.0", "end")
        self.xhs_box.delete("1.0", "end")
        if wechat:
            self.wechat_box.insert("1.0", exporter._format_wechat(wechat))
        if wc_err:
            self.wechat_box.insert("1.0", f"⚠ 公众号生成失败：{wc_err}\n（可重新点「一键生成」重试）\n\n")
        if xhs:
            self.xhs_box.insert("1.0", exporter._format_xhs(xhs))
        if xh_err:
            self.xhs_box.insert("1.0", f"⚠ 小红书生成失败：{xh_err}\n（可重新点「一键生成」重试）\n\n")
        note = "完成"
        if skipped:
            note += f"（已跳过 {skipped} 张坏图）"
        self.status.configure(text=note)
        self.gen_btn.configure(state="normal")

    def _fail(self, msg):
        self.status.configure(text="出错")
        self.gen_btn.configure(state="normal")
        messagebox.showerror("出错", msg)

    # ---- 工具 ----
    def _copy(self, box: ctk.CTkTextbox):
        self.clipboard_clear()
        self.clipboard_append(box.get("1.0", "end"))
        self.status.configure(text="已复制到剪贴板")

    def _open_output(self):
        d = getattr(self, "_last_output_dir", None)
        if d and Path(d).exists():
            import os
            os.startfile(str(d))   # type: ignore[attr-defined]
        else:
            messagebox.showinfo("提示", "还没有输出。先点「一键生成」。")


def run() -> None:
    App().mainloop()
```

- [ ] **Step 2: 实现 main.py**

Create `content_studio/main.py`:
```python
"""Content Studio 入口。"""
from content_studio.gui.app import run

if __name__ == "__main__":
    run()
```

- [ ] **Step 3: 冒烟测试——能 import 且语法无误**

Run: `.\.venv-paddle\Scripts\python.exe -c "from content_studio.gui import app; from content_studio.main import run; print('import ok')"`
Expected: 输出 `import ok`（无报错）。

- [ ] **Step 4: 冒烟测试——全量单测仍通过**

Run: `.\.venv-paddle\Scripts\python.exe -m pytest -q`
Expected: 全部 core 测试通过（GUI 无测试）。

- [ ] **Step 5: 手动验收（需要真实 api_key）**

1. Run: `.\.venv-paddle\Scripts\python.exe -m content_studio.main`
2. 点「设置」→ 选 provider → 填 API Key 和模型名 → 保存。
3. 粘贴一段文字，加 1~2 张图片，点「一键生成」。
4. 预期：公众号/小红书 tab 出现生成文本；`output/wechat`、`output/xiaohongshu` 下出现处理后图片（小红书首图为 3:4 带标题+水印）。
5. 点「复制公众号」「复制小红书」可复制；「打开输出目录」可打开。

- [ ] **Step 6: 提交**

```bash
git add content_studio/gui/app.py content_studio/main.py
git commit -m "feat(gui): CustomTkinter main window with one-click generation flow"
```

---

## Task 10: 端到端集成测试

**Files:**
- Test: `tests/test_end_to_end.py`

**Interfaces:**
- Consumes: `core/*`、`config`、`exporter`

- [ ] **Step 1: 写端到端测试（mock LLM）**

Create `tests/test_end_to_end.py`:
```python
from pathlib import Path
from PIL import Image

from content_studio.config import ImageConfig
from content_studio.core import exporter, image_pipeline
from content_studio.core.generator import Generator, build_material


class StubClient:
    """模拟 LLM：公众号和小红书各返回固定 JSON。"""
    def __init__(self): self.calls = 0
    def complete_json(self, system, user):
        self.calls += 1
        if "公众号" in system:
            return '{"title":"公众号标题","summary":"摘要","body_html":"<p>正文</p>","image_captions":["图1"]}'
        return '{"title":"小红书标题","body":"正文✨","hashtags":["#话题"],"cover_text":"封面"}'


def test_end_to_end_material_to_export(tmp_path: Path):
    # 1) 组装素材
    material = build_material("我的素材文字", ocr_text="", image_count=1)
    assert "我的素材文字" in material

    # 2) 生成
    gen = Generator(StubClient())
    wechat = gen.generate_wechat(material)
    xhs = gen.generate_xhs(material)
    assert wechat.title == "公众号标题"
    assert xhs.hashtags == ["#话题"]

    # 3) 图片 + 导出
    imgs = [Image.new("RGB", (1000, 800), (30, 60, 90))]
    art = exporter.export(wechat, xhs, imgs, ImageConfig(), tmp_path / "out")

    # 4) 断言产出齐全
    assert art.wechat_text_path.read_text(encoding="utf-8").startswith("标题：公众号标题")
    assert "小红书标题" in art.xhs_text_path.read_text(encoding="utf-8")
    assert art.wechat_images[0].exists()
    from PIL import Image as PILImage
    assert PILImage.open(art.xhs_images[0]).size == image_pipeline.XHS_COVER_SIZE
    assert PILImage.open(art.wechat_images[0]).size == image_pipeline.WECHAT_COVER_SIZE


def test_one_platform_failure_does_not_block_other():
    class HalfFailingClient:
        def __init__(self): self.n = 0
        def complete_json(self, system, user):
            self.n += 1
            if "公众号" in system:
                return "### 不是 json ###"   # 两次都坏 -> 降级
            return '{"title":"小红书OK","body":"b","hashtags":[],"cover_text":""}'
    gen = Generator(HalfFailingClient())
    wechat = gen.generate_wechat("素材")
    xhs = gen.generate_xhs("素材")
    assert wechat.fell_back is True          # 公众号降级
    assert xhs.fell_back is False and xhs.title == "小红书OK"   # 小红书正常
```

- [ ] **Step 2: 运行验证通过**

Run: `.\.venv-paddle\Scripts\python.exe -m pytest tests/test_end_to_end.py -q`
Expected: `2 passed`

- [ ] **Step 3: 跑全量测试**

Run: `.\.venv-paddle\Scripts\python.exe -m pytest -q`
Expected: 所有 core + 集成测试通过（GUI 无测试）。

- [ ] **Step 4: 提交**

```bash
git add tests/test_end_to_end.py
git commit -m "test: end-to-end integration with stubbed LLM"
```

---

## 验收清单（对应 spec 第 11 节）

1. ✅ 选择 1~9 张图片 + 粘贴文字（Task 9 GUI）
2. ✅ 一键生成并行产出公众号长文 + 小红书笔记（Task 5 + 9）
3. ✅ 图片按平台规格处理：小红书 3:4 带大字标题+水印；公众号 2.35:1 封面+压缩正文图（Task 6）
4. ✅ GUI 预览 / 一键复制 / 导出图片到目录（Task 7 + 9）
5. ✅ 设置里切换 LLM provider 并生效（Task 2 + 9）
6. ✅ 单平台失败时另一平台仍可用、可重试（Task 5 + 10）
7. ✅ `core/` 单元测试通过（Task 2~8、10）
