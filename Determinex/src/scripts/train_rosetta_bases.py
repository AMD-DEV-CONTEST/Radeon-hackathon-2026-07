"""
train_rosetta_bases.py — Rosetta Stone v1 Training Script
==========================================================
Runs on RunPod A100 (80GB). ~3-5 hours end to end.

Strategy: Sequential Extraction → Joint MLP Training
  Phase A: Load each base model one at a time, extract input embeddings, save to disk.
           Peak VRAM during extraction: one model at a time (~14-16GB fp16 for 7B).
  Phase B: Load all saved embeddings (CPU RAM), train MLP encoder/decoder pairs.
           Peak VRAM during training: tiny (MLPs are <10M params total).

Communication model: trains on INPUT EMBEDDINGS (embedding lookup table output, layer 0).
This is consistent with v1 soft prefix injection — training and inference use the same
representation. Mid-layer hidden states are Phase 3.

Loss: Pure InfoNCE between model pairs. No external anchor model.
Same prompt through all 5 bases → align in Rosetta space.
Different prompts → push apart.

Output: /workspace/outputs/rosetta_v1.pt — sealed (SHA256 + chmod 444)

Usage (on RunPod):
  python3 train_rosetta_bases.py
  python3 train_rosetta_bases.py --data-dir /workspace/data --out-dir /workspace/outputs
  python3 train_rosetta_bases.py --skip-extraction  # if embeddings already saved
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import random
import stat
import sys
import time
from pathlib import Path

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.optim import AdamW

# ─────────────────────────────────────────────────────────────────────────────
# Base Model Registry
# ─────────────────────────────────────────────────────────────────────────────

# One representative per architecture family.
# Chosen for: wide adoption, open weights, <8B for sequential A100 fit.
BASE_MODELS = {
    "llama": {
        "hf_id": "meta-llama/Llama-3.1-8B-Instruct",
        "dim": 4096,
        "gated": True,  # HF license required: huggingface.co/meta-llama/Llama-3.1-8B-Instruct
        "embed_path": "model.embed_tokens",
        "vram_gb": 16,  # fp16, fits on 20GB pod with cache cleanup
    },
    "mistral": {
        "hf_id": "mistralai/Mistral-7B-Instruct-v0.3",
        "dim": 4096,
        "gated": False,  # Apache 2.0 — openly downloadable, no license gate
        "embed_path": "model.embed_tokens",
        "vram_gb": 15,
    },
    "qwen2": {
        "hf_id": "Qwen/Qwen2.5-7B-Instruct",
        "dim": 3584,
        "gated": False,
        "embed_path": "model.embed_tokens",
        "vram_gb": 15,
    },
    "phi3": {
        "hf_id": "microsoft/Phi-3-mini-4k-instruct",
        "dim": 3072,
        "gated": False,
        "embed_path": "model.embed_tokens",
        "vram_gb": 8,
    },
    # DeepSeek architecture family representative.
    # DeepSeek-Coder-V2-Lite is a 16B MoE (~30GB fp16) — does NOT fit 20GB pod volume.
    # Use deepseek-coder-6.7b-instruct instead: same DeepSeek architectural dialect, ~13GB fp16.
    # Alternative: deepseek-coder-1.3b-instruct (<3GB) if volume is still tight.
    "deepseek2": {
        "hf_id": "deepseek-ai/deepseek-coder-6.7b-instruct",
        "dim": 4096,
        "gated": False,
        "embed_path": "model.embed_tokens",
        "vram_gb": 13,
    },
    # Qwen2-1.5B: same architecture family as qwen2-7B but hidden_dim=1536.
    # Required for Rosetta projection with the determinex-engineer GGUF (Qwen2-1.5B).
    # Without this, Phase 3 injection falls back to direct self-injection because
    # the 1536-dim builder doesn't match the qwen2-7B entry (dim=3584).
    "qwen2_1b5": {
        "hf_id": "Qwen/Qwen2.5-1.5B-Instruct",
        "dim": 1536,
        "gated": False,
        "embed_path": "model.embed_tokens",
        "vram_gb": 3,
    },
    # Qwen2-3B: same qwen2 family but hidden_dim=2048.
    # Required for Rosetta projection with determinex-observer GGUFs (Qwen2.5-Coder-3B).
    # Confirmed from GGUF header: general.architecture=qwen2, embedding_length=2048.
    "qwen2_3b": {
        "hf_id": "Qwen/Qwen2.5-Coder-3B-Instruct",
        "dim": 2048,
        "gated": False,
        "embed_path": "model.embed_tokens",
        "vram_gb": 6,
    },
}

D_ROSETTA = 4096  # Universal hub dimension
TEMPERATURE = 0.10  # InfoNCE temperature. 0.07 is standard for vision, but creates extreme
# gradients for architecturally similar pairs (llama/mistral both at d=4096)
# causing them to be pushed to opposite Rosetta-space hemispheres.
# 0.10 is warmer/softer — allows the harder same-family pairs to converge.
MAX_SEQ_LEN = 128  # Truncation length for embedding extraction (prompts only)
EXTRACT_BATCH = 64  # Prompts per extraction batch
TRAIN_BATCH = 256  # Pairs per training batch
EPOCHS = 15
LR = 3e-4

# Synthetic plan fragments — cover what the Architect role produces.
# These teach the Rosetta Space to encode PLAN semantics, not just code.
SYNTHETIC_PLANS = [
    "Step 1: implement the data structure using Arc<Mutex<T>> for thread-safe shared ownership.",
    "Step 2: write the acquisition logic using RAII guard pattern to prevent lock leaks.",
    "Step 3: implement error handling with Result<T, E> and propagate with the ? operator.",
    "Step 4: add exponential backoff retry logic, cap at 5 attempts, log each failure.",
    "Step 5: write unit tests for the happy path and the mutex poison error case.",
    "Step 1: define the Go struct with exported fields and json tags for serialization.",
    "Step 2: implement the interface methods with proper error returns, no panic allowed.",
    "Step 3: add goroutine-safe access using sync.RWMutex, prefer RLock for reads.",
    "Step 4: write the HTTP handler, validate input, return structured JSON errors.",
    "Step 5: add context cancellation support to all blocking operations.",
    "Step 1: define Python dataclass with type annotations for all fields.",
    "Step 2: implement async generator for streaming response chunks from the API.",
    "Step 3: add retry decorator with exponential backoff, max 3 attempts.",
    "Step 4: write the validation function, raise ValueError with descriptive message.",
    "Step 5: implement the context manager for resource cleanup on exit or exception.",
    "Step 1: create the function signature with explicit parameter types and return type.",
    "Step 2: implement input validation at the system boundary, reject invalid inputs early.",
    "Step 3: write the core logic with no side effects, pure function where possible.",
    "Step 4: add comprehensive error handling, no silent failures.",
    "Step 5: compile and test with edge cases including empty input and boundary values.",
    "implement concurrent data processing pipeline with worker pool pattern",
    "write thread-safe cache with TTL expiration and LRU eviction",
    "build async HTTP client with connection pooling and timeout handling",
    "implement binary search tree with proper memory management",
    "create state machine for order processing workflow with transitions",
    "design event-driven architecture with publish-subscribe pattern",
    "implement rate limiter using token bucket algorithm",
    "write recursive descent parser for expression grammar",
    "build merkle tree for data integrity verification",
    "implement consensus protocol with quorum-based voting",
]

# ─────────────────────────────────────────────────────────────────────────────
# Pre-flight Checks
# ─────────────────────────────────────────────────────────────────────────────


def preflight(data_dir: Path, out_dir: Path) -> str:
    """Run pre-flight checks. Returns HF token. Exits on failure."""
    print("=" * 60)
    print("PRE-FLIGHT CHECKS")
    print("=" * 60)

    # HF token
    hf_token = os.environ.get("HF_TOKEN", "")
    if not hf_token:
        print("  WARNING  : HF_TOKEN not set — gated models (llama, mistral) will be skipped.")
        print("             Ungated arches (qwen2_1b5, qwen2, phi3, deepseek2) proceed normally.")
    else:
        print(f"  HF_TOKEN : {'*' * 8}{hf_token[-4:]}  OK")

    # GPU
    if not torch.cuda.is_available():
        print("ERROR: No CUDA GPU detected. This script requires a GPU.")
        sys.exit(1)
    gpu_name = torch.cuda.get_device_name(0)
    vram_gb = torch.cuda.get_device_properties(0).total_memory / 1e9
    print(f"  GPU      : {gpu_name}  ({vram_gb:.0f} GB VRAM)  OK")
    if vram_gb < 20:
        print("  WARNING  : <20GB VRAM. Extraction will use CPU offload.")

    # Disk space (workspace)
    import shutil

    free_gb = shutil.disk_usage("/workspace").free / 1e9
    print(f"  Disk /ws : {free_gb:.0f} GB free")
    if free_gb < 80:
        print("  WARNING  : <80GB free. Model downloads may fail mid-stream.")

    # Data directory
    if not data_dir.exists():
        print(f"  WARNING  : data-dir {data_dir} not found. Using synthetic data only.")
    else:
        jsonl_files = list(data_dir.glob("*.jsonl"))
        print(f"  Data     : {data_dir}  ({len(jsonl_files)} JSONL files)  OK")

    # Output directory
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"  Out dir  : {out_dir}  OK")

    # HF auth test (only when token provided)
    if hf_token:
        print("  Testing HF authentication...", end=" ", flush=True)
        try:
            from huggingface_hub import HfApi

            api = HfApi(token=hf_token)
            api.whoami()
            print("OK")
        except Exception as e:
            print(f"FAIL\n  ERROR: {e}")
            sys.exit(1)
    else:
        print("  HF auth   : skipped (no token — ungated-only mode)")

    print()
    return hf_token


def check_gated_access(hf_token: str) -> None:
    """
    Verify the user has DOWNLOAD access (not just metadata access) for gated models.

    api.model_info() is a false positive — it returns metadata even without license acceptance.
    The actual test is attempting to download a tiny config file. A 403 here means the
    license has NOT been accepted on the HuggingFace website.
    """
    import tempfile

    from huggingface_hub import hf_hub_download

    print("Checking gated model download access:")
    gated = [(arch, info) for arch, info in BASE_MODELS.items() if info["gated"]]
    failed = []

    for arch, info in gated:
        hf_id = info["hf_id"]
        try:
            # Try downloading config.json (tiny, ~1KB) to a temp dir — real access probe
            with tempfile.TemporaryDirectory() as tmp:
                hf_hub_download(
                    repo_id=hf_id,
                    filename="config.json",
                    token=hf_token,
                    local_dir=tmp,
                )
            print(f"  OK   {hf_id}")
        except Exception as e:
            err = str(e)
            if "403" in err or "Gated" in err or "gated" in err or "not in the authorized" in err:
                print(f"  FAIL {hf_id}  — license NOT accepted")
                print(f"       Visit: https://huggingface.co/{hf_id}")
            else:
                print(f"  FAIL {hf_id}  — {err[:120]}")
            failed.append(hf_id)

    if failed:
        print(
            f"\nAccept the license for {len(failed)} model(s) above on huggingface.co, then re-run."
        )
        sys.exit(1)
    print()


# ─────────────────────────────────────────────────────────────────────────────
# Training Data Loading
# ─────────────────────────────────────────────────────────────────────────────


def load_training_prompts(data_dir: Path) -> list[str]:
    """
    Load text prompts from:
      1. curriculum.jsonl — extract prompt_templates arrays
      2. gap_*.jsonl — extract user message content (chat format)
      3. SYNTHETIC_PLANS — plan/intent fragments

    Returns deduplicated list of plain text strings.
    """
    prompts: list[str] = []

    # JSONL files
    if data_dir.exists():
        for fpath in sorted(data_dir.glob("*.jsonl")):
            count_before = len(prompts)
            with open(fpath, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    # curriculum.jsonl format: {prompt_templates: [...]}
                    if "prompt_templates" in obj:
                        for tmpl in obj["prompt_templates"]:
                            if isinstance(tmpl, str) and tmpl.strip():
                                prompts.append(tmpl.strip())

                    # gap/SFT format: {messages: [{role, content}, ...]}
                    elif "messages" in obj:
                        for msg in obj["messages"]:
                            if msg.get("role") == "user":
                                content = msg.get("content", "").strip()
                                if content:
                                    prompts.append(content)

                    # Distilled format: {user: "...", assistant: "...", system: "..."}
                    elif "user" in obj:
                        content = obj["user"].strip() if isinstance(obj["user"], str) else ""
                        if content:
                            prompts.append(content)

                    # Simple {instruction: ...} format
                    elif "instruction" in obj:
                        content = obj["instruction"].strip()
                        if content:
                            prompts.append(content)

            loaded = len(prompts) - count_before
            print(f"  {fpath.name}: {loaded} prompts")

    # Synthetic plan fragments
    prompts.extend(SYNTHETIC_PLANS)
    print(f"  Synthetic plans: {len(SYNTHETIC_PLANS)} prompts")

    # Deduplicate preserving order
    seen = set()
    unique = []
    for p in prompts:
        key = p[:100]
        if key not in seen:
            seen.add(key)
            unique.append(p)

    print(f"  Total unique prompts: {len(unique)}")
    if len(unique) < 50:
        print("  WARNING: Very few prompts. Rosetta alignment will be weak. Add more data.")
    return unique


# ─────────────────────────────────────────────────────────────────────────────
# Phase A — Sequential Embedding Extraction
# ─────────────────────────────────────────────────────────────────────────────


def _get_embed_layer(model, embed_path: str) -> nn.Module:
    """Traverse dotted attribute path to get the embedding layer."""
    obj = model
    for part in embed_path.split("."):
        obj = getattr(obj, part)
    return obj


def extract_embeddings(
    arch: str,
    model_info: dict,
    prompts: list[str],
    hf_token: str,
    save_path: Path,
    device: str = "cuda",
) -> torch.Tensor:
    """
    Load one base model, extract mean-pooled input embeddings for all prompts, save.

    Mean pooling over token dimension (not CLS, not last token) handles tokenizer
    differences across model families — same prompt → same-length output regardless
    of how many tokens each family produces.

    Returns: [N, dim] float16 tensor, also saved to save_path.
    """
    from transformers import AutoModelForCausalLM, AutoTokenizer

    hf_id = model_info["hf_id"]
    dim = model_info["dim"]

    print(f"\n{'=' * 60}")
    print(f"EXTRACTION: {arch.upper()}  ({hf_id})")
    print(f"{'=' * 60}")

    # Load tokenizer
    print("Loading tokenizer...", flush=True)
    _tok = hf_token or None  # empty string → None (avoids "Bearer " header)
    tokenizer = AutoTokenizer.from_pretrained(hf_id, token=_tok, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    # Load model — CPU if not enough VRAM, GPU if available
    vram_gb = (
        torch.cuda.get_device_properties(0).total_memory / 1e9 if torch.cuda.is_available() else 0
    )
    use_gpu = vram_gb >= 16

    print(f"Loading model on {'GPU' if use_gpu else 'CPU'} (fp16)...", flush=True)
    t0 = time.time()
    model = AutoModelForCausalLM.from_pretrained(
        hf_id,
        token=_tok,
        torch_dtype=torch.float16,
        device_map="auto" if use_gpu else "cpu",
        trust_remote_code=True,
        low_cpu_mem_usage=True,
    )
    model.eval()
    print(f"  Loaded in {time.time() - t0:.0f}s", flush=True)

    embed_layer = _get_embed_layer(model, model_info["embed_path"])
    embed_device = next(embed_layer.parameters()).device

    all_embeddings: list[torch.Tensor] = []
    n_batches = (len(prompts) + EXTRACT_BATCH - 1) // EXTRACT_BATCH

    print(f"Extracting {len(prompts)} prompts in {n_batches} batches...", flush=True)
    t0 = time.time()

    with torch.no_grad():
        for i in range(0, len(prompts), EXTRACT_BATCH):
            batch_prompts = prompts[i : i + EXTRACT_BATCH]

            tokens = tokenizer(
                batch_prompts,
                return_tensors="pt",
                padding=True,
                truncation=True,
                max_length=MAX_SEQ_LEN,
            )
            input_ids = tokens["input_ids"].to(embed_device)
            attention_mask = tokens["attention_mask"].to(embed_device)

            # Input embedding lookup — Layer 0 output, before positional encoding
            # Shape: [batch, seq_len, dim]
            embeddings = embed_layer(input_ids).float()

            # Mean pool over token dimension (masked — exclude padding tokens)
            mask_expanded = attention_mask.unsqueeze(-1).float()
            pooled = (embeddings * mask_expanded).sum(dim=1) / mask_expanded.sum(dim=1).clamp(min=1)
            # Shape: [batch, dim] — fixed size regardless of tokenizer

            all_embeddings.append(pooled.cpu().to(torch.float16))

            if (i // EXTRACT_BATCH + 1) % 10 == 0:
                elapsed = time.time() - t0
                done = i + len(batch_prompts)
                eta = elapsed / done * (len(prompts) - done)
                print(f"  [{done}/{len(prompts)}]  ETA: {eta:.0f}s", flush=True)

    result = torch.cat(all_embeddings, dim=0)  # [N, dim]
    assert result.shape == (len(prompts), dim), (
        f"Shape mismatch: expected ({len(prompts)}, {dim}), got {result.shape}"
    )

    # ── Extract special token embeddings (EOS/BOS/PAD) ───────────────────
    # These are saved alongside prompt embeddings for use in EOS repulsion loss.
    # During inference, decoder outputs that land near these coordinates cause
    # the target model to misinterpret the prefix as a sequence delimiter.
    special_embeds: list[torch.Tensor] = []
    special_names: list[str] = []
    seen_ids: set[int] = set()
    for sname, tok_id in [
        ("eos", tokenizer.eos_token_id),
        ("bos", getattr(tokenizer, "bos_token_id", None)),
        (
            "pad",
            tokenizer.pad_token_id if tokenizer.pad_token_id != tokenizer.eos_token_id else None,
        ),
    ]:
        if tok_id is not None and tok_id not in seen_ids:
            seen_ids.add(tok_id)
            with torch.no_grad():
                tid_tensor = torch.tensor([tok_id], dtype=torch.long).to(embed_device)
                s_embed = embed_layer(tid_tensor).float().cpu().to(torch.float16)  # [1, dim]
            special_embeds.append(s_embed)
            special_names.append(sname)

    special_tensor = (
        torch.cat(special_embeds, dim=0)
        if special_embeds
        else torch.zeros(0, dim, dtype=torch.float16)
    )
    print(f"  Special tokens extracted: {special_names}  shape={special_tensor.shape}", flush=True)

    # ── #24 Extract full vocabulary embedding matrix ─────────────────────
    # Used during training to anchor decoder outputs near real token coordinates,
    # preventing "void space" activations that destabilize target model forward passes.
    vocab_embeds = embed_layer.weight.data.clone().cpu().to(torch.float16)  # [vocab_size, dim]
    print(
        f"  Vocabulary embeddings: shape={vocab_embeds.shape}  ({vocab_embeds.numel() * 2 / 1e6:.0f} MB)",
        flush=True,
    )

    # ── #11 MoE router weight extraction ─────────────────────────────────
    # If this is an MoE model, extract the gating router weight matrix from
    # the first MoE layer. Used during training to penalize decoder outputs
    # that would route to incorrect expert subspaces.
    router_weight = None
    n_experts = getattr(getattr(model, "config", None), "num_local_experts", 0) or 0
    if n_experts == 0:
        n_experts = getattr(getattr(model, "config", None), "n_routed_experts", 0) or 0
    if n_experts > 0:
        print(f"  MoE detected: {n_experts} experts. Extracting router weights...", flush=True)
        try:
            for layer in model.model.layers:
                # Mixtral / Qwen-MoE style: block_sparse_moe.gate
                if hasattr(layer, "block_sparse_moe") and hasattr(layer.block_sparse_moe, "gate"):
                    router_weight = (
                        layer.block_sparse_moe.gate.weight.data.clone().cpu().to(torch.float16)
                    )
                    break
                # DeepSeek-V2 style: mlp.gate
                if hasattr(layer, "mlp") and hasattr(layer.mlp, "gate"):
                    gate = layer.mlp.gate
                    if hasattr(gate, "weight"):
                        router_weight = gate.weight.data.clone().cpu().to(torch.float16)
                        break
            if router_weight is not None:
                print(
                    f"  Router weight: shape={router_weight.shape}  ({n_experts} experts x {router_weight.shape[1]} dim)",
                    flush=True,
                )
            else:
                print(
                    f"  WARNING: MoE detected ({n_experts} experts) but router weight not found in expected locations.",
                    flush=True,
                )
        except Exception as e:
            print(f"  WARNING: Failed to extract MoE router weight: {e}", flush=True)
    else:
        print("  Dense model (no MoE).", flush=True)

    # Save
    save_path.parent.mkdir(parents=True, exist_ok=True)
    save_dict = {
        "arch": arch,
        "dim": dim,
        "embeddings": result,
        "special_embeds": special_tensor,  # [K, dim] — EOS/BOS/PAD vectors
        "special_names": special_names,
        "vocab_embeds": vocab_embeds,  # [vocab_size, dim] — #24 void space anchor
    }
    if router_weight is not None:
        save_dict["router_weight"] = router_weight  # [n_experts, dim] — #11 MoE gating
        save_dict["n_experts"] = n_experts
    torch.save(save_dict, str(save_path))
    size_mb = save_path.stat().st_size / 1e6
    print(f"  Saved: {save_path}  ({size_mb:.0f} MB)  shape={result.shape}", flush=True)

    # Free GPU memory before loading next model
    del model, embed_layer
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        print(f"  VRAM freed. {torch.cuda.memory_allocated() / 1e9:.2f} GB remaining.", flush=True)

    return result


def run_extraction_phase(
    prompts: list[str],
    hf_token: str,
    cache_dir: Path,
    arches: list[str] | None = None,
) -> tuple[
    dict[str, torch.Tensor],
    dict[str, torch.Tensor],
    dict[str, torch.Tensor],
    dict[str, torch.Tensor],
]:
    """
    Extract embeddings for all base models sequentially.
    Skips models whose cache files already exist.
    Returns (embeddings, special_embeds, vocab_embeds, router_weights) where:
      embeddings:     {arch: [N, dim]}  — mean-pooled prompt embeddings
      special_embeds: {arch: [K, dim]}  — EOS/BOS/PAD token embeddings (for repulsion training)
      vocab_embeds:   {arch: [vocab_size, dim]}  — full vocabulary embeddings (#24 void space anchor)
      router_weights: {arch: [n_experts, dim]}   — MoE router weights (#11 expert gating)
    """
    target_arches = arches or list(BASE_MODELS.keys())
    results: dict[str, torch.Tensor] = {}
    specials: dict[str, torch.Tensor] = {}
    vocabs: dict[str, torch.Tensor] = {}
    routers: dict[str, torch.Tensor] = {}

    for arch in target_arches:
        # Skip gated models when no HF_TOKEN is available
        if not hf_token and BASE_MODELS[arch].get("gated", False):
            print(f"\nSkipping {arch} (gated model, no HF_TOKEN)")
            continue

        save_path = cache_dir / f"{arch}_embeddings.pt"

        if save_path.exists():
            print(f"\nLoading cached embeddings: {arch} ({save_path})")
            ckpt = torch.load(str(save_path), map_location="cpu", weights_only=True)
            emb = ckpt["embeddings"]
            expected_dim = BASE_MODELS[arch]["dim"]
            if emb.shape[1] != expected_dim:
                print(f"  WARNING: dim mismatch ({emb.shape[1]} vs {expected_dim}). Re-extracting.")
            elif emb.shape[0] != len(prompts):
                print(
                    f"  WARNING: prompt count mismatch ({emb.shape[0]} vs {len(prompts)}). Re-extracting."
                )
            else:
                results[arch] = emb.float()
                # Load special token embeddings if present (older caches may not have them)
                if "special_embeds" in ckpt and ckpt["special_embeds"].shape[0] > 0:
                    specials[arch] = ckpt["special_embeds"].float()
                    print(f"  {arch}: {emb.shape}  special={ckpt['special_embeds'].shape}  OK")
                else:
                    print(
                        f"  {arch}: {emb.shape}  (no special embeds — re-run without --skip-extraction to capture them)"
                    )
                # Load vocab embeddings if present (#24 void space anchor)
                if "vocab_embeds" in ckpt:
                    vocabs[arch] = ckpt["vocab_embeds"].float()
                # Load MoE router weights if present (#11 expert gating)
                if "router_weight" in ckpt:
                    routers[arch] = ckpt["router_weight"].float()
                continue

        result = extract_embeddings(
            arch=arch,
            model_info=BASE_MODELS[arch],
            prompts=prompts,
            hf_token=hf_token,
            save_path=save_path,
        ).float()
        results[arch] = result

        # Load special embeds from the just-written cache file
        ckpt2 = torch.load(str(save_path), map_location="cpu", weights_only=True)
        if "special_embeds" in ckpt2 and ckpt2["special_embeds"].shape[0] > 0:
            specials[arch] = ckpt2["special_embeds"].float()
        # Load vocab embeddings from the just-written cache file (#24)
        if "vocab_embeds" in ckpt2:
            vocabs[arch] = ckpt2["vocab_embeds"].float()
        # Load MoE router weights from the just-written cache file (#11)
        if "router_weight" in ckpt2:
            routers[arch] = ckpt2["router_weight"].float()

        # Free HF download cache after extraction — each 7B model is ~15GB cached.
        # Embeddings are saved to cache_dir; the downloaded weights are no longer needed.
        _clear_hf_model_cache(BASE_MODELS[arch]["hf_id"])

    return results, specials, vocabs, routers


def _clear_hf_model_cache(hf_id: str) -> None:
    """Remove downloaded model weights from HuggingFace hub cache to reclaim disk."""
    import shutil

    cache_root = Path.home() / ".cache" / "huggingface" / "hub"
    # HF hub stores models as models--org--name
    model_dir_name = "models--" + hf_id.replace("/", "--")
    model_cache = cache_root / model_dir_name
    if model_cache.exists():
        size_gb = sum(f.stat().st_size for f in model_cache.rglob("*") if f.is_file()) / 1e9
        shutil.rmtree(model_cache, ignore_errors=True)
        print(f"  Cleared HF cache for {hf_id} ({size_gb:.1f} GB freed)", flush=True)


# ─────────────────────────────────────────────────────────────────────────────
# MLP Architecture (must stay in sync with determinex_rosetta.py:build_mlp)
# ─────────────────────────────────────────────────────────────────────────────


def build_mlp(d_in: int, d_out: int, d_hidden: int | None = None) -> nn.Module:
    """
    2-layer MLP: d_in → d_hidden (GELU + LayerNorm) → d_out
    KEEP IN SYNC with determinex_rosetta.py:build_mlp — same architecture, same init.
    """
    d_h = d_hidden or max(d_in, d_out)
    net = nn.Sequential(
        nn.Linear(d_in, d_h, bias=False),
        nn.GELU(),
        nn.LayerNorm(d_h),
        nn.Linear(d_h, d_out, bias=False),
    )
    nn.init.xavier_uniform_(net[0].weight, gain=0.02)
    nn.init.xavier_uniform_(net[3].weight, gain=0.02)
    return net


# ─────────────────────────────────────────────────────────────────────────────
# Phase B — InfoNCE Training
# ─────────────────────────────────────────────────────────────────────────────


def infonce_loss(
    h_a: torch.Tensor,
    h_b: torch.Tensor,
    temperature: float = TEMPERATURE,
) -> torch.Tensor:
    """
    Symmetric InfoNCE contrastive loss.

    h_a: [N, D_ROSETTA] — N prompts from model A, projected to Rosetta space
    h_b: [N, D_ROSETTA] — same N prompts from model B, projected to Rosetta space

    Positives: (h_a[i], h_b[i]) — same prompt through different architectures
    Negatives: (h_a[i], h_b[j]) for all i≠j — different prompts

    Symmetric: both directions (A→B and B→A) contribute to the loss.
    """
    N = h_a.shape[0]

    # L2 normalize for cosine similarity
    h_a = F.normalize(h_a, dim=-1)
    h_b = F.normalize(h_b, dim=-1)

    # Similarity matrix [N, N] — diagonal = positive pairs
    sim = torch.matmul(h_a, h_b.T) / temperature

    # Labels: diagonal indices are the correct positive pairs
    labels = torch.arange(N, device=h_a.device)

    # Symmetric cross-entropy loss (both directions)
    loss = (F.cross_entropy(sim, labels) + F.cross_entropy(sim.T, labels)) / 2
    return loss


def eos_repulsion_loss(
    decoder_output: torch.Tensor,  # [B, dim_target] — what the decoder injects into target model
    special_embeds: torch.Tensor,  # [K, dim_target] — EOS/BOS/PAD embeddings of target model
    margin: float = 0.3,
) -> torch.Tensor:
    """
    Push decoder outputs away from special token embedding coordinates in the TARGET model's space.

    Motivation: when decoder_B(encoder_A(h_A)) is injected as a soft prefix into model B,
    model B's attention should NOT confuse it with model B's EOS/BOS/PAD tokens.
    If the decoder output lands geometrically near EOS coordinates, model B may terminate
    generation early or hallucinate end-of-sequence behavior.

    Loss = mean(relu(margin - cosine_distance(decoder_out, special_embed)))
    Only penalises when the distance drops below `margin`. No penalty when already far apart.
    margin=0.3 means vectors must be at least 30% of cosine distance from special tokens.
    """
    if special_embeds.shape[0] == 0:
        return torch.tensor(0.0, device=decoder_output.device)

    dec_norm = F.normalize(decoder_output, dim=-1)  # [B, dim]
    spec_norm = F.normalize(special_embeds.to(decoder_output.device), dim=-1)  # [K, dim]
    cos_sim = torch.matmul(dec_norm, spec_norm.T)  # [B, K]
    cos_dist = 1.0 - cos_sim  # [B, K]
    return F.relu(margin - cos_dist).mean()


def vocab_anchor_loss(
    decoder_output: torch.Tensor,  # [B, dim_target] — decoder output in target model's space
    vocab_norm: torch.Tensor,  # [vocab_size, dim_target] — L2-normalized vocab embeddings
    threshold: float = 0.5,
) -> torch.Tensor:
    """
    #24 Void Space Anchor: penalize decoder outputs far from all real token embeddings.

    If the decoder projects a Rosetta vector into a coordinate that is geometrically
    distant from every token in the target model's vocabulary, the target model has
    never seen this region during pretraining. Processing such coordinates causes
    activation instability in the forward pass.

    Loss = mean(relu(threshold - max_cosine_sim(decoder_out, all_vocab_tokens)))
    Only penalizes when decoder output is farther than `threshold` from the nearest
    real token embedding. No penalty when already close to a real coordinate.
    """
    dec_norm = F.normalize(decoder_output, dim=-1)  # [B, dim]
    cos_sim = torch.matmul(dec_norm, vocab_norm.T)  # [B, vocab_size]
    max_sim = cos_sim.max(dim=-1).values  # [B]
    return F.relu(threshold - max_sim).mean()


def expert_gating_loss(
    decoder_output: torch.Tensor,  # [B, dim_target]
    router_weight: torch.Tensor,  # [n_experts, dim_target] — MoE router weight matrix
    concentration_target: float = 2.0,
) -> torch.Tensor:
    """
    #11 MoE Router Blindness: penalize decoder outputs with diffuse expert routing.

    For MoE models, the first FFN layer routes tokens to specific experts based on
    dot-product similarity with the router weight matrix. If the decoder output
    activates all experts equally (high entropy routing), the model's MoE gate
    produces an unfocused mixture, degrading generation quality.

    Loss = relu(entropy(softmax(output @ router.T)) - concentration_target)
    Only penalizes when routing entropy exceeds the target. Lower entropy = more
    concentrated expert selection = better.

    concentration_target=2.0 allows moderate spread across ~7 experts (in a 64-expert
    model entropy is log(64) ~= 4.16, so 2.0 allows ~4-5 active experts).
    """
    logits = F.linear(
        F.normalize(decoder_output, dim=-1), F.normalize(router_weight, dim=-1)
    )  # [B, n_experts]
    probs = F.softmax(logits / 0.1, dim=-1)  # sharp temperature for routing
    log_probs = (probs + 1e-8).log()
    entropy = -(probs * log_probs).sum(dim=-1).mean()  # mean entropy across batch
    return F.relu(entropy - concentration_target)


def train_mlp_projectors(
    embeddings: dict[str, torch.Tensor],
    out_path: Path,
    special_embeds: dict[str, torch.Tensor] | None = None,
    vocab_embeds: dict[str, torch.Tensor] | None = None,
    router_weights: dict[str, torch.Tensor] | None = None,
    device: str = "cuda",
    epochs: int = EPOCHS,
    lr: float = LR,
) -> None:
    """
    Train MLP encoder/decoder pairs for all base architectures.

    Strategy: for each pair (arch_a, arch_b), train both encoders to project
    their embeddings into a shared Rosetta space where same-prompt embeddings
    from different models are close, different-prompt embeddings are far.

    All architectures are trained jointly — each encoder contributes to all pairs.
    """
    arches = list(embeddings.keys())
    N = next(iter(embeddings.values())).shape[0]

    print(f"\n{'=' * 60}")
    print(f"TRAINING  {len(arches)} architectures  {N} prompts each")
    print(f"  Arches : {arches}")
    print(f"  Epochs : {epochs}  Batch: {TRAIN_BATCH}  LR: {lr}  Temp: {TEMPERATURE}")
    print(f"{'=' * 60}\n", flush=True)

    # Build encoder (arch → Rosetta) for each architecture
    encoders: dict[str, nn.Module] = {}
    decoders: dict[str, nn.Module] = {}
    for arch in arches:
        dim = BASE_MODELS[arch]["dim"]
        encoders[arch] = build_mlp(dim, D_ROSETTA).to(device)
        decoders[arch] = build_mlp(D_ROSETTA, dim).to(device)

    # Single optimizer over all MLP parameters
    all_params = []
    for arch in arches:
        all_params.extend(encoders[arch].parameters())
        all_params.extend(decoders[arch].parameters())
    optimizer = AdamW(all_params, lr=lr, weight_decay=1e-4)

    # Cosine LR schedule
    total_steps = epochs * ((N + TRAIN_BATCH - 1) // TRAIN_BATCH)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
        optimizer, T_max=total_steps, eta_min=lr * 0.01
    )

    # Move embeddings to device
    emb_gpu = {arch: emb.to(device) for arch, emb in embeddings.items()}

    # ── #16 Scale targets: average L2 norm of raw embeddings per arch ────────
    # Decoder outputs should match this scale so injected tokens look natural
    # to the target model's first normalisation layer (RMSNorm / LayerNorm).
    emb_rms: dict[str, float] = {arch: emb_gpu[arch].norm(dim=-1).mean().item() for arch in arches}
    print(f"  Embedding RMS norms: { {k: f'{v:.2f}' for k, v in emb_rms.items()} }")

    # ── #17 EOS repulsion: move special token embeddings to device ───────────
    special_gpu: dict[str, torch.Tensor] = {}
    if special_embeds:
        for arch, se in special_embeds.items():
            if arch in arches and se.shape[0] > 0:
                special_gpu[arch] = se.to(device)
        if special_gpu:
            print(f"  EOS repulsion active for: {list(special_gpu.keys())}")
        else:
            print("  EOS repulsion: no special embeds available (will skip)")

    # ── #24 Vocabulary anchor: L2-normalize vocab embeddings once ────────────
    vocab_gpu: dict[str, torch.Tensor] = {}
    if vocab_embeds:
        for arch, ve in vocab_embeds.items():
            if arch in arches:
                vocab_gpu[arch] = F.normalize(ve.to(device), dim=-1)
        if vocab_gpu:
            total_mb = sum(v.numel() * 4 / 1e6 for v in vocab_gpu.values())  # float32
            print(
                f"  Vocab anchor active for: {list(vocab_gpu.keys())}  ({total_mb:.0f} MB on device)"
            )
        else:
            print("  Vocab anchor: no vocab embeddings available (will skip)")

    # ── #11 MoE expert gating: move router weights to device ─────────────────
    router_gpu: dict[str, torch.Tensor] = {}
    if router_weights:
        for arch, rw in router_weights.items():
            if arch in arches:
                router_gpu[arch] = rw.to(device)
        if router_gpu:
            print(f"  MoE gating active for: {list(router_gpu.keys())}")
        else:
            print("  MoE gating: no router weights available (all dense models)")

    # Generate all unique architecture pairs for InfoNCE
    pairs = [(a, b) for i, a in enumerate(arches) for b in arches[i + 1 :]]
    print(f"  Training {len(pairs)} arch pairs: {pairs}\n", flush=True)

    best_loss = float("inf")
    best_state: dict | None = None

    for epoch in range(1, epochs + 1):
        epoch_loss = 0.0
        epoch_eos_loss = 0.0
        epoch_scale_loss = 0.0
        epoch_vocab_loss = 0.0
        epoch_expert_loss = 0.0
        n_steps = 0

        # Shuffle indices each epoch
        idx = torch.randperm(N)

        for start in range(0, N, TRAIN_BATCH):
            batch_idx = idx[start : start + TRAIN_BATCH]
            if len(batch_idx) < 4:
                continue  # skip tiny tail batches

            optimizer.zero_grad()
            batch_loss = torch.tensor(0.0, device=device)

            for arch_a, arch_b in pairs:
                h_a_raw = emb_gpu[arch_a][batch_idx]  # [B, dim_a]
                h_b_raw = emb_gpu[arch_b][batch_idx]  # [B, dim_b]

                # Project to Rosetta space
                h_a = encoders[arch_a](h_a_raw)  # [B, D_ROSETTA]
                h_b = encoders[arch_b](h_b_raw)  # [B, D_ROSETTA]

                # ── #20 BF16 precision simulation ────────────────────────────
                # Round-trip through BF16 trains the adapter to produce outputs that
                # survive quantisation noise (GGUF inference runs at BF16 or lower).
                # Applied before loss so the MLP learns to be robust to this truncation.
                h_a = h_a.to(torch.bfloat16).to(torch.float32)
                h_b = h_b.to(torch.bfloat16).to(torch.float32)

                # InfoNCE: align same-prompt across architectures
                loss_fwd = infonce_loss(h_a, h_b)

                # Reconstruction loss: Rosetta → original space (decoder regularization)
                h_a_recon = decoders[arch_a](h_a)
                h_b_recon = decoders[arch_b](h_b)
                loss_recon = (
                    F.mse_loss(h_a_recon, h_a_raw.float()) + F.mse_loss(h_b_recon, h_b_raw.float())
                ) * 0.1  # Small weight — reconstruction is a regularizer, not the objective

                # ── #17 EOS repulsion ────────────────────────────────────────
                # Penalise when decoder_B output is geometrically close to model B's
                # EOS/BOS tokens. At inference these coordinates cause early termination.
                loss_eos = torch.tensor(0.0, device=device)
                if arch_a in special_gpu:
                    loss_eos = loss_eos + eos_repulsion_loss(h_a_recon, special_gpu[arch_a])
                if arch_b in special_gpu:
                    loss_eos = loss_eos + eos_repulsion_loss(h_b_recon, special_gpu[arch_b])
                loss_eos = loss_eos * 0.15  # Weighted: important but secondary to alignment

                # ── #16 RMSNorm scale matching ───────────────────────────────
                # Decoder output scale must match what target model expects at its
                # embedding layer input (RMSNorm/LayerNorm calibrates on real token scales).
                # Penalise when the decoder output's average L2 norm deviates from the
                # observed embedding scale for that architecture.
                pred_rms_a = h_a_recon.norm(dim=-1).mean()
                pred_rms_b = h_b_recon.norm(dim=-1).mean()
                loss_scale = (
                    (pred_rms_a - emb_rms[arch_a]) ** 2 + (pred_rms_b - emb_rms[arch_b]) ** 2
                ) * 0.05

                # ── #21 Gate survival (SiLU/GELU) ───────────────────────────
                # Simulate the first transformer block's activation gate. If the
                # decoder output has mostly negative values, the SiLU gate in the
                # first FFN block will suppress the signal. Penalise strong suppression.
                # Using SiLU as the generic gate (Llama/Mistral/DeepSeek/Qwen all use it).
                gate_a = F.silu(h_a_recon)
                gate_b = F.silu(h_b_recon)
                # Fraction of near-zero outputs after SiLU → proxy for suppression
                suppression = (
                    (gate_a.abs() < 0.01).float().mean() + (gate_b.abs() < 0.01).float().mean()
                ) * 0.5
                loss_gate = suppression * 0.02

                # ── #24 Vocabulary anchor ────────────────────────────────────
                # Penalize decoder outputs landing in "void space" — far from
                # any real token embedding in the target model's vocabulary.
                loss_vocab = torch.tensor(0.0, device=device)
                if arch_a in vocab_gpu:
                    loss_vocab = loss_vocab + vocab_anchor_loss(h_a_recon, vocab_gpu[arch_a])
                if arch_b in vocab_gpu:
                    loss_vocab = loss_vocab + vocab_anchor_loss(h_b_recon, vocab_gpu[arch_b])
                loss_vocab = loss_vocab * 0.05  # Regularizer weight

                # ── #11 MoE expert gating ────────────────────────────────────
                # Penalize decoder outputs that scatter across all expert subspaces.
                loss_expert = torch.tensor(0.0, device=device)
                if arch_a in router_gpu:
                    loss_expert = loss_expert + expert_gating_loss(h_a_recon, router_gpu[arch_a])
                if arch_b in router_gpu:
                    loss_expert = loss_expert + expert_gating_loss(h_b_recon, router_gpu[arch_b])
                loss_expert = loss_expert * 0.08  # MoE routing weight

                batch_loss = (
                    batch_loss
                    + loss_fwd
                    + loss_recon
                    + loss_eos
                    + loss_scale
                    + loss_gate
                    + loss_vocab
                    + loss_expert
                )
                epoch_eos_loss += loss_eos.item()
                epoch_scale_loss += loss_scale.item()
                epoch_vocab_loss += loss_vocab.item()
                epoch_expert_loss += loss_expert.item()

            batch_loss.backward()

            # Gradient clipping for stability
            torch.nn.utils.clip_grad_norm_(all_params, max_norm=1.0)

            optimizer.step()
            scheduler.step()

            epoch_loss += batch_loss.item()
            n_steps += 1

        avg_loss = epoch_loss / max(n_steps, 1)
        avg_eos_loss = epoch_eos_loss / max(n_steps, 1)
        avg_scale_loss = epoch_scale_loss / max(n_steps, 1)
        avg_vocab_loss = epoch_vocab_loss / max(n_steps, 1)
        avg_expert_loss = epoch_expert_loss / max(n_steps, 1)

        if avg_loss < best_loss:
            best_loss = avg_loss
            best_state = {
                arch: {
                    "enc": {k: v.cpu() for k, v in encoders[arch].state_dict().items()},
                    "dec": {k: v.cpu() for k, v in decoders[arch].state_dict().items()},
                }
                for arch in arches
            }

        lr_now = scheduler.get_last_lr()[0]
        print(
            f"  Epoch {epoch:02d}/{epochs}  loss={avg_loss:.4f}  best={best_loss:.4f}"
            f"  eos={avg_eos_loss:.4f}  scale={avg_scale_loss:.4f}"
            f"  vocab={avg_vocab_loss:.4f}  expert={avg_expert_loss:.4f}  lr={lr_now:.2e}",
            flush=True,
        )

    print(f"\nTraining complete. Best loss: {best_loss:.4f}", flush=True)

    # ── Assemble checkpoint ───────────────────────────────────────────────
    ckpt: dict = {
        "version": "1.0.0",
        "d_rosetta": D_ROSETTA,
        "anchor": "pure_infonce",
        "dims": {arch: BASE_MODELS[arch]["dim"] for arch in arches},
        "arches": arches,
    }

    assert best_state is not None
    for arch in arches:
        ckpt[f"{arch}_encoder"] = best_state[arch]["enc"]
        ckpt[f"{arch}_decoder"] = best_state[arch]["dec"]

    # Save
    out_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(ckpt, str(out_path))
    print(f"  Saved checkpoint: {out_path}  ({out_path.stat().st_size / 1e6:.0f} MB)", flush=True)


# ─────────────────────────────────────────────────────────────────────────────
# Sealing — tensor-content SHA256 (matches determinex_rosetta._verify_sha256)
# ─────────────────────────────────────────────────────────────────────────────


def _compute_weights_sha256(ckpt: dict) -> str:
    """
    Deterministic SHA256 over all weight tensors and string fields in the checkpoint.
    Excludes the "sha256" key itself (bootstrap problem).
    Keys iterated in sorted order for reproducibility.

    MUST stay byte-for-byte identical to the same function in determinex_rosetta.py.
    If you change one, change both.
    """
    h = hashlib.sha256()
    for key in sorted(ckpt.keys()):
        if key == "sha256":
            continue
        val = ckpt[key]
        if isinstance(val, dict):
            for k2 in sorted(val.keys()):
                t = val[k2]
                if hasattr(t, "cpu") and hasattr(t, "numpy"):
                    h.update(key.encode())
                    h.update(k2.encode())
                    h.update(t.cpu().numpy().tobytes())
        elif isinstance(val, str):
            h.update(key.encode())
            h.update(val.encode())
    return h.hexdigest()


def seal_rosetta(path: Path) -> str:
    """
    Seal a newly written Rosetta Stone:
      1. Load the checkpoint
      2. Compute SHA256 of all weight tensors + string fields (excluding sha256 key)
      3. Embed it as ckpt["sha256"]
      4. Save back
      5. chmod 444

    This is the canonical seal implementation — must match _verify_sha256 in
    determinex_rosetta.py exactly. Both functions call _compute_weights_sha256 with
    the same logic, so seal and verify always agree regardless of platform.

    Returns the hex SHA256 string.
    """
    ckpt = torch.load(str(path), map_location="cpu", weights_only=True)
    sha = _compute_weights_sha256(ckpt)
    ckpt["sha256"] = sha
    torch.save(ckpt, str(path))

    # chmod 444
    mode = path.stat().st_mode
    new_mode = mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
    try:
        os.chmod(str(path), new_mode)
    except PermissionError:
        print("  WARNING: could not set read-only permissions (advisory on Windows).")

    size_mb = path.stat().st_size / 1e6
    print(f"\nSealed: {path.name}")
    print(f"  Size   : {size_mb:.0f} MB")
    print(f"  SHA256 : {sha[:16]}...")
    print("  Mode   : read-only")
    return sha


# ─────────────────────────────────────────────────────────────────────────────
# Validation — quick sanity check after training
# ─────────────────────────────────────────────────────────────────────────────


def validate(out_path: Path, embeddings: dict[str, torch.Tensor], n_samples: int = 100) -> None:
    """
    Sanity check: load the sealed Rosetta Stone, run a few projections,
    measure cosine similarity of same-prompt pairs vs different-prompt pairs.
    A working Rosetta Stone should show clearly higher similarity for same-prompt pairs.
    """
    print(f"\n{'=' * 60}")
    print("VALIDATION")
    print(f"{'=' * 60}")

    ckpt = torch.load(str(out_path), map_location="cpu", weights_only=True)
    arches = list(embeddings.keys())
    pairs = [(a, b) for i, a in enumerate(arches) for b in arches[i + 1 :]]

    for arch_a, arch_b in pairs:  # All pairs — was incorrectly [:3] before
        dim_a = BASE_MODELS[arch_a]["dim"]
        dim_b = BASE_MODELS[arch_b]["dim"]

        enc_a = build_mlp(dim_a, D_ROSETTA)
        enc_b = build_mlp(dim_b, D_ROSETTA)
        enc_a.load_state_dict(ckpt[f"{arch_a}_encoder"])
        enc_b.load_state_dict(ckpt[f"{arch_b}_encoder"])
        enc_a.eval()
        enc_b.eval()

        idx = torch.randperm(len(embeddings[arch_a]))[:n_samples]

        with torch.no_grad():
            h_a = F.normalize(enc_a(embeddings[arch_a][idx].float()), dim=-1)
            h_b = F.normalize(enc_b(embeddings[arch_b][idx].float()), dim=-1)

        # Same-prompt cosine similarity (diagonal)
        same_sim = (h_a * h_b).sum(dim=-1).mean().item()

        # Different-prompt cosine similarity (off-diagonal sample)
        idx_shuffled = torch.randperm(n_samples)
        diff_sim = (h_a * h_b[idx_shuffled]).sum(dim=-1).mean().item()

        gap = same_sim - diff_sim
        status = "GOOD" if gap > 0.05 else ("WEAK" if gap > 0 else "FAIL")
        print(
            f"  {arch_a} ↔ {arch_b}: same={same_sim:.3f}  diff={diff_sim:.3f}  gap={gap:.3f}  [{status}]"
        )

    print()
    print("  GOOD (gap > 0.05): strong alignment — projections are semantically meaningful")
    print("  WEAK (gap 0-0.05): some alignment — may need more training data or epochs")
    print("  FAIL (gap < 0)   : no alignment — check training data diversity and prompts")


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Train Rosetta Stone v1 — universal latent bridge for Determinex Hive Mind"
    )
    parser.add_argument(
        "--data-dir",
        default="/workspace/data",
        help="Directory containing curriculum/gap JSONL files",
    )
    parser.add_argument(
        "--out-dir", default="/workspace/outputs", help="Output directory for rosetta_v1.pt"
    )
    parser.add_argument(
        "--cache-dir",
        default="/workspace/rosetta_cache",
        help="Directory to cache extracted embeddings between runs",
    )
    parser.add_argument(
        "--skip-extraction", action="store_true", help="Skip extraction phase, load from cache only"
    )
    parser.add_argument(
        "--skip-gated-check", action="store_true", help="Skip HF gated model license verification"
    )
    parser.add_argument(
        "--arches",
        default=None,
        help="Comma-separated subset of arches to train (e.g. llama,mistral)",
    )
    parser.add_argument(
        "--epochs", type=int, default=EPOCHS, help=f"Training epochs (default {EPOCHS})"
    )
    parser.add_argument("--lr", type=float, default=LR, help=f"Learning rate (default {LR})")
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()

    # Override training hyperparameters from CLI (passed as locals, not globals)
    train_epochs = args.epochs
    train_lr = args.lr

    data_dir = Path(args.data_dir)
    out_dir = Path(args.out_dir)
    cache_dir = Path(args.cache_dir)
    out_path = out_dir / "rosetta_v1.pt"
    arches = args.arches.split(",") if args.arches else None

    t_start = time.time()

    # ── Pre-flight ────────────────────────────────────────────────────────
    hf_token = preflight(data_dir, out_dir)
    if not args.skip_gated_check:
        check_gated_access(hf_token)

    # ── Load training data ────────────────────────────────────────────────
    print(f"\n{'=' * 60}")
    print("LOADING TRAINING DATA")
    print(f"{'=' * 60}")
    prompts = load_training_prompts(data_dir)
    random.shuffle(prompts)

    # ── Phase A: Sequential extraction ───────────────────────────────────
    if not args.skip_extraction:
        print(f"\n{'=' * 60}")
        print("PHASE A — SEQUENTIAL EMBEDDING EXTRACTION")
        print(f"{'=' * 60}")
    else:
        print("\nSkipping extraction phase (--skip-extraction). Loading from cache.")

    embeddings, special_embeds, vocab_embeds, router_weights = run_extraction_phase(
        prompts=prompts,
        hf_token=hf_token,
        cache_dir=cache_dir,
        arches=arches,
    )

    if len(embeddings) < 2:
        print("ERROR: Need at least 2 architectures to train. Check extraction output.")
        sys.exit(1)

    # ── Phase B: MLP training ─────────────────────────────────────────────
    print(f"\n{'=' * 60}")
    print("PHASE B — MLP PROJECTOR TRAINING")
    print(f"{'=' * 60}")
    train_mlp_projectors(
        embeddings=embeddings,
        out_path=out_path,
        special_embeds=special_embeds,
        vocab_embeds=vocab_embeds,
        router_weights=router_weights,
        device=args.device,
        epochs=train_epochs,
        lr=train_lr,
    )

    # ── Seal ──────────────────────────────────────────────────────────────
    sha = seal_rosetta(out_path)

    # ── Validate ──────────────────────────────────────────────────────────
    validate(out_path, embeddings)

    # ── Summary ───────────────────────────────────────────────────────────
    elapsed = time.time() - t_start
    print(f"\n{'=' * 60}")
    print("ROSETTA STONE v1 — COMPLETE")
    print(f"{'=' * 60}")
    print(f"  Output  : {out_path}")
    print(f"  SHA256  : {sha}")
    print(f"  Arches  : {list(embeddings.keys())}")
    print(f"  Prompts : {len(prompts)}")
    print(f"  Elapsed : {elapsed / 60:.0f} min")
    print()
    print("Next step: SCP to local machine and place in ~/.determinex/rosetta/")
    print(
        f"  scp -P PORT -i ~/.ssh/id_runpod root@POD:{out_path} ~/.determinex/rosetta/rosetta_v1.pt"
    )


if __name__ == "__main__":
    main()
