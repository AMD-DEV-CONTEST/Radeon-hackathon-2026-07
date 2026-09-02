"""Torch-free Rosetta projection: export to .npz, run with numpy.

WHY
---
`rosetta_v1.pt` is 1.68 GB of float32 torch tensors, and the shipped engine binary
deliberately excludes torch (including it would take the binary from 111 MB to
~2 GB). So the latent bridge worked in a source install and was unavailable in the
product -- the exact "works on my machine" split this project exists to avoid.

The projection network does not need torch. Each encoder/decoder is:

    Linear(d_in -> d_h, bias=False) -> GELU -> LayerNorm(d_h) -> Linear(d_h -> d_out, bias=False)

That is four numpy operations. This module exports the weights to per-architecture
`.npz` shards and runs the forward pass with numpy alone, which:

  * removes torch from the runtime entirely (numpy is already a dependency),
  * halves the bytes by storing float16 and computing in float32 (accuracy below
    is measured, not assumed),
  * lets the IDE fetch ONLY the architecture pair it needs -- about 60 MB instead
    of 1.68 GB -- which is what makes distribution over HuggingFace practical.

EXACTNESS
---------
The numpy forward must match torch's, so the details are pinned deliberately:
  * `nn.GELU()` defaults to `approximate='none'`, i.e. the exact erf form
    `0.5 * x * (1 + erf(x / sqrt(2)))` -- NOT the tanh approximation.
  * `nn.LayerNorm` uses the BIASED variance (divide by N, not N-1) and
    `eps=1e-5`, applied over the last dimension, with affine weight and bias.
Getting either wrong produces plausible-looking output that is quietly wrong, so
`verify_parity()` compares against torch directly and reports the real error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

MANIFEST_NAME = "rosetta_npz_manifest.json"
LAYERNORM_EPS = 1e-5


# ── numpy forward pass ───────────────────────────────────────────────────────


def _gelu_exact(x: np.ndarray) -> np.ndarray:
    """torch.nn.GELU(approximate='none'). The tanh approximation differs by ~1e-3,
    which is small per-element and large enough to move a cosine similarity."""
    # numpy has no erf and scipy is deliberately not a dependency, so this uses
    # math.erf (C-implemented) over a flat view. These are one-shot last-token
    # projections -- a few thousand elements -- not a training loop, so the Python
    # level iteration is not worth trading exactness for. The tanh approximation
    # would be faster and would NOT match torch's default.
    from math import erf, sqrt

    flat = np.asarray(x, dtype=np.float64).reshape(-1)
    erfs = np.fromiter((erf(v / sqrt(2.0)) for v in flat), dtype=np.float64, count=flat.size)
    return 0.5 * np.asarray(x, dtype=np.float32) * (1.0 + erfs.reshape(x.shape).astype(np.float32))


def _layer_norm(x: np.ndarray, weight: np.ndarray, bias: np.ndarray) -> np.ndarray:
    mean = x.mean(axis=-1, keepdims=True)
    # Biased variance, matching torch. Using ddof=1 here would be a silent,
    # dimension-dependent error.
    var = ((x - mean) ** 2).mean(axis=-1, keepdims=True)
    return (x - mean) / np.sqrt(var + LAYERNORM_EPS) * weight + bias


def mlp_forward(
    x: np.ndarray, w0: np.ndarray, ln_w: np.ndarray, ln_b: np.ndarray, w3: np.ndarray
) -> np.ndarray:
    """The projection block, in float32 regardless of stored dtype."""
    h = x.astype(np.float32) @ w0.astype(np.float32).T
    h = _gelu_exact(h)
    h = _layer_norm(h, ln_w.astype(np.float32), ln_b.astype(np.float32))
    return h @ w3.astype(np.float32).T


# ── export ───────────────────────────────────────────────────────────────────


def export_npz(
    ckpt_path: Path,
    out_dir: Path,
    dtype: str = "float16",
) -> dict:
    """Export a rosetta_vN.pt into per-architecture .npz shards plus a manifest.

    Requires torch, and is meant to run in a dev checkout -- the point is that the
    RESULT needs no torch.
    """
    import torch

    ckpt = torch.load(str(ckpt_path), map_location="cpu", weights_only=True)
    arches = list(ckpt.get("arches") or [])
    dims = dict(ckpt.get("dims") or {})
    if not arches:
        raise SystemExit(f"{ckpt_path} declares no 'arches'; refusing to guess")

    out_dir.mkdir(parents=True, exist_ok=True)
    np_dtype = np.float16 if dtype == "float16" else np.float32
    shards: dict[str, dict] = {}

    for arch in arches:
        payload: dict[str, np.ndarray] = {}
        for role in ("encoder", "decoder"):
            sd = ckpt.get(f"{arch}_{role}")
            if sd is None:
                continue
            for key in ("0.weight", "2.weight", "2.bias", "3.weight"):
                if key not in sd:
                    raise SystemExit(
                        f"{arch}_{role} is missing '{key}'. The checkpoint's module "
                        "layout is not the expected Linear/GELU/LayerNorm/Linear."
                    )
                # LayerNorm's affine params stay float32: one vector each, so the
                # size cost is nil, and they are the most precision-sensitive part
                # of the block.
                keep_f32 = key.startswith("2.")
                arr = sd[key].detach().cpu().numpy()
                payload[f"{role}.{key}"] = arr.astype(np.float32 if keep_f32 else np_dtype)
        if not payload:
            continue
        shard = out_dir / f"{ckpt_path.stem}_{arch}.npz"
        np.savez(shard, **payload)
        digest = hashlib.sha256(shard.read_bytes()).hexdigest()
        shards[arch] = {
            "file": shard.name,
            "bytes": shard.stat().st_size,
            "sha256": digest,
            "dim": dims.get(arch),
        }
        print(f"  {arch:12} {shard.stat().st_size / 1_000_000:7.1f} MB  {digest[:12]}")

    manifest = {
        "source_checkpoint": ckpt_path.name,
        "source_weights_sha256": ckpt.get("sha256"),
        "d_rosetta": ckpt.get("d_rosetta"),
        "anchor": ckpt.get("anchor"),
        "storage_dtype": dtype,
        "layernorm_eps": LAYERNORM_EPS,
        "gelu": "exact_erf",
        "dims": dims,
        "shards": shards,
    }
    (out_dir / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


# ── torch-free runtime ───────────────────────────────────────────────────────


class NumpyRosettaStone:
    """Runtime projector over exported .npz shards. Loads a shard on first use."""

    def __init__(self, directory: Path, manifest: dict):
        self.dir = Path(directory)
        self.manifest = manifest
        self._cache: dict[str, dict[str, np.ndarray]] = {}

    @classmethod
    def load(cls, directory: Path) -> NumpyRosettaStone:
        directory = Path(directory)
        mpath = directory / MANIFEST_NAME
        if not mpath.is_file():
            raise FileNotFoundError(f"No {MANIFEST_NAME} in {directory}")
        return cls(directory, json.loads(mpath.read_text(encoding="utf-8")))

    def supported_arches(self) -> list[str]:
        return sorted(self.manifest.get("shards", {}).keys())

    def _shard(self, arch: str) -> dict[str, np.ndarray]:
        if arch in self._cache:
            return self._cache[arch]
        entry = self.manifest.get("shards", {}).get(arch)
        if entry is None:
            raise KeyError(f"No shard for '{arch}'. Have: {self.supported_arches()}")
        path = self.dir / entry["file"]
        if not path.is_file():
            raise FileNotFoundError(
                f"Shard for '{arch}' is listed in the manifest but missing at {path}. "
                "Fetch it before projecting."
            )
        # Integrity check: a truncated download is a plausible failure for a
        # 60 MB file fetched over the network, and silently projecting through
        # half a weight matrix would produce confident nonsense.
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != entry["sha256"]:
            raise ValueError(
                f"Shard {path.name} failed its checksum (expected {entry['sha256'][:12]}, "
                f"got {digest[:12]}). Re-download it."
            )
        with np.load(path) as z:
            self._cache[arch] = {k: z[k] for k in z.files}
        return self._cache[arch]

    def _run(self, x: np.ndarray, arch: str, role: str) -> np.ndarray:
        w = self._shard(arch)
        try:
            return mlp_forward(
                x,
                w[f"{role}.0.weight"],
                w[f"{role}.2.weight"],
                w[f"{role}.2.bias"],
                w[f"{role}.3.weight"],
            )
        except KeyError as e:
            raise KeyError(f"No {role} for '{arch}' in its shard ({e})") from e

    def encode(self, x: np.ndarray, arch: str) -> np.ndarray:
        """[seq, arch_dim] -> [seq, d_rosetta]"""
        return self._run(np.asarray(x), arch, "encoder")

    def decode(self, x: np.ndarray, arch: str) -> np.ndarray:
        """[seq, d_rosetta] -> [seq, arch_dim]"""
        return self._run(np.asarray(x), arch, "decoder")

    def project(self, x: np.ndarray, from_arch: str, to_arch: str) -> np.ndarray:
        return self.decode(self.encode(x, from_arch), to_arch)


# ── parity check ─────────────────────────────────────────────────────────────


def verify_parity(ckpt_path: Path, npz_dir: Path, arch: str | None = None, seq: int = 4) -> int:
    """Compare the numpy path against torch on real weights. Returns an exit code.

    TWO checks, because one of them cannot do the job alone -- and the first version
    of this function got that wrong.

    It compared the shipped float16 shards to torch with a 2e-2 threshold and
    reported "PARITY OK" at 1.45e-03. But a WRONG GELU (tanh approximation instead
    of torch's exact erf) moves the output by ~1.2e-03 relative -- the same order as
    float16 storage noise. So the check could not distinguish a broken forward pass
    from expected precision loss, and a canary that swapped the GELU passed it. A
    check that cannot fail for the thing it is checking is worse than no check.

      STRICT  -- float32 weights taken straight from the checkpoint, threshold 1e-05.
                 Isolates the MATH. A wrong GELU, an unbiased variance or a wrong eps
                 fails here by two orders of magnitude.
      STORAGE -- the actual float16 shards, threshold 2e-02. Confirms the shipped
                 precision is acceptable. Informational, not a maths check.
    """
    import torch
    import torch.nn as nn

    ckpt = torch.load(str(ckpt_path), map_location="cpu", weights_only=True)
    stone = NumpyRosettaStone.load(npz_dir)
    dims = ckpt.get("dims") or {}
    arches = [arch] if arch else stone.supported_arches()
    rng = np.random.default_rng(0)

    def torch_ref(sd: dict, x: np.ndarray) -> np.ndarray:
        d_in = x.shape[-1]
        net = nn.Sequential(
            nn.Linear(d_in, sd["0.weight"].shape[0], bias=False),
            nn.GELU(),
            nn.LayerNorm(sd["0.weight"].shape[0]),
            nn.Linear(sd["0.weight"].shape[0], sd["3.weight"].shape[0], bias=False),
        )
        net.load_state_dict(sd)
        net.eval()
        with torch.no_grad():
            return net(torch.from_numpy(x)).numpy()

    strict_worst, strict_where = 0.0, ""
    store_worst, store_where = 0.0, ""

    for a in arches:
        d = dims.get(a)
        if not d:
            continue
        for role, d_in in (("encoder", d), ("decoder", ckpt.get("d_rosetta"))):
            sd = ckpt.get(f"{a}_{role}")
            if sd is None:
                continue
            x = rng.standard_normal((seq, d_in), dtype=np.float32)
            expected = torch_ref(sd, x)
            denom = float(np.abs(expected).mean()) or 1.0

            # STRICT: float32 weights from the checkpoint -- no storage loss at all.
            f32 = mlp_forward(
                x,
                sd["0.weight"].numpy().astype(np.float32),
                sd["2.weight"].numpy().astype(np.float32),
                sd["2.bias"].numpy().astype(np.float32),
                sd["3.weight"].numpy().astype(np.float32),
            )
            rel_strict = float(np.abs(f32 - expected).max() / denom)
            if rel_strict > strict_worst:
                strict_worst, strict_where = rel_strict, f"{a}/{role}"

            # STORAGE: what actually ships.
            got = stone.encode(x, a) if role == "encoder" else stone.decode(x, a)
            rel_store = float(np.abs(got - expected).max() / denom)
            if rel_store > store_worst:
                store_worst, store_where = rel_store, f"{a}/{role}"

            print(f"  {a:12} {role:8} strict {rel_strict:.2e}   float16 {rel_store:.2e}")

    STRICT_MAX, STORAGE_MAX = 1e-5, 2e-2
    print()
    print(f"STRICT  worst {strict_worst:.2e} at {strict_where or '-'} (max {STRICT_MAX:.0e})")
    print(f"STORAGE worst {store_worst:.2e} at {store_where or '-'} (max {STORAGE_MAX:.0e})")

    failed = False
    if strict_worst > STRICT_MAX:
        print("FAIL: the numpy forward pass does not match torch. This is a MATHS bug,")
        print("      not precision -- check GELU (exact erf, not tanh), LayerNorm's")
        print("      biased variance, and eps=1e-5.")
        failed = True
    if store_worst > STORAGE_MAX:
        print("FAIL: float16 storage error is larger than expected for these weights.")
        failed = True
    if failed:
        return 1
    print("PARITY OK -- maths matches torch exactly; float16 storage within budget.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("export", help="Export a .pt checkpoint to .npz shards")
    e.add_argument("checkpoint")
    e.add_argument("--out", required=True)
    e.add_argument("--dtype", choices=["float16", "float32"], default="float16")

    v = sub.add_parser("verify", help="Check the numpy path against torch")
    v.add_argument("checkpoint")
    v.add_argument("--npz", required=True)
    v.add_argument("--arch")

    i = sub.add_parser("info", help="Show what an exported directory contains")
    i.add_argument("--npz", required=True)

    args = ap.parse_args()
    if args.cmd == "export":
        m = export_npz(Path(args.checkpoint), Path(args.out), args.dtype)
        total = sum(s["bytes"] for s in m["shards"].values())
        print(f"\n{len(m['shards'])} shards, {total / 1_000_000:.1f} MB total -> {args.out}")
        return 0
    if args.cmd == "verify":
        return verify_parity(Path(args.checkpoint), Path(args.npz), args.arch)
    stone = NumpyRosettaStone.load(Path(args.npz))
    print(json.dumps(stone.manifest, indent=2)[:1200])
    return 0


if __name__ == "__main__":
    sys.exit(main())
