from __future__ import annotations

from collections.abc import Callable
from typing import Literal

import numpy as np


class Embedder:
    def __init__(
        self,
        model: str = "BAAI/bge-small-en-v1.5",
        backend: Literal["auto", "gpu", "cpu"] = "auto",
        batch_size: int = 16,
        fallback_on_oom: bool = True,
        on_embed_failed: Callable[[str], None] | None = None,
    ) -> None:
        self.model_name = model
        self.requested_backend = backend
        self.batch_size = batch_size
        self.effective_batch_size = batch_size
        self.fallback_on_oom = fallback_on_oom
        self.on_embed_failed = on_embed_failed
        self.fallback_to_cpu = False
        self._device = "cpu"
        self._tokenizer = None
        self._model = None
        self._load()

    def _load(self) -> None:
        import torch
        self._torch = torch
        desired = self.requested_backend
        if desired == "auto":
            desired = "gpu" if torch.cuda.is_available() else "cpu"
        if desired == "gpu":
            if not self._check_gpu():
                desired = "cpu"
                self.fallback_to_cpu = True
        self._device = "cuda" if desired == "gpu" else "cpu"
        from transformers import AutoModel, AutoTokenizer
        self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
        self._model = AutoModel.from_pretrained(self.model_name).to(self._device).eval()

    def _check_gpu(self) -> bool:
        try:
            return bool(self._torch.cuda.is_available()) and self._torch.cuda.device_count() > 0
        except Exception:
            return False

    def _prefix(self, text: str) -> str:
        return f"finding: {text}" if not text.startswith(("finding:", "query:", "passage:")) else text

    def embed(self, texts: list[str]) -> np.ndarray:
        torch = self._torch
        prefix = [self._prefix(t) for t in texts]
        if self.fallback_to_cpu and self._device == "cuda":
            self._device = "cpu"
            self._model = self._model.to(self._device)
        out_all: list[np.ndarray] = []
        i = 0
        while i < len(prefix):
            batch = prefix[i : i + self.effective_batch_size]
            try:
                enc = self._tokenizer(batch, padding=True, truncation=True, max_length=512, return_tensors="pt").to(self._device)
                with torch.inference_mode():
                    hidden = self._model(**enc).last_hidden_state
                mask = enc["attention_mask"].unsqueeze(-1).to(hidden.dtype)
                pooled = (hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1)
                pooled = torch.nn.functional.normalize(pooled, dim=-1)
                out_all.append(pooled.cpu().numpy().astype(np.float16))
                i += self.effective_batch_size
            except RuntimeError as e:
                msg = str(e)
                if "out of memory" in msg.lower() and self.fallback_on_oom and self.effective_batch_size > 1:
                    self.effective_batch_size = max(1, self.effective_batch_size // 2)
                    if self.on_embed_failed:
                        self.on_embed_failed(f"oom:halve_to={self.effective_batch_size}")
                    continue
                if self.on_embed_failed:
                    self.on_embed_failed(f"runtime:{msg[:80]}")
                raise
        return np.concatenate(out_all, axis=0) if out_all else np.zeros((0, 384), dtype=np.float16)

    def embed_one(self, text: str) -> np.ndarray:
        return self.embed([text])[0]
