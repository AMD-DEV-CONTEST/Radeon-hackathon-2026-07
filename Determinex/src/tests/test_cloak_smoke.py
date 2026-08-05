"""
tests/test_cloak_smoke.py — Project Cloak smoke tests.

These are coarse-grained regression tests for the privacy-critical paths:
  - SymbolMap.build is deterministic across re-runs
  - obfuscate_source replaces every private identifier with x_NNNN
  - restore_patch reverses the obfuscation on a unified diff
  - Round-trip obfuscate → restore preserves file content
  - Single-char identifiers and dunders are NOT obfuscated
  - AI-invented x_NNNN tokens (not in symbol map) pass through unchanged

The cloak module is privacy-critical; failures here have leaked code in the
past (see CLAUDE.md §"Pipeline hardening sprint"). Keep these green.
"""

from __future__ import annotations

import ast

import pytest
from determinex_cloak import CloakContext, CloakObfuscationError, SymbolMap
from determinex_cloak.classifier import _IdentifierCollector
from determinex_cloak.restoration import restore_file_content, restore_patch
from determinex_cloak.transformer import obfuscate_source

_SAMPLE = (
    "def compute_total(price, qty):\n"
    "    discount = 0.1 if qty > 10 else 0.0\n"
    "    return price * qty * (1 - discount)\n"
    "\n"
    "class OrderRecord:\n"
    "    def __init__(self, sku, qty):\n"
    "        self.sku = sku\n"
    "        self.qty = qty\n"
)


def _collect(source: str, safe: frozenset[str]) -> frozenset[str]:
    tree = ast.parse(source)
    c = _IdentifierCollector(safe)
    c.visit(tree)
    return frozenset(c.found)


def test_symbol_map_is_deterministic():
    ids = frozenset({"alpha", "Bravo", "charlie"})
    m1 = SymbolMap.build(ids)
    m2 = SymbolMap.build(ids)
    assert m1.forward == m2.forward
    assert m1.reverse == m2.reverse
    # x_NNNN tokens use 4-digit zero-padded indices
    assert all(v.startswith("x_") and len(v) == 6 for v in m1.forward.values())


def test_symbol_map_round_trip():
    ids = frozenset({"foo", "bar", "baz"})
    m = SymbolMap.build(ids)
    for name in ids:
        tok = m.forward[name]
        assert m.reverse[tok] == name


def test_obfuscate_replaces_private_identifiers():
    private = _collect(_SAMPLE, safe=frozenset({"price"}))
    assert "compute_total" in private
    assert "OrderRecord" in private
    assert "price" not in private  # in safe-list
    sm = SymbolMap.build(private)
    obf = obfuscate_source(_SAMPLE, sm)
    # original names must not appear
    for name in private:
        assert name not in obf, f"{name!r} leaked through obfuscation"
    # safe identifier preserved
    assert "price" in obf
    # x_NNNN tokens appear
    assert "x_" in obf


def test_obfuscate_preserves_single_chars_and_dunders():
    private = _collect(_SAMPLE, safe=frozenset())
    # Single-char names and dunders are unconditionally skipped by classifier
    assert "i" not in private
    assert "__init__" not in private


def test_restore_file_content_round_trip():
    private = _collect(_SAMPLE, safe=frozenset({"price"}))
    sm = SymbolMap.build(private)
    obf = obfuscate_source(_SAMPLE, sm)
    restored = restore_file_content(obf, sm)
    assert restored == _SAMPLE


def test_restore_patch_with_unified_diff():
    private = frozenset({"compute_total", "OrderRecord", "discount"})
    sm = SymbolMap.build(private)
    # synthetic diff
    patch = (
        "--- a/app.py\n"
        "+++ b/app.py\n"
        "@@ -1,2 +1,2 @@\n"
        f"-def {sm.forward['compute_total']}(price, qty):\n"
        f"+def {sm.forward['compute_total']}(price, qty, fee=0):\n"
    )
    restored, err = restore_patch(patch, sm)
    assert err is None, err
    assert restored is not None
    # diff headers untouched
    assert restored.startswith("--- a/app.py\n+++ b/app.py\n@@")
    # body restored
    assert "compute_total" in restored
    assert "x_" not in restored


def test_restore_patch_passes_through_unknown_tokens():
    """AI-invented x_NNNN tokens not in the symbol map must NOT raise."""
    sm = SymbolMap.build(frozenset({"known_func"}))
    patch = (
        "--- a/app.py\n"
        "+++ b/app.py\n"
        "@@ -1 +1,2 @@\n"
        f" def {sm.forward['known_func']}():\n"
        "+    return x_9999()  # AI invented this token\n"
    )
    restored, err = restore_patch(patch, sm)
    assert err is None
    assert restored is not None
    # known token restored
    assert "known_func" in restored
    # unknown token preserved verbatim
    assert "x_9999" in restored


def test_restore_patch_fails_on_empty():
    sm = SymbolMap.build(frozenset({"a"}))
    restored, err = restore_patch("", sm)
    assert restored is None
    assert err is not None


# ────────────────────────────────────────────────────────────────────────────
# Fail-closed invariant tests — these protect the central privacy claim.
#
# Before this fix, obfuscate_source caught Exception and returned the original
# (plaintext) source with only a log.warning. Any AST/regex crash during
# obfuscation would silently leak proprietary identifiers to the next API call.
# The fix makes every obfuscation failure raise CloakObfuscationError so callers
# MUST decide to abort the API call rather than send unredacted source.
# ────────────────────────────────────────────────────────────────────────────


class _BoomSymbolMap:
    """SymbolMap stand-in whose `.forward` raises on attribute access.

    Triggers the internal `_process_source_text` or the post-process regex loop
    to crash, which `obfuscate_source` must convert into CloakObfuscationError
    (not silently return the plaintext source).
    """

    def __init__(self, source_len: int = 0):
        self._n = source_len

    @property
    def forward(self):  # any access blows up
        raise RuntimeError("induced obfuscation crash")


def test_obfuscate_source_fail_closed_on_internal_error():
    """obfuscate_source must raise CloakObfuscationError, NEVER return the plaintext."""
    src = "def secret_function():\n    return 'proprietary'\n"
    with pytest.raises(CloakObfuscationError) as excinfo:
        obfuscate_source(src, _BoomSymbolMap(source_len=len(src)))  # type: ignore[arg-type]
    # Structured fields populated for audit
    assert excinfo.value.cause is not None
    assert excinfo.value.source_len == len(src)
    # The plaintext leaked nowhere — the exception message must not embed it
    assert "secret_function" not in str(excinfo.value)
    assert "proprietary" not in str(excinfo.value)


def test_obfuscate_source_str_fail_closed_propagates_through_context():
    """CloakContext.obfuscate_source_str must propagate the structured error.

    Previously this wrapper would return whatever obfuscate_source returned
    (silently re-cached). Now any crash inside the leaf raises through, and the
    wrapper attaches the cache_key as `path` for audit context.
    """
    ctx = CloakContext(
        instance_id="test-instance",
        symbol_map=_BoomSymbolMap(source_len=10),  # type: ignore[arg-type]
        star_import_warnings=[],
    )
    with pytest.raises(CloakObfuscationError) as excinfo:
        ctx.obfuscate_source_str("def x(): pass\n", cache_key="src/critical.py")
    assert excinfo.value.path == "src/critical.py"
    # No partial result was cached under the failing key
    assert "src/critical.py" not in ctx._file_cache


def test_cloak_obfuscation_error_to_dict_redacts_source():
    """The structured error dict must not contain the source it failed on."""
    err = CloakObfuscationError(
        path="src/proprietary.py",
        cause=ValueError("induced"),
        source_len=1234,
    )
    d = err.to_dict()
    assert d["error"] == "CloakObfuscationError"
    assert d["path"] == "src/proprietary.py"
    assert d["cause_type"] == "ValueError"
    assert d["source_len"] == 1234
    # No source content fields — failure record carries only metadata
    for v in d.values():
        if isinstance(v, str):
            assert "proprietary" not in v.lower() or v == "src/proprietary.py"
