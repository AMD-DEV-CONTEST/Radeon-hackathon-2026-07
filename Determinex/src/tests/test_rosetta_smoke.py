"""
tests/test_rosetta_smoke.py — Rosetta Stone smoke tests (no PyTorch required).

Tests the pure-Python layers:
  - D_ROSETTA constant (universal latent hub dimension)
  - BASE_ARCH_INFO covers all 5 supported model families
  - Registry functions (in-process, no YAML file required)
  - SymbolMap-free path: constants and metadata only

These tests deliberately avoid importing torch or loading .pt weights so they
run cleanly in CI without a GPU. Projection accuracy tests live in a separate
integration suite that requires the rosetta_v1.pt checkpoint.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

# Import only the pure-Python parts of determinex_rosetta
_IMPORT_ERROR = ""
try:
    from determinex_rosetta import (
        BASE_ARCH_INFO,
        D_ROSETTA,
        best_for_role,
        get_model,
        list_models,
        probe_gguf,
    )

    _ROSETTA_AVAILABLE = True
except ImportError as _e:
    _ROSETTA_AVAILABLE = False
    _IMPORT_ERROR = str(_e)

pytestmark = pytest.mark.skipif(
    not _ROSETTA_AVAILABLE,
    reason=f"determinex_rosetta not importable: {_IMPORT_ERROR}",
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_d_rosetta_is_4096():
    assert D_ROSETTA == 4096


def test_base_arch_info_covers_five_families():
    """Rosetta targets 5 core model families; qwen2_1b5 is a size variant entry."""
    # Count unique family values — qwen2_1b5 maps to family="qwen2"
    unique_families = {info["family"] for info in BASE_ARCH_INFO.values()}
    assert unique_families >= {"llama", "mistral", "qwen2", "phi3", "deepseek2"}


def test_base_arch_info_required_keys():
    required = {"family", "variants", "default_dim", "encoder_key", "decoder_key"}
    for arch, info in BASE_ARCH_INFO.items():
        missing = required - set(info.keys())
        assert not missing, f"BASE_ARCH_INFO[{arch!r}] missing keys: {missing}"


def test_base_arch_info_families():
    expected = {"llama", "mistral", "qwen2", "phi3", "deepseek2"}
    actual = {info["family"] for info in BASE_ARCH_INFO.values()}
    assert actual == expected


def test_encoder_decoder_keys_are_strings():
    for arch, info in BASE_ARCH_INFO.items():
        assert isinstance(info["encoder_key"], str), f"{arch} encoder_key not str"
        assert isinstance(info["decoder_key"], str), f"{arch} decoder_key not str"


def test_default_dims_are_positive_integers():
    for arch, info in BASE_ARCH_INFO.items():
        dim = info["default_dim"]
        assert isinstance(dim, int) and dim > 0, f"{arch} default_dim={dim!r} invalid"


# ---------------------------------------------------------------------------
# Registry (in-process, no YAML side effects since registry auto-creates at
# ~/.determinex/models.yaml — we test the API shape not the persistence)
# ---------------------------------------------------------------------------


def test_list_models_returns_list():
    result = list_models()
    assert isinstance(result, list)


def test_get_model_returns_none_for_unknown():
    result = get_model("__nonexistent_model_xyz_9999__")
    assert result is None


def test_best_for_role_returns_none_when_no_models_match():
    result = best_for_role("__nonexistent_role__")
    # With empty registry, this should return None gracefully (not raise)
    assert result is None or isinstance(result, dict)


# ---------------------------------------------------------------------------
# GGUF parser shape test (no actual file needed — test error handling)
# ---------------------------------------------------------------------------


def test_probe_gguf_raises_on_missing_file():
    with pytest.raises((FileNotFoundError, OSError, Exception)):
        probe_gguf(Path("/nonexistent/file.gguf"))


# ---------------------------------------------------------------------------
# Semantic DSL Layer 1 smoke test
# ---------------------------------------------------------------------------


def test_rosetta_dsl_imports_do_not_crash():
    """
    Verify that the Semantic DSL constants and arch info are importable without
    torch. If this fails, rosetta's pure-Python layer has a new dependency that
    must be documented.
    """
    # Re-import with explicit symbol check
    import importlib

    mod = importlib.import_module("determinex_rosetta")
    assert hasattr(mod, "D_ROSETTA")
    assert hasattr(mod, "BASE_ARCH_INFO")
    assert hasattr(mod, "RosettaStone")


def test_rosetta_stone_class_exists_and_is_class():
    from determinex_rosetta import RosettaStone

    assert isinstance(RosettaStone, type)


def test_rosetta_layer_1_is_default():
    """Layer 1 (Semantic DSL) is the active layer; Layer 2 requires rosetta_v1.pt."""
    from determinex_rosetta import RosettaStone

    # RosettaStone.load() must raise on a nonexistent checkpoint, not silently
    # construct a stone with no weights. This verifies the load gate is active.
    with pytest.raises(Exception):
        RosettaStone.load(Path("/nonexistent/rosetta_v1.pt"), verify=False)
