"""
determinex_rosetta.py — Universal Latent Bridge (Rosetta Stone)
============================================================
Foundation layer for the Hive Mind architecture.

Architecture:
  - GGUF header parser: detects base architecture + hidden_dim (pure Python, no deps)
  - Model registry: YAML at ~/.determinex/models.yaml
  - Rosetta Stone loader: loads rosetta_vN.pt, verifies SHA256, enforces read-only
  - project(h, src, tgt): two MLP ops, microseconds
  - CLI: probe | register | list | verify | project

Rosetta Space: D_ROSETTA = 4096 (matches Mistral/Llama-8B natively, minimal overhead)

v1 injection model: input embedding space (soft prefix) — natively supported by all
inference backends. Mid-layer injection is Phase 3 (requires custom inference engine).

Supported base architectures (all open-source LLM families trace back to these five):
  llama, mistral, qwen2, phi3, deepseek2
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
import hashlib
import logging
import os
import stat
import struct
import sys
from pathlib import Path
from typing import Any

# PyYAML — only non-stdlib dep at import time. torch is imported locally
# inside functions that need it, so the parser/registry work without any ML stack.
try:
    import yaml
except ImportError:
    print("[ERROR] PyYAML not installed. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

D_ROSETTA = 4096  # Universal latent hub dimension

# Known base architectures: arch_key → metadata about that family.
# arch_key = value of `general.architecture` in GGUF metadata.
# variants = {hidden_dim: size_label} — used for display only, not logic.
BASE_ARCH_INFO: dict[str, dict] = {
    "llama": {
        "family": "llama",
        "variants": {3072: "3B", 4096: "8B", 8192: "70B"},
        "default_dim": 4096,
        "encoder_key": "llama_encoder",
        "decoder_key": "llama_decoder",
    },
    "mistral": {
        "family": "mistral",
        "variants": {4096: "7B"},
        "default_dim": 4096,
        "encoder_key": "mistral_encoder",
        "decoder_key": "mistral_decoder",
    },
    "qwen2": {
        "family": "qwen2",
        "variants": {1536: "1.5B", 3584: "7B"},
        "default_dim": 3584,
        "encoder_key": "qwen2_encoder",
        "decoder_key": "qwen2_decoder",
    },
    "phi3": {
        "family": "phi3",
        "variants": {3072: "mini", 5120: "medium"},
        "default_dim": 3072,
        "encoder_key": "phi3_encoder",
        "decoder_key": "phi3_decoder",
    },
    "deepseek2": {
        "family": "deepseek2",
        "variants": {2048: "lite", 5120: "full"},
        "default_dim": 2048,
        "encoder_key": "deepseek2_encoder",
        "decoder_key": "deepseek2_decoder",
    },
    "qwen2_1b5": {
        "family": "qwen2",
        "variants": {1536: "1.5B"},
        "default_dim": 1536,
        "encoder_key": "qwen2_1b5_encoder",
        "decoder_key": "qwen2_1b5_decoder",
    },
}

# GGUF metadata key patterns for the hidden dimension, in priority order.
# The spec uses `{arch}.embedding_length`; some models add a second alias.
GGUF_DIM_KEYS = [
    "{arch}.embedding_length",
    "{arch}.hidden_size",
]

REGISTRY_PATH = Path.home() / ".determinex" / "models.yaml"
ROSETTA_DIR = Path.home() / ".determinex" / "rosetta"
# Pre-rename location. Kept in the search path so a checkpoint left behind by the
# Citadel -> Determinex rename is still found instead of silently disabling the
# latent bridge.
LEGACY_ROSETTA_DIR = Path.home() / ".citadel" / "rosetta"
ADAPTERS_DIR = ROSETTA_DIR / "adapters"

# ─────────────────────────────────────────────────────────────────────────────
# GGUF Header Parser — pure Python, no llama-cpp, no ML libraries required
# ─────────────────────────────────────────────────────────────────────────────

GGUF_MAGIC = b"GGUF"

# GGUF value type IDs (from the GGUF spec)
_GGUF_TYPE_UINT8 = 0
_GGUF_TYPE_INT8 = 1
_GGUF_TYPE_UINT16 = 2
_GGUF_TYPE_INT16 = 3
_GGUF_TYPE_UINT32 = 4
_GGUF_TYPE_INT32 = 5
_GGUF_TYPE_FLOAT32 = 6
_GGUF_TYPE_BOOL = 7
_GGUF_TYPE_STRING = 8
_GGUF_TYPE_ARRAY = 9
_GGUF_TYPE_UINT64 = 10
_GGUF_TYPE_INT64 = 11
_GGUF_TYPE_FLOAT64 = 12


class _GGUFParser:
    """
    Minimal pure-Python GGUF header parser.
    Reads only the metadata section — never loads tensor data.
    Handles GGUF v1, v2, v3.
    """

    def __init__(self, path: Path, max_header_bytes: int = 2 * 1024 * 1024):
        self.path = path
        self._buf: bytes = b""
        self._pos = 0
        self.version: int = 0
        self.n_tensors: int = 0
        self.n_kv: int = 0
        self.metadata: dict[str, Any] = {}
        self._max = max_header_bytes

    # ── Primitive readers ──────────────────────────────────────────────────

    def _read(self, n: int) -> bytes:
        chunk = self._buf[self._pos : self._pos + n]
        if len(chunk) != n:
            raise ValueError(f"Truncated GGUF at byte {self._pos}: need {n}, got {len(chunk)}")
        self._pos += n
        return chunk

    def _u8(self) -> int:
        return struct.unpack_from("<B", self._read(1))[0]

    def _i8(self) -> int:
        return struct.unpack_from("<b", self._read(1))[0]

    def _u16(self) -> int:
        return struct.unpack_from("<H", self._read(2))[0]

    def _i16(self) -> int:
        return struct.unpack_from("<h", self._read(2))[0]

    def _u32(self) -> int:
        return struct.unpack_from("<I", self._read(4))[0]

    def _i32(self) -> int:
        return struct.unpack_from("<i", self._read(4))[0]

    def _u64(self) -> int:
        return struct.unpack_from("<Q", self._read(8))[0]

    def _i64(self) -> int:
        return struct.unpack_from("<q", self._read(8))[0]

    def _f32(self) -> float:
        return struct.unpack_from("<f", self._read(4))[0]

    def _f64(self) -> float:
        return struct.unpack_from("<d", self._read(8))[0]

    def _bool(self) -> bool:
        return bool(self._u8())

    def _string(self) -> str:
        length = self._u64()
        return self._read(length).decode("utf-8", errors="replace")

    def _value(self, vtype: int) -> Any:
        dispatch = {
            _GGUF_TYPE_UINT8: self._u8,
            _GGUF_TYPE_INT8: self._i8,
            _GGUF_TYPE_UINT16: self._u16,
            _GGUF_TYPE_INT16: self._i16,
            _GGUF_TYPE_UINT32: self._u32,
            _GGUF_TYPE_INT32: self._i32,
            _GGUF_TYPE_FLOAT32: self._f32,
            _GGUF_TYPE_BOOL: self._bool,
            _GGUF_TYPE_STRING: self._string,
            _GGUF_TYPE_UINT64: self._u64,
            _GGUF_TYPE_INT64: self._i64,
            _GGUF_TYPE_FLOAT64: self._f64,
        }
        if vtype in dispatch:
            return dispatch[vtype]()
        if vtype == _GGUF_TYPE_ARRAY:
            item_type = self._u32()
            count = self._u64()
            # Read the full array but cap stored output at 8 elements
            result = []
            for i in range(count):
                v = self._value(item_type)
                if i < 8:
                    result.append(v)
            return result
        raise ValueError(f"Unknown GGUF value type: {vtype}")

    # ── Public parse method ────────────────────────────────────────────────

    def parse(self) -> _GGUFParser:
        with open(self.path, "rb") as f:
            self._buf = f.read(self._max)

        self._pos = 0

        magic = self._read(4)
        if magic != GGUF_MAGIC:
            raise ValueError(f"Not a GGUF file: {self.path!r}  (magic={magic!r})")

        self.version = self._u32()
        if self.version not in (1, 2, 3):
            raise ValueError(f"Unsupported GGUF version {self.version} in {self.path!r}")

        if self.version == 1:
            self.n_tensors = self._u32()
            self.n_kv = self._u32()
        else:
            self.n_tensors = self._u64()
            self.n_kv = self._u64()

        for _ in range(self.n_kv):
            key = self._string()
            vtype = self._u32()
            val = self._value(vtype)
            self.metadata[key] = val

        return self


def probe_gguf(path: Path) -> dict:
    """
    Read a GGUF file's header and return a summary dict:

      {
        "path":          str,
        "arch":          str,   # e.g. "mistral", "qwen2" — from general.architecture
        "hidden_dim":    int,   # {arch}.embedding_length
        "family":        str,   # canonical family name
        "variant":       str,   # size label (e.g. "7B", "1.5B", "custom-2304")
        "rosetta_ready": bool,  # True if arch is in our known base map
        "gguf_version":  int,
        "n_tensors":     int,
        "metadata":      dict,  # scalar/string keys only (arrays excluded)
      }
    """
    parser = _GGUFParser(path).parse()
    meta = parser.metadata
    arch = meta.get("general.architecture", "unknown")

    hidden_dim: int | None = None
    for key_tmpl in GGUF_DIM_KEYS:
        key = key_tmpl.format(arch=arch)
        if key in meta:
            hidden_dim = int(meta[key])
            break

    info = BASE_ARCH_INFO.get(arch)
    variant = "unknown"
    if info and hidden_dim is not None:
        variant = info["variants"].get(hidden_dim, f"custom-{hidden_dim}")

    clean_meta = {k: v for k, v in meta.items() if not isinstance(v, list)}

    # #11 MoE detection: expert_count from GGUF metadata
    expert_count = 0
    expert_count_key = f"{arch}.expert_count"
    if expert_count_key in meta:
        expert_count = int(meta[expert_count_key])

    return {
        "path": str(path),
        "arch": arch,
        "hidden_dim": hidden_dim,
        "family": info["family"] if info else arch,
        "variant": variant,
        "rosetta_ready": arch in BASE_ARCH_INFO and hidden_dim is not None,
        "expert_count": expert_count,  # #11 — 0 for dense models, >0 for MoE
        "gguf_version": parser.version,
        "n_tensors": parser.n_tensors,
        "metadata": clean_meta,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Model Registry — ~/.determinex/models.yaml
# ─────────────────────────────────────────────────────────────────────────────

"""
Registry entry format (YAML):
  models:
    determinex-sentinel-v3:
      path: "${DETERMINEX_MODELS_DIR:-~/determinex-models}/determinex-sentinel-v3-lora.gguf"
      base_path: "${DETERMINEX_MODELS_DIR:-~/determinex-models}/determinex-sentinel-base-q8.gguf"
      arch: "mistral"
      hidden_dim: 4096
      family: "mistral"
      variant: "7B"
      ollama_name: "determinex-sentinel-v3"
      scores:
        public: null
        micro_eval: null
        calibration: null
        composite: null
      roles:
        oracle: 0.0
        architect: 0.0
        builder: 0.0
        monitor: 0.0
      registered_at: "2026-04-14"
      tags: []
"""


def _load_registry() -> dict:
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not REGISTRY_PATH.exists():
        return {"version": "1.0.0", "models": {}}
    with open(REGISTRY_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    data.setdefault("version", "1.0.0")
    data.setdefault("models", {})
    return data


def _save_registry(registry: dict) -> None:
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
        yaml.dump(registry, f, default_flow_style=False, sort_keys=False)


def register_model(
    name: str,
    gguf_path: Path,
    base_path: Path | None = None,
    ollama_name: str | None = None,
    tags: list[str] | None = None,
    force: bool = False,
) -> dict:
    """
    Register a GGUF model. Probes the header for arch/dim automatically.
    Returns the new registry entry.
    """
    from datetime import date

    if not gguf_path.exists():
        raise FileNotFoundError(f"GGUF not found: {gguf_path}")

    info = probe_gguf(gguf_path)
    registry = _load_registry()

    if name in registry["models"] and not force:
        raise ValueError(f"'{name}' already registered. Use --force to overwrite.")

    entry: dict = {
        "path": str(gguf_path),
        "arch": info["arch"],
        "hidden_dim": info["hidden_dim"],
        "family": info["family"],
        "variant": info["variant"],
        "ollama_name": ollama_name or name,
        "scores": {
            "public": None,
            "micro_eval": None,
            "calibration": None,
            "composite": None,
        },
        "roles": {
            "oracle": 0.0,
            "architect": 0.0,
            "builder": 0.0,
            "monitor": 0.0,
        },
        "registered_at": str(date.today()),
        "tags": tags or [],
    }

    if base_path is not None:
        entry["base_path"] = str(base_path)

    registry["models"][name] = entry
    _save_registry(registry)
    return entry


def update_scores(name: str, **scores) -> dict:
    """
    Update benchmark scores for a registered model and recompute the composite.
    Composite = 0.3 * public + 0.5 * micro_eval + 0.2 * calibration
    Returns the updated scores dict.
    """
    registry = _load_registry()
    if name not in registry["models"]:
        raise KeyError(f"Model '{name}' not registered.")

    s = registry["models"][name]["scores"]
    for k, v in scores.items():
        if k in s:
            s[k] = float(v)

    pub = s.get("public")
    mev = s.get("micro_eval")
    cal = s.get("calibration")
    if all(x is not None for x in [pub, mev, cal]):
        s["composite"] = 0.3 * pub + 0.5 * mev + 0.2 * cal

    _save_registry(registry)
    return s


def get_model(name: str) -> dict | None:
    return _load_registry()["models"].get(name)


def list_models() -> list[dict]:
    return [{"name": k, **v} for k, v in _load_registry()["models"].items()]


def best_for_role(role: str, exclude: list[str] | None = None) -> dict | None:
    """
    Return the registry entry with the highest composite score for a given role.
    Role: "oracle" | "architect" | "builder" | "monitor"
    Falls back to micro_eval if composite not yet computed.
    """
    models = list_models()
    exclude = exclude or []
    eligible = [m for m in models if m["name"] not in exclude]

    def _score(m: dict) -> float:
        s = m.get("scores", {})
        if s.get("composite") is not None:
            return float(s["composite"])
        if s.get("micro_eval") is not None:
            return float(s["micro_eval"])
        return 0.0

    eligible.sort(key=_score, reverse=True)
    return eligible[0] if eligible else None


# ─────────────────────────────────────────────────────────────────────────────
# MLP Architecture — 2-layer, GELU + LayerNorm, Xavier init
# Shared between loader (inference) and training script
# ─────────────────────────────────────────────────────────────────────────────


def build_mlp(d_in: int, d_out: int, d_hidden: int | None = None) -> torch.nn.Module:
    """
    Standard Rosetta Stone projection block:
      d_in → d_hidden (GELU + LayerNorm) → d_out

    d_hidden defaults to max(d_in, d_out) — wide enough to express nonlinear
    manifold alignment without excessive parameter count.

    Xavier init with gain=0.02: starts small to prevent runaway projections
    before the first gradient steps.
    """
    import torch.nn as nn

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
# Rosetta Stone File Protection
# ─────────────────────────────────────────────────────────────────────────────


def _enforce_readonly(path: Path) -> None:
    """Remove write bits from a Rosetta Stone file (chmod 444)."""
    mode = path.stat().st_mode
    if mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH):
        try:
            new_mode = mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
            os.chmod(str(path), new_mode)
        except PermissionError:
            print(
                f"[WARN] Cannot enforce read-only on {path} — check file ownership.",
                file=sys.stderr,
            )


def _compute_weights_sha256(ckpt: dict) -> str:
    """
    Deterministic SHA256 over all weight tensors in the checkpoint.
    Excludes the "sha256" key itself (bootstrap problem).
    Keys iterated in sorted order for reproducibility.
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


def _verify_sha256(path: Path, expected: str) -> None:
    """
    Verify the checkpoint's SHA256 matches the embedded value.
    Raises ValueError on mismatch — file is corrupted or tampered.
    """
    import torch

    if not expected:
        print(f"[WARN] No SHA256 in {path.name} — skipping integrity check.", file=sys.stderr)
        return

    ckpt = torch.load(str(path), map_location="cpu", weights_only=True)
    actual = _compute_weights_sha256(ckpt)
    if actual != expected:
        raise ValueError(
            f"Rosetta Stone integrity FAILED: {path.name}\n"
            f"  Expected SHA256: {expected}\n"
            f"  Actual   SHA256: {actual}\n"
            "File may be corrupted or tampered with. Re-download from a trusted source."
        )


def seal_rosetta(path: Path) -> str:
    """
    Seal a newly written Rosetta Stone:
      1. Load the checkpoint
      2. Compute SHA256 of all weight tensors
      3. Embed it as ckpt["sha256"]
      4. Save back
      5. chmod 444

    Returns the hex SHA256 string.
    Called by train_rosetta_bases.py after the training run completes.
    """
    import torch

    ckpt = torch.load(str(path), map_location="cpu", weights_only=True)
    sha = _compute_weights_sha256(ckpt)
    ckpt["sha256"] = sha
    torch.save(ckpt, str(path))
    _enforce_readonly(path)
    print(f"Sealed: {path.name}  SHA256={sha[:16]}...")
    return sha


# ─────────────────────────────────────────────────────────────────────────────
# RosettaStone — Runtime Loader and Projector
# ─────────────────────────────────────────────────────────────────────────────


class RosettaStone:
    """
    Runtime interface to a trained rosetta_vN.pt file.

    Checkpoint structure:
      {
        "llama_encoder":    state_dict,   # MLP: llama_dim → D_ROSETTA
        "llama_decoder":    state_dict,   # MLP: D_ROSETTA → llama_dim
        "mistral_encoder":  state_dict,
        "mistral_decoder":  state_dict,
        ... (one pair per trained arch)
        "dims":             {"llama": 4096, "mistral": 4096, ...},
        "version":          "1.0.0",
        "sha256":           "<hex>",
        "anchor":           "jina-embeddings-v2-base-code",  # or "sentence-transformers/all-MiniLM-L6-v2"
        "d_rosetta":        4096,
      }

    v1 projection model: input embedding space (soft prefix).
    Two matrix ops, runs in microseconds on CPU.

    Usage:
      stone = RosettaStone.load("~/.determinex/rosetta/rosetta_v1.pt")
      h_tgt = stone.project(h_src, source_arch="mistral", target_arch="qwen2")
      # h_src: [seq_len, 4096]  →  h_tgt: [seq_len, 3584]
    """

    def __init__(self, path: Path, ckpt: dict):
        self.path = path
        self.version = ckpt.get("version", "unknown")
        self.anchor = ckpt.get("anchor", "unknown")
        self.d_rosetta = int(ckpt.get("d_rosetta", D_ROSETTA))
        self.dims: dict[str, int] = ckpt.get("dims", {})
        self._encoders: dict[str, Any] = {}
        self._decoders: dict[str, Any] = {}

    @classmethod
    def load(cls, path: Path, verify: bool = True) -> RosettaStone:
        """
        Load and validate a Rosetta Stone file.
          - Enforces read-only on disk
          - Verifies SHA256 integrity
          - Instantiates all encoder/decoder MLPs
        """
        import torch

        path = Path(path).expanduser()
        if not path.exists():
            raise FileNotFoundError(
                f"Rosetta Stone not found: {path}\n"
                f"Run train_rosetta_bases.py on RunPod to generate it."
            )

        _enforce_readonly(path)

        ckpt = torch.load(str(path), map_location="cpu", weights_only=True)
        stone = cls(path, ckpt)

        if verify:
            _verify_sha256(path, ckpt.get("sha256", ""))

        # Fix C — Version compatibility check
        loaded_version = ckpt.get("version", "unknown")
        if loaded_version != "1.0.0":
            print(
                f"[ROSETTA] WARNING: Loaded version {loaded_version} but current is 1.0.0 "
                "— recalibration recommended",
                file=sys.stderr,
            )

        stone._instantiate_mlps(ckpt)
        return stone

    def _instantiate_mlps(self, ckpt: dict) -> None:

        # Build arch→(enc_key, dec_key, dim) map from known arches + any novel ones in ckpt
        arch_map: dict[str, tuple[str, str, int]] = {}
        for arch, info in BASE_ARCH_INFO.items():
            arch_map[arch] = (
                info["encoder_key"],
                info["decoder_key"],
                self.dims.get(arch, info["default_dim"]),
            )

        # Auto-detect novel arches stored in ckpt that aren't in BASE_ARCH_INFO
        for key in ckpt:
            if key.endswith("_encoder"):
                arch = key[: -len("_encoder")]
                if arch not in arch_map and arch in self.dims:
                    arch_map[arch] = (key, f"{arch}_decoder", self.dims[arch])

        for arch, (enc_key, dec_key, dim) in arch_map.items():
            if enc_key in ckpt:
                enc = build_mlp(dim, self.d_rosetta)
                enc.load_state_dict(ckpt[enc_key])
                enc.eval()
                self._encoders[arch] = enc

            if dec_key in ckpt:
                dec = build_mlp(self.d_rosetta, dim)
                dec.load_state_dict(ckpt[dec_key])
                dec.eval()
                self._decoders[arch] = dec

    def _infer_dim(self, arch: str) -> int | None:
        """
        Fallback dimension inference: read the encoder's first weight shape.
        encoder weight shape is [d_rosetta, d_src], so d_src = shape[1].
        """
        if arch in self._encoders:
            try:
                # Sequential[0] is the first Linear layer
                weight = self._encoders[arch][0].weight  # shape: [d_hidden, d_src]
                inferred = weight.shape[1]
                print(
                    f"[ROSETTA] Unknown arch dim for '{arch}', inferred {inferred} from weight shape",
                    file=sys.stderr,
                )
                return inferred
            except (IndexError, AttributeError):
                pass
        return None

    # ── Core API ──────────────────────────────────────────────────────────

    def encode(self, h: torch.Tensor, arch: str) -> torch.Tensor:
        """
        Encode from `arch` hidden space → Rosetta space.
        h: [seq_len, arch_dim]  →  [seq_len, D_ROSETTA]
        """
        import torch

        if arch not in self._encoders:
            # Fix A — try dim inference fallback before raising
            inferred = self._infer_dim(arch)
            if inferred is None:
                raise KeyError(
                    f"No encoder for '{arch}'. Trained arches: {self.supported_arches()}\n"
                    "Re-train rosetta_bases with this architecture included."
                )
        with torch.no_grad():
            return self._encoders[arch](h)

    def decode(self, h: torch.Tensor, arch: str) -> torch.Tensor:
        """
        Decode from Rosetta space → `arch` hidden space.
        h: [seq_len, D_ROSETTA]  →  [seq_len, arch_dim]
        """
        import torch

        if arch not in self._decoders:
            # Fix A — try dim inference fallback before raising
            inferred = self._infer_dim(arch)
            if inferred is None:
                raise KeyError(
                    f"No decoder for '{arch}'. Trained arches: {self.supported_arches()}"
                )
        with torch.no_grad():
            return self._decoders[arch](h)

    def project(
        self,
        h: torch.Tensor,
        source_arch: str,
        target_arch: str,
    ) -> torch.Tensor:
        """
        Project hidden state: source_arch space → Rosetta space → target_arch space.
        Two MLP ops. Runs on CPU, completes in microseconds.

        #15 Cross-Tokenizer Alignment Fracture Guard:

        Different tokenizers (SentencePiece vs. Tiktoken BPE) produce DIFFERENT
        hidden state sequences for the SAME input text because they disagree on
        subword boundaries.  "authentication" might be ["auth", "ent", "ication"]
        on Model A  but ["authen", "tication"] on Model B.  The Rosetta encoder
        was trained on model A's boundary pattern — if you feed it model B's
        hidden states, the positional alignment breaks and the encoder outputs
        noise instead of signal through the GELU.

        This is a HARD assertion, not a warning.  A poisoned soft prefix injected
        into the target model causes catastrophic hallucination — the model treats
        the random vector as an instruction embedding and generates based on it.

        Safe caller pattern:
          h = model_A.embed(tokens)  # [seq, dim_A]
          assert h.shape[-1] == stone.dims.get("model_A_arch", dim_A)
          soft = stone.project(h, "mistral", "qwen2")  # [seq, dim_qwen2]
        """
        import torch

        # #15: Strict dimensional assertion — silent garbage is worse than a crash.
        expected_dim = self.dims.get(source_arch)
        if expected_dim is None:
            info = BASE_ARCH_INFO.get(source_arch)
            if info:
                expected_dim = info["default_dim"]

        if expected_dim is not None and h.shape[-1] != expected_dim:
            raise ValueError(
                f"#15 TOKENIZER ALIGNMENT FRACTURE: "
                f"source_arch='{source_arch}' expects hidden_dim={expected_dim}, "
                f"but input tensor has shape {list(h.shape)} (last dim={h.shape[-1]}). "
                f"This usually means the wrong model's hidden states were passed to "
                f"project(). The Rosetta encoder will produce garbage if dimensions "
                f"don't match — halting to prevent silent hallucination injection."
            )

        # #15: Enforce BF16 → FP32 promotion before MLP forward pass.
        # BF16 has only 7 bits of mantissa (vs FP32's 23). The GELU activation
        # in the encoder MLP amplifies rounding noise in BF16 — a 1e-3 error
        # in the input becomes a 5e-2 error in the Rosetta latent, which then
        # gets decoded into an entirely different region of the target space.
        if h.dtype == torch.bfloat16:
            h = h.float()

        return self.decode(self.encode(h, source_arch), target_arch)

    def broadcast(
        self,
        h: torch.Tensor,
        source_arch: str,
        targets: list[str] | None = None,
    ) -> dict[str, torch.Tensor]:
        """
        Encode once → decode to all target architectures.
        Efficient for Hive Mind broadcast topology (Oracle → all roles simultaneously).

        Returns {arch: projected_tensor} for each target.
        """
        import torch

        h_rosetta = self.encode(h, source_arch)
        if targets is None:
            targets = self.supported_arches()

        result = {}
        with torch.no_grad():
            for arch in targets:
                if arch in self._decoders and arch != source_arch:
                    result[arch] = self._decoders[arch](h_rosetta)
        return result

    def supported_arches(self) -> list[str]:
        """Architectures with at least an encoder trained."""
        return sorted(self._encoders.keys())

    def load_family_extension(self, path: Path | str, *, verify: bool = True) -> str:
        """
        Load one architecture's encoder/decoder from a standalone `family_<arch>.pt`
        file (produced by scripts/export_rosetta_families.py) and register it into
        this already-loaded RosettaStone, without needing to re-load the full
        rosetta_vN.pt. This is what determinex_registry.py's dynamic registry
        client calls after downloading a new/updated family delta.

        Family file format (see export_rosetta_families.py):
          {
            "arch": "<arch_key>",
            "dim":  <int>,
            "<arch>_encoder": state_dict,   # MLP: dim -> d_rosetta
            "<arch>_decoder": state_dict,   # MLP: d_rosetta -> dim
            "d_rosetta": <int>,             # must match this stone's d_rosetta
            "version": "<str>",
            "sha256": "<hex, tensor-content hash excluding this key>",
          }

        Returns the arch key that was activated.
        """
        import torch

        path = Path(path).expanduser()
        ckpt = torch.load(str(path), map_location="cpu", weights_only=True)

        arch = ckpt.get("arch")
        if not arch or not isinstance(arch, str):
            raise ValueError(f"family extension {path} is missing a valid 'arch' key")

        if verify:
            expected = ckpt.get("sha256", "")
            actual = _compute_weights_sha256(ckpt)
            if not expected or actual != expected:
                raise ValueError(
                    f"family extension {path} failed integrity check "
                    f"(expected {expected!r}, computed {actual!r}) -- corrupted or tampered."
                )

        family_d_rosetta = int(ckpt.get("d_rosetta", self.d_rosetta))
        if family_d_rosetta != self.d_rosetta:
            raise ValueError(
                f"family extension '{arch}' was trained with d_rosetta={family_d_rosetta}, "
                f"but this stone uses d_rosetta={self.d_rosetta} -- incompatible hub dimension."
            )

        dim = ckpt.get("dim")
        if not isinstance(dim, int) or dim <= 0:
            raise ValueError(f"family extension {path} is missing a valid 'dim' key")

        enc_key, dec_key = f"{arch}_encoder", f"{arch}_decoder"
        if enc_key not in ckpt or dec_key not in ckpt:
            raise ValueError(f"family extension {path} is missing '{enc_key}' or '{dec_key}'")

        enc = build_mlp(dim, self.d_rosetta)
        enc.load_state_dict(ckpt[enc_key])
        enc.eval()
        self._encoders[arch] = enc

        dec = build_mlp(self.d_rosetta, dim)
        dec.load_state_dict(ckpt[dec_key])
        dec.eval()
        self._decoders[arch] = dec

        self.dims[arch] = dim
        return arch

    def __repr__(self) -> str:
        return (
            f"RosettaStone(version={self.version!r}, "
            f"anchor={self.anchor!r}, "
            f"d_rosetta={self.d_rosetta}, "
            f"arches={self.supported_arches()})"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Discovery — locate installed Rosetta Stone files
# ─────────────────────────────────────────────────────────────────────────────


def find_rosetta_files(extra_dirs: list[Path] | None = None) -> list[Path]:
    """
    Search standard locations for rosetta_v*.pt files.
    Returns list sorted newest-version-first.
    """
    # LEGACY_ROSETTA_DIR is searched too, and this is not cosmetic.
    #
    # The Citadel -> Determinex rename moved ROSETTA_DIR from ~/.citadel/rosetta to
    # ~/.determinex/rosetta. The 1.68 GB rosetta_v1.pt does not live in git
    # (.gitignore excludes *.pt, correctly -- it is a model weight), so nothing
    # carried it across and nothing reported that it had been left behind. The
    # bridge simply reported itself unavailable, which looked like a feature that
    # was never finished rather than an artifact orphaned by a rename.
    #
    # Found 2026-07-28 at the old path, intact: stored weights hash matched its
    # own recomputed hash, and it covers SEVEN arches (llama, mistral, qwen2, phi3,
    # deepseek2, qwen2_1b5, qwen2_3b) -- more than the five on record.
    search = [ROSETTA_DIR, LEGACY_ROSETTA_DIR, Path.cwd()]
    if extra_dirs:
        search.extend(extra_dirs)

    found: list[Path] = []
    for d in search:
        if d.exists():
            found.extend(d.glob("rosetta_v*.pt"))

    def _ver(p: Path) -> int:
        try:
            return int(p.stem.replace("rosetta_v", ""))
        except ValueError:
            return 0

    return sorted(set(found), key=_ver, reverse=True)


def load_latest_rosetta(verify: bool = True) -> RosettaStone | None:
    """Load the highest-version rosetta_v*.pt available. Returns None if none found."""
    files = find_rosetta_files()
    if not files:
        return None
    chosen = files[0]
    if LEGACY_ROSETTA_DIR in chosen.parents:
        # Loud on purpose: it works, but it is sitting in the pre-rename directory
        # and the next cleanup of ~/.citadel would delete it.
        logging.getLogger("rosetta").warning(
            "Loaded %s from the pre-rename directory %s. Move it to %s so a cleanup "
            "of the old path cannot delete it.",
            chosen.name,
            LEGACY_ROSETTA_DIR,
            ROSETTA_DIR,
        )
    return RosettaStone.load(chosen, verify=verify)


# ─────────────────────────────────────────────────────────────────────────────
# Local Adapter Support — per-rig fine-tune corrections (~/.determinex/rosetta/adapters/)
# ─────────────────────────────────────────────────────────────────────────────


def save_adapter(name: str, data: dict) -> Path:
    """
    Save a local adapter (user-specific fine-tune correction).
    Adapters are WRITABLE — they're the user's own refinements.
    Stored at ~/.determinex/rosetta/adapters/{name}.pt
    """
    import torch

    ADAPTERS_DIR.mkdir(parents=True, exist_ok=True)
    path = ADAPTERS_DIR / f"{name}.pt"
    torch.save(data, str(path))
    return path


def load_adapter(name: str) -> dict | None:
    """Load a local adapter by name. Returns None if not found."""
    import torch

    path = ADAPTERS_DIR / f"{name}.pt"
    if not path.exists():
        return None
    return torch.load(str(path), map_location="cpu", weights_only=True)


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────


def _cmd_probe(args: argparse.Namespace) -> None:
    path = Path(args.gguf_path)
    if not path.exists():
        print(f"ERROR: File not found: {path}")
        sys.exit(1)

    info = probe_gguf(path)

    print(f"\nGGUF Probe: {path.name}")
    print(f"  Architecture : {info['arch']}")
    print(f"  Hidden dim   : {info['hidden_dim']}")
    print(f"  Family       : {info['family']}")
    print(f"  Variant      : {info['variant']}")
    print(f"  GGUF version : {info['gguf_version']}")
    print(f"  Tensors      : {info['n_tensors']}")
    if info["rosetta_ready"]:
        print("  Rosetta ready: YES")
    else:
        print(f"  Rosetta ready: NO  (arch '{info['arch']}' not in known base set)")
        print("  Hint: if this is a known base, add it to BASE_ARCH_INFO in determinex_rosetta.py")

    if args.verbose:
        print("\n  Raw GGUF metadata:")
        for k, v in sorted(info["metadata"].items()):
            print(f"    {k} = {v!r}")

    # Fix B — --force-dim override
    if hasattr(args, "force_dim") and args.force_dim is not None:
        print(
            f"\n  --force-dim override: {args.force_dim} (replaces detected {info['hidden_dim']})"
        )


def _cmd_register(args: argparse.Namespace) -> None:
    path = Path(args.gguf_path)
    base_path = Path(args.base_path) if args.base_path else None
    tags = [t.strip() for t in args.tags.split(",")] if args.tags else []

    entry = register_model(
        name=args.name,
        gguf_path=path,
        base_path=base_path,
        ollama_name=args.ollama_name,
        tags=tags,
        force=args.force,
    )

    print(f"\nRegistered '{args.name}':")
    print(f"  Arch       : {entry['arch']}")
    print(f"  Hidden dim : {entry['hidden_dim']}")
    print(f"  Variant    : {entry['variant']}")
    print(f"  Rosetta    : {'ready' if entry['arch'] in BASE_ARCH_INFO else 'unknown arch'}")
    print(f"  Registry   : {REGISTRY_PATH}")

    # Auto-generate a hardware-calibrated Modelfile for Ollama and surface any
    # hardware warnings so users know what to expect before the first inference.
    try:
        import sys as _sys

        _sys.path.insert(0, str(Path(__file__).resolve().parent))
        from hive.hardware import generate_modelfile, get_vram_warnings

        modelfile_path = path.parent / f"Modelfile.{args.name}"
        modelfile_path.write_text(generate_modelfile(path))
        ollama_name = args.ollama_name or args.name
        print(f"  Modelfile  : {modelfile_path}")
        print("  Register with Ollama:")
        print(f'    ollama create {ollama_name} -f "{modelfile_path}"')

        # Hardware warnings — only shown when a real issue is detected.
        # Suppressed entirely on hardware that can handle the model without issue.
        hw_warnings = get_vram_warnings(path)
        if hw_warnings:
            print("\n  ⚠  Hardware notices for this model:")
            for w in hw_warnings:
                print(f"     • {w}")
    except Exception as exc:
        print(f"  [WARN] Modelfile auto-generation failed: {exc}")


def _cmd_list(args: argparse.Namespace) -> None:
    models = list_models()
    if not models:
        print("No models registered.")
        print("Run: python determinex_rosetta.py register <name> <gguf_path>")
        return

    print(f"\n{'NAME':<32} {'ARCH':<12} {'DIM':<6} {'VARIANT':<10} {'MICRO':>6} {'COMP':>7}")
    print("─" * 78)
    for m in models:
        s = m.get("scores", {})
        mev = f"{s['micro_eval']:.3f}" if s.get("micro_eval") is not None else "—"
        cmp = f"{s['composite']:.3f}" if s.get("composite") is not None else "—"
        dim = str(m.get("hidden_dim") or "?")
        print(f"{m['name']:<32} {m['arch']:<12} {dim:<6} {m['variant']:<10} {mev:>6} {cmp:>7}")


def _cmd_verify(args: argparse.Namespace) -> None:
    import torch

    path = Path(args.rosetta_path).expanduser()
    if not path.exists():
        print(f"ERROR: {path} not found")
        sys.exit(1)

    ckpt = torch.load(str(path), map_location="cpu", weights_only=True)
    expected = ckpt.get("sha256", "")

    try:
        _verify_sha256(path, expected)
        print(f"OK  {path.name}  SHA256={expected[:16]}...")
    except ValueError as e:
        print(f"FAIL  {e}")
        sys.exit(1)

    print(f"  Version    : {ckpt.get('version', '?')}")
    print(f"  Anchor     : {ckpt.get('anchor', '?')}")
    print(f"  D_Rosetta  : {ckpt.get('d_rosetta', '?')}")
    print(f"  Dims       : {ckpt.get('dims', {})}")
    arches = sorted(k.replace("_encoder", "") for k in ckpt if k.endswith("_encoder"))
    print(f"  Arches     : {arches}")


def _cmd_project(args: argparse.Namespace) -> None:
    """Load a .pt tensor, project from src → tgt arch, save result. For testing."""
    import torch

    stone = load_latest_rosetta()
    if stone is None:
        print("ERROR: No rosetta_v*.pt found in standard locations.")
        print(f"Searched: {ROSETTA_DIR}, {Path.cwd()}")
        sys.exit(1)

    print(stone)

    h = torch.load(args.input, map_location="cpu")
    h_out = stone.project(h, args.src, args.tgt)

    out_path = args.output or args.input.replace(".pt", f"_{args.src}→{args.tgt}.pt")
    torch.save(h_out, out_path)
    print(f"Projected {args.src}{list(h.shape)} → {args.tgt}{list(h_out.shape)}")
    print(f"Saved: {out_path}")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="determinex_rosetta",
        description=(
            "Rosetta Stone — Universal Latent Bridge\n"
            "Models never pass text to each other. They pass tensors through here."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="command", required=True)

    # probe
    pp = sub.add_parser("probe", help="Inspect a GGUF file's architecture and hidden dim")
    pp.add_argument("gguf_path")
    pp.add_argument("-v", "--verbose", action="store_true", help="Show full metadata")
    pp.add_argument(
        "--force-dim",
        type=int,
        default=None,
        help="Override detected hidden dim (for GGUFs where header parser fails)",
    )
    pp.set_defaults(func=_cmd_probe)

    # register
    rp = sub.add_parser("register", help="Register a GGUF model in ~/.determinex/models.yaml")
    rp.add_argument("name", help="Short name (e.g. determinex-sentinel-v3)")
    rp.add_argument("gguf_path", help="Path to GGUF file")
    rp.add_argument(
        "--base-path",
        dest="base_path",
        default=None,
        help="Path to base GGUF (if name is a LoRA adapter)",
    )
    rp.add_argument(
        "--ollama-name",
        dest="ollama_name",
        default=None,
        help="Ollama model name (defaults to <name>)",
    )
    rp.add_argument("--tags", default="", help="Comma-separated tags")
    rp.add_argument("--force", action="store_true", help="Overwrite existing entry")
    rp.set_defaults(func=_cmd_register)

    # list
    lp = sub.add_parser("list", help="List all registered models with scores")
    lp.set_defaults(func=_cmd_list)

    # verify
    vp = sub.add_parser("verify", help="Verify Rosetta Stone file SHA256 integrity")
    vp.add_argument("rosetta_path", help="Path to rosetta_vN.pt")
    vp.set_defaults(func=_cmd_verify)

    # project
    xp = sub.add_parser("project", help="Project a tensor from one arch to another (testing)")
    xp.add_argument("--src", required=True, help="Source arch (e.g. mistral)")
    xp.add_argument("--tgt", required=True, help="Target arch (e.g. qwen2)")
    xp.add_argument("--input", required=True, help="Input .pt tensor file")
    xp.add_argument("--output", default=None, help="Output .pt file (auto-named if omitted)")
    xp.set_defaults(func=_cmd_project)

    return p


if __name__ == "__main__":
    parser = _build_parser()
    args = parser.parse_args()
    args.func(args)
