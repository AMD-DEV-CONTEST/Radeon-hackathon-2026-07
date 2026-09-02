"""
scripts/determinex_inference.py — Llama API Wrapper & Logit Bridge
===============================================================

Handles the low-level interactions with llama-cpp-python, replacing Olama
for receiving models.

Responsibilities:
  - Local model execution via GGUF and llama_cpp
  - Soft-prefix embedding injection (K=1 normal, K=3 ambiguous)
  - Logit capture before sampling (logit bridge source side)
  - Calibrated confidence score extraction
"""

import ctypes
import json
import logging
import os
import unicodedata
from pathlib import Path
from typing import Union

# ── #6 CUDA Allocator Fragmentation Guard ─────────────────────────────────────
os.environ.setdefault(
    "PYTORCH_CUDA_ALLOC_CONF",
    "expandable_segments:True,garbage_collection_threshold:0.6",
)

try:
    from llama_cpp import Llama, llama_batch_free, llama_batch_init, llama_decode
except ImportError:
    Llama = None

import numpy as np
import torch
from determinex_rosetta import RosettaStone

log = logging.getLogger("inference")


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def _clear_cuda_cache() -> None:
    if torch.cuda.is_available():
        torch.cuda.synchronize()
        torch.cuda.empty_cache()
        torch.cuda.ipc_collect()


class DeterminexInference:
    def __init__(
        self,
        gguf_path: Union[str, Path],
        arch_name: str,
        n_ctx: int = 4096,
        n_gpu_layers: int = -1,
        entropy_cal_path: Path | None = None,
    ):
        if Llama is None:
            raise ImportError("llama-cpp-python is required for DeterminexInference.")

        self.gguf_path = str(gguf_path)
        self.arch_name = arch_name
        self.entropy_table = self._load_entropy_table(entropy_cal_path)

        _clear_cuda_cache()

        log.info(f"Loading {self.arch_name} from {self.gguf_path}")
        self.model = Llama(
            model_path=self.gguf_path,
            n_ctx=n_ctx,
            n_gpu_layers=n_gpu_layers,
            vocab_only=False,
            embedding=True,  # llama-cpp-python 0.3.x: enables model.embed()
            logits_all=True,
        )
        self.hidden_dim = self.model.n_embd()

    def __del__(self) -> None:
        try:
            if hasattr(self, "model") and self.model is not None:
                del self.model
                self.model = None
            _clear_cuda_cache()
        except Exception:
            pass

    def _load_entropy_table(self, path: Path | None) -> dict[str, float]:
        if path and path.exists():
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        return {}

    def extract_logits(self, tokens: list[int]) -> np.ndarray:
        self.model.eval(tokens)
        vocab_size = self.model.n_vocab()
        logits_ptr = self.model._ctx.logits
        if not logits_ptr:
            raise ValueError("Model was not configured to yield logits.")
        n_tokens = len(tokens)
        last_token_idx = n_tokens - 1
        logits_array = np.ctypeslib.as_array(
            logits_ptr[last_token_idx * vocab_size : (last_token_idx + 1) * vocab_size]
        )
        return logits_array.copy()

    def compute_confidence(self, logits: np.ndarray) -> float:
        logits_tensor = torch.tensor(logits, dtype=torch.float32)
        probs = torch.nn.functional.softmax(logits_tensor, dim=-1)
        entropy = -torch.sum(probs * torch.log(probs + 1e-10)).item()
        if self.arch_name in self.entropy_table:
            cal = self.entropy_table[self.arch_name]
            base_ent = cal.get("base_entropy", 2.0)
            scale = cal.get("scale", 1.0)
            return min(100.0, max(0.0, 100.0 - (scale * abs(entropy - base_ent))))
        return max(0.0, min(100.0, 100.0 - (entropy * 10.0)))

    def inject_soft_prompt(
        self, text_tokens: list[int], soft_embeddings: torch.Tensor
    ) -> list[int]:
        """
        Hybrid two-pass injection:

          Pass 1 (low-level):  llama_batch_init(K, hidden_dim, 1) → fill embd[] →
                               llama_decode   positions 0..K-1 written to KV cache.

          Pass 2 (high-level): set model.n_tokens = K so eval() uses K as n_past,
                               then model.eval(text_tokens) → positions K..K+n-1.
                               eval() calls kv_cache_seq_rm(-1, K, -1) first,
                               which removes nothing (KV is only populated 0..K-1).

          Generation:          model.sample() + model.eval([tok]) per new token.
                               model.n_tokens tracks position automatically.

        Each call resets KV state so retries (with compiler error in text_prompt)
        produce a clean context with only the fresh soft prefix + updated text.
        """
        K, dim = soft_embeddings.shape
        if dim != self.hidden_dim:
            raise ValueError(f"Dim mismatch: expected {self.hidden_dim}, got {dim}")
        if K not in (1, 3):
            log.warning("Expected K=1 or K=3 soft tokens, got K=%d", K)

        # Clear KV cache and reset counter so each call starts from position 0.
        self.model._ctx.kv_cache_clear()
        self.model.n_tokens = 0

        ctx = self.model._ctx.ctx
        np_embd = soft_embeddings.detach().cpu().numpy().astype(np.float32).flatten()

        # ── Pass 1: soft embedding prefix at positions 0..K-1 ────────────────
        batch_embd = llama_batch_init(K, self.hidden_dim, 1)
        try:
            for i in range(K):
                off = i * dim
                for j in range(dim):
                    batch_embd.embd[off + j] = ctypes.c_float(np_embd[off + j])
                batch_embd.pos[i] = i
                batch_embd.n_seq_id[i] = 1
                batch_embd.seq_id[i][0] = 0
                batch_embd.logits[i] = 0
            batch_embd.n_tokens = K
            ret = llama_decode(ctx, batch_embd)
            if ret != 0:
                raise RuntimeError(f"llama_decode (embd pass) failed: {ret}")
        finally:
            llama_batch_free(batch_embd)

        # Tell the high-level wrapper K slots are occupied so eval() starts at K.
        self.model.n_tokens = K

        # ── Pass 2: text tokens at positions K..K+n-1 (via high-level eval) ──
        self.model.eval(text_tokens)  # n_tokens becomes K + len(text_tokens)

        # ── Autoregressive generation ─────────────────────────────────────────
        eos: set = {self.model.token_eos()}
        for stop_str in ("<|im_end|>", "<|endoftext|>"):
            try:
                ids = self.model.tokenize(stop_str.encode(), special=True)
                if len(ids) == 1:
                    eos.add(ids[0])
            except Exception:
                pass

        output_tokens: list[int] = []
        for _ in range(512):
            sampled_tok = self.model.sample()
            if sampled_tok in eos:
                break
            output_tokens.append(sampled_tok)
            self.model.eval([sampled_tok])

        return output_tokens

    def process_rosetta_injection(
        self, source_h: torch.Tensor, source_arch: str, stone: RosettaStone, text_prompt: str
    ) -> str:
        """
        Projects thought vector → target space → injects as K=1 soft prefix.
        """
        text_tokens = self.model.tokenize(_nfc(text_prompt).encode("utf-8"), special=True)

        # Ensure 2D [K, dim] for inject_soft_prompt. Callers may pass [dim] (1D).
        if source_h.dim() == 1:
            source_h = source_h.unsqueeze(0)  # [dim] → [1, dim]

        target_h = stone.project(source_h, source_arch, self.arch_name)
        out_tokens = self.inject_soft_prompt(text_tokens, target_h)
        return _nfc(self.model.detokenize(out_tokens).decode("utf-8", errors="ignore"))
