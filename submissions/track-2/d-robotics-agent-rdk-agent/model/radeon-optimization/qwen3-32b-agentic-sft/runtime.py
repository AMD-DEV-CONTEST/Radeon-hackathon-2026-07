#!/usr/bin/env python3
"""Inference runtime for the competition's main 32B agent model on Radeon gfx1100.

Model identity (verified fail-closed by benchmark.py before any run):
- alias:    Qwen3-32B-Agentic-SFT-r1-v3
- base:     unsloth/Qwen3-32B-bnb-4bit @ 7f721e74a6a8cc9ee352f7e49303a2c1705f9083
- adapter:  checkpoint-000119 (adapter_model.safetensors SHA-256
            4dcee6914e3f9c61aeb33529208bf7e63f37c4c5ae5e0e37e7f7c6b3bfff20bf)

Two arms, identical base weights, identical adapter file, identical GPU:

- "baseline"  replicates the production serving path byte-for-byte:
  bnb NF4 4-bit base + PEFT *online* (unmerged) LoRA, SDPA attention,
  fp32 RMSNorm, bf16 autocast, greedy decoding, DynamicCache.  The
  production server buffers the full completion before emitting SSE
  chunks, so the user-visible TTFT of this arm equals its e2e latency.

- "optimized" keeps the same base, the same adapter file and the same
  online (unmerged) LoRA math, with two changes:
    1. true token streaming (TextIteratorStreamer): the first token
       reaches the consumer right after prefill instead of after the
       full completion (user-visible streaming/TTFT optimization).
    2. lean LoRA execution: each PEFT lora Linear4bit forward is replaced
       by  base_layer(x) + (x @ A^T) @ (scaling * B)^T  with the adapter
       weights pre-cast to bf16 and the scaling folded into B.  Canary
       verified token-identical output vs the production fp32 PEFT path
       (runtime optimization, small decode gain).

Candidates that were implemented, measured on this machine, and REJECTED
(details in README.md and results.json boundaries):
- Merging the LoRA into the NF4 base (peft merge_and_unload): the adapter
  delta (||dW|| ~ 0.3 per projection) is far below the NF4 quantization
  step, so requantization destroys it (cosine(applied change, intended
  delta) = 0.006) and the merged model degenerates to near-base behavior.
- torch.compile(mode="reduce-overhead") on the decode step + StaticCache:
  +40% decode on a short canary prompt, but the padded static-cache
  attention cost grows with cache length on this stack (11.7 tok/s at
  ~900 KV slots, 6.5 at 4608, 3.6 at 12288), so at production prompt
  lengths (3-6k tokens) it is SLOWER than the eager baseline, and every
  new cache length also costs a 60-120s recompile.

Both arms measure internal first-token latency with the same streamer so
the comparison is instrument-identical.
"""
from __future__ import annotations

import json
import re
import threading
import time
import uuid
from typing import Any

import torch
import torch.nn.functional as TF
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer, TextIteratorStreamer

TOOL_CALL_PATTERN = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)
THINK_PATTERN = re.compile(r"^\s*<think>.*?</think>\s*", re.DOTALL)
EXPECTED_EOS_TOKEN_IDS = [151645, 151643]
MAX_CONTEXT_TOKENS = 40960


def parse_tool_calls(text: str, allowed_names: set[str]) -> tuple[str, list[dict[str, Any]]]:
    """Identical post-processing to the production server (qwen3_agentic_openai_server.py)."""
    text = THINK_PATTERN.sub("", text, count=1)
    matches = TOOL_CALL_PATTERN.findall(text)
    tool_calls: list[dict[str, Any]] = []
    for raw in matches:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict) or not isinstance(payload.get("name"), str):
            continue
        name = payload["name"]
        if allowed_names and name not in allowed_names:
            continue
        arguments = payload.get("arguments", {})
        if isinstance(arguments, str):
            try:
                parsed = json.loads(arguments)
            except json.JSONDecodeError:
                continue
            if not isinstance(parsed, dict):
                continue
            argument_text = json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))
        elif isinstance(arguments, dict):
            argument_text = json.dumps(arguments, ensure_ascii=False, separators=(",", ":"))
        else:
            continue
        tool_calls.append({
            "id": "call_" + uuid.uuid4().hex[:24],
            "type": "function",
            "function": {"name": name, "arguments": argument_text},
        })
    content = TOOL_CALL_PATTERN.sub("", text).strip()
    return content, tool_calls


def apply_lean_lora(model: Any) -> int:
    """Replace each PEFT lora Linear4bit forward with a minimal-overhead
    equivalent: base_layer(x) + (x @ A^T) @ (scaling*B)^T, adapters in bf16.
    Same math, far less per-token Python/cast overhead."""
    patched = 0
    for module in model.modules():
        if module.__class__.__name__ == "Linear4bit" and hasattr(module, "lora_A"):
            a = module.lora_A["default"].weight.data
            b = module.lora_B["default"].weight.data
            scaling = module.scaling["default"]
            module._lean_a = a.to(torch.bfloat16).contiguous()
            module._lean_b = (b * scaling).to(torch.bfloat16).contiguous()

            def lean_forward(x: torch.Tensor, *args: Any, _m: Any = module, **kwargs: Any) -> torch.Tensor:
                out = _m.base_layer(x, *args, **kwargs)
                return out + TF.linear(TF.linear(x, _m._lean_a), _m._lean_b)

            module.forward = lean_forward
            patched += 1
    return patched


class Runtime:
    def __init__(self, model_path: str, adapter_path: str, arm: str) -> None:
        if arm not in ("baseline", "optimized"):
            raise ValueError(f"unknown arm: {arm}")
        self.arm = arm
        load_started = time.monotonic()
        self.tokenizer = AutoTokenizer.from_pretrained(
            model_path, local_files_only=True, trust_remote_code=False
        )
        base = AutoModelForCausalLM.from_pretrained(
            model_path,
            local_files_only=True,
            trust_remote_code=False,
            use_safetensors=True,
            device_map={"": 0},
            dtype=torch.bfloat16,
            attn_implementation="sdpa",
        )
        for module in base.modules():
            if module.__class__.__name__.endswith("RMSNorm"):
                module.to(torch.float32)
        base.config.use_cache = True
        model = PeftModel.from_pretrained(
            base,
            adapter_path,
            is_trainable=False,
            autocast_adapter_dtype=False,
            low_cpu_mem_usage=False,
            local_files_only=True,
        )
        model.eval()
        model.config.use_cache = True
        model.generation_config.pad_token_id = self.tokenizer.pad_token_id
        eos = model.generation_config.eos_token_id
        eos = list(eos) if isinstance(eos, (list, tuple)) else [int(eos)]
        if eos != EXPECTED_EOS_TOKEN_IDS:
            raise RuntimeError(f"generation eos_token_id drift: {eos}")
        self.eos_token_id = eos
        self.lean_patched = 0
        if arm == "optimized":
            self.lean_patched = apply_lean_lora(model)
        self.model = model
        torch.cuda.synchronize(0)
        self.load_seconds = round(time.monotonic() - load_started, 3)
        self.merge_seconds = None  # kept for schema compatibility; merging is not used
        self.load_vram_bytes = int(torch.cuda.memory_allocated(0))

    def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        max_tokens: int,
        timeout_seconds: float = 900.0,
    ) -> dict[str, Any]:
        """Greedy generation with per-token timing.  Returns text, parsed tool
        calls, finish reason and timing/token metrics for one request."""
        prompt = self.tokenizer.apply_chat_template(
            messages,
            tools=tools or None,
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )
        encoded = self.tokenizer(prompt, return_tensors="pt", add_special_tokens=False)
        prompt_tokens = int(encoded["input_ids"].shape[1])
        if prompt_tokens + max_tokens > MAX_CONTEXT_TOKENS:
            raise ValueError("prompt + max_tokens exceeds context window")
        inputs = {key: value.to("cuda:0") for key, value in encoded.items()}
        streamer = TextIteratorStreamer(
            self.tokenizer, skip_prompt=True, skip_special_tokens=True
        )
        result: dict[str, Any] = {}

        def worker() -> None:
            try:
                with torch.inference_mode(), torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                    output = self.model.generate(
                        **inputs,
                        max_new_tokens=max_tokens,
                        do_sample=False,
                        use_cache=True,
                        pad_token_id=self.tokenizer.pad_token_id,
                        eos_token_id=self.eos_token_id,
                        streamer=streamer,
                    )
                    torch.cuda.synchronize(0)
                result["output"] = output
            except Exception as error:  # surfaced after join
                result["error"] = error

        torch.cuda.reset_peak_memory_stats(0)
        started = time.monotonic()
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        first_token_at: float | None = None
        for piece in streamer:
            if piece and first_token_at is None:
                first_token_at = time.monotonic()
        thread.join(timeout=timeout_seconds)
        if thread.is_alive():
            raise TimeoutError(f"generation exceeded {timeout_seconds}s")
        ended = time.monotonic()
        if "error" in result:
            raise result["error"]
        output = result["output"]
        completion_tokens = int(output.shape[1]) - prompt_tokens
        text = self.tokenizer.decode(output[0, prompt_tokens:], skip_special_tokens=True)
        allowed = {tool["function"]["name"] for tool in (tools or [])}
        content, tool_calls = parse_tool_calls(text, allowed)
        if tool_calls:
            finish_reason = "tool_calls"
        else:
            finish_reason = "length" if completion_tokens >= max_tokens else "stop"
        e2e_seconds = ended - started
        first_token_seconds = (first_token_at - started) if first_token_at else e2e_seconds
        decode_tps = None
        if completion_tokens > 1 and first_token_at is not None and ended > first_token_at:
            decode_tps = (completion_tokens - 1) / (ended - first_token_at)
        return {
            "content": content,
            "tool_calls": tool_calls,
            "finish_reason": finish_reason,
            "raw_text_sha256_input": text,
            "metrics": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "e2e_seconds": round(e2e_seconds, 4),
                "first_token_seconds": round(first_token_seconds, 4),
                # Production baseline emits SSE only after full generation,
                # so its user-visible TTFT is the full e2e latency.  The
                # optimized arm streams for real.
                "user_visible_ttft_seconds": round(
                    e2e_seconds if self.arm == "baseline" else first_token_seconds, 4
                ),
                "decode_tokens_per_second": round(decode_tps, 4) if decode_tps else None,
                "peak_vram_bytes": int(torch.cuda.max_memory_allocated(0)),
            },
        }
