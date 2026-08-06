"""
ROCm-optimized local LLM inference engine.

Designed for maximum performance and reliability on AMD Radeon GPUs
using the PyTorch ROCm backend (exposed as torch.cuda).
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Any

try:
    import torch
    _HAS_TORCH = True
except ImportError:
    _HAS_TORCH = False

from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    logging as hf_logging,
)

# Reduce HF noise
hf_logging.set_verbosity_error()
logger = logging.getLogger(__name__)


class LLMEngine:
    """
    High-performance local inference engine optimized for ROCm.

    Key ROCm features:
    - Automatic AMD GPU detection via torch.cuda
    - 4-bit / 8-bit quantization (bitsandbytes)
    - SDPA attention for better throughput
    - Real-time VRAM statistics
    - Graceful CPU fallback
    """

    def __init__(
        self,
        model_name: str = "microsoft/Phi-3-mini-4k-instruct",
        quantize: str = "4bit",
        device: str = "auto",
        max_new_tokens: int = 1024,
        temperature: float = 0.3,
        top_p: float = 0.9,
    ):
        if not _HAS_TORCH:
            from .mock_llm import MockLLMEngine
            self.__class__ = MockLLMEngine
            MockLLMEngine.__init__(self, model_name, quantize, device, max_new_tokens, temperature, top_p)
            return

        self.model_name = model_name
        self.quantize = quantize
        self.max_new_tokens = max_new_tokens
        self.temperature = temperature
        self.top_p = top_p

        self.device = self._resolve_device(device)
        self.tokenizer = self._load_tokenizer()
        self.model = self._load_model()

        logger.info(
            f"LLMEngine ready | model={model_name} | device={self.device} | quantize={quantize}"
        )

    def _resolve_device(self, requested: str) -> str:
        if requested == "cpu":
            return "cpu"
        if requested in ("auto", "cuda"):
            if torch.cuda.is_available():
                name = torch.cuda.get_device_name(0)
                logger.info(f"ROCm/CUDA device detected → {name}")
                return "cuda"
            logger.warning("No GPU detected. Falling back to CPU (slow).")
            return "cpu"
        return requested

    def _load_tokenizer(self):
        tokenizer = AutoTokenizer.from_pretrained(
            self.model_name,
            trust_remote_code=True,
            use_fast=True,
        )
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token
        return tokenizer

    def _load_model(self):
        quant_config = None
        torch_dtype = torch.float16 if self.device == "cuda" else torch.float32

        if self.quantize == "4bit" and self.device == "cuda":
            quant_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_compute_dtype=torch.float16,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_use_double_quant=True,
            )
        elif self.quantize == "8bit" and self.device == "cuda":
            quant_config = BitsAndBytesConfig(load_in_8bit=True)

        model = AutoModelForCausalLM.from_pretrained(
            self.model_name,
            quantization_config=quant_config,
            device_map="auto" if self.device == "cuda" else None,
            torch_dtype=torch_dtype,
            trust_remote_code=True,
            attn_implementation="sdpa",  # good throughput on modern GPUs
            low_cpu_mem_usage=True,
        )
        model.eval()
        return model

    def generate(
        self,
        messages: List[Dict[str, str]],
        max_new_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
    ) -> str:
        """
        Generate a response from a list of chat messages.
        Uses the model's chat template when available.
        """
        max_new_tokens = max_new_tokens or self.max_new_tokens
        temperature = temperature if temperature is not None else self.temperature
        top_p = top_p if top_p is not None else self.top_p

        try:
            prompt = self.tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
            )
        except Exception:
            # Fallback for models without chat template
            prompt = ""
            for m in messages:
                role = m["role"].capitalize()
                prompt += f"{role}: {m['content']}\n"
            prompt += "Assistant:"

        inputs = self.tokenizer(
            prompt,
            return_tensors="pt",
            truncation=True,
            max_length=self.tokenizer.model_max_length - max_new_tokens,
        )
        inputs = {k: v.to(self.model.device) for k, v in inputs.items()}

        generate_kwargs = {
            "max_new_tokens": max_new_tokens,
            "do_sample": temperature > 0.0,
            "temperature": max(temperature, 1e-5),
            "top_p": top_p,
            "pad_token_id": self.tokenizer.eos_token_id,
            "eos_token_id": self.tokenizer.eos_token_id,
        }

        with torch.inference_mode():
            outputs = self.model.generate(**inputs, **generate_kwargs)

        generated = outputs[0][inputs["input_ids"].shape[1] :]
        text = self.tokenizer.decode(generated, skip_special_tokens=True)
        return text.strip()

    def get_stats(self) -> Dict[str, Any]:
        """Return current device and memory statistics (useful for demos)."""
        stats: Dict[str, Any] = {
            "model": self.model_name,
            "quantize": self.quantize,
            "device": self.device,
        }
        if self.device == "cuda" and torch.cuda.is_available():
            stats.update(
                {
                    "gpu_name": torch.cuda.get_device_name(0),
                    "vram_allocated_gb": round(torch.cuda.memory_allocated() / 1e9, 2),
                    "vram_reserved_gb": round(torch.cuda.memory_reserved() / 1e9, 2),
                    "cuda_version": torch.version.cuda or "ROCm",
                }
            )
        return stats

    def __repr__(self) -> str:
        return f"LLMEngine(model={self.model_name}, device={self.device}, quantize={self.quantize})"
