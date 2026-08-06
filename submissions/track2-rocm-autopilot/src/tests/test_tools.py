import json

from autopilot.tools import Ctx, dispatch


def test_power_cap_out_of_range_rejected():
    out = json.loads(dispatch("set_power_cap", {"watts": 20}, Ctx.for_tests()))
    assert out["error"] == "rejected"
    assert "range" in out["reason"]


def test_batch_out_of_range_rejected():
    out = json.loads(dispatch(
        "run_benchmark",
        {"max_num_seqs": 9999, "enable_prefix_caching": True, "concurrency": 8},
        Ctx.for_tests()))
    assert out["error"] == "rejected"


def test_benchmark_dispatches_with_pending_power_cap():
    ctx = Ctx.for_tests()
    dispatch("set_power_cap", {"watts": 220}, ctx)  # gfx1100 bounds: (100, 241)
    out = json.loads(dispatch(
        "run_benchmark",
        {"max_num_seqs": 64, "enable_prefix_caching": True, "concurrency": 8},
        ctx))
    assert out["cfg"]["power_cap_w"] == 220


def test_unknown_tool_is_soft_error():
    out = json.loads(dispatch("rm_rf", {}, Ctx.for_tests()))
    assert "unknown tool" in out["error"]


def test_restart_server_whitelist_and_dispatch():
    ctx = Ctx.for_tests()
    ctx.extra["restart_fn"] = lambda b: True
    ok = json.loads(dispatch("restart_server", {"attention_backend": "TRITON_ATTN"}, ctx))
    assert ok["restarted"] is True
    bad = json.loads(dispatch("restart_server", {"attention_backend": "rm -rf /"}, ctx))
    assert bad["error"] == "rejected"
