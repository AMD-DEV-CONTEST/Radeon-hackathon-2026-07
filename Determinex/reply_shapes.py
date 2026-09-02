#!/usr/bin/env python3
"""determinex_reply_shapes.py — extract code from a model reply, whatever shape it arrives in.

WHY THIS EXISTS. Three separate times this harness measured p=0.000 for a model that could do
the task, and every time the cause was the reply shape, not the model:

  1. The reply began with prose ("Certainly! Below is...") and the extractor only stripped a
     fence when the reply STARTED with one, so exec() got the prose and failed on the first
     word.
  2. The request went to /v1/completions, which applies no chat template. Instruct models
     degrade badly through it; small ones collapse.
  3. Reasoning models (Qwen3 and kin) emit <think>...</think> before answering. With a tight
     token budget the whole budget went to the reasoning trace and the answer never arrived.
     Qwen3-4B read 0.000 on a task its 1.7B sibling solved - that asymmetry was the only clue.

A wrong p is worse than a missing one: it looks like a finding. So the shape handling belongs
in one place that every caller uses, and it detects rather than being told.

    from determinex_reply_shapes import extract_code, budget_for
"""

from __future__ import annotations

import re

#: Families that emit a reasoning trace before the answer and therefore need a larger budget.
#: Matched against the served model id, lowercased. Add rather than special-case at call sites.
REASONING_HINTS = (
    "qwen3", "qwq", "deepseek-r1", "-r1-", "reasoner", "thinking", "marco-o1", "skywork-o1",
)

#: Tags reasoning models wrap their scratchpad in. Both halves matter: an UNTERMINATED opener
#: means the budget ran out mid-thought, and the answer never came - which must not be read as
#: "the model produced nothing useful".
_THINK = re.compile(r"<(think|thinking|reasoning)>.*?</\1>", re.S | re.I)
_THINK_OPEN = re.compile(r"^.*?</(think|thinking|reasoning)>", re.S | re.I)
_FENCE = re.compile(r"```(?:python|py)?[ \t]*\n(.*?)```", re.S)
_CODE_START = re.compile(r"\s*(def |class |import |from )")


def is_reasoning_model(model_id: str) -> bool:
    """Does this model emit a scratchpad before answering?

    Detected from the id rather than configured per run, because the failure it prevents is
    silent: nothing errors, the model simply appears incapable.
    """
    m = (model_id or "").lower()
    return any(h in m for h in REASONING_HINTS)


def budget_for(model_id: str, base: int = 400) -> int:
    """Token budget, widened for models that think out loud before answering.

    A reasoning model given a non-reasoning budget spends all of it reasoning. That is not a
    capability measurement, it is a measurement of the budget.
    """
    return max(base, 1600) if is_reasoning_model(model_id) else base


def strip_reasoning(text: str) -> str:
    """Remove a scratchpad, closed or truncated."""
    t = _THINK.sub("", text)
    if re.search(r"</(think|thinking|reasoning)>", t, re.I):
        t = _THINK_OPEN.sub("", t)
    return t


def extract_code(text: str) -> str:
    """The code a model meant to hand back, from any of the shapes they use.

    Order matters. Reasoning is stripped first: a scratchpad often contains a fenced block the
    model was only CONSIDERING, and matching that would score a draft the model itself
    rejected.
    """
    t = strip_reasoning(text or "")
    m = _FENCE.search(t)
    if m:
        return m.group(1).strip()
    lines = t.splitlines()
    for i, ln in enumerate(lines):
        if _CODE_START.match(ln):
            return "\n".join(lines[i:]).strip()
    return t.strip()


def _selftest() -> int:
    """Every shape that has actually cost us a false zero, plus controls."""
    cases = [
        ("bare", "def f():\n    return 1", "def f():"),
        ("fenced", "```python\ndef f():\n    return 1\n```", "def f():"),
        ("prose then fence",
         "Certainly! Below is a function.\n\n```python\ndef f():\n    return 1\n```\nHope this helps.",
         "def f():"),
        ("think then fence",
         "<think>\nMaybe an f-string?\n</think>\n\n```python\ndef f():\n    return 1\n```",
         "def f():"),
        ("think containing a REJECTED draft",
         "<think>\n```python\ndef wrong():\n    pass\n```\nno, better:\n</think>\n"
         "```python\ndef f():\n    return 1\n```",
         "def f():"),
        ("truncated think, answer after",
         "Okay so I should...\n</think>\ndef f():\n    return 1",
         "def f():"),
        ("prose only, no code", "I cannot help with that.", "I cannot help"),
    ]
    bad = 0
    for name, raw, expect in cases:
        got = extract_code(raw)
        ok = got.startswith(expect)
        if not ok:
            bad += 1
        print(f"  {'ok  ' if ok else 'FAIL'} {name:<34} -> {got.splitlines()[0][:44] if got else '(empty)'}")
    for mid, want in (("Qwen/Qwen3-4B", True), ("Qwen/Qwen2.5-Coder-7B-Instruct", False),
                      ("deepseek-ai/DeepSeek-R1-Distill-Qwen-7B", True),
                      ("bigcode/starcoder2-3b", False)):
        got = is_reasoning_model(mid)
        ok = got == want
        bad += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} detect {mid.split('/')[-1]:<34} reasoning={got}")
    print(f"\n  {'all shapes handled' if not bad else f'{bad} FAILURE(S)'}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
