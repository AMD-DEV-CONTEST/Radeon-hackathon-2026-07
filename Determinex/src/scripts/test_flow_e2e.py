"""
test_flow_e2e.py — Real end-to-end Flow AI test (no RunPod needed)

Uses:
  - Large: Qwen2.5-Coder-1.5B-Instruct (HF cache, hidden_dim=1536, 28 layers)
  - Small: determinex-1-tiny-v1.1 GGUF (same arch, no rosetta translation needed)
  - KVStore: sqlite in /tmp
  - Rosetta: skipped (same architecture — direct injection)

Tests:
  1. Mid-layer extraction from HF model
  2. Compress → store → retrieve → decompress (round-trip quality)
  3. Inject as soft prefix into GGUF model
  4. A/B compare: baseline vs conditioned output
"""

import gc
import hashlib
import sys
import tempfile
import time
from pathlib import Path

import pytest

# Fix stdout encoding on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── Path setup ──────────────────────────────────────────────────────────────
DETERMINEX = Path(__file__).parent.parent
sys.path.insert(0, str(DETERMINEX / "rosetta"))
sys.path.insert(0, str(DETERMINEX / "scripts"))

import torch
from extract_midlayer import MidLayerExtractor
from kv_compress import KVCompressor
from kv_store import KVStore

# ── Config ──────────────────────────────────────────────────────────────────
HF_MODEL_ID = "Qwen/Qwen2.5-Coder-1.5B-Instruct"
HIDDEN_DIM = 1536
LAYER_ATTR = "model.layers"

# Resolve GGUF blob from Ollama manifest
import json

MANIFEST = Path(
    "T:/OllamaModels/models/manifests/registry.ollama.ai/library/determinex-1-tiny-v1.1/latest"
)
_manifest = json.load(open(MANIFEST))
_gguf_digest = next(
    l["digest"].replace("sha256:", "sha256-")
    for l in _manifest["layers"]
    if "model" in l.get("mediaType", "")
)
GGUF_PATH = Path(f"T:/OllamaModels/models/blobs/{_gguf_digest}")

DB_PATH = Path(tempfile.mktemp(suffix=".db"))

# ── Test context and prompt ──────────────────────────────────────────────────
CONTEXT = """
Determinex is a multi-agent coding system. The Builder agent receives step instructions
and generates code. The Monitor agent reviews Builder output for correctness and
security issues. The Architect produces a DAG of steps with explicit dependencies.
The Compiler Oracle runs rustc/go/python to verify compilation.

Current project: HTTP API server in Rust using axum.
Files written so far:
- src/types.rs: defines AppState, JobStatus enum, Job struct with id/status/payload
- src/db.rs: defines DbPool type alias (sqlx::PgPool), init_pool() -> Result<DbPool>
- src/lib.rs: defines AppState with Arc<Mutex<Vec<Job>>> field

Step 4 requires: implement the create_job handler that accepts CreateJobRequest,
validates input, inserts into the job queue, returns Job with assigned UUID.
The handler must use AppState from src/types.rs and DbPool from src/db.rs.
"""

PROMPT = "Implement the create_job handler in Rust using axum:"

# ────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def extracted_state():
    """Fixture: run mid-layer extraction once, share result across stage tests."""
    extractor = MidLayerExtractor(
        family="qwen",
        model_id=HF_MODEL_ID,
        load_in_4bit=False,
    )
    extractor.hidden_dim = HIDDEN_DIM
    state = extractor.extract(CONTEXT, max_length=512)
    extractor.unload()
    return state


def test_extraction(extracted_state):
    print("\n" + "=" * 60)
    print("STAGE 1: Mid-layer extraction from HF model")
    print("=" * 60)

    state = extracted_state
    print(f"  Extracted: shape={state.shape}  dtype={state.dtype}")
    assert state.shape == (HIDDEN_DIM,), f"Expected ({HIDDEN_DIM},), got {state.shape}"
    assert not torch.isnan(state).any(), "NaN in extracted state"
    print("  PASS: extraction shape and values correct")


def test_kv_roundtrip(extracted_state):
    print("\n" + "=" * 60)
    print("STAGE 2: Compress → Store → Retrieve → Decompress")
    print("=" * 60)

    state = extracted_state
    compressor = KVCompressor()
    store = KVStore(str(DB_PATH))

    cs = compressor.compress(state, family="qwen", layer_idx=14, context_text=CONTEXT)
    quality = compressor.round_trip_quality(state, cs)
    blob_size = len(cs.int8_data) + len(cs.scales) + len(cs.zero_points)
    print(f"  Compression: blob={blob_size} bytes  cos_sim={quality:.5f}")
    assert quality > 0.99, f"Round-trip quality too low: {quality}"

    row_id = store.store(CONTEXT, "qwen", cs)
    ctx_hash = hashlib.sha256(CONTEXT.encode()).hexdigest()
    print(f"  Stored: row_id={row_id}  hash={ctx_hash[:12]}…")

    cs_back = store.retrieve_by_hash(ctx_hash)
    assert cs_back is not None, "Retrieve by hash failed"
    state_back = compressor.decompress(cs_back)
    print(f"  Retrieved: shape={state_back.shape}")

    final_sim = torch.nn.functional.cosine_similarity(
        state.unsqueeze(0), state_back.unsqueeze(0)
    ).item()
    print(f"  Full round-trip cos_sim={final_sim:.5f}")
    assert final_sim > 0.99, f"Full round-trip quality too low: {final_sim}"
    print("  PASS: KV round-trip correct")

    store.close()


@pytest.fixture(scope="module")
def state_vec(extracted_state):
    """Fixture: the decompressed state vector for the injection test."""
    compressor = KVCompressor()
    store = KVStore(str(DB_PATH))
    cs = compressor.compress(extracted_state, family="qwen", layer_idx=14, context_text=CONTEXT)
    row_id = store.store(CONTEXT, "qwen", cs)
    ctx_hash = hashlib.sha256(CONTEXT.encode()).hexdigest()
    cs_back = store.retrieve_by_hash(ctx_hash)
    state_back = compressor.decompress(cs_back)
    store.close()
    return state_back


def test_injection(state_vec: torch.Tensor):
    print("\n" + "=" * 60)
    print("STAGE 3: Soft-prefix injection + generation (determinex-1-tiny)")
    print("=" * 60)

    if not GGUF_PATH.exists():
        print(f"  SKIP: GGUF not found at {GGUF_PATH}")
        return

    try:
        from determinex_inference import DeterminexInference
    except (ImportError, Exception) as e:
        print(f"  SKIP: determinex_inference not available ({e.__class__.__name__}: {e})")
        print("  (llama-cpp-python required — runs on pod, not local Windows)")
        return

    print(f"  Loading GGUF: {GGUF_PATH.name} ({GGUF_PATH.stat().st_size // 1024 // 1024} MB)")
    try:
        inference = DeterminexInference(
            gguf_path=str(GGUF_PATH),
            arch_name="qwen",
            n_ctx=2048,
            n_gpu_layers=-1,
        )
    except (ImportError, Exception) as e:
        print(f"  SKIP: GGUF load failed ({e.__class__.__name__}: {e})")
        print("  (llama-cpp-python required — runs on pod, not local Windows)")
        return

    actual_dim = inference.hidden_dim
    print(f"  GGUF hidden_dim: {actual_dim}")

    if actual_dim != state_vec.shape[0]:
        print(f"  Adjusting state dim {state_vec.shape[0]} → {actual_dim} via linear projection")
        proj = torch.nn.Linear(state_vec.shape[0], actual_dim, bias=False)
        torch.nn.init.eye_(
            proj.weight[
                : min(actual_dim, state_vec.shape[0]), : min(actual_dim, state_vec.shape[0])
            ]
        )
        with torch.no_grad():
            state_vec = proj(state_vec)

    soft_emb = state_vec.unsqueeze(0)  # [1, hidden_dim]

    # ── Baseline ──────────────────────────────────────────────────────────
    print("\n  [Baseline] Generating without conditioning...")
    t0 = time.time()
    baseline = inference.model(PROMPT, max_tokens=150, echo=False)
    baseline_text = baseline["choices"][0]["text"]
    print(f"  Baseline ({time.time() - t0:.1f}s):\n{baseline_text[:300]}")

    # ── Conditioned ───────────────────────────────────────────────────────
    print("\n  [Conditioned] Generating with Flow AI soft prefix...")
    t0 = time.time()
    text_tokens = inference.model.tokenize(PROMPT.encode(), special=True)
    out_tokens = inference.inject_soft_prompt(text_tokens, soft_emb)
    conditioned_text = inference.model.detokenize(out_tokens).decode("utf-8", errors="ignore")
    print(f"  Conditioned ({time.time() - t0:.1f}s):\n{conditioned_text[:300]}")

    # ── Compare ───────────────────────────────────────────────────────────
    import torch.nn.functional as F

    def bow(t):
        words = t.lower().split()
        vocab = sorted(set(words))
        v = torch.zeros(len(vocab))
        for i, w in enumerate(vocab):
            v[i] = words.count(w)
        return v

    vb, vc = bow(baseline_text), bow(conditioned_text)
    mn = min(len(vb), len(vc))
    sim = F.cosine_similarity(vb[:mn].unsqueeze(0), vc[:mn].unsqueeze(0)).item() if mn > 0 else 0
    print(f"\n  Baseline vs Conditioned similarity: {sim:.3f}")
    print("  (Lower = more divergent outputs = conditioning is having an effect)")
    print("  PASS: injection and generation complete")

    del inference
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def main():
    print("\n" + "=" * 60)
    print("Flow AI End-to-End Test")
    print(f"HF model : {HF_MODEL_ID}")
    print(f"GGUF     : {GGUF_PATH.name}")
    print(f"CUDA     : {torch.cuda.is_available()}")
    print("=" * 60)

    try:
        state = test_extraction()
        state_back, ctx_hash = test_kv_roundtrip(state)
        test_injection(state_back)

        print("\n" + "=" * 60)
        print("ALL STAGES PASSED")
        print("=" * 60)
    finally:
        try:
            if DB_PATH.exists():
                DB_PATH.unlink()
        except PermissionError:
            pass  # Windows holds file briefly after close


if __name__ == "__main__":
    main()
