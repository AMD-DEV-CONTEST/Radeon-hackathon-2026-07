"""
tests/test_rosetta_family_extension.py — RosettaStone.load_family_extension() +
export_rosetta_families.py's export format.

Uses small SYNTHETIC checkpoints (dim=8, d_rosetta=16) built in-memory, not the real
1.3GB rosetta_v1.pt (which lives on T: drive, is not committed, and would make this
suite depend on external storage). Requires torch; skipped entirely if unavailable,
matching test_rosetta_smoke.py's existing pattern.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

_IMPORT_ERROR = ""
try:
    import torch  # noqa: F401
    from determinex_rosetta import RosettaStone, _compute_weights_sha256, build_mlp

    _TORCH_AVAILABLE = True
except ImportError as _e:
    _TORCH_AVAILABLE = False
    _IMPORT_ERROR = str(_e)

pytestmark = pytest.mark.skipif(
    not _TORCH_AVAILABLE,
    reason=f"torch/determinex_rosetta not importable: {_IMPORT_ERROR}",
)

D_ROSETTA_TEST = 16


def _make_family_ckpt(
    arch: str, dim: int, d_rosetta: int = D_ROSETTA_TEST, *, seed: int = 0
) -> dict:
    """Build a real, small, trained-looking family checkpoint in the exact format
    export_rosetta_families.py produces -- encoder/decoder state dicts + metadata +
    an embedded tensor-content sha256."""
    torch.manual_seed(seed)
    enc = build_mlp(dim, d_rosetta)
    dec = build_mlp(d_rosetta, dim)
    ckpt = {
        "arch": arch,
        "dim": dim,
        f"{arch}_encoder": enc.state_dict(),
        f"{arch}_decoder": dec.state_dict(),
        "d_rosetta": d_rosetta,
        "version": "1.0.0",
    }
    ckpt["sha256"] = _compute_weights_sha256(ckpt)
    return ckpt


def _fresh_stone(d_rosetta: int = D_ROSETTA_TEST) -> RosettaStone:
    return RosettaStone(
        Path("nonexistent"),
        {
            "version": "1.0.0",
            "anchor": "test",
            "d_rosetta": d_rosetta,
            "dims": {},
        },
    )


def test_load_family_extension_activates_the_arch():
    ckpt = _make_family_ckpt("testarch", dim=8)
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "family_testarch.pt"
        torch.save(ckpt, str(path))

        stone = _fresh_stone()
        assert stone.supported_arches() == []
        activated = stone.load_family_extension(path)
        assert activated == "testarch"
        assert "testarch" in stone.supported_arches()
        assert stone.dims["testarch"] == 8


def test_load_family_extension_encode_decode_matches_source_mlp():
    """The whole point: an extension-loaded arch must behave identically to one
    loaded via the normal full-checkpoint path (RosettaStone._instantiate_mlps)."""
    torch.manual_seed(7)
    enc = build_mlp(8, D_ROSETTA_TEST)
    dec = build_mlp(D_ROSETTA_TEST, 8)
    ckpt = {
        "arch": "testarch",
        "dim": 8,
        "testarch_encoder": enc.state_dict(),
        "testarch_decoder": dec.state_dict(),
        "d_rosetta": D_ROSETTA_TEST,
        "version": "1.0.0",
    }
    ckpt["sha256"] = _compute_weights_sha256(ckpt)

    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "family_testarch.pt"
        torch.save(ckpt, str(path))
        stone = _fresh_stone()
        stone.load_family_extension(path)

        h = torch.randn(3, 8)
        h_rosetta = stone.encode(h, "testarch")
        h_back = stone.decode(h_rosetta, "testarch")

        # Ground truth: run the SAME source MLPs directly.
        enc.eval()
        dec.eval()
        with torch.no_grad():
            expected_rosetta = enc(h)
            expected_back = dec(expected_rosetta)

        assert torch.equal(h_rosetta, expected_rosetta)
        assert torch.equal(h_back, expected_back)


def test_load_family_extension_rejects_tampered_file():
    ckpt = _make_family_ckpt("testarch", dim=8)
    ckpt["sha256"] = "0" * 64  # wrong hash
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "family_testarch.pt"
        torch.save(ckpt, str(path))
        stone = _fresh_stone()
        with pytest.raises(ValueError, match="integrity check"):
            stone.load_family_extension(path, verify=True)


def test_load_family_extension_can_skip_verification():
    ckpt = _make_family_ckpt("testarch", dim=8)
    ckpt["sha256"] = "0" * 64  # wrong hash, but verify=False should not care
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "family_testarch.pt"
        torch.save(ckpt, str(path))
        stone = _fresh_stone()
        activated = stone.load_family_extension(path, verify=False)
        assert activated == "testarch"


def test_load_family_extension_rejects_wrong_hub_dimension():
    """A family trained against a different d_rosetta hub can't be mixed into
    this stone -- the resulting vectors would be dimensionally meaningless."""
    ckpt = _make_family_ckpt("testarch", dim=8, d_rosetta=32)  # wrong hub dim
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "family_testarch.pt"
        torch.save(ckpt, str(path))
        stone = _fresh_stone(d_rosetta=D_ROSETTA_TEST)
        with pytest.raises(ValueError, match="d_rosetta"):
            stone.load_family_extension(path)


def test_load_family_extension_rejects_missing_arch_key():
    ckpt = _make_family_ckpt("testarch", dim=8)
    del ckpt["arch"]
    ckpt["sha256"] = _compute_weights_sha256(ckpt)
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "family_bad.pt"
        torch.save(ckpt, str(path))
        stone = _fresh_stone()
        with pytest.raises(ValueError, match="arch"):
            stone.load_family_extension(path)


def test_load_family_extension_rejects_missing_encoder_or_decoder():
    ckpt = _make_family_ckpt("testarch", dim=8)
    del ckpt["testarch_decoder"]
    ckpt["sha256"] = _compute_weights_sha256(ckpt)
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "family_bad.pt"
        torch.save(ckpt, str(path))
        stone = _fresh_stone()
        with pytest.raises(ValueError, match="testarch_decoder"):
            stone.load_family_extension(path)


def test_two_families_can_be_loaded_into_the_same_stone():
    ckpt_a = _make_family_ckpt("arch_a", dim=8, seed=1)
    ckpt_b = _make_family_ckpt("arch_b", dim=12, seed=2)
    with tempfile.TemporaryDirectory() as td:
        path_a = Path(td) / "family_arch_a.pt"
        path_b = Path(td) / "family_arch_b.pt"
        torch.save(ckpt_a, str(path_a))
        torch.save(ckpt_b, str(path_b))

        stone = _fresh_stone()
        stone.load_family_extension(path_a)
        stone.load_family_extension(path_b)
        assert set(stone.supported_arches()) == {"arch_a", "arch_b"}
        assert stone.dims["arch_a"] == 8
        assert stone.dims["arch_b"] == 12
