"""The torch-free Rosetta projection path.

These tests exist because the numpy forward pass has to match torch EXACTLY, and
the first version of the parity check could not tell a wrong forward pass from
float16 storage noise: a canary that swapped torch's exact-erf GELU for the tanh
approximation moved the output by ~1.2e-03, and float16 storage noise was already
1.45e-03, so the check reported "PARITY OK" on broken maths.

The lesson is in the structure here: the maths is checked at float32 with a tight
tolerance, and storage precision is a separate, looser assertion. Mixing them is
what made the original check incapable of failing.

No torch and no 1.68 GB checkpoint required -- the reference values are computed
from the definitions.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"
for p in (str(REPO_ROOT), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from determinex_rosetta_npz import (  # noqa: E402
    LAYERNORM_EPS,
    MANIFEST_NAME,
    NumpyRosettaStone,
    _gelu_exact,
    _layer_norm,
    mlp_forward,
)

# ── the two operations that are easy to get subtly wrong ─────────────────────


def test_gelu_is_the_exact_erf_form_not_the_tanh_approximation():
    x = np.array([-3.0, -0.5, 0.0, 0.5, 3.0], dtype=np.float32)
    got = _gelu_exact(x)
    want = np.array([0.5 * v * (1.0 + math.erf(v / math.sqrt(2.0))) for v in x], dtype=np.float32)
    assert np.abs(got - want).max() < 1e-6

    # And it must NOT equal the tanh approximation, which is what torch uses only
    # when you ask for approximate='tanh'. This is the canary that fooled the
    # original parity check, so it is pinned here as a real assertion.
    tanh_form = 0.5 * x * (1.0 + np.tanh(0.7978845608 * (x + 0.044715 * x**3)))
    assert np.abs(got - tanh_form).max() > 1e-5, (
        "exact and tanh GELU came out identical; the implementation is probably "
        "using the approximation"
    )


def test_layer_norm_uses_biased_variance():
    x = np.array([[1.0, 2.0, 3.0, 4.0]], dtype=np.float32)
    w = np.ones(4, dtype=np.float32)
    b = np.zeros(4, dtype=np.float32)
    got = _layer_norm(x, w, b)

    mean = x.mean()
    biased = ((x - mean) ** 2).mean()  # torch's choice: divide by N
    want = (x - mean) / np.sqrt(biased + LAYERNORM_EPS)
    assert np.abs(got - want).max() < 1e-6

    # ddof=1 would be the silent, dimension-dependent error.
    unbiased = ((x - mean) ** 2).sum() / (x.size - 1)
    wrong = (x - mean) / np.sqrt(unbiased + LAYERNORM_EPS)
    assert np.abs(got - wrong).max() > 1e-3


def test_mlp_forward_matches_a_hand_computed_reference():
    rng = np.random.default_rng(7)
    d_in, d_h, d_out = 6, 8, 4
    w0 = rng.standard_normal((d_h, d_in)).astype(np.float32)
    lw = rng.standard_normal(d_h).astype(np.float32)
    lb = rng.standard_normal(d_h).astype(np.float32)
    w3 = rng.standard_normal((d_out, d_h)).astype(np.float32)
    x = rng.standard_normal((3, d_in)).astype(np.float32)

    h = x @ w0.T
    h = _gelu_exact(h)
    h = _layer_norm(h, lw, lb)
    want = h @ w3.T

    assert np.abs(mlp_forward(x, w0, lw, lb, w3) - want).max() < 1e-5


# ── the runtime loader ───────────────────────────────────────────────────────


def _write_shard(tmp: Path, arch: str, dim: int, d_rosetta: int, corrupt: bool = False) -> Path:
    import hashlib

    rng = np.random.default_rng(3)
    payload = {}
    for role, d_in, d_out in (("encoder", dim, d_rosetta), ("decoder", d_rosetta, dim)):
        d_h = max(d_in, d_out)
        payload[f"{role}.0.weight"] = rng.standard_normal((d_h, d_in)).astype(np.float16)
        payload[f"{role}.2.weight"] = rng.standard_normal(d_h).astype(np.float32)
        payload[f"{role}.2.bias"] = rng.standard_normal(d_h).astype(np.float32)
        payload[f"{role}.3.weight"] = rng.standard_normal((d_out, d_h)).astype(np.float16)

    shard = tmp / f"rosetta_test_{arch}.npz"
    np.savez(shard, **payload)
    digest = hashlib.sha256(shard.read_bytes()).hexdigest()
    if corrupt:
        digest = "0" * 64
    (tmp / MANIFEST_NAME).write_text(
        json.dumps(
            {
                "d_rosetta": d_rosetta,
                "storage_dtype": "float16",
                "dims": {arch: dim},
                "shards": {
                    arch: {
                        "file": shard.name,
                        "bytes": shard.stat().st_size,
                        "sha256": digest,
                        "dim": dim,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return shard


def test_round_trip_projects_through_the_shared_space(tmp_path):
    _write_shard(tmp_path, "testarch", dim=16, d_rosetta=32)
    stone = NumpyRosettaStone.load(tmp_path)

    assert stone.supported_arches() == ["testarch"]
    x = np.random.default_rng(1).standard_normal((5, 16)).astype(np.float32)
    z = stone.encode(x, "testarch")
    assert z.shape == (5, 32)
    back = stone.decode(z, "testarch")
    assert back.shape == (5, 16)
    assert np.isfinite(z).all() and np.isfinite(back).all()


def test_a_corrupted_shard_is_rejected_not_silently_projected(tmp_path):
    """A truncated 92 MB download is a realistic failure. Projecting through half a
    weight matrix would produce confident nonsense, which is worse than an error."""
    _write_shard(tmp_path, "testarch", dim=8, d_rosetta=16, corrupt=True)
    stone = NumpyRosettaStone.load(tmp_path)
    with pytest.raises(ValueError, match="checksum"):
        stone.encode(np.zeros((1, 8), dtype=np.float32), "testarch")


def test_a_missing_shard_says_so_rather_than_guessing(tmp_path):
    shard = _write_shard(tmp_path, "testarch", dim=8, d_rosetta=16)
    shard.unlink()
    stone = NumpyRosettaStone.load(tmp_path)
    with pytest.raises(FileNotFoundError, match="missing"):
        stone.encode(np.zeros((1, 8), dtype=np.float32), "testarch")


def test_unknown_arch_lists_what_is_available(tmp_path):
    _write_shard(tmp_path, "testarch", dim=8, d_rosetta=16)
    stone = NumpyRosettaStone.load(tmp_path)
    with pytest.raises(KeyError, match="testarch"):
        stone.encode(np.zeros((1, 8), dtype=np.float32), "nope")


def test_no_manifest_is_an_explicit_error(tmp_path):
    with pytest.raises(FileNotFoundError, match=MANIFEST_NAME):
        NumpyRosettaStone.load(tmp_path)


def test_the_runtime_never_imports_torch():
    """The entire point of this module: it must work where torch does not exist."""
    import determinex_rosetta_npz as mod

    src = Path(mod.__file__).read_text(encoding="utf-8")
    # Bound the slice at verify_parity: everything from the class up to it is the
    # RUNTIME. `export_npz` and `verify_parity` are dev-only tools and are
    # supposed to use torch -- a slice to end-of-file swallowed them and made this
    # test fail on correct code.
    runtime = src[src.index("class NumpyRosettaStone") : src.index("def verify_parity(")]
    assert "import torch" not in runtime, (
        "NumpyRosettaStone imports torch; the runtime must be torch-free. "
        "Only export_npz and verify_parity may use it."
    )
