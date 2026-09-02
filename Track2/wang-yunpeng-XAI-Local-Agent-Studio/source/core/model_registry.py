"""XAI 模型注册表（多模型管理：增加/删除/切换）"""
from __future__ import annotations

import json
import os
import time
import uuid
import threading
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional, List


REGISTRY_PATH = os.path.join(os.environ.get("XAI_HOME", os.path.expanduser("~/.xai")), "models.json")


@dataclass
class ModelEntry:
    id: str
    name: str           # 用户命名（显示用）
    provider: str       # deepseek/openai/anthropic/ollama/custom
    model: str          # 模型标识符（API 调用用）
    base_url: str
    api_key: str
    created_at: float = field(default_factory=time.time)
    is_active: bool = False
    vision: bool = False  # 视觉/多模态能力（图片输入）。显式标记或按模型名启发式推断

    _VISION_HINTS = ("vision", "vl-", "-vl", "qwen-vl", "qwen2-vl", "qwen2.5-vl",
                     "gpt-4o", "gpt-4-v", "gpt-4.1", "grok-4", "multimodal",
                     "pixtral", "llava", "internvl", "minicpm-v", "cogvlm", "glm-4v")

    def is_vision(self) -> bool:
        """是否支持图片视觉输入。显式标记优先，否则按模型名启发式推断。"""
        if self.vision:
            return True
        low = (self.name + " " + self.model).lower()
        return any(k in low for k in self._VISION_HINTS)

    def mask_key(self) -> str:
        if not self.api_key:
            return ""
        if len(self.api_key) <= 8:
            return "***"
        return self.api_key[:4] + "***" + self.api_key[-4:]

    def to_dict(self, mask=True) -> dict:
        d = asdict(self)
        if mask:
            d["api_key"] = self.mask_key()
        return d


class ModelRegistry:
    """多模型管理 · 持久化到 ~/.xai/models.json。"""

    def __init__(self, path: Optional[str] = None):
        self.path = path or REGISTRY_PATH
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._lock = threading.RLock()  # 可重入：stats() 持锁内调用 active() 不会自死锁
        self._models: List[ModelEntry] = []
        self._load()

    def _load(self) -> None:
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._models = [ModelEntry(**m) for m in data.get("models", [])]
            except Exception:
                self._models = []
        self._ensure_seed()

    def _save(self) -> None:
        with self._lock:
            data = {"models": [asdict(m) for m in self._models]}
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

    def _ensure_seed(self) -> None:
        """从环境变量/现有 key 引导出第一个模型。"""
        if self._models:
            if not any(m.is_active for m in self._models):
                self._models[0].is_active = True
                self._save()
            return
        # 引导：检查环境变量，注册云端+本地模型
        env_key = os.environ.get("DEEPSEEK_API_KEY")
        if env_key:
            # DeepSeek V4 Flash（默认激活，速度优先）
            flash_entry = ModelEntry(
                id=f"mdl:{uuid.uuid4().hex[:8]}",
                name="DeepSeek V4 Flash",
                provider="deepseek",
                model="deepseek-v4-flash",
                base_url="https://api.deepseek.com/v1/chat/completions",
                api_key=env_key,
                is_active=True,
            )
            self._models.append(flash_entry)
            # DeepSeek V4 Pro（大参数高精度）
            pro_entry = ModelEntry(
                id=f"mdl:{uuid.uuid4().hex[:8]}",
                name="DeepSeek V4 Pro",
                provider="deepseek",
                model="deepseek-v4-pro",
                base_url="https://api.deepseek.com/v1/chat/completions",
                api_key=env_key,
                is_active=False,
            )
            self._models.append(pro_entry)
            self._save()

    def list(self) -> List[ModelEntry]:
        with self._lock:
            return list(self._models)

    def active(self) -> Optional[ModelEntry]:
        with self._lock:
            for m in self._models:
                if m.is_active:
                    return m
        return None

    def detect_local_models(self) -> int:
        """v2.1: 自动检测本地模型（llama.cpp server / Ollama）并注册。

        返回新增模型数。
        """
        added = 0
        # 检测 llama.cpp server (OpenAI-compatible /v1/models API)
        try:
            import urllib.request
            req = urllib.request.Request("http://127.0.0.1:11434/v1/models")
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read())
                local_models = data.get("data", [])
                for lm in local_models:
                    name = lm.get("id", "")
                    if name and not any(
                        m.provider == "llamacpp" and m.model == name
                        for m in self._models
                    ):
                        entry = ModelEntry(
                            id=f"mdl:{uuid.uuid4().hex[:8]}",
                            name=f"本地·{name}",
                            provider="llamacpp",
                            model=name,
                            base_url="http://127.0.0.1:11434/v1",
                            api_key="llamacpp",
                            is_active=False,
                        )
                        self._models.append(entry)
                        added += 1
        except Exception:
            # 尝试 Ollama（旧兼容）
            try:
                import urllib.request
                req = urllib.request.Request("http://localhost:11434/api/tags")
                with urllib.request.urlopen(req, timeout=3) as resp:
                    data = json.loads(resp.read())
                    ollama_models = data.get("models", [])
                    for om in ollama_models:
                        name = om.get("name", "")
                        if name and not any(
                            m.provider == "ollama" and m.model == name
                            for m in self._models
                        ):
                            entry = ModelEntry(
                                id=f"mdl:{uuid.uuid4().hex[:8]}",
                                name=f"Ollama {name}",
                                provider="ollama",
                                model=name,
                                base_url="http://localhost:11434",
                                api_key="",
                                is_active=False,
                            )
                            self._models.append(entry)
                            added += 1
            except Exception:
                pass  # 无本地模型

        # 检测 Grok Build (作为代码引擎，非对话模型)
        try:
            import shutil
            grok_bin = shutil.which("grok") or os.path.expanduser(
                "~/.grok/bin/grok")
            if grok_bin and os.path.isfile(grok_bin) and not any(
                m.provider == "grok" for m in self._models
            ):
                entry = ModelEntry(
                    id=f"mdl:{uuid.uuid4().hex[:8]}",
                    name="Grok Build (代码引擎)",
                    provider="grok",
                    model="grok-build",
                    base_url="local://grok-build-bridge",
                    api_key="",
                    is_active=False,
                )
                self._models.append(entry)
                added += 1
        except Exception:
            pass

        if added:
            self._save()
        return added

    def add(self, name: str, provider: str, model: str, base_url: str, api_key: str) -> ModelEntry:
        with self._lock:
            entry = ModelEntry(
                id=f"mdl:{uuid.uuid4().hex[:8]}",
                name=name.strip() or model,
                provider=provider.strip().lower(),
                model=model.strip(),
                base_url=base_url.strip(),
                api_key=api_key.strip(),
            )
            self._models.append(entry)
            self._save()
            return entry

    def delete(self, model_id: str) -> bool:
        with self._lock:
            before = len(self._models)
            self._models = [m for m in self._models if m.id != model_id]
            if len(self._models) == before:
                return False
            # 保持至少一个激活
            if not any(m.is_active for m in self._models) and self._models:
                self._models[0].is_active = True
            self._save()
            return True

    def activate(self, model_id: str) -> Optional[ModelEntry]:
        with self._lock:
            target = None
            for m in self._models:
                if m.id == model_id:
                    target = m
                    m.is_active = True
                else:
                    m.is_active = False
            self._save()
            return target

    def stats(self) -> dict:
        with self._lock:
            return {
                "total": len(self._models),
                "active": self.active().to_dict(mask=True) if self.active() else None,
            }


_singleton: Optional[ModelRegistry] = None
_singleton_lock = threading.Lock()


def default_registry() -> ModelRegistry:
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = ModelRegistry()
    return _singleton
