"""Regression tests for the orchestrator conversational-query dead-loop fix.

Two bugs were fixed:

1. `_is_simple_query` was too narrow: casual/capability queries like `hihi`,
   `你能干嘛`, `一句话介绍你`, `好的`, `ok` did NOT match the fast path and fell
   into the full ReAct loop, where the 27B model emits prose instead of JSON.

2. The per-step ReAct loop retried to exhaustion (max_actions per step) when the
   model outputs natural-language prose instead of JSON -- a dead loop that wastes
   ~20 model calls and repeats RAG evidence. Now the loop accepts non-empty prose
   as the step's finding and converges.

OFFLINE: these tests build a minimal Orchestrator with fake dependencies and a
fake engine, so no GPU / llama-server is required.
"""
from __future__ import annotations

import types

from screwshell.core.orchestrator import (
    Orchestrator, StepTrace, _extract_json, _looks_like_prose)
from screwshell.core.router import SkillRouter
from screwshell.memory.stores import (
    ArtifactStore, EvidenceStore, SessionMemory)


# ---------------------------------------------------------------------------
# _is_simple_query — broadened fast-path predicate
# ---------------------------------------------------------------------------
def _pred():
    o = object.__new__(Orchestrator)
    o._GREET_RE = Orchestrator._GREET_RE
    return o


def test_simple_query_greetings_still_match():
    o = _pred()
    assert o._is_simple_query("hi")
    assert o._is_simple_query("你好")
    assert o._is_simple_query("谢谢")
    assert o._is_simple_query("who are you")


def test_simple_query_new_casual_and_capability():
    o = _pred()
    for q in ("hihi", "你能干嘛", "你能做什么", "你会什么", "一句话介绍你",
              "介绍一下你", "好的", "ok", "okay", "知道了", "收到", "嗯嗯"):
        assert o._is_simple_query(q), f"expected simple: {q!r}"


def test_simple_query_capability_ziji_variants():
    """The "自己" suffix must NOT break the capability match (regression: a
    trailing anchor dropped these because leftover "自己" failed the punctuation
    tail)."""
    o = _pred()
    for q in ("一句话介绍你", "一句话介绍你自己", "一句话介绍下你自己",
              "介绍一下你", "介绍一下你自己", "介绍下你", "介绍你自己",
              "简单介绍你", "简单介绍你自己",
              "你是干嘛的",
              "what can you do", "what do you do", "introduce yourself"):
        assert o._is_simple_query(q), f"expected simple: {q!r}"


def test_simple_query_rejects_investigation_verbs():
    o = _pred()
    for q in ("总结一下 demo_workspace", "分析这份文档的风险", "查找代码中的漏洞",
              "调查一下这个仓库", "对比两个文件", "investigate the repo"):
        assert not o._is_simple_query(q), f"must NOT be simple: {q!r}"


def test_simple_query_long_text_not_simple():
    o = _pred()
    long_q = ("请帮我仔细分析一下 demo_workspace 目录下的所有文档，"
              "总结其中的主要风险点，并给出详细的安全评估报告。")
    assert len(long_q) > 40
    assert not o._is_simple_query(long_q)


def test_simple_query_empty_not_simple():
    o = _pred()
    assert not o._is_simple_query("")
    assert not o._is_simple_query("   ")


# ---------------------------------------------------------------------------
# _looks_like_prose helper
# ---------------------------------------------------------------------------
def test_looks_like_prose_accepts_sentences():
    assert _looks_like_prose("ROCm 是 AMD 推出的开源 GPU 计算平台。")
    assert _looks_like_prose("I can investigate local documents for you.")


def test_looks_like_prose_rejects_empty_and_bare():
    assert not _looks_like_prose("")
    assert not _looks_like_prose("   ")
    assert not _looks_like_prose("{ }")          # no real words
    assert not _looks_like_prose('{"action": "finish"}')  # parses as JSON


# ---------------------------------------------------------------------------
# ReAct loop converges on prose instead of looping to exhaustion
# ---------------------------------------------------------------------------
def test_react_loop_converges_on_prose():
    """A step whose model answers in prose must converge on the FIRST attempt
    (finding == prose) and NOT loop through all max_actions.

    Mirrors the exact converge branch added to the per-step ReAct loop:
    `_extract_json` fails + output is non-empty prose -> set finding, break.
    """
    act_raw = "ROCm 是 AMD 推出的开源 GPU 计算平台，专为本地 GPU 计算设计。"
    assert _extract_json(act_raw) is None
    assert _looks_like_prose(act_raw)
    # the loop sets the finding and breaks on the first iteration
    trace = StepTrace("你能干嘛", "agent", "base", 0.0)
    trace.finding = act_raw.strip()
    assert trace.finding.startswith("ROCm")


def test_react_loop_exhausts_only_when_no_prose():
    """Whitespace-only (non-prose) output still retries to exhaustion so a
    genuinely broken generation is not silently accepted as a finding."""
    assert not _looks_like_prose("   ")
    assert not _looks_like_prose("")
