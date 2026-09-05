"""Unit tests for ServerConfig first-class autotune fields (tune-loop plan, Todo 1).

No GPU / no llama-server required — pure argv-list generation.
"""
from __future__ import annotations

from screwshell.gateway.config import ServerConfig


def test_to_argv_emits_new_flags():
    c = ServerConfig(
        model_path="/m",
        flash_attn="on",
        cache_type_k="q8_0",
        cache_type_v="q8_0",
        parallel=2,
        n_batch=512,
    )
    argv = c.to_argv()
    assert "--flash-attn" in argv
    assert "--cache-type-k" in argv
    assert "--cache-type-v" in argv
    assert "--parallel" in argv
    assert "--batch-size" in argv
    # '--batch-size' must be immediately followed by the value '512'
    assert argv[argv.index("--batch-size") + 1] == "512"
    # new flags come AFTER reasoning-budget, BEFORE extra_args (extra_args empty)
    assert argv.index("--reasoning-budget") < argv.index("--flash-attn")


def test_to_argv_omits_none_and_falsy():
    c = ServerConfig(
        model_path="/m",
        flash_attn="",          # empty -> omit
        parallel=0,             # falsy -> omit
        n_batch=None,
        cache_type_k=None,
        cache_type_v=None,
    )
    argv = c.to_argv()
    assert "--batch-size" not in argv
    assert "--cache-type-k" not in argv
    assert "--cache-type-v" not in argv
    assert "--flash-attn" not in argv
    assert "--parallel" not in argv


def test_reasoning_budget_coerced():
    # regression guard: never -1 (deadlocks agentic tool calls)
    c = ServerConfig(model_path="/m", reasoning_budget=-1)
    assert c.reasoning_budget == 4096


def test_extra_args_still_last():
    c = ServerConfig(model_path="/m", parallel=4, extra_args=["--foo", "bar"])
    argv = c.to_argv()
    assert argv[-2:] == ["--foo", "bar"]
    # extra_args after the new flags
    assert argv.index("--parallel") < argv.index("--foo")


def test_to_argv_preserves_fixed_order():
    c = ServerConfig(model_path="/m", parallel=2, n_batch=256)
    argv = c.to_argv()
    fixed = ["--jinja", "--alias", "--host", "--port",
             "--ctx-size", "--n-gpu-layers", "--threads", "--reasoning-budget"]
    idxs = [argv.index(f) for f in fixed]
    assert idxs == sorted(idxs)          # fixed block keeps order
    # new conditional flags after the fixed block
    assert argv.index("--reasoning-budget") < argv.index("--parallel")
