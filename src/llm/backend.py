"""LLM backends: OpenAI-compatible API and optional local Transformers (ROCm/CUDA)."""

from __future__ import annotations

import os
from typing import Any

from src.config import LLMConfig


class LLMBackend:
    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        raise NotImplementedError


class OpenAICompatibleBackend(LLMBackend):
    def __init__(self, cfg: LLMConfig) -> None:
        from openai import OpenAI

        self.cfg = cfg
        self.client = OpenAI(base_url=cfg.base_url.rstrip("/"), api_key=cfg.api_key)

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        resp = self.client.chat.completions.create(
            model=kwargs.get("model", self.cfg.model),
            messages=messages,
            temperature=kwargs.get("temperature", self.cfg.temperature),
            max_tokens=kwargs.get("max_tokens", self.cfg.max_tokens),
        )
        return (resp.choices[0].message.content or "").strip()


class LocalTransformersBackend(LLMBackend):
    """Local inference path for AMD Radeon GPU via ROCm PyTorch."""

    def __init__(self, cfg: LLMConfig) -> None:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.cfg = cfg
        dtype = torch.float16 if cfg.dtype == "float16" else torch.bfloat16
        mid = cfg.local_model_id
        trust = os.getenv("PLA_TRUST_REMOTE_CODE", "0").lower() in {"1", "true", "yes"}
        # Qwen-family often needs trust_remote_code; allow known prefixes by default.
        if any(mid.lower().startswith(p) for p in ("qwen/", "qwen2", "qwen2.5")):
            trust = True
        print(f"[llm] loading tokenizer: {mid} (trust_remote_code={trust})", flush=True)
        self.tokenizer = self._from_pretrained(AutoTokenizer, mid, trust_remote_code=trust)

        load_kwargs: dict[str, Any] = {
            "torch_dtype": dtype,
            "trust_remote_code": trust,
            "low_cpu_mem_usage": True,
        }
        if torch.cuda.is_available():
            load_kwargs["device_map"] = "auto"
            print("[llm] cuda available, loading weights to GPU...", flush=True)
        else:
            print("[llm] cuda not available, loading on CPU (slower)...", flush=True)

        self.model = self._from_pretrained(AutoModelForCausalLM, mid, **load_kwargs)
        self.model.eval()
        self.device = next(self.model.parameters()).device
        print(f"[llm] ready on {self.device}", flush=True)

    @staticmethod
    def _from_pretrained(loader: Any, model_id: str, **kwargs: Any) -> Any:
        """Prefer local HF cache to skip hub round-trips; fall back to download."""
        offline = os.getenv("HF_HUB_OFFLINE", "").lower() in {"1", "true", "yes"}
        offline = offline or os.getenv("TRANSFORMERS_OFFLINE", "").lower() in {"1", "true", "yes"}
        if offline:
            return loader.from_pretrained(model_id, local_files_only=True, **kwargs)
        try:
            return loader.from_pretrained(model_id, local_files_only=True, **kwargs)
        except Exception:
            print(f"[llm] cache miss for {model_id}, downloading...", flush=True)
            return loader.from_pretrained(model_id, **kwargs)

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        import torch

        prompt = self.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )
        inputs = self.tokenizer(prompt, return_tensors="pt")
        inputs = {k: v.to(self.device) for k, v in inputs.items()}
        max_new = int(kwargs.get("max_tokens", self.cfg.max_tokens))
        with torch.inference_mode():
            output = self.model.generate(
                **inputs,
                max_new_tokens=max_new,
                do_sample=True,
                temperature=max(0.01, float(kwargs.get("temperature", self.cfg.temperature))),
                use_cache=True,
            )
        generated = output[0][inputs["input_ids"].shape[-1] :]
        return self.tokenizer.decode(generated, skip_special_tokens=True).strip()


def build_llm(cfg: LLMConfig) -> LLMBackend:
    if cfg.backend == "local_transformers":
        return LocalTransformersBackend(cfg)
    return OpenAICompatibleBackend(cfg)
