"""Unit tests for the autotune preset mapper (tune-loop plan, Todo 4)."""
from __future__ import annotations

import pytest

from screwshell.autotune.mapper import preset, parse_natural_language, TuneGoal
from screwshell.gateway.capacity import MAX_CTX_TOKENS


def test_preset_vram_shrinks_ctx_floor():
    g = preset("vram", {"n_ctx": 98304})
    assert isinstance(g, TuneGoal)
    assert g.param == "n_ctx"
    assert g.target < 98304
    assert g.target >= 4096


def test_preset_vram_floor_at_4096():
    g = preset("vram", {"n_ctx": 4096})
    assert g.target == 4096          # never below the floor


def test_preset_ctx_capped_at_max():
    g = preset("ctx", {"n_ctx": 200000})
    assert g.param == "n_ctx"
    assert g.target <= MAX_CTX_TOKENS


def test_preset_ctx_grows_toward_cap():
    g = preset("ctx", {"n_ctx": 8192})
    assert g.target == MAX_CTX_TOKENS


def test_preset_speed_doubles_batch():
    g = preset("speed", {"n_batch": 256})
    assert g.param == "n_batch"
    assert g.target >= 512
    assert g.target == max(256 * 2, 512)


def test_preset_balance_no_change():
    g = preset("balance", {"n_ctx": 98304})
    assert g.param == "__none__"
    assert g.target is None


def test_preset_unknown_raises():
    with pytest.raises(ValueError):
        preset("bogus", {})


def test_parse_nl_not_implemented():
    with pytest.raises(NotImplementedError):
        parse_natural_language("make it faster please")
