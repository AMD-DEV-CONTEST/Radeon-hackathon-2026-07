"""ScrewShell Orchestrator: a lightweight, self-built ReAct loop.

Flow per user query:
  1. Plan: LLM (agent expert) drafts a Task Card (steps + skill tags)
  2. For each step: SkillRouter picks a LoRA expert -> mount it, then ReAct:
     think -> tool call -> observe
  3. Tool raw outputs -> ArtifactStore; key findings -> EvidenceCards
  4. Final answer synthesized with citations from the EvidenceStore

The MoL Router IS the orchestration core — no external agent framework.

L3 runtime governance (optional)
--------------------------------
When a `Governor` is supplied, the orchestrator:
  * picks a scheduling mode (roomy / tight) — see governor.select_mode;
  * in "roomy" mode mounts experts via the engine's hot-swap (scale toggle,
    ~0.65ms on W7900, no restart);
  * in "tight" mode swaps experts by restarting the llama-server with a
    different `--lora` set (llama-swap style). One swap == one full 27B
    reload. Measured on W7900: ~4.6-5.1s each, ~19.4s worst for a 4-expert
    task. Step clustering + idempotent mounts keep the count small.
  * runs a conservative gear machine after every generation (tok/s / empty
    rate / VRAM) — see governor.Governor.observe — toggling thinking
    immediately and surfacing ctx/KV adjustments (applied on next restart in
    tight mode, or echoed as events in roomy mode).

Nothing here forces a torch import: the engine is duck-typed (the 5-method
contract from MoLEngine / MoLLlamaCpp), so this module stays importable on
deploy hosts and in unit tests without CUDA/torch.
"""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Optional

from screwshell.core.citations import merge_citations, validate_citations
from screwshell.core.config import E2EConfig, get_config
from screwshell.core.metrics import RunMetrics
from screwshell.core.mol_types import GenStats, SwitchRecord
from screwshell.core.router import SkillRouter
from screwshell.memory.stores import (ArtifactStore, EvidenceCard, EvidenceStore,
                                      SessionMemory, TaskCard)
from screwshell.tools.toolkit import Toolkit
from screwshell.autotune.governor import (
    Governor, LlamaServerLifecycle, RuntimeMetrics, SwapStep, cluster_steps,
)

log = logging.getLogger("screwshell.orchestrator")

SYSTEM = """You are ScrewShell, a private local knowledge investigator running \
fully on an AMD Radeon GPU. You investigate LOCAL documents, code and notes only. \
Never invent facts: every claim must come from tool observations. Cite sources \
as path#Lstart-Lend."""

PLAN_PROMPT = """User request: {query}

Known evidence so far:
{evidence}

Break this into 1-4 concrete investigation steps. For each step pick a skill:
- doc     (document reading / summarization / evidence report)
- code    (code investigation)
- tool    (heavy tool usage: search, grep, listing)
- agent   (multi-step reasoning / verification / planning)
- security (security audit: vuln/CVE/exploit/injection/auth analysis)

Reply ONLY with JSON: {{"steps": [{{"desc": "...", "skill": "doc|code|tool|agent|security"}}]}}"""

REACT_PROMPT = """Current step: {step}

Available tools:
{tools}

Evidence so far:
{evidence}

Recent observations:
{observations}

Decide the next action. Reply ONLY with JSON, one of:
{{"action": "tool", "tool": "<name>", "args": {{...}}}}
{{"action": "finish", "finding": "<what this step concluded, with citations path#Lx-Ly>"}}"""

# Constrained-decoding schema for the planner (T7, 2026-08-04): llama.cpp
# `response_format: json_schema` keeps the plan JSON well-formed, so the
# json_parse fallback becomes a safety net instead of the primary path.
PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "desc": {"type": "string"},
                    "skill": {"type": "string",
                              "enum": ["doc", "code", "tool", "agent",
                                       "security"]},
                },
                "required": ["desc", "skill"],
            },
        }
    },
    "required": ["steps"],
}

FINAL_PROMPT = """User request: {query}

Evidence cards collected:
{evidence}

Write the final answer for the user. Requirements:
- answer directly and concisely
- cite sources inline as (path#Lstart-Lend) for every claim
- if evidence is insufficient, say what is missing"""

# Skills that *synthesize* evidence rather than gather it. Heuristic used by the
# step-clustering dependency graph: a synthesis step depends on all earlier
# steps, so it is scheduled last. This is a safe over-approximation — synthesis
# never runs before its inputs exist — and is the mitigation for the
# "reordering breaks step dependencies" risk flagged during planning.
SYNTHESIS_SKILLS = frozenset({"doc", "agent"})


@dataclass
class StepTrace:
    step: str
    skill: str
    adapter: Optional[str]
    switch_ms: float
    actions: list[dict] = field(default_factory=list)
    finding: str = ""


@dataclass
class RunResult:
    answer: str
    task: TaskCard
    traces: list[StepTrace]
    stats: dict


def _extract_json(text: str) -> Optional[dict]:
    """Robust JSON extraction with light repair (models sometimes wrap in prose)."""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    frag = m.group(0)
    for candidate in (frag, frag.replace("'", '"'),
                      re.sub(r",\s*([}\]])", r"\1", frag)):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


# A generation that has no JSON object is "prose" when it carries real words.
# We use this to bail out of the ReAct retry loop: if the model answered a
# conversational query in natural language (instead of the required JSON
# action), we accept the prose as the step finding rather than looping.
_WORD_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.I)


def _looks_like_prose(text: str) -> bool:
    """True when `text` is a natural-language answer, not a tool/JSON call.

    Heuristic: it contains at least two "word" characters (so a stray brace or
    single token is not mistaken for prose) and does NOT parse as JSON (the
    caller already failed `_extract_json`). Pure code/fragments like "{ }" or a
    bare JSON key are rejected; real sentences / explanations pass.
    """
    if not text or not text.strip():
        return False
    if _extract_json(text) is not None:
        return False
    # require at least two word-ish characters so a lone "{" or "x" doesn't
    # count as prose
    return len(_WORD_RE.findall(text)) >= 2


class Orchestrator:
    def __init__(self, engine: object, router: SkillRouter, toolkit: Toolkit,
                 memory: SessionMemory, evidence: EvidenceStore,
                 artifacts: ArtifactStore,
                 on_event: Optional[Callable[[str, dict], None]] = None,
                 max_actions_per_step: int = 5,
                 governor: Optional[Governor] = None,
                 lifecycle: Optional[LlamaServerLifecycle] = None,
                 launch_cmd: Optional[str] = None,
                 takeover: bool = False,
                 l3_mode: Optional[str] = None,
                 config: Optional[E2EConfig] = None):
        self.engine = engine
        self.router = router
        self.toolkit = toolkit
        self.memory = memory
        self.evidence = evidence
        self.artifacts = artifacts
        self.on_event = on_event or (lambda kind, data: None)
        self.max_actions = max_actions_per_step
        # Stable id for this UI session: every LLM request it makes
        # (plan / react / final / quick) is stamped with it so the observ panel
        # can tag them [UI] instead of [opencode]. The engine forwards it as the
        # X-Run-Id header; the relay reads it back into RequestEvent.run_id and
        # the panel derives `entry` from run_id presence.
        self.run_id = uuid.uuid4().hex[:16]

        # Feature flags (ADR-2). Defaults reproduce today's behavior exactly,
        # so an un-configured Orchestrator is the control arm of every A/B.
        self.config = config if config is not None else get_config()
        # Per-query LLM / tool accounting. Replaced at the top of every run();
        # pre-created so a caller that pokes at `metrics` before the first run
        # gets an empty meter instead of an AttributeError.
        self.metrics = RunMetrics()

        # --- L3 runtime governance (all optional; None == legacy behavior) ---
        self.governor = governor
        self.lifecycle = lifecycle
        self.launch_cmd = launch_cmd
        self.takeover = takeover
        self.l3_mode = l3_mode
        self._mode = self._resolve_mode()

        # gear-machine runtime state
        self._thinking_on = False  # default OFF: the UI runs with no governor to re-enable it, so leaving thinking ON only burns tokens on reasoning chains (and can truncate the real answer) while slowing every call
        self._ctx_tokens = 8192
        self._recent: list[tuple[bool, float]] = []   # (non_empty, tok/s) window
        self._recent_window = 8
        self._mounted: Optional[str] = None
        self._last_mount_rec: Optional[SwitchRecord] = None
        self._force_deep = False  # UI may set True to force the full investigation loop (bypass the fast path)

    # ---------- mode resolution ----------

    def _resolve_mode(self) -> str:
        """roomy | tight. 'auto' resolves to tight iff we can drive the server."""
        if self.governor is not None and self.governor.mode != "auto":
            return self.governor.mode
        if self.l3_mode and self.l3_mode != "auto":
            return self.l3_mode
        # auto: tight only when we actually have a lifecycle to restart with
        return "tight" if (self.lifecycle and self.launch_cmd) else "roomy"

    # ---------- expert mounting (the L3 core) ----------

    def _mount(self, adapter: Optional[str]) -> SwitchRecord:
        """Mount `adapter` (name or None for base).

        roomy  -> engine.activate (hot-swap scale toggle, sub-ms)
        tight  -> restart llama-server with that expert's --lora (full reload)
        Idempotent: mounting the already-mounted expert is a no-op in both modes.
        """
        if self._mounted == adapter and self._last_mount_rec is not None:
            return self._last_mount_rec
        prev = self._mounted

        if self._mode == "tight" and self.lifecycle is not None:
            path = self.engine.adapters.get(adapter, {}).get("path") if adapter else None
            lora_arg = path or ""   # base-only expert -> server with no --lora
            to_serve = self.lifecycle.restart_with(lora_arg, takeover=self.takeover)
            if self.governor is not None:
                self.governor.note_swap()
                alert = self.governor.swap_cap_exceeded()
                if alert:
                    self.on_event("governor_alert", alert.payload)
            # chat must NOT inject a stale per-request lora id (server already
            # has exactly this expert loaded via --lora).
            self.engine.active_adapter = None
            self.on_event("lora_swap_restart",
                          {"to": adapter or "base",
                           "to_serve_s": round(to_serve or 0.0, 2),
                           "mode": "tight"})
            rec = SwitchRecord(time.time(), prev, adapter,
                               round((to_serve or 0.0) * 1000, 2), "restart_swap")
            # mirror roomy-mode accounting so engine.status() reports the swap
            # count / last switch correctly in the final stats.
            self.engine.switch_log.append(rec)
        else:
            rec = self.engine.activate(adapter)

        self._mounted = adapter
        self._last_mount_rec = rec
        return rec

    def _mount_skill(self, skill_tag: str, query: str = "") -> SwitchRecord:
        decision = self.router.route(query, task_tag=skill_tag)
        rec = self._mount(decision.adapter)
        self.on_event("lora_switch",
                      {"from": rec.from_adapter, "to": rec.to_adapter,
                       "ms": rec.latency_ms, "skill": decision.skill,
                       "mode": rec.mode})
        return rec

    # ---------- step clustering ----------

    def _order_steps(self, task: TaskCard) -> list[dict]:
        """Reorder steps to minimize expert swaps while preserving dependencies.

        Returns a new list of the same step dicts. Falls back to the original
        order if clustering reports an infeasible (cyclic) plan.
        """
        if self.governor is None:
            return task.steps
        swap_steps: list[SwapStep] = []
        for i, s in enumerate(task.steps):
            skill = s.get("skill", "agent")
            adapter = self.router.route(s.get("desc", ""), task_tag=skill).adapter
            deps = [f"st{j}" for j in range(i)] if skill in SYNTHESIS_SKILLS else []
            swap_steps.append(SwapStep(step_id=f"st{i}",
                                       expert=adapter or "base", deps=deps))
        plan = cluster_steps(swap_steps)
        if not plan.feasible:
            return task.steps
        return [task.steps[int(sid[2:])] for sid in plan.order]

    # ---------- gear machine ----------

    def _vram_pct(self) -> float:
        """Return VRAM usage as a real 0-100 percentage for the governor.

        The governor treats ``vram_pct`` as a 0-100 figure (threshold 90).
        Resolution order:
          1. engine.vram_pct()  -- the real percentage (e.g. llama.cpp parses
             rocm-smi; peft computes used/total). Preferred.
          2. vram_gb()/vram_total_gb()*100  -- engine reports GB + total.
          3. vram_gb()  -- GB-only engine (legacy); governor misreads it as %,
             so we log a one-time warning: the KV-quant safety net is degraded.
          4. 0.0  -- unmeasurable (no GPU); governor assumes headroom, never
             fires KV-quant on a phantom number.
        """
        eng = self.engine
        pct = getattr(eng, "vram_pct", None)
        if callable(pct):
            try:
                v = pct()
                if v is not None:
                    return float(v)
            except Exception:
                pass
        gb = None
        try:
            gb = eng.vram_gb()  # type: ignore[attr-defined]
        except Exception:
            gb = None
        total = getattr(eng, "vram_total_gb", None)
        tot = None
        if callable(total):
            try:
                tot = total()
            except Exception:
                tot = None
        if gb is not None and tot:
            return float(gb) / float(tot) * 100.0
        if gb is not None:
            if not getattr(self, "_vram_pct_warned", False):
                log.warning("engine reports vram_gb=%s but no vram_total_gb; "
                            "VRAM percentage (and the governor KV-quant safety "
                            "net) is degraded -- feeding raw GB as %%", gb)
                self._vram_pct_warned = True
            return float(gb)
        return 0.0

    def _observe(self, stats: GenStats, text: str) -> None:
        if self.governor is None:
            return
        self._recent.append((bool(text and text.strip()), stats.tokens_per_s))
        if len(self._recent) > self._recent_window:
            self._recent.pop(0)
        empty = (sum(1 for e, _ in self._recent if not e) / len(self._recent)
                 if self._recent else 0.0)
        m = RuntimeMetrics(tokens_per_s=stats.tokens_per_s, empty_rate=empty,
                           vram_pct=self._vram_pct(),
                           ctx_tokens=self._ctx_tokens,
                           thinking_on=self._thinking_on)
        for a in self.governor.observe(m):
            # D1 (BUILD_OBSERVATORY_V3 §2.8): emit ONE unified governor_action
            # event per returned action so any observer (UI card, future
            # dashboard) can show "what the auto-tuner just did" without
            # special-casing every action kind. Pure observation — no behavior
            # change to the existing set_thinking/set_ctx/set_kv_quant/alert
            # handling below.
            self.on_event("governor_action",
                          {"kind": a.kind, "reason": a.reason,
                           "payload": a.payload})
            if a.kind == "set_thinking":
                self._thinking_on = a.payload.get("thinking", False)
                self.on_event("governor_thinking", a.payload)
            elif a.kind == "set_ctx":
                self._ctx_tokens = a.payload.get("ctx", self._ctx_tokens)
                if self.lifecycle is not None:
                    self.lifecycle.ctx_tokens = self._ctx_tokens
                self.on_event("governor_ctx", a.payload)
            elif a.kind == "set_kv_quant":
                if self.lifecycle is not None:
                    self.lifecycle.kv_quant = a.payload.get("kv_quant", "none")
                self.on_event("governor_kv", a.payload)
            elif a.kind == "alert":
                self.on_event("governor_alert", a.payload)

    # ---------- fast path (greetings / trivial Q&A) ----------

    # WHOLE-UTTERANCE match, never substring.
    #
    # The first version of this used `any(g in ql for g in GREETINGS)`, and the
    # short English greetings ("hi" / "hey") are substrings of extremely common
    # words: t-hi-s, w-hi-ch, hi-story, hi-erarchy, somet-hi-ng, mac-hi-ne,
    # t-hey. Real questions like "What is this repo about?" or "Which adapter
    # is mounted?" were classified as chit-chat and skipped plan + ReAct
    # entirely -- the user gets a friendly non-answer and no investigation ever
    # runs. It also silently disabled the BUG-2 plan-fallback logging fix,
    # because the regression test queries "do something" (somet-hi-ng).
    #
    # So: the query must consist of a greeting AND NOTHING ELSE (trailing
    # punctuation allowed). If in doubt, run the full loop -- a wasted
    # investigation is cheap, a skipped one is a wrong answer.
    _GREET_RE = re.compile(
        r"^(?:"
        r"你好呀?|您好呀?|哈喽|哈啰|嗨|在吗|在么|你在吗|"
        r"早上好|上午好|中午好|下午好|晚上好|"
        r"谢谢(?:你|您)?|多谢|感谢(?:你|您)?|"
        r"你是谁|您是谁|你是什么|你叫什么(?:名字)?|"
        r"hi|hi there|hello|hey|yo|"
        r"good morning|good afternoon|good evening|"
        r"thanks|thank you|thx|who are you|what are you"
        r")"
        r"[\s!！。.?？~～、,，:：)）]*$",
        re.I,
    )

    # Verbs that signal a real investigation request -- even if the query is
    # short, these must NOT be swallowed by the fast path.
    _INVESTIGATE_RE = re.compile(
        r"调查|分析|总结|查找|搜索|文件|代码|文档|风险|计划|对比|找一下|查一下|"
        r"investigate|analyze|analyse|summar",
        re.I,
    )

    # Casual acknowledgments / filler that need no investigation and are not
    # covered by _GREET_RE (e.g. "hihi" -- "hi" inside _GREET_RE is anchored
    # but "hihi" is not; "好的" / "ok" are ack, not a real query).
    _CASUAL_RE = re.compile(
        r"^(?:"
        r"hihi|hihi+|嗨嗨|嘿嘿|哈喽呀|哈喽哈喽|嘿|"
        r"hey there|yo+|hey hey|sup|"
        r"嗯嗯|嗯哼|好的|好滴|好嘞|ok|okay|o\.k\.|"
        r"知道了|明白|明白了|收到|了解|懂了|晓得了|"
        r"哈哈|哈哈哈|嘻嘻|呵呵"
        r")"
        r"[\s!！。.?？~～、,，:：)）]*$",
        re.I,
    )

    # Short identity / capability questions that need no investigation.
    # PREFIX-oriented (anchored at ^ only): the 40-char guard already blocks long
    # sentences, so a looser suffix is safe. Each phrase tolerates an optional
    # "...自己"/"...你自己" and trailing punctuation, so "一句话介绍你自己。" and
    # "介绍一下你自己" both match -- the trailing-anchor variant missed these
    # because leftover "自己" failed the punctuation-only tail.
    _CAPABILITY_RE = re.compile(
        r"^(?:"
        r"你能干嘛|你能干啥|你能做什么|你会什么|你会做啥|"
        r"你有什么功能|你有什么用|你有什么能力|你擅长什么|"
        r"你是干嘛的|你是谁|你是什么|你叫什么(?:名字)?|"
        r"介绍一下你(?:自己)?|介绍下你(?:自己)?|介绍你(?:自己)?|"
        r"一句话介绍你(?:自己)?|一句话介绍下你(?:自己)?|简单介绍你(?:自己)?|"
        r"what can you do|what do you do|what are you|"
        r"what are your (?:features|capabilities)|"
        r"tell me about you|introduce yourself"
        r")"
        r"(?:自己)?"
        r"[\s!！。.?？~～、,，:：)）]*$",
        re.I,
    )

    def _is_simple_query(self, q: str) -> bool:
        """True only for a short, conversational query that needs no investigation.

        Deliberately conservative -- see the _GREET_RE comment. Anything that
        merely *contains* a greeting word ("hi" inside "which") is a real query
        and goes through the full plan + ReAct loop.

        Beyond bare greetings / thank-yous, we now also treat short casual
        acknowledgments (hihi, 好的, ok) and short identity/capability questions
        (你能干嘛 / 一句话介绍你) as simple -- the 27B model cannot reliably emit
        the ReAct JSON for these, so running the full loop wastes ~20 model calls
        and repeats RAG evidence. Investigation verbs (调查/分析/总结/...) are
        always excluded so real queries still reach the full loop.
        """
        ql = (q or "").strip().lower()
        if not ql or len(ql) > 40:
            return False
        if self._INVESTIGATE_RE.search(ql):
            return False
        return bool(self._GREET_RE.match(ql)
                    or self._CASUAL_RE.match(ql)
                    or self._CAPABILITY_RE.match(ql))

    def _switch_stats(self) -> list[dict]:
        """This query's expert swaps, read from the REAL engine switch log.

        run() clears engine.switch_log at the top of every query, so whatever is
        in it belongs to this query only. Never hardcode this list: the fast
        path used to report a literal `[]` while still performing a mount, which
        under-reported swaps and contradicted the per-query accounting fix.
        """
        entries = getattr(self.engine, "switch_log", None) or []
        return [{"to": r.to_adapter, "ms": r.latency_ms, "mode": r.mode}
                for r in entries[-12:]]

    def _quick_prompt(self, q: str) -> str:
        return (
            f"用户说：{q}\n\n"
            "这是一句简短的寒暄或简单问答，不需要调查工具，也不需要输出 JSON。"
            "直接用用户的语言，简洁、友好地回答。")

    # ---------- LLM helpers ----------

    def _llm(self, prompt: str, max_new_tokens: int = 512,
             phase: str = "other", step_idx: Optional[int] = None,
             stream: bool = False,
             json_schema: Optional[dict] = None) -> str:
        """One engine round trip, metered.

        `phase` / `step_idx` are pure accounting: they let the report say
        *where* the tokens and the seconds went (plan vs each ReAct step vs
        final synthesis) instead of handing back one opaque total. Without that
        split there is no way to tell an expensive planner from an expensive
        loop, and therefore no way to know which optimization paid off.

        `stream=True` forwards token deltas to the UI via the "answer_chunk"
        event (the llama.cpp backend calls ``on_token`` per SSE delta; the peft
        backend ignores streaming and returns the full text as today). Only the
        user-visible final answer (and the fast-path greeting) use stream=True;
        the planner / ReAct steps stay non-streaming so their JSON is never
        surfaced as half-typed bubbles.
        """
        msgs = [{"role": "system", "content": SYSTEM}]
        msgs += self.memory.history(limit=8)
        msgs.append({"role": "user", "content": prompt})
        on_token = None
        if stream:
            on_token = lambda piece: self.on_event(
                "answer_chunk", {"text": piece})
        text, stats = self.engine.chat(
            msgs, max_new_tokens=max_new_tokens,
            enable_thinking=self._thinking_on,
            stream=stream, on_token=on_token,
            json_schema=json_schema, run_id=self.run_id)
        if self.config.metrics:
            self.metrics.record(stats, phase=phase, step_idx=step_idx)
        self.on_event("generation", {"adapter": stats.adapter,
                                     "tokens_per_s": round(stats.tokens_per_s, 1),
                                     "new_tokens": stats.new_tokens})
        self._observe(stats, text)
        return text

    def _note_json(self, ok: bool) -> None:
        """Tag the most recent metered call with its JSON parse verdict."""
        if self.config.metrics:
            self.metrics.note_json(bool(ok))

    def _mark(self, phase: str) -> None:
        """Close the current phase timer (no-op when metrics are off)."""
        if self.config.metrics:
            self.metrics.mark(phase)

    # ---------- main entry ----------

    def _budget_stats(self, traces: list[StepTrace],
                      actions_used: int, exhausted: int) -> dict:
        """Where the per-step action budget went (T7 reads this back)."""
        return {
            "max_actions_per_step": self.max_actions,
            "steps": len(traces),
            "actions_used": actions_used,
            "actions_available": self.max_actions * len(traces),
            "steps_hitting_limit": exhausted,
        }

    def _compose_stats(self, base: dict, traces: list[StepTrace],
                       actions_used: int, exhausted: int) -> dict:
        """Attach the measurement keys to a stats dict.

        The keys already in `base` (seconds / l3_mode / engine / switches /
        switch_kind / fast_path) are a test contract: this method may only ADD.
        """
        base["llm"] = self.metrics.summary()
        base["phases"] = self.metrics.phases()
        base["tools"] = self.metrics.tools_summary()
        base["budget"] = self._budget_stats(traces, actions_used, exhausted)
        base["config"] = self.config.non_default()
        return base

    def run(self, query: str) -> RunResult:
        t0 = time.time()
        # One meter per query. Rebuilt here (not in __init__) so a long-lived
        # REPL/UI session reports THIS query's token bill rather than a
        # session-cumulative tally -- the same per-query accounting rule that
        # already governs engine.switch_log below.
        self.metrics = RunMetrics()
        self.memory.add_turn("user", query)
        if self.governor is not None:
            self.governor.reset_swap_count()
        # Reset PER-QUERY switch accounting. engine.switch_log otherwise keeps
        # growing for every query in a REPL / multi-turn session, so both
        # engine.status()['switches'] and RunResult.stats['switches'] would
        # report a session-cumulative tally instead of THIS query's swaps
        # (the "switches" figure would bleed across queries). The Governor
        # tracks its own swap budget via _swap_count, so clearing here is
        # purely a reporting fix and does not affect swap-cap enforcement.
        _sl = getattr(self.engine, "switch_log", None)
        if isinstance(_sl, list):
            _sl.clear()
        self._mounted = None
        self._last_mount_rec = None

        # 0. fast path: greetings / trivial Q&A skip the plan+ReAct loop entirely
        if self._is_simple_query(query) and not self._force_deep:
            self.on_event("phase", {"text": "quick"})
            # NO mount here, on purpose. Mounting the agent expert to say "hi"
            # costs a full 27B server restart in tight mode (~5s) -- the single
            # most expensive operation in the system, incurred by the path whose
            # whole point is to be cheap. Any currently-loaded expert can answer
            # a greeting, so we reuse whatever the engine already has.
            answer = self._llm(self._quick_prompt(query), max_new_tokens=512,
                               phase="quick", stream=True)
            self.memory.add_turn("assistant", answer)
            self._mark("quick")
            return RunResult(
                answer, TaskCard(goal=query, steps=[]), [],
                self._compose_stats(
                    {"seconds": round(time.time() - t0, 1),
                     "l3_mode": self._mode,
                     "fast_path": True, "engine": self.engine.status(),
                     "switches": self._switch_stats(), "switch_kind": "none"},
                    traces=[], actions_used=0, exhausted=0))

        # 1. plan
        self.on_event("phase", {"text": "planning"})
        self._mount_skill("agent", PLAN_PROMPT.format(
            query=query, evidence=self.evidence.context_block()))
        plan_raw = self._llm(PLAN_PROMPT.format(
            query=query, evidence=self.evidence.context_block()),
            max_new_tokens=384, phase="plan", json_schema=PLAN_SCHEMA)
        plan = _extract_json(plan_raw)
        self._note_json(plan is not None)
        self._mark("plan")
        if plan is None:
            log.warning("planner returned non-JSON plan (raw=%r); falling back "
                        "to a single 'agent' step for query=%r", plan_raw[:200],
                        query[:120])
            plan = {"steps": [{"desc": query, "skill": "agent"}]}
        steps = plan.get("steps") or [{"desc": query, "skill": "agent"}]
        task = TaskCard(goal=query,
                        steps=[{"desc": s.get("desc", query),
                                "skill": s.get("skill", "agent"),
                                "status": "pending"} for s in steps[:4]])
        self.on_event("plan", {"task": task.render()})

        # 2. execute steps (reordered by L3 clustering when a governor runs)
        ordered = self._order_steps(task)
        traces: list[StepTrace] = []
        total_steps = len(ordered)
        actions_used = 0
        exhausted_steps = 0
        for idx, step in enumerate(ordered):
            self.on_event("phase", {"text": f"step_{idx + 1}_{total_steps}"})
            step["status"] = "running"
            self.on_event("step_start", {"desc": step["desc"], "skill": step["skill"]})
            decision = self.router.route(step["desc"], task_tag=step["skill"])
            rec = self._mount(decision.adapter)
            trace = StepTrace(step["desc"], decision.skill, decision.adapter,
                              rec.latency_ms)
            observations: list[str] = []
            for _ in range(self.max_actions):
                act_raw = self._llm(REACT_PROMPT.format(
                    step=step["desc"],
                    tools=json.dumps(self.toolkit.spec(), indent=1),
                    evidence=self.evidence.context_block(),
                    observations="\n---\n".join(observations[-3:]) or "(none)"),
                    max_new_tokens=384, phase="react", step_idx=idx)
                actions_used += 1
                act = _extract_json(act_raw)
                self._note_json(act is not None)
                if not act:
                    # Convergence guard: the planner routed a conversational /
                    # simple query into the ReAct loop, and the 27B model answered
                    # in natural-language prose instead of emitting the required
                    # JSON action. Retrying to exhaustion (max_actions calls, all
                    # prose) is the dead-loop bug -- it burns ~20 model calls per
                    # query and, because synthesis re-uses the same RAG evidence,
                    # repeats the same sentence back to the user. Instead, accept
                    # non-empty prose as this step's finding and move on. Empty /
                    # whitespace-only output is still retried (a genuinely broken
                    # generation), and valid JSON `tool` / `finish` paths are
                    # untouched below.
                    if act_raw and act_raw.strip() and _looks_like_prose(act_raw):
                        trace.finding = act_raw.strip()
                        break
                    observations.append("Your reply was not valid JSON. Try again.")
                    continue
                if act.get("action") == "finish":
                    trace.finding = act.get("finding", "")
                    break
                if act.get("action") == "tool":
                    tool, args = act.get("tool", ""), act.get("args") or {}
                    _tt = time.perf_counter()
                    result = self.toolkit.run(tool, **args)
                    if self.config.metrics:
                        self.metrics.tool(tool, bool(result.ok),
                                          time.perf_counter() - _tt)
                    aid = self.artifacts.put(tool, result.raw) if result.raw else None
                    trace.actions.append({"tool": tool, "args": args,
                                          "ok": result.ok, "artifact": aid,
                                          "citations": result.citations
                                          if result.ok else []})
                    self.on_event("tool", {"tool": tool, "ok": result.ok,
                                           "digest": result.digest[:280]})
                    observations.append(f"TOOL {tool} -> {result.digest[:1800]}")
                    if result.ok and result.citations:
                        self.evidence.add(EvidenceCard(
                            claim=f"[{step['skill']}] {tool} on "
                                  f"{json.dumps(args, default=str)[:80]}: "
                                  f"{result.digest[:160]}",
                            citations=result.citations, confidence=0.6))
                else:
                    observations.append("Unknown action. Use 'tool' or 'finish'.")
            else:
                exhausted_steps += 1
                trace.finding = trace.finding or "(step hit action limit)"
            if trace.finding and trace.finding != "(step hit action limit)":
                # T4 fix: the finding card used to hardcode citations=[] -- a
                # dead-code-style empty reference that made the evidence trail
                # end at the LLM's goodwill. Backfill it with the citations
                # the step's own tool calls actually produced and retrieved.
                step_cites = [c for a in trace.actions
                              for c in a.get("citations", [])]
                self.evidence.add(EvidenceCard(
                    claim=trace.finding[:400],
                    citations=merge_citations(step_cites), confidence=0.75))
            step["status"] = "done" if trace.finding else "failed"
            traces.append(trace)
            self.on_event("step_done", {"desc": step["desc"],
                                        "finding": trace.finding[:200]})
            # Accumulative: one mark per step sums into `phases()["steps_s"]`.
            self._mark("steps")

        # 3. final synthesis (doc/agent expert)
        self.on_event("phase", {"text": "finalizing"})
        self._mount_skill("doc")
        answer = self._llm(FINAL_PROMPT.format(
            query=query, evidence=self.evidence.context_block(limit=12)),
            max_new_tokens=768, phase="final", stream=True)
        # T4: programmatically validate every `file#Lx-Ly` citation in the
        # answer against the filesystem + what was actually retrieved this
        # run (annotate mode never changes answer semantics; off = control
        # arm for the measurement gate). The report rides along in stats so
        # bench/eval_e2e.py can score citation_accuracy honestly.
        citation_report = None
        if self.config.citations:
            answer, citation_report = validate_citations(
                answer, workspace=str(self.toolkit.workspace),
                retrieved=[c for card in self.evidence.active()
                           for c in card.citations],
                mode=self.config.citations_mode)
        self.memory.add_turn("assistant", answer, task_id=task.id)
        self._mark("final")

        switch_kind = "restart_swap" if self._mode == "tight" else "hot_swap"
        stats = self._compose_stats({
            "seconds": round(time.time() - t0, 1),
            "l3_mode": self._mode,
            "engine": self.engine.status(),
            "switches": self._switch_stats(),
            "switch_kind": switch_kind,
        }, traces=traces, actions_used=actions_used,
            exhausted=exhausted_steps)
        if citation_report is not None:
            stats["citations"] = citation_report.to_dict()
        return RunResult(answer, task, traces, stats)

    def shutdown(self) -> None:
        """Best-effort teardown of the server lifecycle (tight mode)."""
        if self.lifecycle is not None:
            try:
                self.lifecycle.stop()
            except Exception:
                pass
