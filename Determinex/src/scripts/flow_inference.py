"""
scripts/flow_inference.py — Flow AI End-to-End Pipeline

Wires the full Flow AI stack:
  1. Large HuggingFace model extracts mid-layer hidden state from context
  2. KVCompressor int8-quantizes and stores the state in sqlite
  3. RosettaStone translates large-model → small-model embedding space
  4. DeterminexInference.inject_soft_prompt() injects as K=1 soft prefix
  5. Small GGUF model generates conditioned on large model's understanding

This is the "practical" Flow AI: local large→small KV state conditioning.
No C++ required. No real-time token broadcast. All Python. All offline.

Usage:
    # One-time setup: load context into KV store
    pipeline = FlowAIPipeline(config)
    context_hash = pipeline.process_context("Full project context here...")

    # Generation: small model conditioned on large model's understanding
    result = pipeline.generate_conditioned(context_hash, "Implement the auth handler")

    # A/B eval: baseline vs conditioned
    report = pipeline.ab_eval("Implement the auth handler", context_hash, n_trials=5)
"""

import hashlib
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import torch

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── Module imports (handle both package and standalone execution) ────────────
_HERE = Path(__file__).parent
_ROSETTA = _HERE.parent / "rosetta"
if str(_ROSETTA) not in sys.path:
    sys.path.insert(0, str(_ROSETTA))
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from extract_midlayer import FAMILY_CONFIGS, MidLayerExtractor
from kv_compress import KVCompressor
from kv_store import KVStore

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------


@dataclass
class FlowAIConfig:
    """
    All configuration for the Flow AI pipeline.
    Designed to be serializable to JSON for reproducible runs.
    """

    # Large model (HuggingFace, used for context extraction only)
    large_family: str = "mistral"
    large_model_id: str | None = None  # None = use FAMILY_CONFIGS default
    large_load_4bit: bool = True

    # Small model (GGUF, used for generation)
    small_gguf_path: str = ""  # Required: path to .gguf file
    small_family: str = "qwen"  # family name for rosetta translation
    small_arch_name: str = "qwen"  # arch_name for DeterminexInference
    small_n_ctx: int = 4096
    small_gpu_layers: int = -1

    # Rosetta: which checkpoint to use
    # 'last'     = use existing rosetta_v1.pt (input-embedding space)
    # 'midlayer' = use rosetta_midlayer_v1.pt (mid-layer KV space, Phase 3)
    rosetta_path: str = ""  # path to rosetta best/ or final/ dir
    rosetta_mode: str = "last"  # 'last' or 'midlayer'

    # KV store
    db_path: str = "determinex_kv.db"

    # Extraction
    max_context_len: int = 2048  # token limit for large model
    n_soft_tokens: int = 1  # K for inject_soft_prompt (1 or 3)

    def to_json(self) -> str:
        return json.dumps(self.__dict__, indent=2)

    @classmethod
    def from_json(cls, s: str) -> "FlowAIConfig":
        return cls(**json.loads(s))


# ---------------------------------------------------------------------------
# PIPELINE
# ---------------------------------------------------------------------------


class FlowAIPipeline:
    """
    End-to-end Flow AI pipeline: context extraction → KV storage →
    rosetta translation → soft-prefix injection → conditioned generation.

    Design:
        The large HuggingFace model is loaded on demand for extraction and
        immediately unloaded to free VRAM before the GGUF model runs.
        The GGUF model stays loaded for the lifetime of the pipeline.
    """

    def __init__(self, config: FlowAIConfig):
        self.config = config
        self.compressor = KVCompressor()
        self.store = KVStore(config.db_path)
        self._rosetta = None
        self._inference = None
        self._extractor = None  # lazy-loaded, immediately unloaded after use

        self._load_rosetta()
        self._load_inference()
        print("[FlowAI] Pipeline ready.", flush=True)

    # ── Rosetta ──────────────────────────────────────────────────────────────

    def _load_rosetta(self):
        from determinex_rosetta import RosettaStone

        rosetta_path = Path(self.config.rosetta_path)
        if not rosetta_path.exists():
            print(
                f"[FlowAI] WARNING: rosetta_path '{rosetta_path}' not found. "
                f"Translation will use identity mapping (baseline mode).",
                flush=True,
            )
            self._rosetta = None
            return
        self._rosetta = RosettaStone.load(rosetta_path)
        self._rosetta.eval()
        print(
            f"[FlowAI] RosettaStone loaded from {rosetta_path} (mode={self.config.rosetta_mode})",
            flush=True,
        )

    # ── Inference (GGUF) ──────────────────────────────────────────────────────

    def _load_inference(self):
        if not self.config.small_gguf_path:
            print("[FlowAI] No small_gguf_path set. Generation disabled.", flush=True)
            return
        try:
            from determinex_inference import DeterminexInference

            self._inference = DeterminexInference(
                gguf_path=self.config.small_gguf_path,
                arch_name=self.config.small_arch_name,
                n_ctx=self.config.small_n_ctx,
                n_gpu_layers=self.config.small_gpu_layers,
            )
            print(f"[FlowAI] DeterminexInference loaded: {self.config.small_gguf_path}", flush=True)
        except Exception as e:
            print(f"[FlowAI] WARNING: Could not load DeterminexInference: {e}", flush=True)
            self._inference = None

    # ── Extractor (lazy, VRAM-careful) ────────────────────────────────────────

    def _extract_and_unload(self, context_text: str) -> torch.Tensor:
        """
        Load the large HF model, extract mid-layer state, immediately unload.
        Returns pooled float32 tensor [hidden_dim].
        """
        extractor = MidLayerExtractor(
            family=self.config.large_family,
            model_id=self.config.large_model_id,
            load_in_4bit=self.config.large_load_4bit,
        )
        try:
            state = extractor.extract(context_text, max_length=self.config.max_context_len)
        finally:
            extractor.unload()  # always free VRAM
        return state

    # ── Core API ─────────────────────────────────────────────────────────────

    def process_context(self, context_text: str) -> str:
        """
        Run the large model on context_text, compress the mid-layer state,
        and store it in the KV store.

        Returns:
            context_hash (str) — pass to generate_conditioned() to retrieve
        """
        t0 = time.time()
        print(f"[FlowAI] process_context: {len(context_text):,} chars", flush=True)

        # Extract
        state = self._extract_and_unload(context_text)

        # Find layer index from extractor config (mid layer of large model)
        large_cfg = FAMILY_CONFIGS[self.config.large_family]
        # We don't know exact layer count without loading — use typical values
        # mistral-7b: 32 layers → mid=16  llama-3b: 28 layers → mid=14
        # Store with layer_idx=-1 as sentinel meaning "midlayer auto"
        layer_idx = -1

        # Compress
        cs = self.compressor.compress(
            state,
            family=self.config.large_family,
            layer_idx=layer_idx,
            context_text=context_text,
            seq_len=1,
        )

        # Store
        row_id = self.store.store(context_text, self.config.large_family, cs)
        context_hash = hashlib.sha256(context_text.encode()).hexdigest()

        elapsed = time.time() - t0
        quality = self.compressor.round_trip_quality(state, cs)
        print(
            f"[FlowAI] Context stored: hash={context_hash[:12]}…  "
            f"dim={state.shape[0]}  cos_sim={quality:.4f}  "
            f"time={elapsed:.1f}s  row_id={row_id}",
            flush=True,
        )
        return context_hash

    def generate_conditioned(
        self,
        prompt: str,
        context_hash: str | None = None,
        context_text: str | None = None,
    ) -> str:
        """
        Generate text conditioned on a previously stored large-model state.

        Args:
            prompt        : the actual generation prompt for the small model
            context_hash  : hash from process_context() — used to look up state
            context_text  : convenience alternative — will hash to retrieve

        Returns:
            Generated text string
        """
        if self._inference is None:
            raise RuntimeError("No GGUF model loaded. Set small_gguf_path in config.")

        # Resolve hash
        if context_hash is None and context_text is not None:
            context_hash = hashlib.sha256(context_text.encode()).hexdigest()
        if context_hash is None:
            raise ValueError("Provide either context_hash or context_text.")

        # Retrieve compressed state
        cs = self.store.retrieve_by_hash(context_hash)
        if cs is None:
            print(
                f"[FlowAI] No stored state for hash {context_hash[:12]}…, using baseline.",
                flush=True,
            )
            return self._generate_baseline(prompt)

        # Decompress → [hidden_dim] fp32
        state_vec = self.compressor.decompress(cs)

        # Translate: large family → small family via RosettaStone
        if self._rosetta is not None:
            with torch.no_grad():
                projected = self._rosetta.project(
                    state_vec.unsqueeze(0),
                    self.config.large_family,
                    self.config.small_family,
                ).squeeze(0)  # [small_hidden_dim]
        else:
            # No rosetta: use raw state (will likely be wrong dimension — baseline only)
            projected = state_vec
            print("[FlowAI] No RosettaStone — using untranslated state (baseline).", flush=True)

        # Ensure K soft tokens shape: [K, hidden_dim]
        K = self.config.n_soft_tokens
        if K == 1:
            soft_emb = projected.unsqueeze(0)  # [1, dim]
        else:
            # K=3: replicate with small noise for stability
            noise = torch.randn(K - 1, projected.shape[0]) * 0.01
            soft_emb = torch.cat([projected.unsqueeze(0), projected.unsqueeze(0) + noise], dim=0)[
                :K
            ]

        # Inject and generate
        text_tokens = self._inference.model.tokenize(prompt.encode("utf-8"), special=True)
        out_tokens = self._inference.inject_soft_prompt(text_tokens, soft_emb)
        result = self._inference.model.detokenize(out_tokens).decode("utf-8", errors="ignore")

        print(
            f"[FlowAI] Generated {len(result)} chars (conditioned, hash={context_hash[:12]}…)",
            flush=True,
        )
        return result

    def _generate_baseline(self, prompt: str, max_tokens: int = 512) -> str:
        """Generate without any conditioning (baseline for A/B eval)."""
        if self._inference is None:
            return "[No inference model]"
        result = self._inference.model(
            prompt,
            max_tokens=max_tokens,
            echo=False,
        )
        return result["choices"][0]["text"]

    # ── A/B Eval ─────────────────────────────────────────────────────────────

    def ab_eval(
        self,
        prompt: str,
        context_hash: str,
        n_trials: int = 3,
    ) -> dict:
        """
        Run A/B evaluation: baseline (no conditioning) vs Flow AI conditioned.

        Returns dict with:
            baseline_outputs  : list of n_trials baseline outputs
            conditioned_outputs: list of n_trials conditioned outputs
            avg_cos_sim       : average cosine similarity baseline vs conditioned
            summary           : human-readable summary
        """
        import torch.nn.functional as F

        print(f"[FlowAI] A/B eval: {n_trials} trials, prompt='{prompt[:60]}…'", flush=True)

        baselines = []
        conditioned = []

        for i in range(n_trials):
            b = self._generate_baseline(prompt)
            c = self.generate_conditioned(prompt, context_hash=context_hash)
            baselines.append(b)
            conditioned.append(c)
            print(f"[FlowAI] Trial {i + 1}/{n_trials} done", flush=True)

        report = {
            "prompt": prompt,
            "context_hash": context_hash,
            "n_trials": n_trials,
            "baseline_outputs": baselines,
            "conditioned_outputs": conditioned,
            "config": self.config.__dict__,
        }

        # Cosine similarity via token overlap (fallback if no embedding model)
        def token_vec(text: str) -> torch.Tensor:
            tokens = set(text.lower().split())
            # Build a simple BoW vector over shared vocabulary
            vocab = sorted(tokens)
            v = torch.zeros(max(len(vocab), 1))
            for i, t in enumerate(vocab):
                v[i] = text.lower().count(t)
            return v

        cos_sims = []
        for b, c in zip(baselines, conditioned):
            vb = token_vec(b)
            vc = token_vec(c)
            min_len = min(len(vb), len(vc))
            if min_len > 0:
                sim = F.cosine_similarity(
                    vb[:min_len].unsqueeze(0), vc[:min_len].unsqueeze(0)
                ).item()
                cos_sims.append(sim)

        avg_cos = sum(cos_sims) / len(cos_sims) if cos_sims else 0.0
        report["avg_cos_sim_baseline_vs_conditioned"] = avg_cos

        len_b = sum(len(x) for x in baselines) / max(n_trials, 1)
        len_c = sum(len(x) for x in conditioned) / max(n_trials, 1)
        report["summary"] = (
            f"avg_cos_sim={avg_cos:.3f}  "
            f"avg_baseline_len={len_b:.0f}  avg_conditioned_len={len_c:.0f}"
        )

        print(f"[FlowAI] A/B result: {report['summary']}", flush=True)
        return report

    # ── Diagnostics ───────────────────────────────────────────────────────────

    def status(self) -> dict:
        """Return current pipeline status."""
        return {
            "large_family": self.config.large_family,
            "small_family": self.config.small_family,
            "rosetta_loaded": self._rosetta is not None,
            "inference_ready": self._inference is not None,
            "kv_store": self.store.stats(),
        }

    def close(self):
        self.store.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


# ---------------------------------------------------------------------------
# CLI / SMOKE TEST
# ---------------------------------------------------------------------------


def _smoke_test():
    """
    Smoke test that validates the full pipeline logic WITHOUT loading any model.
    Uses dummy tensors to verify compress → store → retrieve → decompress.
    """
    import tempfile

    print("[FlowAI] Running smoke test (no model load)...", flush=True)

    compressor = KVCompressor()

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    with KVStore(db_path) as store:
        # Simulate large model output
        large_dim = FAMILY_CONFIGS["mistral"]["hidden_dim"]  # 4096
        small_dim = FAMILY_CONFIGS["qwen"]["hidden_dim"]  # 2048
        fake_state = torch.randn(large_dim)
        context_txt = "This is a test context representing project code."

        # Compress + store (same as process_context)
        cs = compressor.compress(fake_state, "mistral", -1, context_txt)
        row_id = store.store(context_txt, "mistral", cs)
        ctx_hash = hashlib.sha256(context_txt.encode()).hexdigest()

        # Retrieve + decompress (same as generate_conditioned)
        cs_back = store.retrieve_by_hash(ctx_hash)
        assert cs_back is not None, "Retrieve failed"
        state_v = compressor.decompress(cs_back)
        quality = compressor.round_trip_quality(fake_state, cs_back)

        print(f"  compress→store→retrieve→decompress: cos_sim={quality:.5f}  ok={quality > 0.99}")
        assert quality > 0.99, f"Round-trip quality too low: {quality}"

        # Simulate rosetta translation (linear projection, no actual weights)
        proj_matrix = torch.randn(small_dim, large_dim) * 0.01
        projected = (proj_matrix @ state_v).unsqueeze(0)  # [1, small_dim]
        print(f"  simulated rosetta projection: {state_v.shape} → {projected.shape}  ok")

        # Simulate soft prefix
        soft_emb = projected  # [1, small_dim]
        assert soft_emb.shape == (1, small_dim)
        print(f"  soft_emb shape: {soft_emb.shape}  ok")

        # Stats
        s = store.stats()
        print(f"  kv_store stats: {s}")

    import os

    os.unlink(db_path)
    print("[FlowAI] Smoke test passed.", flush=True)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Flow AI pipeline")
    parser.add_argument("--test", action="store_true", help="Run smoke test")
    parser.add_argument("--config", type=str, default=None, help="JSON config file")
    parser.add_argument("--context", type=str, default=None, help="Context text to process")
    parser.add_argument("--prompt", type=str, default=None, help="Generation prompt")
    parser.add_argument("--hash", type=str, default=None, help="Context hash to condition on")
    parser.add_argument("--status", action="store_true", help="Show pipeline status")
    args = parser.parse_args()

    if args.test:
        _smoke_test()
        sys.exit(0)

    if args.config is None:
        print("[FlowAI] No config. Use --test for smoke test, or --config path/to/config.json")
        parser.print_help()
        sys.exit(1)

    with open(args.config) as f:
        config = FlowAIConfig.from_json(f.read())

    with FlowAIPipeline(config) as pipeline:
        if args.status:
            print(json.dumps(pipeline.status(), indent=2))

        elif args.context:
            ctx_hash = pipeline.process_context(args.context)
            print(f"Context stored. Hash: {ctx_hash}")

        elif args.prompt and args.hash:
            result = pipeline.generate_conditioned(args.prompt, context_hash=args.hash)
            print("--- Generated Output ---")
            print(result)
