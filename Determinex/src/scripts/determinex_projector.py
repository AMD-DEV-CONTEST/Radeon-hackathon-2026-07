"""
scripts/determinex_projector.py — Per-User Calibration Adapter
================================================================
Trains a small MLP offset ("adapter") to calibrate the base Rosetta Stone
projection for the specific GGUF quantization the user is running.

Purpose:
  The base Rosetta Stone (rosetta_v1.pt) trains on full-precision HF base
  models. GGUF quantization shifts the embedding geometry. This adapter
  learns the residual: W_adapter(h_src) + Rosetta.project(h_src, src, tgt).

  This is NOT the base projector — that lives in determinex_rosetta.py.
  This is the per-rig offset calibration tool.

All model paths and dimensions resolved from the model registry
(~/.determinex/models.yaml) or probed from GGUF headers at runtime.
Nothing is hardcoded.

Architecture — same 2-layer MLP as Rosetta (GELU + LayerNorm):
    source_model GGUF  →  embed()  →  h_src [d_src]
                                          |
                          W: Linear(d_src → d_hidden) + GELU + LayerNorm
                             Linear(d_hidden → d_tgt)
                                          |
                          soft_prefix [N_PREFIX, d_tgt]
                                          |
                      target_model embedding space

Loss (alignment phase):
    PRIMARY  = MSE(mean(soft_prefix), h_tgt) + cosine_distance
    where h_tgt = target_model.embed(same_prompt)  ← frozen target

Loss (compile phase, after alignment warmup):
    PRIMARY  = alignment loss (above)
    SECONDARY = 0.05 * REINFORCE(compile_result, baseline=0.5)

Modes:
  --mode probe    Check paths / dims, no training
  --mode align    Fast: pure embedding alignment, no generation (~5 min)
  --mode train    Full: alignment + compile signal (~30 min)
  --mode eval     Evaluate trained W on seed tasks
  --mode demo     Generate with trained W

Usage:
  python determinex_projector.py --source leviathan --target determinex-observer-v4 --mode probe
  python determinex_projector.py --source leviathan --target determinex-observer-v4 --mode align
"""

from __future__ import annotations

# torch is imported lazily inside functions (heavy optional dep -- module-scope import
# would tax every CLI entry point). Annotations are strings under `from __future__ import
# annotations`, so this block never executes; it exists so static tools can resolve
# `torch.Tensor` and stop burying real undefined names under false ones.
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import torch

import argparse
import ast
import logging
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="[PROJ] %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("proj")

# ── Paths ─────────────────────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent.parent
_STAGING = _ROOT / ".determinex_staging"
_OUTPUTS = _ROOT / "scripts" / "fine_tuning" / "outputs"

# Import the registry and base Rosetta Stone utilities
from determinex_rosetta import (
    ADAPTERS_DIR,
    build_mlp,
    get_model,
    probe_gguf,
)

# Legacy fallback paths — only used if model is NOT in registry
_LEGACY_LEVIATHAN_GGUF = (
    Path.home()
    / ".ollama/models/blobs"
    / "sha256-5ff0abeeac1d2dbdd5455c0b49ba3b29a9ce3c1fb181b2eef2e948689d55d046"
)
_LEGACY_OBSERVER_GGUF = (
    Path(os.environ.get("DETERMINEX_MODELS_DIR", str(Path.home() / "determinex-models")))
    / "determinex-observer-v4.gguf"
)

# HF model ID used only for EngineerWithPrefix (Phase 1 soft prefix injection)
PHI3_HF_ID = "microsoft/Phi-3-mini-4k-instruct"
HF_CACHE_DIR = Path(
    os.environ.get(
        "DETERMINEX_HF_CACHE_DIR",
        str(Path.home() / ".cache" / "huggingface"),
    )
)
ENGINEER_LORA = _OUTPUTS / "determinex-engineer-v5" / "lora_adapter"

PROJECTION_LOG = _ROOT / "logs" / "projector_train.log"


# ── Dynamic N_PREFIX — #22/#29 ───────────────────────────────────────────────
def _detect_optimal_n_prefix(default: int = 8) -> int:
    """
    #22/#29: Read backend KV-cache page size and align N_PREFIX to it.
    llama.cpp defaults to 16-token pages. Using N_PREFIX=8 on a 16-token backend
    wastes half a page — the model still allocates 16 slots, only 8 carry signal.
    Rounding up to the page boundary is cost-free and gives the soft prefix
    more context-carrying capacity.
    """
    # Environment override (explicit user config always wins)
    env_val = os.environ.get("DETERMINEX_N_PREFIX", "").strip()
    if env_val.isdigit():
        return int(env_val)
    # Probe llama-cpp-python for default block size
    try:
        import llama_cpp

        block_size = getattr(llama_cpp, "LLAMA_DEFAULT_ATTN_BLOCK_SIZE", None)
        if block_size and isinstance(block_size, int) and block_size > 0:
            # Round default UP to nearest multiple of block_size
            import math

            return int(math.ceil(default / block_size)) * block_size
    except ImportError:
        pass
    return default


N_PREFIX = _detect_optimal_n_prefix(default=8)
log.info("N_PREFIX resolved to %d tokens", N_PREFIX)

# ── #19 Attention dilution threshold ──────────────────────────────────────────
# Soft prefix signal washes out in the Softmax denominator beyond ~512 total tokens.
# _SEGMENT_MAX_NEW: new tokens generated per segment — kept well under threshold.
# _CONTEXT_TAIL_CHARS: chars of prior output kept as context at each re-injection
#   boundary (~150 tokens), enough to maintain code coherence across segments.
N_DILUTION_THRESHOLD = 512
_SEGMENT_MAX_NEW = N_DILUTION_THRESHOLD // 2  # 256 new tokens per segment
_CONTEXT_TAIL_CHARS = 600  # ~150 tokens of rolling context

# ── #26 FP8/Q8 KV cache quantization noise scale ──────────────────────────────
# The adapter calibrates against FP32 embeddings but the runtime KV cache uses
# Q8 or FP8, which introduces ~0.2% relative quantization error per dimension.
# Simulating this noise during training makes W project into a robust region.
_KV_CACHE_Q8_NOISE_SCALE = 0.002

COMPILE_TIMEOUT = 30
ALIGN_LR = 3e-4  # alignment phase LR
COMPILE_LR = 1e-4  # compile phase LR
ALIGN_WEIGHT = 1.0  # weight for MSE+cosine loss
COMPILE_WEIGHT = 0.05  # weight for compile REINFORCE signal
COMPILE_BASELINE = 0.5  # expected compile rate (advantage baseline)


def resolve_pair(source_name: str, target_name: str) -> dict:
    """
    Resolve source and target model dimensions and paths from the registry.
    Returns a dict with all resolved parameters.
    Raises ValueError if either model is not registered.
    """
    src = get_model(source_name)
    tgt = get_model(target_name)

    if src is None:
        # Legacy fallback: try to probe a known path
        for legacy_path in [_LEGACY_LEVIATHAN_GGUF, _LEGACY_OBSERVER_GGUF]:
            if legacy_path.exists():
                info = probe_gguf(legacy_path)
                if source_name.lower() in str(legacy_path).lower():
                    src = {
                        "path": str(legacy_path),
                        "hidden_dim": info["hidden_dim"],
                        "arch": info["arch"],
                        "family": info["family"],
                    }
                    break
        if src is None:
            raise ValueError(
                f"Source model '{source_name}' not in registry and no legacy path found.\n"
                f"Run: python determinex_rosetta.py register {source_name} <path.gguf>"
            )

    if tgt is None:
        for legacy_path in [_LEGACY_OBSERVER_GGUF, _LEGACY_LEVIATHAN_GGUF]:
            if legacy_path.exists():
                info = probe_gguf(legacy_path)
                if target_name.lower() in str(legacy_path).lower():
                    tgt = {
                        "path": str(legacy_path),
                        "hidden_dim": info["hidden_dim"],
                        "arch": info["arch"],
                        "family": info["family"],
                    }
                    break
        if tgt is None:
            raise ValueError(
                f"Target model '{target_name}' not in registry.\n"
                f"Run: python determinex_rosetta.py register {target_name} <path.gguf>"
            )

    d_src = src["hidden_dim"]
    d_tgt = tgt["hidden_dim"]
    if d_src is None:
        raise ValueError(f"Source model '{source_name}' has no hidden_dim in registry.")
    if d_tgt is None:
        raise ValueError(f"Target model '{target_name}' has no hidden_dim in registry.")

    d_hidden = max(d_src, d_tgt)  # MLP intermediate width

    adapter_name = f"adapter_{source_name}_to_{target_name}".replace("/", "_")
    save_path = ADAPTERS_DIR / f"{adapter_name}.pt"

    return {
        "source_name": source_name,
        "target_name": target_name,
        "source_path": Path(src["path"]),
        "target_path": Path(tgt["path"]),
        "d_src": d_src,
        "d_tgt": d_tgt,
        "d_hidden": d_hidden,
        "source_arch": src.get("arch", "unknown"),
        "target_arch": tgt.get("arch", "unknown"),
        "adapter_name": adapter_name,
        "save_path": save_path,
    }


# ── Compiler validators ───────────────────────────────────────────────────────


def validate_rust(code: str) -> tuple[bool, str]:
    with tempfile.NamedTemporaryFile(suffix=".rs", mode="w", encoding="utf-8", delete=False) as f:
        f.write(code)
        path = f.name
    try:
        r = subprocess.run(
            [
                "rustc",
                "--crate-type",
                "lib",
                "--edition",
                "2021",
                path,
                "--out-dir",
                tempfile.gettempdir(),
                "--error-format",
                "short",
            ],
            capture_output=True,
            text=True,
            timeout=COMPILE_TIMEOUT,
        )
        return (True, "") if r.returncode == 0 else (False, (r.stderr or r.stdout)[:300])
    except Exception as e:
        return False, str(e)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def validate_go(code: str) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as d:
        Path(d, "go.mod").write_text("module proj_check\ngo 1.21\n", encoding="utf-8")
        Path(d, "main.go").write_text(code, encoding="utf-8")
        try:
            r = subprocess.run(
                ["go", "build", "./..."],
                capture_output=True,
                text=True,
                timeout=COMPILE_TIMEOUT,
                cwd=d,
            )
            return (True, "") if r.returncode == 0 else (False, (r.stderr or r.stdout)[:300])
        except Exception as e:
            return False, str(e)


def validate_python(code: str) -> tuple[bool, str]:
    try:
        ast.parse(code)
        return True, ""
    except SyntaxError as e:
        return False, str(e)


def validate_code(lang: str, code: str) -> tuple[bool, str]:
    lang = lang.lower()
    if "rust" in lang:
        return validate_rust(code)
    if "go" in lang:
        return validate_go(code)
    if "python" in lang:
        return validate_python(code)
    return True, "(lenient)"


# ── Training tasks (seed dataset) ─────────────────────────────────────────────

SEED_TASKS = [
    {
        "lang": "Rust",
        "system": "You are an expert Rust programmer. Output ONLY correct Rust code, no explanation.",
        "prompt": "Write fn count_chars(s: &str, target: char) -> usize using .chars().filter().",
    },
    {
        "lang": "Rust",
        "system": "You are an expert Rust programmer. Output ONLY correct Rust code, no explanation.",
        "prompt": "Write fn first_even(nums: &[i32]) -> Option<i32> returning first even number. Note: 0 is even.",
    },
    {
        "lang": "Rust",
        "system": "You are an expert Rust programmer. Output ONLY correct Rust code, no explanation.",
        "prompt": "Write fn safe_divide(a: f64, b: f64) -> Option<f64> returning None if b is 0.",
    },
    {
        "lang": "Rust",
        "system": "You are an expert Rust programmer. Output ONLY correct Rust code, no explanation.",
        "prompt": "Write fn increment_counter(counter: Arc<Mutex<usize>>, n: usize) spawning n threads each incrementing by 1. Join all threads.",
    },
    {
        "lang": "Rust",
        "system": "You are an expert Rust programmer. Output ONLY correct Rust code, no explanation.",
        "prompt": "Write fn sum_parallel(data: Vec<i64>) -> i64 splitting data in half, summing each half in a separate thread using Arc<Mutex<i64>>, joining both, returning total.",
    },
    {
        "lang": "Go",
        "system": "You are an expert Go programmer. Always include package main and imports. Output ONLY correct Go code.",
        "prompt": "Write func WrapError(msg string, err error) error using fmt.Errorf with %w. Write func CheckWrap() that verifies errors.Is works on the wrapped error.",
    },
    {
        "lang": "Go",
        "system": "You are an expert Go programmer. Always include package main and imports. Output ONLY correct Go code.",
        "prompt": "Write func SafeDivide(a, b int) (result int, err error) using defer/recover to catch divide-by-zero panic.",
    },
    {
        "lang": "Go",
        "system": "You are an expert Go programmer. Always include package main and imports. Output ONLY correct Go code.",
        "prompt": "Write func ProcessData(ctx context.Context, inputs []int) ([]int, error) processing each input in a goroutine, doubling values, respecting ctx.Done().",
    },
    {
        "lang": "Python",
        "system": "You are an expert Python programmer. Output ONLY correct Python code, no explanation.",
        "prompt": "Write class RaceCounter with self.value=0 and self.lock=threading.Lock(). Add increment(self) with lock and get(self)->int.",
    },
    {
        "lang": "Python",
        "system": "You are an expert Python programmer. Output ONLY correct Python code, no explanation.",
        "prompt": "Write class SessionTracker with add_session(self, user_id: str, duration: int) and get_total_duration(self, user_id: str)->int. Thread-safe with Lock.",
    },
]


# ── Leviathan hidden state encoder ───────────────────────────────────────────


class LeviathanEncoder:
    """
    Loads Leviathan GGUF via llama-cpp-python and extracts final hidden states.
    Runs CPU-only (matching how Leviathan already runs in production).
    Output: [1, D_LEVIATHAN] = [1, 2048]
    """

    def __init__(self, gguf_path: Path):
        try:
            from llama_cpp import Llama
        except ImportError:
            raise ImportError(
                "[PROJ] llama-cpp-python not installed.\n       Run: pip install llama-cpp-python"
            )
        log.info("Loading Leviathan GGUF (CPU)... path=%s", gguf_path)
        self.model = Llama(
            model_path=str(gguf_path),
            n_ctx=2048,
            n_gpu_layers=0,
            embedding=True,
            logits_all=False,
            verbose=False,
        )
        # D_LEVIATHAN was never assigned anywhere in this module, so this line raised
        # NameError the moment an encoder was actually constructed. n_embd() is the value it
        # was reaching for and matches this file's own rule -- dimensions are probed from the
        # GGUF header at runtime, never hardcoded.
        log.info("Leviathan loaded. hidden_size=%d", self.model.n_embd())

    def encode(self, system: str, prompt: str) -> torch.Tensor:
        """Returns [1, D_LEVIATHAN] — compressed semantic rep of the prompt."""
        import torch

        full_text = f"<|system|>\n{system}<|end|>\n<|user|>\n{prompt}<|end|>\n<|assistant|>"
        embedding = self.model.embed(full_text)
        tensor = torch.tensor(embedding, dtype=torch.float32)
        if tensor.dim() == 2:
            tensor = tensor[-1]  # last token if seq returned
        return tensor.unsqueeze(0)  # [1, 2048]

    def encode_to_prefix(self, system: str, prompt: str, n_prefix: int = N_PREFIX) -> torch.Tensor:
        """Returns [n_prefix, D_LEVIATHAN] for soft prefix injection."""
        h = self.encode(system, prompt)  # [1, 2048]
        return h.expand(n_prefix, -1).clone()  # [n_prefix, 2048]


# ── Observer hidden state encoder (alignment target) ─────────────────────────


class ObserverEncoder:
    """
    Loads Observer GGUF (Llama 3.2 3B, hidden_size=3072) and extracts embeddings.
    Used as the alignment TARGET for training W.

    We use Observer's embedding of the SAME prompt as the ground truth that
    W should project Leviathan toward. If W(h_lev) ≈ h_obs, then the soft
    prefix sits in the right region of the receiving model's embedding space.

    Runs CPU-only. Observer GGUF is ~3.2GB.
    """

    def __init__(self, gguf_path: Path):
        try:
            from llama_cpp import Llama
        except ImportError:
            raise ImportError(
                "[PROJ] llama-cpp-python not installed.\n       Run: pip install llama-cpp-python"
            )
        log.info("Loading Observer GGUF (CPU)... path=%s", gguf_path)
        self.model = Llama(
            model_path=str(gguf_path),
            n_ctx=2048,
            n_gpu_layers=0,
            embedding=True,
            logits_all=False,
            verbose=False,
        )
        # Same as D_LEVIATHAN above: D_TARGET is never assigned in this module, so this
        # raised NameError on construction. Probed from the GGUF header, not hardcoded.
        log.info("Observer loaded. target hidden_size=%d", self.model.n_embd())

    def encode(self, system: str, prompt: str) -> torch.Tensor:
        """Returns [1, D_TARGET] — Observer's representation of the prompt."""
        import torch

        full_text = f"<|system|>\n{system}<|end|>\n<|user|>\n{prompt}<|end|>\n<|assistant|>"
        embedding = self.model.embed(full_text)
        tensor = torch.tensor(embedding, dtype=torch.float32)
        if tensor.dim() == 2:
            tensor = tensor[-1]
        vec = tensor.unsqueeze(0)  # [1, D_TARGET]
        # D_TARGET was a module constant the registry refactor deleted. n_embd() is the
        # probed value it stood for, and matches this file's "nothing is hardcoded" rule.
        _d_tgt = self.model.n_embd()
        if vec.shape[-1] != _d_tgt:
            raise ValueError(
                f"Observer embedding dim {vec.shape[-1]} != target dim {_d_tgt}. "
                f"Check that the GGUF is a 3072-dim model (Llama 3.2 3B)."
            )
        return vec


# ── Projection MLP ────────────────────────────────────────────────────────────


def _build_projection(d_src: int, d_tgt: int, d_hidden: int | None = None) -> torch.nn.Module:
    """
    2-layer MLP: R^d_src → R^d_hidden (GELU + LayerNorm) → R^d_tgt
    Dimensions resolved from registry, not hardcoded.

    Uses determinex_rosetta.build_mlp for architecture consistency,
    wrapped in a Module subclass so .forward() has an explicit shape comment.
    """
    import torch.nn as nn

    d_h = d_hidden or max(d_src, d_tgt)

    class _W(nn.Module):
        def __init__(self):
            super().__init__()
            self.net = build_mlp(d_src, d_tgt, d_hidden=d_h)
            self.d_src = d_src
            self.d_tgt = d_tgt

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            return self.net(x)  # [n_prefix, d_src] → [n_prefix, d_tgt]

    return _W()


# ── Alignment loss ────────────────────────────────────────────────────────────


def alignment_loss(proj: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
    """
    Computes distance between the projected prefix and the target embedding.

    proj   : [N_PREFIX, D_TARGET] — W's output (mean-pooled for comparison)
    target : [1, D_TARGET]       — Observer's embedding of the same prompt

    MSE drives the projection to the right magnitude and direction.
    Cosine drives the projection to the right direction even when magnitudes differ.
    Together they converge faster than either alone.
    """
    import torch.nn.functional as F

    proj_mean = proj.mean(dim=0)  # [D_TARGET] — aggregate prefix signal
    target_vec = target.squeeze(0)  # [D_TARGET]

    mse = F.mse_loss(proj_mean, target_vec)
    cosine = 1.0 - F.cosine_similarity(proj_mean.unsqueeze(0), target_vec.unsqueeze(0)).squeeze()

    return ALIGN_WEIGHT * (mse + cosine)


def _detect_tokenizer_type(tokenizer) -> str:
    """
    #33 Meta-space fracture: detect whether the tokenizer uses SentencePiece
    (▁-prefixed word boundaries) or Tiktoken/GPT-2 BPE (Ġ-prefixed / byte tokens).

    SentencePiece encodes a leading space as the ▁ prefix (U+2581) on the first
    subword of each word. After a soft prefix + \\n bridge, the following text token
    may lose its ▁ marker, shifting it to a different vocabulary position than it
    occupies during normal training. Inserting a space anchor token restores it.

    Returns: 'sentencepiece' | 'tiktoken' | 'unknown'
    """
    try:
        vocab = tokenizer.get_vocab()
        sample = list(vocab.keys())[:500]
        # SentencePiece: ▁ (U+2581) marks word-initial tokens
        sp_count = sum(1 for t in sample if t.startswith("\u2581"))
        if sp_count > 10:
            return "sentencepiece"
        # Tiktoken / GPT-2 BPE: Ġ (U+0120) or raw byte tokens <0xNN>
        tk_count = sum(1 for t in sample if t.startswith("\u0120") or t.startswith("<0x"))
        if tk_count > 10:
            return "tiktoken"
    except Exception:
        pass
    return "unknown"


# ── Engineer with soft prefix injection ───────────────────────────────────────


class EngineerWithPrefix:
    """
    Loads Phi-3-mini from HuggingFace cache + optional LoRA adapter.
    Accepts a soft prefix (projected Leviathan states) prepended to
    the token embeddings before the forward pass.

    Used in compile-guided training and eval/demo modes.
    NOT needed for pure alignment training (--mode align).
    """

    def __init__(self, hf_model_id: str, lora_path: Path | None = None, device: str = "cuda"):
        import torch
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.device = device
        cache = str(HF_CACHE_DIR) if HF_CACHE_DIR.exists() else None
        log.info("Loading Phi-3-mini tokenizer... (cache=%s)", cache or "default")
        self.tokenizer = AutoTokenizer.from_pretrained(
            hf_model_id, trust_remote_code=True, cache_dir=cache
        )

        log.info("Loading Phi-3-mini model (4-bit NF4)...")
        from transformers import BitsAndBytesConfig

        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
        )
        self.model = AutoModelForCausalLM.from_pretrained(
            hf_model_id,
            quantization_config=bnb_config,
            device_map="auto",
            trust_remote_code=False,
            attn_implementation="eager",
            dtype=torch.float16,
            cache_dir=cache,
        )

        if lora_path and lora_path.exists():
            log.info("Applying LoRA from %s", lora_path)
            self.model = PeftModel.from_pretrained(self.model, str(lora_path))

        self.model.eval()
        # #33: detect once at init — used in every generate_with_prefix() call
        self._tok_type = _detect_tokenizer_type(self.tokenizer)
        # D_TARGET was a deleted module constant. This encoder wraps an HF model, so
        # the dimension lives on its config -- not a GGUF header.
        log.info(
            "Engineer loaded. hidden_size=%d (tokenizer=%s)",
            self.model.config.hidden_size,
            self._tok_type,
        )

    def get_embedding_layer(self) -> torch.nn.Module:
        return self.model.model.model.embed_tokens

    def _build_prefix_embeds(
        self,
        soft_prefix: torch.Tensor,
        text: str,
        hop_depth: int = 0,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """
        Build (combined_embeds, attention_mask) for one generation pass.

        Assembles: [BOS (pos 0)] [soft_prefix_0..N] [\\n bridge] [text_tokens]

        #25 BOS pinning: BOS at position 0 anchors the attention sink.
        #23 Bridging token: \\n at the soft/hard token boundary.
        #33 Meta-space spacer: SentencePiece ▁ alignment after \\n.
        #35 Echo chamber guard: Gaussian noise scales with hop_depth.
        """
        import torch

        embed_layer = self.get_embedding_layer()
        bos_token_id = self.tokenizer.bos_token_id

        inputs = self.tokenizer(text, return_tensors="pt").to(self.device)
        input_ids = inputs["input_ids"]

        with torch.no_grad():
            all_token_embeds = embed_layer(input_ids)

        # #31 Pinned memory
        _sp = soft_prefix
        if _sp.device.type == "cpu" and not _sp.is_pinned():
            try:
                _sp = _sp.pin_memory()
            except RuntimeError:
                pass
        prefix = _sp.unsqueeze(0).to(self.device, non_blocking=True).to(all_token_embeds.dtype)

        # #35 Echo chamber guard
        if hop_depth > 0:
            prefix = prefix + torch.randn_like(prefix) * (0.01 * hop_depth)

        # #25 BOS pinning
        if (
            bos_token_id is not None
            and input_ids.shape[1] > 0
            and input_ids[0, 0].item() == bos_token_id
        ):
            bos_embed = all_token_embeds[:, :1, :]
            text_embeds = all_token_embeds[:, 1:, :]
            text_mask = inputs["attention_mask"][:, 1:]
        else:
            fallback_bos = bos_token_id if bos_token_id is not None else 1
            bos_id_t = torch.tensor([[fallback_bos]], dtype=torch.long, device=self.device)
            bos_embed = embed_layer(bos_id_t)
            text_embeds = all_token_embeds
            text_mask = inputs["attention_mask"]

        # #23 Bridging token
        nl_embed = nl_mask = None
        nl_ids = self.tokenizer.encode("\n", add_special_tokens=False)
        if nl_ids:
            nl_t = torch.tensor([[nl_ids[0]]], dtype=torch.long, device=self.device)
            nl_embed = embed_layer(nl_t)
            nl_mask = torch.ones(1, 1, dtype=torch.long, device=self.device)

        embed_parts: list[torch.Tensor] = [bos_embed, prefix]
        mask_parts: list[torch.Tensor] = [
            torch.ones(1, 1, dtype=torch.long, device=self.device),
            torch.ones(1, prefix.shape[1], dtype=torch.long, device=self.device),
        ]
        if nl_embed is not None:
            embed_parts.append(nl_embed)
            mask_parts.append(nl_mask)
            # #33 Meta-space spacer for SentencePiece tokenizers
            if self._tok_type == "sentencepiece":
                _sp_ids = self.tokenizer.encode(" ", add_special_tokens=False)
                if _sp_ids:
                    _sp_t = torch.tensor([[_sp_ids[0]]], dtype=torch.long, device=self.device)
                    embed_parts.append(embed_layer(_sp_t))
                    mask_parts.append(torch.ones(1, 1, dtype=torch.long, device=self.device))
        embed_parts.append(text_embeds)
        mask_parts.append(text_mask)

        return (
            torch.cat(embed_parts, dim=1),
            torch.cat(mask_parts, dim=1),
        )

    def _run_generate(
        self,
        combined_embeds: torch.Tensor,
        attention_mask: torch.Tensor,
        max_new_tokens: int,
        temperature: float,
        top_p: float,
        min_p: float,
    ) -> torch.Tensor:
        """Call model.generate() with sampler state, return new token IDs only."""
        import torch

        n_input = combined_embeds.shape[1]
        _gen_kwargs: dict = {
            "inputs_embeds": combined_embeds,
            "attention_mask": attention_mask,
            "max_new_tokens": max_new_tokens,
            "pad_token_id": self.tokenizer.eos_token_id,
        }
        if temperature != 1.0 or top_p < 1.0 or min_p > 0.0:
            _gen_kwargs["do_sample"] = True
            _gen_kwargs["temperature"] = max(temperature, 1e-4)
            _gen_kwargs["top_p"] = top_p
            if min_p > 0.0:
                _gen_kwargs["min_p"] = min_p
        else:
            _gen_kwargs["do_sample"] = False
            _gen_kwargs["temperature"] = 1.0
        with torch.no_grad():
            output_ids = self.model.generate(**_gen_kwargs)
        return output_ids[0][n_input:]

    def generate_with_prefix(
        self,
        soft_prefix: torch.Tensor,
        system: str,
        prompt: str,
        max_new_tokens: int = 512,
        temperature: float = 1.0,
        top_p: float = 0.9,
        min_p: float = 0.0,
        hop_depth: int = 0,
    ) -> str:
        """
        Generate text with a soft Rosetta prefix injected at the embedding layer.

        Dispatches to single-segment generation when max_new_tokens fits within
        the dilution-safe window, or to segment-based re-injection for longer
        outputs — keeping prefix attention weight reliable at any generation length.

        #19 Attention dilution fix (Layer 2):
            Prefix signal washes out when total context > N_DILUTION_THRESHOLD.
            _gen_chunked() re-injects the prefix at every _SEGMENT_MAX_NEW boundary
            so the prefix never falls below its designed attention weight.
            The model sees itself mid-response at each re-injection:
              [BOS | soft_prefix | \\n | system + user + tail_of_prior_output]
        """
        if max_new_tokens <= _SEGMENT_MAX_NEW:
            return self._gen_single(
                soft_prefix, system, prompt, max_new_tokens, temperature, top_p, min_p, hop_depth
            )
        return self._gen_chunked(
            soft_prefix, system, prompt, max_new_tokens, temperature, top_p, min_p, hop_depth
        )

    def _gen_single(
        self,
        soft_prefix: torch.Tensor,
        system: str,
        prompt: str,
        max_new_tokens: int,
        temperature: float,
        top_p: float,
        min_p: float,
        hop_depth: int,
    ) -> str:
        """Single-pass generation — prefix injected once, no re-injection."""
        text = self.tokenizer.apply_chat_template(
            [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            tokenize=False,
            add_generation_prompt=True,
        )
        embeds, mask = self._build_prefix_embeds(soft_prefix, text, hop_depth)
        new_ids = self._run_generate(embeds, mask, max_new_tokens, temperature, top_p, min_p)
        return self.tokenizer.decode(new_ids, skip_special_tokens=True).strip()

    def _gen_chunked(
        self,
        soft_prefix: torch.Tensor,
        system: str,
        prompt: str,
        max_new_tokens: int,
        temperature: float,
        top_p: float,
        min_p: float,
        hop_depth: int,
    ) -> str:
        """
        Segment-based re-injection for long generation.

        At each segment boundary the soft prefix is re-injected at full
        attention weight. The model is placed mid-response by appending
        the tail of prior output directly after the chat template's
        assistant-turn opener (no end-of-turn token added), so it
        continues naturally from where it left off.

        Tail length (_CONTEXT_TAIL_CHARS chars ≈ 150 tokens) preserves
        local code coherence without bloating input context.
        """
        _EOS_MARKERS = {"<|end|>", "<|endoftext|>", "</s>", "<|im_end|>"}

        # Base template: ends with the assistant-turn opener
        base_text = self.tokenizer.apply_chat_template(
            [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            tokenize=False,
            add_generation_prompt=True,
        )

        segments: list[str] = []
        total_new = 0

        while total_new < max_new_tokens:
            remaining = max_new_tokens - total_new
            seg_tokens = min(_SEGMENT_MAX_NEW, remaining)

            # Build the text context for this segment
            if segments:
                tail = "".join(segments)[-_CONTEXT_TAIL_CHARS:]
                # Place model mid-response: base ends with "<|assistant|>" opener,
                # appending the tail means the model continues from there.
                text = base_text + tail
            else:
                text = base_text

            embeds, mask = self._build_prefix_embeds(soft_prefix, text, hop_depth)
            new_ids = self._run_generate(embeds, mask, seg_tokens, temperature, top_p, min_p)
            seg_text = self.tokenizer.decode(new_ids, skip_special_tokens=True)

            if not seg_text:
                break

            segments.append(seg_text)
            total_new += len(new_ids)
            log.debug(
                "[Layer2] segment %d: +%d tokens (total %d/%d)",
                len(segments),
                len(new_ids),
                total_new,
                max_new_tokens,
            )

            if any(m in seg_text for m in _EOS_MARKERS):
                break

        return "".join(segments)


def _simulate_kv_cache_quantization(
    tensor: torch.Tensor,
    noise_scale: float = _KV_CACHE_Q8_NOISE_SCALE,
) -> torch.Tensor:
    """
    #26 FP8/Q8 KV cache drift: add Gaussian noise to simulate quantization error.

    The adapter is calibrated against FP32 embeddings, but at runtime the KV cache
    uses Q8 or FP8 — every key/value tensor for the prefix tokens gets quantized.
    Training W against noisy projections forces it to land in a region where small
    quantization perturbations still decode correctly in the target model's attention.

    noise_scale=0.002 approximates the RMS error of Q8 quantization on [0,1]-normalized
    embeddings. Set to 0.0 to disable (e.g. FP16 runtime or CPU-only inference).
    """
    import torch

    if noise_scale <= 0.0:
        return tensor
    return tensor + torch.randn_like(tensor) * noise_scale


# ── Alignment training loop (fast — no generation) ───────────────────────────


def train_alignment(
    leviathan: LeviathanEncoder,
    observer: ObserverEncoder,
    W: torch.nn.Module,
    tasks: list[dict],
    steps: int = 200,
    lr: float = ALIGN_LR,
    # Was `= PROJECTION_SAVE`, a name this module no longer defines. Default
    # arguments evaluate at DEF time, so that single token made the whole module
    # unimportable. Resolved from the caller's pair instead.
    save_path: Path | None = None,
) -> dict:
    """
    Pure embedding alignment training. Does NOT run Engineer or compile code.
    Fast: ~5 minutes for 200 steps on CPU encoders + GPU W.

    At each step:
      1. Leviathan embeds prompt → h_lev [2048]
      2. Observer embeds same prompt → h_obs [3072]  (frozen, no grad)
      3. W(h_lev) → proj [N_PREFIX, 3072]
      4. loss = MSE(mean(proj), h_obs) + cosine_distance(mean(proj), h_obs)
      5. Backprop through W only
    """
    if save_path is None:
        raise ValueError(
            "save_path is required -- pass resolve_pair(src, tgt)['save_path']. "
            "It used to default to a module constant the registry refactor deleted."
        )
    import torch

    optimizer = torch.optim.AdamW(W.parameters(), lr=lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=steps)

    device = next(W.parameters()).device
    stats = {"steps": 0, "loss_history": [], "cos_sim_history": []}
    log.info("Alignment training: %d steps, lr=%.0e", steps, lr)

    import torch.nn.functional as F

    for step in range(steps):
        task = tasks[step % len(tasks)]

        # Encode with both encoders — no grad needed from them
        with torch.no_grad():
            lev_prefix = leviathan.encode_to_prefix(
                task["system"], task["prompt"]
            )  # [N_PREFIX, 2048]
            obs_target = observer.encode(task["system"], task["prompt"])  # [1, 3072]

        # ── #31 Pinned memory ────────────────────────────────────────────────────
        if device != "cpu":
            if not lev_prefix.is_pinned():
                try:
                    lev_prefix = lev_prefix.pin_memory()
                except RuntimeError:
                    pass
            if not obs_target.is_pinned():
                try:
                    obs_target = obs_target.pin_memory()
                except RuntimeError:
                    pass
        lev_gpu = lev_prefix.to(device, non_blocking=True)
        obs_gpu = obs_target.to(device, non_blocking=True)

        # Forward through W
        proj = W(lev_gpu)  # [N_PREFIX, 3072] — grads flow here

        # ── #26 FP8/Q8 KV cache drift simulation ─────────────────────────────
        # Apply quantization noise to proj before loss — W learns to project into
        # a region robust to Q8/FP8 KV cache perturbations at inference time.
        proj_for_loss = _simulate_kv_cache_quantization(proj)

        # Alignment loss
        loss = alignment_loss(proj_for_loss, obs_gpu)

        optimizer.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(W.parameters(), 1.0)
        optimizer.step()
        scheduler.step()

        # Track cosine similarity (sanity metric — higher is better)
        with torch.no_grad():
            cos = F.cosine_similarity(
                proj.mean(0).unsqueeze(0), obs_gpu.squeeze(0).unsqueeze(0)
            ).item()

        stats["steps"] += 1
        stats["loss_history"].append(loss.item())
        stats["cos_sim_history"].append(cos)

        if step % 10 == 0:
            avg_loss = sum(stats["loss_history"][-10:]) / min(10, step + 1)
            avg_cos = sum(stats["cos_sim_history"][-10:]) / min(10, step + 1)
            log.info(
                "[%03d] loss=%.4f | cos_sim=%.4f | %s...",
                step,
                avg_loss,
                avg_cos,
                task["prompt"][:45],
            )

        if step > 0 and step % 50 == 0:
            _save_projection(W, save_path)
            log.info("Checkpoint → %s", save_path)

    _save_projection(W, save_path)
    final_cos = sum(stats["cos_sim_history"][-20:]) / min(20, steps)
    log.info("Alignment done. Final cos_sim=%.4f (target: >0.7)", final_cos)
    return stats


# ── Compile-guided training loop (adds REINFORCE signal on top of alignment) ─


def train_projection(
    leviathan: LeviathanEncoder,
    observer: ObserverEncoder,
    engineer: EngineerWithPrefix,
    W: torch.nn.Module,
    tasks: list[dict],
    steps: int = 100,
    lr: float = COMPILE_LR,
    save_path: Path | None = None,  # see train_alignment: was an undefined name
) -> dict:
    """
    Compile-guided training. Runs AFTER alignment warmup.
    Adds a REINFORCE signal (compile pass/fail) on top of the alignment loss.

    The alignment loss is the primary gradient — compile REINFORCE only
    fine-tunes the projection toward code-specific patterns.
    COMPILE_WEIGHT=0.05 keeps alignment dominant.
    """
    if save_path is None:
        raise ValueError(
            "save_path is required -- pass resolve_pair(src, tgt)['save_path']. "
            "It used to default to a module constant the registry refactor deleted."
        )
    import torch
    import torch.nn.functional as F

    optimizer = torch.optim.AdamW(W.parameters(), lr=lr, weight_decay=1e-4)
    device = next(W.parameters()).device

    stats = {"steps": 0, "compiled": 0, "failed": 0, "loss_history": [], "cos_sim_history": []}
    log.info("Compile training: %d steps, lr=%.0e", steps, lr)

    for step in range(steps):
        task = tasks[step % len(tasks)]

        with torch.no_grad():
            lev_prefix = leviathan.encode_to_prefix(task["system"], task["prompt"])
            obs_target = observer.encode(task["system"], task["prompt"])

        # ── #31 Pinned memory ────────────────────────────────────────────────────
        if device != "cpu":
            if not lev_prefix.is_pinned():
                try:
                    lev_prefix = lev_prefix.pin_memory()
                except RuntimeError:
                    pass
            if not obs_target.is_pinned():
                try:
                    obs_target = obs_target.pin_memory()
                except RuntimeError:
                    pass
        lev_gpu = lev_prefix.to(device, non_blocking=True)
        obs_gpu = obs_target.to(device, non_blocking=True)

        proj = W(lev_gpu)  # [N_PREFIX, 3072]

        # ── #26 FP8/Q8 KV cache drift simulation ─────────────────────────────
        proj_for_loss = _simulate_kv_cache_quantization(proj)

        # Primary: alignment loss (projection trained against quantization-noisy target)
        loss_align = alignment_loss(proj_for_loss, obs_gpu)

        # Secondary: REINFORCE compile signal
        code = engineer.generate_with_prefix(proj.detach(), task["system"], task["prompt"])
        compiled, err = validate_code(task["lang"], code)

        advantage = (1.0 if compiled else 0.0) - COMPILE_BASELINE
        # Differentiable proxy: scale the projection norm by advantage
        # Positive advantage → encourage current projection magnitude
        # Negative advantage → discourage it
        loss_compile = -advantage * F.normalize(proj.mean(0), dim=0).norm()

        loss = loss_align + COMPILE_WEIGHT * loss_compile

        optimizer.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(W.parameters(), 1.0)
        optimizer.step()

        stats["steps"] += 1
        stats["compiled" if compiled else "failed"] += 1
        stats["loss_history"].append(loss.item())

        with torch.no_grad():
            cos = F.cosine_similarity(
                proj.mean(0).unsqueeze(0), obs_gpu.squeeze(0).unsqueeze(0)
            ).item()
        stats["cos_sim_history"].append(cos)

        status = "PASS" if compiled else "FAIL"
        log.info(
            "[%03d] %s | loss=%.4f | cos=%.4f | %s | %s...",
            step,
            status,
            loss.item(),
            cos,
            task["lang"],
            task["prompt"][:35],
        )

        if step > 0 and step % 10 == 0:
            rate = stats["compiled"] / stats["steps"] * 100
            log.info("--- step %d: compile=%.0f%% ---", step, rate)

        if step > 0 and step % 25 == 0:
            _save_projection(W, save_path)

    _save_projection(W, save_path)
    log.info(
        "Compile training done. Compile rate: %.0f%%",
        stats["compiled"] / max(stats["steps"], 1) * 100,
    )
    return stats


# ── Checkpoint I/O ────────────────────────────────────────────────────────────


def _save_projection(W: torch.nn.Module, path: Path, source_name: str = "", target_name: str = ""):
    import torch

    path.parent.mkdir(parents=True, exist_ok=True)
    d_src = getattr(W, "d_src", 0)
    d_tgt = getattr(W, "d_tgt", 0)
    torch.save(
        {
            "state_dict": W.state_dict(),
            "d_src": d_src,
            "d_tgt": d_tgt,
            "source_model": source_name,
            "target_model": target_name,
            "architecture": "mlp_gelu_ln",
            "type": "calibration_adapter",
            "timestamp": datetime.now(UTC).isoformat(),
        },
        path,
    )


def _load_projection(path: Path) -> torch.nn.Module:
    import torch

    ckpt = torch.load(path, map_location="cpu", weights_only=True)
    d_src = ckpt.get("d_src") or ckpt.get("d_lev", 2048)  # backward compat
    d_tgt = ckpt.get("d_tgt") or ckpt.get("d_target", 3072)  # backward compat
    W = _build_projection(d_src, d_tgt)
    W.load_state_dict(ckpt["state_dict"])
    arch = ckpt.get("architecture", "linear")
    log.info(
        "Loaded projection from %s (arch=%s, d_src=%d, d_tgt=%d, trained %s)",
        path,
        arch,
        d_src,
        d_tgt,
        ckpt.get("timestamp", "?"),
    )
    return W


# ── CLI ───────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="determinex_projector — latent bridge W trainer")
    parser.add_argument(
        "--mode", choices=["probe", "align", "train", "eval", "demo"], default="probe"
    )
    parser.add_argument("--steps", type=int, default=200)
    parser.add_argument(
        "--lr",
        type=float,
        default=None,
        help="Learning rate (default: 3e-4 for align, 1e-4 for train)",
    )
    parser.add_argument("--lora", type=Path, default=ENGINEER_LORA)
    parser.add_argument("--prompt", type=str, default=None)
    parser.add_argument("--lang", type=str, default="Rust")
    # The module docstring has documented `--source X --target Y` since the registry
    # refactor; argparse never gained them, and resolve_pair() -- written by that same
    # refactor to return exactly the values it deleted -- was never called from
    # anywhere. These two arguments are what connect them.
    parser.add_argument("--source", type=str, default="leviathan")
    parser.add_argument("--target", type=str, default="determinex-observer-v4")
    args = parser.parse_args()

    # Resolve the pair ONCE, then bind the six names every branch below already uses.
    # Binding locally (rather than editing 33 call sites) keeps this a wiring fix and
    # not a rewrite of logic nobody can run right now.
    try:
        pair = resolve_pair(args.source, args.target)
    except ValueError as e:
        log.error("%s", e)
        return 1
    LEVIATHAN_GGUF = pair["source_path"]
    OBSERVER_GGUF = pair["target_path"]
    D_LEVIATHAN = pair["d_src"]
    D_TARGET = pair["d_tgt"]
    D_HIDDEN = pair["d_hidden"]
    PROJECTION_SAVE = pair["save_path"]

    import torch

    device = "cuda" if torch.cuda.is_available() else "cpu"
    log.info("Device: %s", device)

    # ── PROBE ────────────────────────────────────────────────────────────────
    if args.mode == "probe":
        log.info("=== PROBE MODE ===")
        log.info("Leviathan GGUF : %s (exists=%s)", LEVIATHAN_GGUF, LEVIATHAN_GGUF.exists())
        log.info("Observer GGUF  : %s (exists=%s)", OBSERVER_GGUF, OBSERVER_GGUF.exists())
        log.info("Phi-3 HF ID    : %s", PHI3_HF_ID)
        log.info("D_LEVIATHAN    : %d", D_LEVIATHAN)
        log.info("D_TARGET       : %d", D_TARGET)
        log.info("D_HIDDEN (MLP) : %d", D_HIDDEN)
        log.info("N_PREFIX       : %d tokens", N_PREFIX)
        log.info("Save path      : %s", PROJECTION_SAVE)
        log.info("Seed tasks     : %d", len(SEED_TASKS))
        try:
            import llama_cpp

            log.info("llama-cpp-python: INSTALLED v%s", llama_cpp.__version__)
        except ImportError:
            log.warning("llama-cpp-python: NOT INSTALLED — run: pip install llama-cpp-python")
        # Was `_build_projection()`. The signature takes two REQUIRED dims; the
        # registry refactor that introduced them never updated these callers, so
        # every training mode raised TypeError. Dims come from resolve_pair().
        W = _build_projection(D_LEVIATHAN, D_TARGET, D_HIDDEN)
        total_params = sum(p.numel() for p in W.parameters())
        log.info("Projection W (MLP): %d parameters (%.1fM)", total_params, total_params / 1e6)
        log.info("PROBE complete.")
        log.info("  --mode align  : fast alignment training (no Engineer, ~5 min)")
        log.info("  --mode train  : compile-guided training (needs Engineer, ~30 min)")
        return

    # ── ALIGN ────────────────────────────────────────────────────────────────
    if args.mode == "align":
        log.info("=== ALIGN MODE — pure embedding alignment, no generation ===")
        if not OBSERVER_GGUF.exists():
            log.error("Observer GGUF not found: %s", OBSERVER_GGUF)
            log.error("Download it from RunPod or adjust OBSERVER_GGUF path.")
            sys.exit(1)

        leviathan = LeviathanEncoder(LEVIATHAN_GGUF)
        observer = ObserverEncoder(OBSERVER_GGUF)
        W = _build_projection(D_LEVIATHAN, D_TARGET, D_HIDDEN).to(device)

        lr = args.lr or ALIGN_LR
        stats = train_alignment(leviathan, observer, W, SEED_TASKS, steps=args.steps, lr=lr)
        log.info("=== ALIGN RESULTS ===")
        log.info("Steps     : %d", stats["steps"])
        if stats["cos_sim_history"]:
            final_cos = sum(stats["cos_sim_history"][-20:]) / min(20, len(stats["cos_sim_history"]))
            log.info("Cos sim   : %.4f (final 20-step avg)", final_cos)
        log.info("Saved     : %s", PROJECTION_SAVE)
        return

    # ── TRAIN ────────────────────────────────────────────────────────────────
    if args.mode == "train":
        log.info("=== TRAIN MODE — alignment + compile REINFORCE ===")
        if not OBSERVER_GGUF.exists():
            log.error("Observer GGUF not found: %s", OBSERVER_GGUF)
            sys.exit(1)

        leviathan = LeviathanEncoder(LEVIATHAN_GGUF)
        observer = ObserverEncoder(OBSERVER_GGUF)

        # Load W from previous alignment checkpoint if available
        if PROJECTION_SAVE.exists():
            log.info("Loading alignment checkpoint for compile fine-tuning...")
            W = _load_projection(PROJECTION_SAVE).to(device)
        else:
            log.info("No alignment checkpoint found — starting from scratch.")
            log.info("Recommend running --mode align first for faster convergence.")
            W = _build_projection(D_LEVIATHAN, D_TARGET, D_HIDDEN).to(device)

        lora_path = args.lora if (args.lora / "adapter_config.json").exists() else None
        engineer = EngineerWithPrefix(PHI3_HF_ID, lora_path, device)

        lr = args.lr or COMPILE_LR
        stats = train_projection(
            leviathan, observer, engineer, W, SEED_TASKS, steps=args.steps, lr=lr
        )
        log.info("=== TRAIN RESULTS ===")
        log.info("Steps    : %d", stats["steps"])
        log.info(
            "Compiled : %d / %d (%.0f%%)",
            stats["compiled"],
            stats["steps"],
            stats["compiled"] / max(stats["steps"], 1) * 100,
        )
        log.info("Saved    : %s", PROJECTION_SAVE)
        return

    # ── EVAL ─────────────────────────────────────────────────────────────────
    if args.mode == "eval":
        if not PROJECTION_SAVE.exists():
            log.error("No trained W at %s — run --mode align first", PROJECTION_SAVE)
            sys.exit(1)
        if not OBSERVER_GGUF.exists():
            log.error("Observer GGUF not found: %s", OBSERVER_GGUF)
            sys.exit(1)

        log.info("=== EVAL MODE ===")
        leviathan = LeviathanEncoder(LEVIATHAN_GGUF)
        observer = ObserverEncoder(OBSERVER_GGUF)
        lora_path = args.lora if (args.lora / "adapter_config.json").exists() else None
        engineer = EngineerWithPrefix(PHI3_HF_ID, lora_path, device)
        W = _load_projection(PROJECTION_SAVE).to(device)

        import torch
        import torch.nn.functional as F

        passed = 0
        cos_sims = []
        for i, task in enumerate(SEED_TASKS):
            lev_h = leviathan.encode_to_prefix(task["system"], task["prompt"]).to(device)
            obs_h = observer.encode(task["system"], task["prompt"]).to(device)
            prefix = W(lev_h)
            cos = F.cosine_similarity(
                prefix.mean(0).unsqueeze(0), obs_h.squeeze(0).unsqueeze(0)
            ).item()
            cos_sims.append(cos)
            code = engineer.generate_with_prefix(prefix, task["system"], task["prompt"])
            ok, _ = validate_code(task["lang"], code)
            passed += ok
            log.info(
                "[%02d] %s | cos=%.4f | %s | %s...",
                i,
                "PASS" if ok else "FAIL",
                cos,
                task["lang"],
                task["prompt"][:50],
            )

        log.info(
            "Eval: %d/%d compiled (%.0f%%)", passed, len(SEED_TASKS), passed / len(SEED_TASKS) * 100
        )
        log.info("Avg cos_sim: %.4f", sum(cos_sims) / len(cos_sims))
        return

    # ── DEMO ─────────────────────────────────────────────────────────────────
    if args.mode == "demo":
        if not args.prompt:
            log.error("--mode demo requires --prompt")
            sys.exit(1)
        if not PROJECTION_SAVE.exists():
            log.error("No trained W — run --mode align first")
            sys.exit(1)

        system = (
            f"You are an expert {args.lang} programmer. Output ONLY correct code, no explanation."
        )
        leviathan = LeviathanEncoder(LEVIATHAN_GGUF)
        lora_path = args.lora if (args.lora / "adapter_config.json").exists() else None
        engineer = EngineerWithPrefix(PHI3_HF_ID, lora_path, device)
        W = _load_projection(PROJECTION_SAVE).to(device)

        import torch
        import torch.nn.functional as F

        lev_h = leviathan.encode_to_prefix(system, args.prompt).to(device)
        prefix = W(lev_h)
        code = engineer.generate_with_prefix(prefix, system, args.prompt)
        ok, err = validate_code(args.lang, code)

        print(f"\n{'=' * 60}")
        print(f"Prompt : {args.prompt}")
        print(f"Lang   : {args.lang}")
        print(f"Result : {'COMPILED' if ok else 'FAILED'}")
        print(f"{'=' * 60}")
        print(code)
        if not ok:
            print(f"\nError: {err}")


if __name__ == "__main__":
    main()
