"""Regression tests: the dispatcher's retry brake and optional-stage
degradation. Tonight's failure mode: an optional tool (preview) failed,
the agent retried identically three times, then blocked the build."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from foundry.tools import ToolBox


def make_toolbox(tmp_path):
    return ToolBox({"run": {"out_root": str(tmp_path)}}, "cfg.toml",
                   teacher_ctl=None)


def _failing(counter, msg="teacher exploded"):
    def boom(**kwargs):
        counter["n"] += 1
        raise RuntimeError(msg)
    return boom


def test_optional_failure_carries_continue_guidance(tmp_path):
    tb = make_toolbox(tmp_path)
    calls = {"n": 0}
    tb.tool_preview_examples = _failing(calls)
    result = tb.dispatch("preview_examples", {})
    assert result["optional_stage"] is True
    assert "continue" in result["guidance"]


def test_third_identical_attempt_never_executes(tmp_path):
    tb = make_toolbox(tmp_path)
    calls = {"n": 0}
    tb.tool_preview_examples = _failing(calls)
    tb.dispatch("preview_examples", {})
    tb.dispatch("preview_examples", {})
    third = tb.dispatch("preview_examples", {})
    assert third["skipped"] is True
    assert calls["n"] == 2, "third attempt must be short-circuited"
    assert "continue the pipeline without it" in third["guidance"]


def test_required_tool_brake_says_stop(tmp_path):
    tb = make_toolbox(tmp_path)
    calls = {"n": 0}
    tb.tool_train_student = _failing(calls, "OOM")
    tb.dispatch("train_student", {})
    tb.dispatch("train_student", {})
    third = tb.dispatch("train_student", {})
    assert third["skipped"] is True
    assert "report the failure" in third["guidance"]


def test_success_resets_streak(tmp_path):
    tb = make_toolbox(tmp_path)
    calls = {"n": 0}
    tb.tool_preview_examples = _failing(calls)
    tb.dispatch("preview_examples", {})
    tb.tool_preview_examples = lambda **k: {"ok": True}
    assert tb.dispatch("preview_examples", {}) == {"ok": True}
    tb.tool_preview_examples = _failing(calls)
    result = tb.dispatch("preview_examples", {})
    assert "skipped" not in result, "streak must reset after a success"


def test_different_error_resets_count(tmp_path):
    tb = make_toolbox(tmp_path)
    calls = {"n": 0}
    tb.tool_preview_examples = _failing(calls, "error A")
    tb.dispatch("preview_examples", {})
    tb.tool_preview_examples = _failing(calls, "error B")
    tb.dispatch("preview_examples", {})
    third = tb.dispatch("preview_examples", {})
    # two different errors: the brake should not have engaged yet
    assert calls["n"] == 3
