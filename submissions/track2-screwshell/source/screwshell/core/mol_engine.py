"""MoL (Mixture-of-LoRA) inference core for ScrewShell.

A frozen Qwen3.5-9B base stays resident in Radeon VRAM; multiple LoRA
experts (community-sourced, hot-swappable) are activated per investigation
skill by the Router. Switching an expert never reloads the base model —
this is the core Radeon inference-speed optimization.

Runs on: /opt/venv (torch 2.10 + ROCm 7.2.4, transformers 5.5, peft 0.19).
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import torch

log = logging.getLogger("screwshell.mol")

# SwitchRecord / GenStats live in mol_types (torch-free) so the llama.cpp
# backend can reuse the exact same data contract without importing torch.
from screwshell.core.mol_types import SwitchRecord, GenStats, CAP_KEYS


class MoLEngine:
    """Frozen base + hot-swappable LoRA experts on one GPU."""

    def __init__(self, base_path: str, dtype=torch.bfloat16, device: str = "cuda:0"):
        self.base_path = base_path
        self.device = device
        self.dtype = dtype
        self.model = None          # PeftModel once adapters are attached
        self.tokenizer = None
        self.adapters: dict[str, dict] = {}   # name -> {"path":..., "target_modules":...}
        self.active_adapter: Optional[str] = None
        self.switch_log: list[SwitchRecord] = []
        self.gen_log: list[GenStats] = []
        self._lock = threading.Lock()
        self._warned: set[str] = set()

    # ---------- degradation reporting ----------

    def _warn_once(self, key: str, msg: str, *args) -> None:
        """Log an ignored-feature warning exactly once per engine instance.

        The peft backend accepts the llama.cpp-only `chat()` parameters purely
        for signature parity. Ignoring them silently would let a caller believe
        constrained decoding is on when it is not; warning on every one of the
        ~10 calls in a run just trains people to ignore the log.
        """
        if key in self._warned:
            return
        self._warned.add(key)
        log.warning(msg, *args)

    # ---------- lifecycle ----------

    def load_base(self):
        from transformers import AutoModelForCausalLM, AutoTokenizer

        t0 = time.time()
        self.tokenizer = AutoTokenizer.from_pretrained(self.base_path)
        self.model = AutoModelForCausalLM.from_pretrained(
            self.base_path, dtype=self.dtype, device_map=self.device
        )
        self.model.eval()
        log.info("base loaded in %.1fs, vram=%.1fGB", time.time() - t0, self.vram_gb())
        return self

    def load_adapter(self, name: str, path: str):
        """Attach a LoRA expert. First adapter wraps base into a PeftModel."""
        from peft import PeftModel

        cfg_path = self._find_adapter_config(path)
        with open(cfg_path) as f:
            cfg = json.load(f)
        adapter_dir = os.path.dirname(cfg_path)
        t0 = time.time()
        with self._lock:
            if not hasattr(self.model, "load_adapter"):  # plain HF model
                self.model = PeftModel.from_pretrained(
                    self.model, adapter_dir, adapter_name=name, is_trainable=False
                )
            else:
                self.model.load_adapter(adapter_dir, adapter_name=name)
        self.adapters[name] = {
            "path": adapter_dir,
            "target_modules": sorted(cfg.get("target_modules") or []),
            "r": cfg.get("r"),
            "load_s": round(time.time() - t0, 2),
        }
        log.info("adapter %s loaded in %.1fs (r=%s)", name,
                 self.adapters[name]["load_s"], cfg.get("r"))
        return self.adapters[name]

    @staticmethod
    def _find_adapter_config(path: str) -> str:
        direct = os.path.join(path, "adapter_config.json")
        if os.path.isfile(direct):
            return direct
        for root, _dirs, files in os.walk(path):
            if "adapter_config.json" in files:
                return os.path.join(root, "adapter_config.json")
        raise FileNotFoundError(f"no adapter_config.json under {path}")

    # ---------- hot swap ----------

    def activate(self, name: Optional[str]) -> SwitchRecord:
        """Hot-swap to adapter `name` (None = pure base). ms-level via set_adapter."""
        with self._lock:
            prev = self.active_adapter
            if name == prev:
                rec = SwitchRecord(time.time(), prev, name, 0.0, "noop")
                self.switch_log.append(rec)
                return rec
            torch.cuda.synchronize()
            t0 = time.time()
            if name is None:
                if hasattr(self.model, "disable_adapter_layers"):
                    self.model.disable_adapter_layers()
                mode = "disable"
            else:
                if name not in self.adapters:
                    raise KeyError(f"adapter {name} not loaded")
                if prev is None and hasattr(self.model, "enable_adapter_layers"):
                    self.model.enable_adapter_layers()
                self.model.set_adapter(name)
                mode = "set_adapter"
            torch.cuda.synchronize()
            latency = (time.time() - t0) * 1000
            self.active_adapter = name
            rec = SwitchRecord(time.time(), prev, name, round(latency, 2), mode)
            self.switch_log.append(rec)
            log.info("switch %s -> %s in %.1fms (%s)", prev, name, latency, mode)
            return rec

    # ---------- generation ----------

    def capabilities(self) -> dict:
        """Server-side feature probe -- always all-False on the peft backend.

        `MoLLlamaCpp.capabilities()` reports what a llama.cpp build supports
        (json_schema / grammar / timings / cache_prompt / stream). None of
        those exist here: peft generates in-process with `model.generate()`.
        Returning the same dict SHAPE with everything off means every caller
        can branch on capabilities unconditionally, and the peft path
        automatically takes the unconstrained fallback.
        """
        caps = {k: False for k in CAP_KEYS}
        caps.update({"build": "peft", "probed": True, "reachable": True})
        return caps

    @torch.no_grad()
    def chat(self, messages: list[dict], max_new_tokens: int = 512,
             temperature: float = 0.0,
             enable_thinking: bool = False,
             response_format: Optional[dict] = None,
             json_schema: Optional[dict] = None,
             grammar: Optional[str] = None,
             cache_prompt: bool = True,
              stream: bool = False,
              on_token: Optional[Callable[[str], None]] = None,
              run_id: Optional[str] = None,
              ) -> tuple[str, GenStats]:
        """One chat completion.

        Signature parity with `MoLLlamaCpp.chat` is a hard contract
        (`tests/test_mol_llamacpp.py::test_interface_parity_with_peft`): the
        Orchestrator is backend-agnostic and must be able to pass the same
        keyword arguments to either engine. The llama.cpp-only parameters are
        accepted and ignored here, each with a one-shot warning, so a caller
        never believes a constraint was applied when it was not.
        """
        # enable_thinking=False keeps agentic JSON replies fast and clean
        # (Qwen3.5 thinking mode otherwise emits a long reasoning preamble).
        if response_format is not None or json_schema is not None:
            self._warn_once("json_schema",
                            "peft backend has no constrained decoding; "
                            "response_format/json_schema ignored")
        if grammar is not None:
            self._warn_once("grammar",
                            "peft backend has no GBNF support; grammar ignored")
        if stream or on_token is not None:
            self._warn_once("stream",
                            "peft backend generates without streaming; "
                            "stream/on_token ignored (no ttft_ms measured)")
        # cache_prompt is a llama.cpp server flag; transformers manages its own
        # KV cache per call and shares nothing between calls, so there is
        # nothing to honour and nothing to warn about.
        del cache_prompt
        try:
            enc = self.tokenizer.apply_chat_template(
                messages, add_generation_prompt=True, return_tensors="pt",
                return_dict=True, enable_thinking=enable_thinking)
        except TypeError:  # tokenizer without thinking-mode support
            enc = self.tokenizer.apply_chat_template(
                messages, add_generation_prompt=True, return_tensors="pt",
                return_dict=True)
        ids = enc["input_ids"].to(self.model.device)
        torch.cuda.synchronize()
        t0 = time.time()
        kwargs = dict(max_new_tokens=max_new_tokens,
                      pad_token_id=self.tokenizer.eos_token_id)
        if temperature and temperature > 0:
            kwargs.update(do_sample=True, temperature=temperature)
        else:
            kwargs.update(do_sample=False)
        try:
            out = self.model.generate(ids, **kwargs)
        except Exception as e:
            torch.cuda.synchronize()
            log.error("generate failed: %s", e)
            stats = GenStats(self.active_adapter, int(ids.shape[1]), 0,
                             round(time.time() - t0, 3),
                             ok=False, error=f"{type(e).__name__}: {e}")
            self.gen_log.append(stats)
            return "", stats
        torch.cuda.synchronize()
        dt = time.time() - t0
        new = out.shape[1] - ids.shape[1]
        text = self.tokenizer.decode(out[0, ids.shape[1]:], skip_special_tokens=True)
        stats = GenStats(self.active_adapter, int(ids.shape[1]), int(new),
                         round(dt, 3),
                         # transformers reports no prefill/decode split, so
                         # prefill_ms/decode_ms stay None rather than being
                         # invented from wall clock. decode_tps below is a real
                         # end-to-end rate, just a coarser one.
                         decode_tps=round(new / dt, 2) if dt > 0 and new else None,
                         finish_reason=("length" if new >= max_new_tokens
                                        else "stop"),
                         ok=True)
        self.gen_log.append(stats)
        return text, stats

    # ---------- introspection ----------

    @staticmethod
    def vram_gb() -> float:
        free, total = torch.cuda.mem_get_info()
        return round((total - free) / 1e9, 2)

    @staticmethod
    def vram_total_gb() -> float:
        _free, total = torch.cuda.mem_get_info()
        return round(total / 1e9, 2)

    def vram_pct(self) -> float:
        """VRAM usage as a real 0-100 percentage (for the governor's KV-quant)."""
        total = self.vram_total_gb()
        return round(self.vram_gb() / total * 100.0, 2) if total else 0.0

    def status(self) -> dict:
        return {
            "base": self.base_path,
            "active_adapter": self.active_adapter,
            "adapters": {n: {"r": a["r"], "load_s": a["load_s"]}
                         for n, a in self.adapters.items()},
            "vram_gb": self.vram_gb(),
            "vram_pct": self.vram_pct(),
            "switches": len(self.switch_log),
            "last_switch_ms": self.switch_log[-1].latency_ms if self.switch_log else None,
            "backend": "peft",
            "caps": self.capabilities(),
        }
