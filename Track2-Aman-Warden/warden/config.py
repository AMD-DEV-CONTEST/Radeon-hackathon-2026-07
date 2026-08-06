"""
Warden global configuration.

Centralizes all settings: model paths, thresholds, tier configs, and
feature flags. Loaded once at startup, referenced everywhere.
"""

from __future__ import annotations

import os
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

_log = logging.getLogger(__name__)


def _probe_free_vram_mb() -> int:
    """Return free VRAM in MB by querying rocm-smi or nvidia-smi.
    Returns 0 if neither is available (CPU-only mode)."""
    import subprocess
    import shutil
    # --- AMD ROCm path ---
    if shutil.which("rocm-smi"):
        try:
            out = subprocess.check_output(
                ["rocm-smi", "--showmeminfo", "vram", "--csv"],
                timeout=5, stderr=subprocess.DEVNULL, text=True,
            )
            lines = out.strip().splitlines()
            if len(lines) >= 2:
                # The first line is the header: device,VRAM Total Memory (B),VRAM Total Used Memory (B)
                # The second line is the data: card0,51522830336,1324359680
                data_line = lines[-1]
                parts = [p.strip() for p in data_line.split(",")]
                if len(parts) >= 3:
                    total_b = int(parts[1])
                    total_used = int(parts[2])
                    if total_b > 0:
                        return max(0, (total_b - total_used) // (1024 * 1024))
        except Exception:
            pass
    # --- NVIDIA path (fallback for CI / mixed environments) ---
    if shutil.which("nvidia-smi"):
        try:
            out = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
                timeout=5, stderr=subprocess.DEVNULL, text=True,
            )
            return int(out.strip().splitlines()[0])
        except Exception:
            pass
    return 0


# Quantization selection table: (min_free_vram_MB, kv_cache_type, model_quant_hint)
# Listed from most VRAM-hungry (best quality) to least.
_QUANT_TABLE = [
    (40_000, "f16",    "F16 / BF16 — full precision, highest quality"),
    (20_000, "q8_0",   "Q8_0 — near-lossless, 8-bit KV cache"),
    (12_000, "q5_k_m", "Q5_K_M — excellent quality/VRAM tradeoff"),
    (6_000,  "q4_k_m", "Q4_K_M — good quality, smallest footprint"),
    (0,      "q4_0",   "Q4_0 — minimum VRAM, degraded quality"),
]


def auto_select_quantization(free_vram_mb: Optional[int] = None) -> tuple[str, str]:
    """Return (kv_cache_type, human_readable_reason) for the available VRAM.

    Probes the GPU if free_vram_mb is not supplied.
    Falls back to q4_0 on CPU-only systems.
    """
    vram = free_vram_mb if free_vram_mb is not None else _probe_free_vram_mb()
    for threshold, kv_type, label in _QUANT_TABLE:
        if vram >= threshold:
            reason = f"{label} (detected {vram:,} MB free VRAM)"
            _log.info(f"[AutoQuant] Selected kv_cache_type={kv_type!r}: {reason}")
            return kv_type, reason
    # Absolute fallback
    return "q4_0", f"Q4_0 fallback — {vram} MB free VRAM (CPU-only or probe failed)"


def auto_select_gpu_layers(free_vram_mb: Optional[int] = None, bytes_per_layer: int = 140_000_000) -> int:
    """Estimate safe n_gpu_layers for the detected VRAM.

    bytes_per_layer default: ~140 MB for a 7B model at Q8_0 per layer.
    Returns -1 (full offload) when VRAM is ample, or a partial layer count.
    """
    vram = free_vram_mb if free_vram_mb is not None else _probe_free_vram_mb()
    if vram <= 0:
        _log.info("[AutoLayers] No GPU detected — n_gpu_layers=0 (CPU inference)")
        return 0
    # Reserve 2 GB headroom for KV-cache, activations, and OS overhead.
    usable_mb = max(0, vram - 2048)
    max_layers = usable_mb * 1024 * 1024 // bytes_per_layer
    if max_layers >= 32:      # Qwen-7B has 32 transformer layers
        _log.info(f"[AutoLayers] Full offload — {vram:,} MB free, n_gpu_layers=-1")
        return -1
    _log.info(f"[AutoLayers] Partial offload — {vram:,} MB free, n_gpu_layers={max_layers}")
    return max(1, max_layers)


class TrustLevel(Enum):
    """Trust classification for incoming content."""
    TRUSTED = "trusted"         # User's direct input, system prompts
    UNTRUSTED = "untrusted"     # Fetched web content, tool outputs, external files
    AMBIGUOUS = "ambiguous"     # Source unclear — treat as untrusted


class ContentSource(Enum):
    """Origin of content entering the system."""
    USER_DIRECT = "user_direct"
    FETCHED_URL = "fetched_url"
    TOOL_OUTPUT = "tool_output"
    LOCAL_FILE = "local_file"
    CODE_DIFF = "code_diff"
    UNKNOWN = "unknown"


class Decision(Enum):
    """Security decision outcome."""
    ALLOW = "allow"
    BLOCK = "block"
    FLAG = "flag"           # Allow but warn the user
    UNCERTAIN = "uncertain" # Needs escalation to next tier


class OperatingMode(Enum):
    """Warden operating modes."""
    ACTIVE = "active"       # Blocks threats, allows clean content
    SHADOW = "shadow"       # Logs everything, blocks nothing
    REPORT = "report"       # Offline analysis of historical data


@dataclass
class RoutingConfig:
    """Configuration for the Intelligent Routing Engine."""

    # Escalation thresholds
    tier0_to_tier1: float = 0.3     # Tier 0 suspicion score → escalate
    tier1_to_tier2: float = 0.4     # Tier 1 confidence below this → escalate
    auto_block: float = 0.85        # Tier 1 confidence above this → block without GPU
    auto_allow: float = -1.0        # Tier 1 confidence below this → allow without GPU (DISABLED for demo)

    # Batch scheduler
    batch_window_ms: int = 100
    max_batch_size: int = 8

    # Timeouts
    tier2_timeout_s: float = 30.0   # Max seconds for a Tier 2 GPU call
    rag_timeout_s: float = 5.0      # Max seconds for RAG retrieval


@dataclass
class ModelConfig:
    """Configuration for LLM models."""

    # Tier 2 model (semantically used by router when Tier 1 is uncertain;
    # also reused by the descoped CaMeL capability tracker for tool-call
    # data-flow checks — see warden/camel/interpreter.py).
    llm_model_path: str = ""
    llm_n_gpu_layers: int = -1      # -1 = offload all layers to GPU
    llm_n_gpu_layers_fallback: int = 20  # Used if -1 fails (large Q8 model on small VRAM)
    llm_n_ctx: int = 2048           # Context window (lowered from 4096 — our prompts are <2.5k tokens)
    llm_temperature: float = 0.1    # Low temp for deterministic classification
    llm_seed: int = 42              # Fixed seed for reproducible benchmarks

    # ROCm optimization parameters
    llm_flash_attn: bool = True     # Flash attention acceleration on Radeon GPUs
    llm_offload_kqv: bool = True    # Offload KQV directly into Radeon VRAM
    llm_n_batch: int = 512          # Prompt batch size for wide parallel instruction processing
    # Auto-quantization (RECOMMENDED ON): probe VRAM at load time and select
    # the best KV cache type + GPU layer count automatically.
    # Set WARDEN_LLM_AUTO_QUANT=0 (or llm_auto_quant=False) to pin manually.
    llm_auto_quant: bool = True

    llm_kv_cache_type: str = "q8_0"  # KV cache quantization: "f16" | "q8_0" | "q5_k_m" | "q4_k_m" | "q4_0"
                                       # Overridden at runtime by auto_select_quantization() when llm_auto_quant=True
    llm_warmup_on_load: bool = True # Dispatch 1-token no-op after load to swap weights into VRAM
    llm_physical_threads: bool = True  # Pin n_threads to physical cores (not logical HT) for prompt eval

    # Advanced ROCm / llama.cpp tuning (optional, env-overridable)
    llm_rope_freq_base: float = 10000.0   # RoPE base frequency (Qwen2.5 default; tune for very-large ctx)
    llm_rope_freq_scale: float = 1.0      # RoPE scale (1.0 = no extrapolation)
    llm_main_gpu: int = 0                 # HIP device index (0 = primary Radeon; set via HIP_VISIBLE_DEVICES too)
    llm_tensor_split: str = ""            # Comma-separated fractions per GPU (empty = auto-even split)
    llm_use_mmap: bool = True             # mmap the GGUF (lower RSS, faster startup); False → full RAM load
    llm_use_mlock: bool = False            # Lock weights in RAM (prevents swap; enable on cloud if RAM ample)
    llm_cache_prompt: bool = True         # Reuse KV across semantically-equal prompts (audit loop / batch scheduler)
    llm_split_mode: str = "layer"         # 'layer' | 'row' for multi-GPU split (layer is default & cache-friendly)
    llm_wait_model_load: bool = True       # Block load() until weights fully on GPU (avoids warmup race)
    llm_n_threads_batch: int = 0           # Separate thread count for prompt-eval (0 = mirror n_threads; nonzero → parallel tokenize)

    # AMD TokenFactory API Integration (Optional Cloud Endpoint Mode)
    tokenfactory_endpoint: str = ""
    tokenfactory_api_key: str = ""
    tokenfactory_model: str = "qwen2.5-coder-7b-instruct"

    # Tier 1 ML Classifier
    classifier_model_name: str = "protectai/deberta-v3-base-prompt-injection-v2"
    classifier_threshold_block: float = 0.85
    classifier_threshold_allow: float = 0.05
    classifier_device: str = "auto"  # "cpu" | "cuda" | "hip" | "auto"
                                        # "auto" = use GPU (ROCm/CUDA) when available, fall back to CPU

    # Model selection note: default is Qwen2.5-Coder-7B-Instruct (Q4_K_M)
    # Change llm_model_path based on what GPU is provided on AMD Radeon Cloud


@dataclass
class WardenConfig:
    """Top-level Warden configuration."""

    # Operating mode
    mode: OperatingMode = OperatingMode.ACTIVE

    # Sub-configs
    routing: RoutingConfig = field(default_factory=RoutingConfig)
    model: ModelConfig = field(default_factory=ModelConfig)

    # Paths
    policy_path: str = "policies/default.yaml"
    audit_db_path: str = "warden_audit.db"
    rag_db_path: str = "warden_rag_db"
    attack_samples_path: str = "attack_samples"

    # Feature flags
    enable_camel: bool = False      # CaMeL dual-LLM split (DESCOPED — capability tracker still works via orchestrator)
    enable_rag: bool = True         # Use RAG augmentation for Tier 2
    enable_memory: bool = True      # Use pattern memory shortcuts
    enable_batch: bool = True       # Use batch scheduler for GPU calls

    @classmethod
    def from_env(cls) -> "WardenConfig":
        """Load configuration from environment variables."""
        config = cls()
        if model_path := os.environ.get("WARDEN_MODEL_PATH"):
            config.model.llm_model_path = model_path
        if endpoint := os.environ.get("WARDEN_TOKENFACTORY_ENDPOINT"):
            config.model.tokenfactory_endpoint = endpoint
        if api_key := os.environ.get("WARDEN_TOKENFACTORY_API_KEY"):
            config.model.tokenfactory_api_key = api_key
        if policy := os.environ.get("WARDEN_POLICY"):
            config.policy_path = policy
        if mode := os.environ.get("WARDEN_MODE"):
            config.mode = OperatingMode(mode)
        if auto_block := os.environ.get("WARDEN_AUTO_BLOCK"):
            config.routing.auto_block = float(auto_block)
        if tier2_timeout := os.environ.get("WARDEN_TIER2_TIMEOUT"):
            config.routing.tier2_timeout_s = float(tier2_timeout)

        # ROCm optimization overrides (env-friendly for Docker/cloud)
        if n_ctx := os.environ.get("WARDEN_LLM_N_CTX"):
            config.model.llm_n_ctx = int(n_ctx)
        if gpu_layers := os.environ.get("WARDEN_LLM_N_GPU_LAYERS"):
            try:
                config.model.llm_n_gpu_layers = int(gpu_layers)
            except ValueError:
                config.model.llm_n_gpu_layers = -1  # accept "-1"
        if gpu_layers_fallback := os.environ.get("WARDEN_LLM_N_GPU_LAYERS_FALLBACK"):
            config.model.llm_n_gpu_layers_fallback = int(gpu_layers_fallback)
        if kv_type := os.environ.get("WARDEN_LLM_KV_CACHE_TYPE"):
            config.model.llm_kv_cache_type = kv_type
        if auto_quant := os.environ.get("WARDEN_LLM_AUTO_QUANT"):
            config.model.llm_auto_quant = auto_quant.lower() in ("1", "true", "yes")
        if seed := os.environ.get("WARDEN_LLM_SEED"):
            config.model.llm_seed = int(seed)
        if warmup := os.environ.get("WARDEN_LLM_WARMUP"):
            config.model.llm_warmup_on_load = warmup.lower() in ("1", "true", "yes")
        if flash := os.environ.get("WARDEN_LLM_FLASH_ATTN"):
            config.model.llm_flash_attn = flash.lower() in ("1", "true", "yes")
        if n_batch := os.environ.get("WARDEN_LLM_N_BATCH"):
            config.model.llm_n_batch = int(n_batch)

        # Advanced ROCm knobs
        if rope_base := os.environ.get("WARDEN_LLM_ROPE_FREQ_BASE"):
            config.model.llm_rope_freq_base = float(rope_base)
        if rope_scale := os.environ.get("WARDEN_LLM_ROPE_FREQ_SCALE"):
            config.model.llm_rope_freq_scale = float(rope_scale)
        if main_gpu := os.environ.get("WARDEN_LLM_MAIN_GPU"):
            config.model.llm_main_gpu = int(main_gpu)
        if tensor_split := os.environ.get("WARDEN_LLM_TENSOR_SPLIT"):
            config.model.llm_tensor_split = tensor_split
        if mmap := os.environ.get("WARDEN_LLM_USE_MMAP"):
            config.model.llm_use_mmap = mmap.lower() in ("1", "true", "yes")
        if mlock := os.environ.get("WARDEN_LLM_USE_MLOCK"):
            config.model.llm_use_mlock = mlock.lower() in ("1", "true", "yes")
        if cache_prompt := os.environ.get("WARDEN_LLM_CACHE_PROMPT"):
            config.model.llm_cache_prompt = cache_prompt.lower() in ("1", "true", "yes")
        if split_mode := os.environ.get("WARDEN_LLM_SPLIT_MODE"):
            config.model.llm_split_mode = split_mode
        if wait_load := os.environ.get("WARDEN_LLM_WAIT_MODEL_LOAD"):
            config.model.llm_wait_model_load = wait_load.lower() in ("1", "true", "yes")
        if n_threads_batch := os.environ.get("WARDEN_LLM_N_THREADS_BATCH"):
            try:
                config.model.llm_n_threads_batch = int(n_threads_batch)
            except ValueError:
                pass  # keep default 0 (mirror n_threads)

        # Feature flags
        for flag, attr in [
            ("WARDEN_ENABLE_CAMEL", "enable_camel"),
            ("WARDEN_ENABLE_RAG", "enable_rag"),
            ("WARDEN_ENABLE_MEMORY", "enable_memory"),
            ("WARDEN_ENABLE_BATCH", "enable_batch"),
        ]:
            if val := os.environ.get(flag):
                setattr(config, attr, val.lower() in ("1", "true", "yes"))
        return config
