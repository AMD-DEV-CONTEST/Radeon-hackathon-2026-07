"""Mock engines and collaborators for the evaluation gate + local tests.

Single source of mock engines for the whole optimization program. Every class
here implements the SAME 5-method contract as ``MoLLlamaCpp`` / ``MoLEngine``
(``load_base`` / ``load_adapter`` / ``activate`` / ``chat`` / ``status``) plus
the extended ``chat(...)`` parameters (``response_format`` / ``json_schema`` /
``grammar`` / ``cache_prompt`` / ``stream`` / ``on_token``) and a *complete*
``GenStats`` including the server-style ``timings`` split. So anything that runs
against a real backend can be exercised locally with zero GPU and zero network.

Hard rule (blueprint §6.2 rule 6): **stdlib only** -- no torch / gradio / numpy
/ any third party. The real backends are torch-heavy; these are not, which is
exactly the point: the eval gate must run on a laptop with no GPU.

``build_mock_orchestrator`` is the one helper that wires a full
``Orchestrator`` from these parts. The harness and the unit tests reuse it
rather than re-assembling the graph by hand every time.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from screwshell.core.mol_types import CAP_KEYS, GenStats, SwitchRecord
from screwshell.core.orchestrator import Orchestrator
from screwshell.core.router import RouteDecision, SkillRouter
from screwshell.memory.stores import (ArtifactStore, EvidenceStore, SessionMemory)
from screwshell.tools.toolkit import ToolResult, Toolkit


# skill -> adapter name. Mirrors ``router.DEFAULT_SKILL_MAP`` so the mock routes
# to adapters the ScriptedEngine actually has registered (otherwise a route would
# return an adapter the engine cannot mount and the run degrades to base).
FAKE_SKILL_MAP = {
    "tool": "btl3", "code": "btl3", "agent": "teichai_plan",
    "security": "cybersec", "doc": "rag_n7", "base": None,
}

# Default adapters the mock engine registers (ids line up with the router above).
_FAKE_ADAPTER_DEFS = [
    ("btl3", "/l/btl3.gguf"),
    ("teichai_plan", "/l/teichai_plan.gguf"),
    ("rag_n7", "/l/rag_n7.gguf"),
    ("cybersec", "/l/cybersec.gguf"),
]


def _fake_adapters() -> dict[str, dict]:
    return {name: {"path": path, "id": i}
            for i, (name, path) in enumerate(_FAKE_ADAPTER_DEFS)}


# ----------------------------------------------------------------- engine --

class ScriptedEngine:
    """A deterministic stand-in for a llama.cpp / peft backend.

    ``script`` maps a prompt *substring* to the text that should be returned
    whenever that substring appears in the conversation. It is evaluated first
    match wins, so order the most specific needles first. Anything that matches
    nothing falls back to ``always``.

    The returned ``GenStats`` carries a *real* simulated ``timings`` split
    (computed from the injected tok/s), so the measurement gate exercises the
    same aggregation path a real server hits. This is honest: the numbers are a
    genuine property of the simulated backend, not a wall-clock guess smuggled
    in for a real one.
    """

    def __init__(self, script: Any = None, *, tok_per_s: float = 26.0,
                 prefill_tps: float = 100.0, cached_ratio: float = 0.0,
                 adapters: Optional[dict] = None, base: str = "Qwen3.6-27B",
                 always: str = "", caps: Optional[dict] = None):
        self.base_path = base
        self.adapters = adapters if adapters is not None else _fake_adapters()
        self.active_adapter: Optional[str] = None
        self.switch_log: list[SwitchRecord] = []
        self.gen_log: list[GenStats] = []
        self._script = self._normalize_script(script)
        self._always = always
        self._tok = float(tok_per_s)
        self._prefill_tps = float(prefill_tps)
        self._cached_ratio = float(cached_ratio)
        self._caps = dict(caps) if caps is not None else None
        self._warned: set[str] = set()
        self._react_calls = 0

    @staticmethod
    def _normalize_script(script: Any) -> list[tuple[str, str]]:
        if not script:
            return []
        if isinstance(script, dict):
            return [(str(k), str(v)) for k, v in script.items()]
        return [(str(k), str(v)) for k, v in script]

    def _warn_once(self, key: str, msg: str, *args: Any) -> None:
        if key in self._warned:
            return
        self._warned.add(key)
        # Fakes stay silent by default; a real engine would log this.

    # ---------- 5-method contract ----------

    def load_base(self) -> "ScriptedEngine":
        return self

    def load_adapter(self, name: str, path: str) -> dict:
        self.adapters[name] = {"path": path, "id": len(self.adapters)}
        return self.adapters[name]

    def activate(self, name: Optional[str]) -> SwitchRecord:
        prev = self.active_adapter
        if name == prev:
            rec = SwitchRecord(time.time(), prev, name, 0.0, "noop")
            self.switch_log.append(rec)
            return rec
        rec = SwitchRecord(time.time(), prev, name, 0.6, "set_adapter")
        self.active_adapter = name
        self.switch_log.append(rec)
        return rec

    def capabilities(self) -> dict:
        if self._caps is not None:
            return dict(self._caps)
        # A simulated server that supports everything and reports timings.
        caps = {k: True for k in CAP_KEYS}
        caps.update({"build": "mock", "probed": True, "reachable": True})
        return caps

    # ---------- generation ----------

    def _script_get(self, needle: str, default: str) -> str:
        """Return the scripted response for `needle`, or `default`."""
        for n, resp in self._script:
            if n == needle:
                return resp
        return default

    def _resolve_text(self, messages: list[dict]) -> str:
        """Decide what this chat call should return, by phase.

        The orchestrator issues three distinct prompts per run; we recognise
        them by a stable substring and script each:

          * plan  ("Break this into")        -> a JSON task card
          * react ("Decide the next action") -> first call a tool (so the
                                                 toolkit runs and records
                                                 citations), then finish
          * final ("Write the final answer")  -> the scripted answer

        The scripted tool call -> finish alternation is what lets the mock
        exercise the real tool/observation path (and populate
        ``CaseResult.retrieved``) without an infinite ReAct loop.
        """
        blob = "\n".join(str(m.get("content", "")) for m in messages)
        if "Break this into" in blob:
            return self._script_get(
                "Break this into",
                '{"steps": [{"desc": "investigate", "skill": "doc"}]}')
        if "Write the final answer" in blob:
            return self._script_get("Write the final answer", self._always)
        if "Decide the next action" in blob:
            self._react_calls += 1
            if self._react_calls % 2 == 1:
                return json.dumps({"action": "tool", "tool": "rag_search",
                                   "args": {"query": "investigate the question"}})
            return json.dumps({"action": "finish", "finding": "done"})
        return self._always

    def chat(self, messages: list[dict], max_new_tokens: int = 512,
             temperature: float = 0.0, enable_thinking: bool = False,
             response_format: Optional[dict] = None,
             json_schema: Optional[dict] = None,
             grammar: Optional[str] = None, cache_prompt: bool = True,
             stream: bool = False,
             on_token: Optional[Callable[[str], None]] = None,
             **_ignored: Any) -> tuple[str, GenStats]:
        """One chat completion with a fully-populated ``GenStats``.

        The leading four params are the original contract; the rest are the new
        opt-in params shared with the real backends. They are accepted and
        recorded (``constrained`` is set when a constraint was requested) but the
        mock never probes -- it already knows what it supports.
        """
        text = self._resolve_text(messages)
        constrained = bool(response_format or json_schema or grammar)

        prompt_tokens = sum(max(1, len(str(m.get("content", ""))) // 4)
                             for m in messages)
        new_tokens = max(1, len(text) // 4)
        cached = min(int(prompt_tokens * self._cached_ratio), prompt_tokens)
        prompt_n = prompt_tokens - cached

        # Simulated but genuine measurements of this fake backend.
        ttft_ms = 80.0
        prefill_ms = (prompt_n / self._prefill_tps * 1000.0
                      if self._prefill_tps > 0 else 0.0)
        decode_ms = (new_tokens / self._tok * 1000.0) if self._tok > 0 else 0.0
        dt = max(0.001, (prefill_ms + decode_ms) / 1000.0)

        if stream and on_token is not None:
            try:
                on_token(text)
            except Exception:
                pass

        stats = GenStats(
            self.active_adapter, prompt_tokens, new_tokens, round(dt, 3),
            prefill_ms=round(prefill_ms, 3),
            decode_ms=round(decode_ms, 3),
            prefill_tps=round(self._prefill_tps, 2),
            decode_tps=round(self._tok, 2),
            cached_tokens=cached, ttft_ms=ttft_ms,
            finish_reason="stop", constrained=constrained, ok=True, error=None)
        self.gen_log.append(stats)
        return text, stats

    def status(self) -> dict:
        return {
            "base": self.base_path,
            "active_adapter": self.active_adapter,
            "adapters": self.adapters,
            "vram_gb": None,
            "switches": len(self.switch_log),
            "last_switch_ms": (self.switch_log[-1].latency_ms
                               if self.switch_log else None),
            "backend": "mock",
            "caps": self.capabilities(),
        }


class FaultyEngine(ScriptedEngine):
    """Inject failures to test degradation / error-surfacing paths.

    Each ``*_on`` is a set of prompt substrings that trigger that fault for the
    matching chat call:

      * ``fail_on``    -> transport/HTTP failure, ``GenStats.ok=False``
      * ``timeout_on`` -> same shape, labelled "Timeout"
      * ``empty_on``   -> success with an empty body (drives empty_rate up)
      * ``nonjson_on`` -> success but non-JSON text (planner/react parse fails)
    """

    def __init__(self, *args: Any, fail_on: Optional[set] = None,
                 empty_on: Optional[set] = None,
                 nonjson_on: Optional[set] = None,
                 timeout_on: Optional[set] = None,
                 error_kind: str = "HTTP", **kw: Any):
        super().__init__(*args, **kw)
        self.fail_on = set(fail_on or [])
        self.empty_on = set(empty_on or [])
        self.nonjson_on = set(nonjson_on or [])
        self.timeout_on = set(timeout_on or [])
        self.error_kind = error_kind

    def _fault_for(self, blob: str) -> Optional[str]:
        for needle in self.empty_on:
            if needle in blob:
                return "empty"
        for needle in self.nonjson_on:
            if needle in blob:
                return "nonjson"
        for needle in self.timeout_on:
            if needle in blob:
                return "timeout"
        for needle in self.fail_on:
            if needle in blob:
                return "fail"
        return None

    def chat(self, messages, *a, **kw):  # type: ignore[override]
        blob = "\n".join(str(m.get("content", "")) for m in messages)
        fault = self._fault_for(blob)
        if fault == "fail" or fault == "timeout":
            kind = "Timeout" if fault == "timeout" else self.error_kind
            stats = GenStats(self.active_adapter, 0, 0, 0.0, ok=False, error=kind)
            self.gen_log.append(stats)
            return "", stats
        text, stats = super().chat(messages, *a, **kw)
        if fault == "empty":
            return "", stats           # ok=True but no text
        if fault == "nonjson":
            return "I cannot produce JSON right now.", stats
        return text, stats


class TimedEngine(ScriptedEngine):
    """Controllable tok/s + KV-cache ratio for latency/budget tests.

    Same contract as ``ScriptedEngine``; only the defaults differ so a test can
    dial throughput and cache-hit rate up or down without spelling every arg.
    """

    def __init__(self, *args: Any, tok_per_s: float = 40.0,
                 prefill_tps: float = 200.0, cached_ratio: float = 0.5,
                 **kw: Any):
        super().__init__(*args, tok_per_s=tok_per_s, prefill_tps=prefill_tps,
                         cached_ratio=cached_ratio, **kw)


# --------------------------------------------------------------- router --

class FakeRouter:
    """Deterministic router: honour an explicit task tag, else default to agent."""

    def __init__(self, skill_map: Optional[dict] = None):
        self.skill_map = dict(skill_map) if skill_map else dict(FAKE_SKILL_MAP)

    def route(self, query: str, task_tag: Optional[str] = None) -> RouteDecision:
        skill = task_tag if (task_tag and task_tag in self.skill_map) else "agent"
        return RouteDecision(skill, self.skill_map.get(skill),
                             f"fake route -> {skill}")


# -------------------------------------------------------------- toolkit --

class FakeToolkit(Toolkit):
    """Toolkit that returns scripted results and records every citation.

    We subclass ``Toolkit`` so the orchestrator's ``spec()``/``run()`` calls keep
    working, but override ``run`` to bypass the real ``PermissionGate`` (no
    sandbox needed for a mock) and to accumulate ``seen_citations`` -- the
    harness reads those into ``CaseResult.retrieved`` for ``rag_recall_at_k``.
    """

    def __init__(self, results: Optional[dict] = None,
                 rag_citations: Optional[list] = None,
                 rag_text: str = "fake rag hit", workspace: str = "."):
        # Bypass Toolkit.__init__ (which wants a PermissionGate) on purpose.
        self.gate = None
        self.workspace = Path(workspace).resolve()
        self.rag_search_fn = None
        self.enable_web = False
        self._results = results or {}
        self.rag_citations = list(rag_citations or [])
        self.rag_text = rag_text
        self.seen_citations: list[dict] = []
        self.call_log: list[tuple] = []

    def spec(self) -> list[dict]:
        return [{"name": n, "desc": f"fake {n}"}
                for n in ["rag_search", "read_file", "list_dir", "grep",
                          "shell_readonly", "rocm_smi"]]

    def run(self, tool: str, **kw: Any) -> ToolResult:
        self.call_log.append((tool, kw))
        if tool == "rag_search" and self.rag_citations:
            cites = self.rag_citations
            self.seen_citations.extend(cites)
            digest = "\n".join(
                f"[{c.get('source')}#L{c.get('start_line')}-L{c.get('end_line')}]"
                f" {self.rag_text}" for c in cites)
            return ToolResult(tool, True, digest, raw=cites, citations=cites)
        res = self._results.get(tool)
        if callable(res):
            res = res(**kw)
        if res is None:
            res = ToolResult(tool, True, f"fake {tool} output")
        if getattr(res, "citations", None):
            self.seen_citations.extend(res.citations)
        return res


# --------------------------------------------------- mock orchestrator --

def _case_answer(case: Any) -> str:
    """Build a plausible answer that satisfies a case's objective fields."""
    if case is None:
        return "This is a mock answer (no case supplied)."
    parts: list[str] = []
    for src in getattr(case, "must_cite", []) or []:
        parts.append(f"Per {src} the key finding holds.")
    for kw in getattr(case, "must_include", []) or []:
        parts.append(f"Also note: {kw}.")
    for gc in getattr(case, "gold_chunks", []) or []:
        src = gc.split("#L")[0]
        parts.append(f"See {gc} in {src}.")
    for forbid in getattr(case, "must_not_include", []) or []:
        # We deliberately do NOT leak forbidden phrases in the mock answer.
        _ = forbid
    if not parts:
        parts.append("Mock answer covering the question.")
    return " ".join(parts)


def _case_script(case: Any, final: Optional[str] = None) -> list[tuple[str, str]]:
    """Script the three orchestrator prompts for a case.

    The orchestrator issues a plan prompt ("Break this into"), per-step react
    prompts ("Decide the next action"), and a final prompt ("Write the final
    answer"). We return one (substring, response) pair per phase.
    """
    skills = list(getattr(case, "expect_skills", []) or []) or ["doc"]
    plan_steps = [{"desc": f"investigate via {s}", "skill": s}
                  for s in skills[:3]] or [{"desc": "investigate", "skill": "doc"}]
    plan = json.dumps({"steps": plan_steps})
    react = json.dumps({"action": "finish",
                        "finding": "done via " + ", ".join(skills)})
    answer = final if final is not None else _case_answer(case)
    return [
        ("Break this into", plan),
        ("Decide the next action", react),
        ("Write the final answer", answer),
    ]


def build_mock_orchestrator(case: Any = None, config: Any = None, *,
                            engine: Optional[ScriptedEngine] = None,
                            adapters: Optional[dict] = None,
                            rag_citations: Optional[list] = None,
                            final: Optional[str] = None,
                            workspace: Optional[str] = None) -> Orchestrator:
    """Assemble a fully-wired ``Orchestrator`` around mock collaborators.

    ``case`` (an ``EvalCase`` or ``None``) scripts a plausible answer that
    satisfies the case's objective expectations, so the eval gate has something
    real to score. ``config`` is an ``E2EConfig`` (a fresh one when omitted, so
    ``metrics`` stays on and the run is deterministic regardless of env).
    """
    from screwshell.core.config import E2EConfig

    if config is None:
        config = E2EConfig()
    if workspace is None:
        import tempfile
        workspace = tempfile.mkdtemp(prefix="screwshell_eval_")
    state = os.path.join(workspace, ".screwshell")

    memory = SessionMemory(state)
    evidence = EvidenceStore(state)
    artifacts = ArtifactStore(state)

    script = _case_script(case, final=final)
    if rag_citations is None and case is not None:
        from screwshell.eval.scorers import _parse_chunk
        rag_citations = []
        for gc in getattr(case, "gold_chunks", []) or []:
            src, s, e = _parse_chunk(gc)
            rag_citations.append({"source": src, "start_line": s,
                                  "end_line": max(e, s)})
    eng = engine or ScriptedEngine(script=script, adapters=adapters,
                                   cached_ratio=0.3)
    router = FakeRouter()
    toolkit = FakeToolkit(rag_citations=rag_citations, workspace=workspace)
    orch = Orchestrator(eng, router, toolkit, memory, evidence, artifacts,
                        config=config)
    return orch


__all__ = ["ScriptedEngine", "FaultyEngine", "TimedEngine", "FakeRouter",
           "FakeToolkit", "FAKE_SKILL_MAP", "build_mock_orchestrator"]
