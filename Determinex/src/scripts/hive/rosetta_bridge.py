"""
scripts/hive/rosetta_bridge.py — Rosetta Stone ↔ Inference Loop Integration
============================================================================

Wires the RosettaStone projection network into the Builder retry loop:

  Monitor evaluates step N
     → extract Monitor's final hidden state (last token, from DeterminexInference)
     → RosettaStone.project(h, monitor_arch, builder_arch)
     → DeterminexInference.inject_soft_prompt(text_tokens, soft_prefix)
     → Builder retry N+1 runs with semantic context from Monitor's evaluation

The bridge is a best-effort layer.  Every public method is wrapped in a broad
try/except so that any failure (missing GGUF, llama_cpp not installed, stone
not trained for an arch pair, etc.) falls back to the vanilla api_call path.
The executor loop never sees an exception from this module.

Model registry integration:
  GGUF paths come from ~/.determinex/models.yaml (determinex_rosetta._load_registry).
  If a model isn't registered, the bridge falls back to the GGUF_PATH_DEFAULTS
  map which hard-codes last-resort fallback GGUF paths.

Projector resolution (first match wins):
  1. ~/.determinex/rosetta/npz/  -- exported .npz shards, run with numpy. Works in
     the packaged binary, which excludes torch. Fetched from HuggingFace on demand
     via scripts/rosetta_hub.py.
  2. ~/.determinex/rosetta/rosetta_v1.pt -- the 1.68 GB source checkpoint. Needs
     torch, so this path only ever works in a dev checkout.
  If neither exists the bridge disables itself and logs once, naming the command
  that fixes it.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import torch

log = logging.getLogger("hive")

# ── GGUF path fallbacks (last resort — used only when model not in registry) ──
# Keys match the Ollama model names resolved by litellm_config.yaml.
# Paths are derived from DETERMINEX_MODELS_DIR env var; set it to override.
import os as _os

_MODELS_BASE = Path(
    _os.environ.get("DETERMINEX_MODELS_DIR", str(Path.home() / "determinex-models"))
)
_GGUF_PATH_DEFAULTS: dict[str, str] = {
    # Current production models (April 27, 2026)
    "determinex-engineer-v11-dsl": str(
        Path("T:/determinex-models/versions/engineer/v11-dsl/determinex-engineer-v11-dsl.gguf")
    ),
    "determinex-observer-v6-dsl": str(
        Path("T:/determinex-models/versions/observer/v6-dsl/determinex-observer-v6-dsl.gguf")
    ),
    "determinex-sentinel-v5-dsl": str(
        Path("T:/determinex-models/versions/sentinel/v5-dsl/determinex-sentinel-v5-dsl.gguf")
    ),
    # Legacy fallbacks
    "determinex-3-medium-v1.1": str(_MODELS_BASE / "determinex-observer-v4.gguf"),
    "determinex-observer-v4": str(_MODELS_BASE / "determinex-observer-v4.gguf"),
    "determinex-1-tiny-v1.1": str(_MODELS_BASE / "determinex-engineer-v9.gguf"),
    "determinex-engineer-v9": str(_MODELS_BASE / "determinex-engineer-v9.gguf"),
}

# Rosetta Stone file location
_ROSETTA_PT_DEFAULT = Path.home() / ".determinex" / "rosetta" / "rosetta_v1.pt"

# ── Architecture map: Ollama model name → Rosetta arch key ───────────────────
# SIZE-SPECIFIC arch keys only. The historical bug — bare "qwen2" receiving a
# 1536-dim tensor when the stone expected 3584 — came from collapsing 1.5B/3B/
# 7B Qwen variants under one key. NEVER restore those entries.
#
# `rosetta.model_registry` is the source of truth; this map is a fallback for
# legacy aliases that aren't (yet) in the registry. `_resolve_arch_for()` below
# checks the registry first.
_OLLAMA_TO_ARCH: dict[str, str] = {
    # Current production models — April 27, 2026
    # rosetta_v1.pt (T:/determinex-models/rosetta/rosetta_v1.pt, 1.678GB, 7 arches)
    "determinex-engineer-v11-dsl": "qwen2_1b5",  # Qwen2.5-Coder-1.5B, dim=1536
    "determinex-observer-v6-dsl": "qwen2_3b",  # Qwen2.5-Coder-3B,   dim=2048
    "determinex-sentinel-v5-dsl": "mistral_7b",  # Mistral-7B,         dim=4096
    "qwen2.5-coder:7b-instruct": "qwen2_7b",  # Qwen2.5-Coder-7B,   dim=3584
    # Previous versions
    "determinex-engineer-v10-dsl": "qwen2_1b5",
    "determinex-observer-v5-dsl": "qwen2_3b",
    "determinex-sentinel-v3": "mistral_7b",
    # Legacy
    "determinex-3-medium-v1.1": "qwen2_3b",
    "determinex-observer-v4": "qwen2_3b",
    "determinex-1-tiny-v1.1": "qwen2_1b5",
    "determinex-engineer-v9": "qwen2_1b5",
    "determinex-sentinel-v2": "qwen2_7b",
}


def _resolve_arch_for(ollama_name: str) -> str | None:
    """Resolve a Rosetta arch key for an Ollama model name.

    Registry wins. Hardcoded legacy map is the fallback. Returns None only when
    nothing matches — callers must then refuse to project rather than guessing.
    """
    try:
        from rosetta.model_registry import resolve_model

        m = resolve_model(ollama_name)
        if m is not None:
            return m.rosetta_arch
    except ImportError:
        pass
    return _OLLAMA_TO_ARCH.get(ollama_name)


def _ollama_name_from_alias(litellm_model_string: str) -> str | None:
    """
    Extract the bare Ollama model name from a litellm model string.
    Examples:
      "ollama/determinex-observer-v5-dsl" → "determinex-observer-v5-dsl"
      "determinex-observer-v5-dsl"       → "determinex-observer-v5-dsl"
      "deepseek/deepseek-chat"       → None  (not a local model)
    """
    if litellm_model_string.startswith("ollama/"):
        return litellm_model_string[len("ollama/") :]
    # Bare Ollama names (no provider prefix) are also local
    if "/" not in litellm_model_string:
        return litellm_model_string
    return None


def _gguf_path_for_ollama(ollama_name: str) -> Path | None:
    """
    Resolve GGUF path for an Ollama model name.
    Priority: Determinex registry → hard-coded fallback map → None.
    """
    # 1. Try the Determinex model registry
    try:
        from determinex_rosetta import get_model

        entry = get_model(ollama_name)
        if entry and entry.get("path") and Path(entry["path"]).exists():
            return Path(entry["path"])
    except Exception:
        pass

    # 2. Hard-coded fallback for known models on this rig
    raw = _GGUF_PATH_DEFAULTS.get(ollama_name)
    if raw:
        p = Path(raw)
        if p.exists():
            return p

    return None


# ── Singleton management ──────────────────────────────────────────────────────
_bridge_lock = threading.Lock()
_bridge_cache: dict[str, object] = {}  # path → DeterminexInference instance
_stone_cache: dict[Path, object] = {}  # path → RosettaStone instance
_unavailable: set[str] = set()  # keys that failed — skip silently


_ROSETTA_NPZ_DEFAULT = Path.home() / ".determinex" / "rosetta" / "npz"


def _load_npz_stone() -> object | None:
    """Torch-free projector over exported .npz shards, if any are present.

    Preferred over the 1.68 GB .pt for one decisive reason: the shipped engine
    binary excludes torch (bundling it would take the binary from 111 MB to ~2 GB),
    so the .pt path can only ever work in a source checkout. The npz shards run on
    numpy alone, are 92-134 MB per architecture, and are fetched from HuggingFace
    on demand -- which is what makes the bridge available in the PRODUCT rather
    than only on a dev machine.

    Verified against torch to better than 1e-05 relative on float32 weights; see
    scripts/determinex_rosetta_npz.py::verify_parity and tests/test_rosetta_npz.py.
    """
    key = str(_ROSETTA_NPZ_DEFAULT)
    with _bridge_lock:
        cached = _stone_cache.get(_ROSETTA_NPZ_DEFAULT)
        if cached is not None:
            return cached
        if key in _unavailable:
            return None
    try:
        from determinex_rosetta_npz import NumpyRosettaStone

        stone = NumpyRosettaStone.load(_ROSETTA_NPZ_DEFAULT)
        with _bridge_lock:
            _stone_cache[_ROSETTA_NPZ_DEFAULT] = stone
        log.info(
            "[Rosetta] npz shards loaded (torch-free): %s arches=%s",
            _ROSETTA_NPZ_DEFAULT,
            stone.supported_arches(),
        )
        return stone
    except FileNotFoundError:
        # Not an error: the shards are an optional download. Recorded so the .pt
        # path gets its turn without this being retried on every projection.
        with _bridge_lock:
            _unavailable.add(key)
        return None
    except Exception as e:
        log.warning("[Rosetta] npz shards present but unusable: %s", e)
        with _bridge_lock:
            _unavailable.add(key)
        return None


def _load_stone(stone_path: Path = _ROSETTA_PT_DEFAULT) -> object | None:
    """Load and cache a projector. Returns None if none is available.

    Order is deliberate: npz first (works everywhere, including the packaged
    binary), then the .pt (source checkouts with torch). Both expose
    encode/decode/project, so callers do not care which they got.
    """
    npz = _load_npz_stone()
    if npz is not None:
        return npz

    with _bridge_lock:
        if stone_path in _stone_cache:
            return _stone_cache[stone_path]
        if str(stone_path) in _unavailable:
            return None

    try:
        from determinex_rosetta import RosettaStone

        stone = RosettaStone.load(stone_path, verify=True)
        with _bridge_lock:
            _stone_cache[stone_path] = stone
        log.info("[Rosetta] Stone loaded: %s  arches=%s", stone_path.name, stone.supported_arches())
        return stone
    except FileNotFoundError:
        log.warning(
            "[Rosetta] No projector available. Neither .npz shards at %s nor a "
            "checkpoint at %s. Fetch the shards (92-134 MB per architecture, no "
            "torch needed) with:  python scripts/rosetta_hub.py pull --arch qwen2_1b5",
            _ROSETTA_NPZ_DEFAULT,
            stone_path,
        )
        with _bridge_lock:
            _unavailable.add(str(stone_path))
        return None
    except Exception as e:
        log.warning("[Rosetta] Stone failed to load (%s) — bridge disabled: %s", stone_path.name, e)
        with _bridge_lock:
            _unavailable.add(str(stone_path))
        return None


def _load_inference(gguf_path: Path, arch: str) -> object | None:
    """Load and cache a DeterminexInference instance. Returns None if unavailable."""
    key = str(gguf_path)
    with _bridge_lock:
        if key in _bridge_cache:
            return _bridge_cache[key]
        if key in _unavailable:
            return None

    try:
        from determinex_inference import DeterminexInference

        inf = DeterminexInference(
            gguf_path=gguf_path,
            arch_name=arch,
            n_ctx=512,  # minimal context — we only need hidden states, not generation
            n_gpu_layers=-1,  # offload everything available
        )
        with _bridge_lock:
            _bridge_cache[key] = inf
        log.info("[Rosetta] DeterminexInference loaded: %s (arch=%s)", gguf_path.name, arch)
        return inf
    except ImportError:
        log.info(
            "[Rosetta] llama-cpp-python not installed — "
            "Rosetta bridge disabled (install llama-cpp-python to enable)"
        )
        with _bridge_lock:
            _unavailable.add(key)
        return None
    except Exception as e:
        log.warning(
            "[Rosetta] DeterminexInference failed to load %s: %s — bridge disabled",
            gguf_path.name,
            e,
        )
        with _bridge_lock:
            _unavailable.add(key)
        return None


def _load_embedding_model(gguf_path: Path) -> object | None:
    """
    Stratagem 3: Load a llama-cpp-python Llama instance in embedding mode.

    embedding=True instructs llama.cpp to run a full forward pass through all
    transformer layers and return the final pooled representation, rather than
    stopping at the logit head.  This is a true activation vector — it changes
    with input context unlike the static input-embedding table lookup that the
    previous implementation used as a proxy.

    Cached separately from DeterminexInference (different load flags, different key).
    Returns None if llama-cpp-python is unavailable or the model fails to load.
    """
    key = f"emb:{gguf_path}"
    with _bridge_lock:
        if key in _bridge_cache:
            return _bridge_cache[key]
        if key in _unavailable:
            return None

    try:
        from llama_cpp import Llama

        model = Llama(
            model_path=str(gguf_path),
            embedding=True,  # full forward pass → pooled last-layer activation
            n_ctx=512,
            n_gpu_layers=-1,
            verbose=False,
        )
        with _bridge_lock:
            _bridge_cache[key] = model
        log.info("[Rosetta] Embedding model loaded (activation mode): %s", gguf_path.name)
        return model
    except ImportError:
        log.debug("[Rosetta] llama-cpp-python not available for embedding extraction")
        with _bridge_lock:
            _unavailable.add(key)
        return None
    except Exception as e:
        log.warning("[Rosetta] Embedding model load failed for %s: %s", gguf_path.name, e)
        with _bridge_lock:
            _unavailable.add(key)
        return None


class RosettaBridge:
    """
    One RosettaBridge instance per executor session.
    Holds the stone + per-model inference references for that session.
    All methods return None or False on any failure — never raise.
    """

    def __init__(
        self,
        builder_model: str,  # resolved litellm model string (e.g. "ollama/determinex-engineer-v10-dsl")
        monitor_model: str,  # resolved litellm model string
        stone_path: Path = _ROSETTA_PT_DEFAULT,
    ):
        self._available = False
        self._stone = None
        self._builder_inf = None
        self._monitor_inf = None
        self._monitor_emb = None  # Stratagem 3: embedding-mode model for activation extraction
        self._builder_arch: str | None = None
        self._monitor_arch: str | None = None

        # Only attempt wiring for local (Ollama) models
        builder_ollama = _ollama_name_from_alias(builder_model)
        monitor_ollama = _ollama_name_from_alias(monitor_model)

        if not builder_ollama or not monitor_ollama:
            log.debug(
                "[Rosetta] Bridge skipped: one or both models are API-backed "
                "(builder=%s, monitor=%s)",
                builder_model,
                monitor_model,
            )
            return

        if builder_ollama == monitor_ollama:
            log.debug(
                "[Rosetta] Bridge skipped: same model for builder and monitor (%s)", builder_ollama
            )
            return

        # Resolve GGUF paths
        builder_gguf = _gguf_path_for_ollama(builder_ollama)
        monitor_gguf = _gguf_path_for_ollama(monitor_ollama)

        if not builder_gguf or not monitor_gguf:
            log.info(
                "[Rosetta] Bridge skipped: could not resolve GGUF paths "
                "(builder=%s → %s, monitor=%s → %s). "
                "Register models with: python scripts/determinex_rosetta.py register",
                builder_ollama,
                builder_gguf,
                monitor_ollama,
                monitor_gguf,
            )
            return

        # Resolve architecture keys — registry-first, legacy map fallback.
        # Both arches must be SIZE-SPECIFIC (qwen2_1b5 not bare qwen2).
        self._builder_arch = _resolve_arch_for(builder_ollama)
        self._monitor_arch = _resolve_arch_for(monitor_ollama)

        if not self._builder_arch or not self._monitor_arch:
            log.info(
                "[Rosetta] Bridge skipped: unknown arch for builder=%s or monitor=%s. "
                "Register in rosetta.model_registry.MODELS or add to _OLLAMA_TO_ARCH.",
                builder_ollama,
                monitor_ollama,
            )
            return

        # Load stone
        self._stone = _load_stone(stone_path)
        if self._stone is None:
            return

        # Verify stone supports both arches
        supported = self._stone.supported_arches()
        if self._builder_arch not in supported or self._monitor_arch not in supported:
            log.info(
                "[Rosetta] Bridge skipped: stone (arches=%s) doesn't cover "
                "builder_arch=%s or monitor_arch=%s. Retrain with both arches.",
                supported,
                self._builder_arch,
                self._monitor_arch,
            )
            return

        # Load inference engines (lazy, cached)
        self._monitor_inf = _load_inference(monitor_gguf, self._monitor_arch)
        self._builder_inf = _load_inference(builder_gguf, self._builder_arch)
        # Stratagem 3: load a separate embedding-mode instance for the monitor.
        # This runs a full forward pass through all transformer layers to produce
        # genuine last-layer activations, replacing the static input-embedding lookup.
        self._monitor_emb = _load_embedding_model(monitor_gguf)

        if self._monitor_inf and self._builder_inf:
            self._available = True
            log.info(
                "[Rosetta] Bridge ACTIVE: monitor(%s→%s) → builder(%s→%s)",
                monitor_ollama,
                self._monitor_arch,
                builder_ollama,
                self._builder_arch,
            )
        else:
            log.info("[Rosetta] Bridge inactive: inference engine(s) unavailable")

    @property
    def available(self) -> bool:
        return self._available

    def extract_monitor_hidden(self, monitor_verdict_text: str) -> torch.Tensor | None:
        """
        Extract the Monitor's final-layer hidden state for the given verdict text.

        Stratagem 3 — Activation-Based Rosetta:
        Uses the embedding-mode Llama instance (_monitor_emb) which runs a complete
        forward pass through all transformer layers and returns the pooled output
        representation.  This is a genuine activation vector that encodes the full
        contextual meaning of the Monitor's verdict — it changes with every input,
        unlike the static vocabulary lookup that was previously used as a proxy.

        Fallback chain:
          1. _monitor_emb.embed(text)         ← full forward pass (preferred)
          2. logit-slice via DeterminexInference  ← weaker but still dynamic
          3. None                             ← bridge silently no-ops
        """
        if not self._available:
            return None
        try:
            import torch

            # ── Path 1: embedding-mode forward pass (true activations) ───────
            if self._monitor_emb is not None:
                raw = self._monitor_emb.embed(monitor_verdict_text)
                # llama-cpp-python embed() returns list[float] or list[list[float]]
                h = torch.tensor(raw, dtype=torch.float32)
                if h.dim() == 1:
                    h = h.unsqueeze(0)  # → [1, hidden_dim]
                elif h.dim() == 2:
                    h = h.mean(dim=0, keepdim=True)  # pool sequence → [1, hidden_dim]
                if h.shape[-1] > 0:
                    log.debug(
                        "[Rosetta] activation extracted via embedding forward pass, dim=%d",
                        h.shape[-1],
                    )
                    return h

            # ── Path 2: logit-slice fallback (DeterminexInference) ──────────────
            if self._monitor_inf is not None:
                tokens = self._monitor_inf.model.tokenize(
                    monitor_verdict_text.encode("utf-8"), special=True
                )
                if tokens:
                    logits = self._monitor_inf.extract_logits(tokens[-256:])
                    hidden_dim = self._monitor_inf.hidden_dim
                    h = torch.tensor(logits[:hidden_dim], dtype=torch.float32).unsqueeze(0)
                    log.debug(
                        "[Rosetta] activation extracted via logit-slice fallback, dim=%d",
                        h.shape[-1],
                    )
                    return h

        except Exception as e:
            log.debug("[Rosetta] extract_monitor_hidden failed (non-fatal): %s", e)
        return None

    def build_soft_prefix(
        self,
        monitor_h: torch.Tensor,
        builder_prompt: str,
    ) -> list[int] | None:
        """
        Project Monitor's hidden state to Builder's space and inject as soft prefix.
        Returns the generated output tokens on success, None on failure.

        Sets self.last_bridge_status to one of:
          ROSETTA_PROJECTED      — cross-arch project + inject ran cleanly
          DIRECT_SELF_INJECTION  — same arch on both sides, no projection needed
          FAILED_BRIDGE          — bridge attempted but failed (dim mismatch, IO err, etc.)
        On dim mismatch the structured RosettaDimensionMismatch is re-raised so the
        caller cannot quietly report Rosetta success after a silent fallback.
        """
        # Lazy-import registry. When unavailable we still run the bridge but
        # skip dim validation — we never silently project a wrong-sized tensor.
        _registry_ok = False
        try:
            from rosetta.model_registry import (
                ARCHES as _ARCHES,
            )
            from rosetta.model_registry import (
                BridgeStatus as _BridgeStatus,
            )
            from rosetta.model_registry import (
                RosettaDimensionMismatch as _RosettaDimensionMismatch,
            )

            _registry_ok = True
        except ImportError:
            _BridgeStatus = None  # type: ignore[assignment]

        self.last_bridge_status = (
            _BridgeStatus.FAILED_BRIDGE.value if _registry_ok and _BridgeStatus else "failed_bridge"
        )

        if not self._available or self._builder_inf is None or self._stone is None:
            return None
        # _builder_arch / _monitor_arch are guaranteed non-None at this point
        # because __init__ early-returns if either is missing — but assert for
        # the type checker.
        assert self._monitor_arch is not None and self._builder_arch is not None
        monitor_arch: str = self._monitor_arch
        builder_arch: str = self._builder_arch

        # Validate the source tensor's dim against the registered monitor arch.
        # Catches the historical "qwen2 expects 3584, got 1536" failure here.
        if _registry_ok:
            actual_dim = monitor_h.shape[-1]
            expected = _ARCHES.get(monitor_arch)
            if expected is not None and actual_dim != expected.hidden_dim:
                # Re-raise to caller — no silent text fallback. The caller MUST
                # decide between text_fallback and surfacing the error.
                raise _RosettaDimensionMismatch(
                    source_model="(monitor)",
                    source_arch=monitor_arch,
                    expected_dim=expected.hidden_dim,
                    actual_dim=actual_dim,
                    target_model="(builder)",
                    target_arch=builder_arch,
                )

        try:
            if monitor_arch == builder_arch:
                # Same arch — no projection needed. Explicit direct self-injection,
                # not a silent skip-the-stone hack. Eval reports must record this
                # distinct path so it does NOT get bucketed with rosetta_projected.
                soft_prefix = monitor_h
                self.last_bridge_status = (
                    _BridgeStatus.DIRECT_SELF_INJECTION.value
                    if _registry_ok and _BridgeStatus
                    else "direct_self_injection"
                )
            else:
                # Cross-arch: project monitor's hidden state through the stone.
                soft_prefix = self._stone.project(
                    monitor_h,
                    source_arch=monitor_arch,
                    target_arch=builder_arch,
                )  # → [1, builder_hidden_dim]
                self.last_bridge_status = (
                    _BridgeStatus.ROSETTA_PROJECTED.value
                    if _registry_ok and _BridgeStatus
                    else "rosetta_projected"
                )

            text_tokens = self._builder_inf.model.tokenize(
                builder_prompt.encode("utf-8"), special=True
            )
            output_tokens = self._builder_inf.inject_soft_prompt(text_tokens, soft_prefix)
            return output_tokens
        except Exception as e:
            # Operational failure (tokenizer, inject, etc.) — record as failed_bridge.
            # We do NOT downgrade to text here; that's the caller's decision and
            # must be recorded as text_fallback, not as rosetta success.
            self.last_bridge_status = (
                _BridgeStatus.FAILED_BRIDGE.value
                if _registry_ok and _BridgeStatus
                else "failed_bridge"
            )
            log.debug("[Rosetta] build_soft_prefix failed (recorded as failed_bridge): %s", e)
            return None

    def decode_output(self, output_tokens: list[int]) -> str | None:
        """Detokenize Builder output tokens to a string."""
        if not self._available or self._builder_inf is None:
            return None
        try:
            raw = self._builder_inf.model.detokenize(output_tokens)
            return raw.decode("utf-8", errors="ignore")
        except Exception as e:
            log.debug("[Rosetta] decode_output failed (non-fatal): %s", e)
            return None


# ── Module-level factory ──────────────────────────────────────────────────────


def make_bridge(
    builder_model: str,
    monitor_model: str,
    stone_path: Path = _ROSETTA_PT_DEFAULT,
) -> RosettaBridge:
    """
    Factory that creates a RosettaBridge for a session.
    Always returns a RosettaBridge — just with available=False if setup fails.
    Never raises.
    """
    try:
        return RosettaBridge(builder_model, monitor_model, stone_path)
    except Exception as e:
        log.warning("[Rosetta] Bridge construction failed (non-fatal): %s", e)
        bridge = object.__new__(RosettaBridge)
        bridge._available = False
        return bridge  # type: ignore[return-value]
