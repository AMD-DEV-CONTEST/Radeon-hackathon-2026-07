"""Integration test: governor wired into Orchestrator (runtime LoRA swapping).

Uses lightweight fakes (no torch, no real llama-server) so it runs anywhere.
Covers:
  * tight mode   -> LlamaServerLifecycle.restart_with drives swaps, engine.activate NOT used
  * roomy mode   -> engine.activate hot-swap, lifecycle untouched
  * idempotent   -> mounting an already-mounted expert costs nothing
  * clustering   -> synthesis step (doc) scheduled last; distinct experts each restart once
  * gear machine -> sustained low tok/s flips thinking off via Governor.observe
"""
import time

import pytest

from screwshell.core.mol_types import GenStats, SwitchRecord
from screwshell.core.orchestrator import Orchestrator
from screwshell.core.router import RouteDecision
from screwshell.autotune.governor import Governor, RuntimeMetrics
from screwshell.memory.stores import TaskCard

ADAPTERS = {
    "teichai_plan": {"path": "/l/teichai.gguf", "id": 0},
    "btl3": {"path": "/l/btl3.gguf", "id": 1},
    "rag_n7": {"path": "/l/rag_n7.gguf", "id": 2},
    "cybersec": {"path": "/l/cybersec.gguf", "id": 3},
}
SKILL_TO_ADAPTER = {
    "agent": "teichai_plan", "tool": "btl3", "code": "btl3",
    "doc": "rag_n7", "security": "cybersec",
}


class FakeEngine:
    def __init__(self, tok_per_s: float = 20.0, empty_text: bool = False):
        self.adapters = {k: dict(v) for k, v in ADAPTERS.items()}
        self.active_adapter = None
        self.switch_log: list[SwitchRecord] = []
        self.gen_log: list[GenStats] = []
        self._tok = tok_per_s
        self._empty_text = empty_text

    def load_base(self):
        return self

    def activate(self, name):
        rec = SwitchRecord(time.time(), self.active_adapter, name, 0.65, "set_adapter")
        self.active_adapter = name
        self.switch_log.append(rec)
        return rec

    def chat(self, messages, max_new_tokens=512, enable_thinking=False,
             stream=False, on_token=None, json_schema=None, run_id=None):
        self.last_run_id = run_id
        content = messages[-1]["content"]
        # plan prompt -> emit a 2-step task (tool then doc) so we exercise clustering
        if "Break this into" in content:
            text = ('{"steps": [{"desc": "grep the repo", "skill": "tool"},'
                    '{"desc": "write the report", "skill": "doc"}]}')
        elif self._empty_text:
            text = ""   # empty answer -> drives empty_rate up (gear machine)
        else:
            text = "ok finding with some evidence"
        new_tokens = 1 if self._tok < 5 else 20
        seconds = 1.0
        stats = GenStats(self.active_adapter, 10, new_tokens, seconds)
        self.gen_log.append(stats)
        # override tok/s to the injected value for the gear machine
        stats.seconds = new_tokens / self._tok if self._tok > 0 else 1.0
        return text, stats

    def status(self):
        return {"adapters": self.adapters, "vram_gb": None, "switches": len(self.switch_log)}

    def vram_gb(self):
        return None

    def vram_pct(self):
        # healthy host for the gear machine; overridden per-test where needed
        return 30.0


class FakeLifecycle:
    def __init__(self):
        self.restarts: list[str] = []
        self.stopped = False
        self.ctx_tokens = 8192
        self.kv_quant = "none"

    def restart_with(self, lora, takeover=False):
        self.restarts.append(lora)
        return 5.0

    def start(self, lora, takeover=False):
        self.restarts.append(lora)
        return 5.0

    def stop(self):
        self.stopped = True


class FakeRouter:
    def route(self, query, task_tag=None):
        skill = task_tag or "agent"
        return RouteDecision(skill, SKILL_TO_ADAPTER.get(skill, "rag_n7"),
                             f"fake route {skill}")


class _Store:
    def history(self, limit=12):
        return []
    def add_turn(self, *a, **k):
        pass
    def context_block(self, limit=8):
        return ""
    def add(self, *a, **k):
        pass
    def put(self, kind, payload):
        return "art-1"


class FakeToolkit:
    def spec(self):
        return [{"name": "read", "desc": "read a file"}]
    def run(self, tool, **args):
        class R:
            raw = "x"
            ok = True
            digest = "file contents"
            citations = []
        return R()


def _build(mode, life=None, tok=20.0, empty_text=False):
    engine = FakeEngine(tok_per_s=tok, empty_text=empty_text)
    gov = Governor(mode=mode)
    orch = Orchestrator(engine, FakeRouter(), FakeToolkit(), _Store(), _Store(),
                        _Store(), max_actions_per_step=1,
                        governor=gov, lifecycle=life, launch_cmd="x {lora}",
                        takeover=False, l3_mode=mode)
    return orch, engine, life, gov


def test_tight_mode_uses_lifecycle_restart():
    life = FakeLifecycle()
    orch, engine, life, gov = _build("tight", life=life)
    orch.run("investigate the repo")
    # agent (plan) + tool (step) + doc (step) each restarted; final doc = idempotent
    assert life.restarts, "tight mode must drive the server lifecycle"
    assert any("teichai.gguf" in r for r in life.restarts)
    assert any("btl3.gguf" in r for r in life.restarts)
    assert any("rag_n7.gguf" in r for r in life.restarts)
    # engine.activate (hot-swap) must NOT be used for swaps in tight mode.
    # Tight mode drives the lifecycle and records restarts as mode="restart_swap"
    # (see orchestrator._mount); it must never emit a "set_adapter" hot-swap.
    hot_swaps = [r for r in engine.switch_log if r.mode == "set_adapter"]
    assert not hot_swaps, "tight mode must not hot-swap via engine.activate"
    assert gov._swap_count >= 1


def test_roomy_mode_hot_swaps_via_engine():
    orch, engine, life, gov = _build("roomy")  # no lifecycle
    assert life is None
    orch.run("investigate the repo")
    assert engine.switch_log, "roomy mode must hot-swap via engine.activate"
    # orchestrator never touched a (None) lifecycle
    assert orch.lifecycle is None


def test_mount_is_idempotent():
    life = FakeLifecycle()
    orch, engine, life, gov = _build("tight", life=life)
    orch._mount("btl3")
    n1 = len(life.restarts)
    orch._mount("btl3")          # same expert -> no-op
    assert len(life.restarts) == n1
    orch._mount("rag_n7")        # different -> restart
    assert len(life.restarts) == n1 + 1


def test_clustering_respects_dependencies():
    orch, engine, life, gov = _build("tight", life=FakeLifecycle())
    # craft a 3-step task: tool, doc, security  (doc is synthesis -> depends on tool)
    task = TaskCard(goal="g", steps=[
        {"desc": "grep", "skill": "tool", "status": "pending"},
        {"desc": "report", "skill": "doc", "status": "pending"},
        {"desc": "audit", "skill": "security", "status": "pending"},
    ])
    ordered = orch._order_steps(task)
    skills = [s["skill"] for s in ordered]
    # synthesis step must run AFTER its dependency (tool), and clustering
    # must produce a feasible plan (not fall back to original).
    assert skills.index("doc") > skills.index("tool")
    assert "doc" in skills and "tool" in skills


def test_gear_machine_drops_ctx_on_low_tokps():
    life = FakeLifecycle()
    orch, engine, life, gov = _build("tight", life=life, tok=1.0)  # <12 tok/s
    assert orch._ctx_tokens == 8192
    orch.run("investigate the repo")
    # 3+ consecutive low-tok/s generations -> Governor drops one ctx gear
    assert orch._ctx_tokens < 8192
    assert life.ctx_tokens == orch._ctx_tokens  # forwarded to lifecycle


def test_thinking_defaults_off():
    """Thinking now starts OFF (the UI runs with no governor to re-enable it).

    Pinned deliberately: this is a behavior change, not an accident, and the
    gear-machine test below has to opt back IN to keep testing anything.
    """
    orch, engine, life, gov = _build("roomy")
    assert orch._thinking_on is False


def test_gear_machine_disables_thinking_on_empty_rate():
    life = FakeLifecycle()
    orch, engine, life, gov = _build("tight", life=life, empty_text=True)
    # Thinking now defaults to OFF, so we must explicitly turn it ON first --
    # otherwise the final assertion passes trivially against the default and
    # stops covering the G3 trap ("can the gear machine actually turn thinking
    # off?"). Flipping the assertion to False instead of setting up the state
    # would have deleted the coverage while leaving the test green.
    orch._thinking_on = True
    orch.run("investigate the repo")
    # sustained empty answers -> Governor disables thinking (G3 trap)
    assert orch._thinking_on is False


def test_swap_cap_alert_emitted():
    life = FakeLifecycle()
    orch, engine, life, gov = _build("tight", life=life)
    gov.cfg.max_swaps_per_task = 1
    orch.run("investigate the repo")  # >=1 swap expected
    # two more mounts push the swap count past the cap of 1
    orch._mount("btl3")
    orch._mount("rag_n7")
    alert = orch.governor.swap_cap_exceeded()
    assert alert is not None
    assert alert.kind == "alert"


# ---- BUG-1 regression: VRAM must reach the governor as a real 0-100% value ----

def _bare_orch(engine):
    """Build an Orchestrator with no __init__ side effects for unit probing."""
    orch = Orchestrator.__new__(Orchestrator)
    orch.engine = engine
    orch._vram_pct_warned = False
    return orch


def test_vram_pct_reports_real_percentage_not_gb():
    """peft backend exposes vram_total_gb, so 45GB/48GB must become 93.75%,
    NOT the raw 45 the old code fed the governor (which never reached 90)."""
    class GbEngine:
        def vram_gb(self):
            return 45.0
        def vram_total_gb(self):
            return 48.0
    assert _bare_orch(GbEngine())._vram_pct() == 93.75


def test_vram_pct_prefers_engine_vram_pct():
    """llama.cpp backend shells out to rocm-smi and returns a true percentage;
    the orchestrator must use it directly rather than re-deriving from GB."""
    class PctEngine:
        def vram_pct(self):
            return 93.75
        def vram_gb(self):
            return 45.0
    assert _bare_orch(PctEngine())._vram_pct() == 93.75


def test_governor_triggers_kv_quant_at_high_vram():
    """The KV-quant safety net must fire at >=90%; this is exactly what the
    old GB-as-percent bug kept silent (45 'percent' never tripped it)."""
    g = Governor()
    acts = g.observe(RuntimeMetrics(vram_pct=93.0, tokens_per_s=40.0,
                                    empty_rate=0.0))
    assert any(a.kind == "set_kv_quant" for a in acts)


# ---- BUG-2 regression: degenerate plan must be logged, not silent ----

def test_plan_fallback_is_logged(caplog):
    """When the planner emits non-JSON, run() must log a warning instead of
    silently degrading to a single 'agent' step."""
    import logging as _logging
    orch, engine, life, gov = _build("roomy")
    with caplog.at_level(_logging.WARNING, logger="screwshell.orchestrator"):
        # force a non-JSON plan from the fake engine
        engine.chat = lambda messages, **kw: ("not json",  # type: ignore[assignment]
                                              GenStats(None, 1, 1, 1.0))
        orch.run("do something")
    assert any("non-JSON plan" in r.message for r in caplog.records)


# ---- MINOR regression: switch accounting is per-query, not session-cumulative ----

def test_switch_log_is_per_query_not_cumulative():
    """In a REPL/multi-turn session the orchestrator instance (and its engine)
    is reused across queries. engine.switch_log used to accumulate forever, so
    engine.status()['switches'] and RunResult.stats['switches'] reported a
    session-wide tally that bled prior queries into the current one. Reset it
    per run() so each query is reported in isolation."""
    orch, engine, life, gov = _build("roomy")
    r1 = orch.run("query one")
    n1 = len(engine.switch_log)
    assert n1 > 0, "first query must have recorded switches"
    assert r1.stats["engine"]["switches"] == n1
    assert len(r1.stats["switches"]) == n1

    r2 = orch.run("query two")
    # the second query must NOT inherit the first query's switch records
    assert len(engine.switch_log) == n1, (
        f"second query switch_log={len(engine.switch_log)} must equal the "
        f"first query's {n1}, not the cumulative {n1 * 2}")
    assert r2.stats["engine"]["switches"] == n1
    assert len(r2.stats["switches"]) == n1


# ---- fast path: greetings skip the loop, real questions never do ----------
#
# The first implementation matched greetings with `any(g in query for g in ...)`.
# "hi" and "hey" are substrings of very ordinary words — t-hi-s, w-hi-ch,
# hi-story, somet-hi-ng, mac-hi-ne, t-hey — so genuine questions were answered
# off the cuff with no plan, no tools and no evidence. It also silently disabled
# the BUG-2 plan-fallback logging fix, whose test queries "do something".
#
# The false-negative direction (a greeting that runs the full loop) merely
# wastes a few seconds. The false-positive direction returns a confident
# non-answer to a real question. These tests weight them accordingly: the
# NEGATIVE list is the valuable half and should grow whenever a new phrasing
# shows up in the wild.

_GREETINGS = [
    "你好", "你好呀", "您好", "哈喽", "嗨", "在吗", "谢谢", "谢谢你", "感谢",
    "早上好", "下午好", "晚上好", "你是谁", "你叫什么名字",
    "hi", "Hi!", "hello", "Hello.", "hey", "yo", "thanks", "Thank you!",
    "good morning", "who are you", "  hi  ",
]

_REAL_QUERIES = [
    # every one of these was classified as chit-chat by the substring version
    "What is this repo about?",          # t-hi-s
    "Which adapter is mounted?",         # w-hi-ch
    "check the history log",             # hi-story
    "hierarchy of the skill map?",       # hi-erarchy
    "do something",                      # somet-hi-ng  <- broke a shipped test
    "audit the machine config",          # mac-hi-ne
    "are they using the right expert?",  # t-hey
    "summarize this file",               # t-hi-s
    "分析一下 architecture 有什么问题",
    "This crashes, why?",
    # not substring traps, just ordinary work that must never be short-circuited
    "调查这个仓库的 LoRA 编排逻辑",
    "hi-res texture pipeline overview",  # starts with the greeting, isn't one
    "hello world program in rust",       # ditto
    "谢谢，另外帮我看下 governor 的 swap 预算是怎么算的",  # greeting + real ask
]


@pytest.mark.parametrize("q", _GREETINGS)
def test_greetings_take_the_fast_path(q):
    orch, engine, life, gov = _build("roomy")
    res = orch.run(q)
    assert res.stats.get("fast_path") is True, f"{q!r} should be chit-chat"
    assert res.traces == [], "the fast path must not execute ReAct steps"
    assert res.task.steps == [], "the fast path must not build a plan"


@pytest.mark.parametrize("q", _REAL_QUERIES)
def test_real_questions_never_take_the_fast_path(q):
    orch, engine, life, gov = _build("roomy")
    res = orch.run(q)
    assert not res.stats.get("fast_path"), (
        f"{q!r} is a real question but was answered as a greeting — the "
        f"investigation loop was skipped entirely"
    )
    assert res.traces, "a real question must produce evidence-bearing steps"


def test_fast_path_does_not_swap_experts():
    """Answering "hi" must not pay for a LoRA swap.

    In tight mode a swap restarts the whole 27B server (~5s). The fast path
    used to mount the agent expert before replying, so the cheapest possible
    query triggered the single most expensive operation in the system —
    the opposite of the point. Any already-loaded expert can say hello.
    """
    life = FakeLifecycle()
    orch, engine, life, gov = _build("tight", life=life)
    res = orch.run("你好")
    assert life.restarts == [], "greeting must not restart the server"
    assert engine.switch_log == [], "greeting must not hot-swap a LoRA"
    assert res.stats["switches"] == [], "and the report must agree"
    assert res.stats["switch_kind"] == "none"


def test_fast_path_reports_real_switches_not_a_hardcoded_empty_list():
    """stats['switches'] is read from the engine, never hardcoded.

    The first version returned a literal [] while still mounting an expert, so
    the fast path under-reported swaps and contradicted the per-query switch
    accounting. Simulating a swap that happens anyway (e.g. left over from a
    lazy mount) must show up in the report.
    """
    orch, engine, life, gov = _build("roomy")
    orch._is_simple_query = lambda q: True          # force the fast path
    original_chat = engine.chat

    def chat_with_swap(messages, **kw):
        engine.activate("btl3")                     # a swap really happened
        return original_chat(messages, **kw)

    engine.chat = chat_with_swap
    res = orch.run("你好")
    assert res.stats["fast_path"] is True
    assert [s["to"] for s in res.stats["switches"]] == ["btl3"], (
        "the fast path must report the swaps the engine actually performed"
    )


def test_force_deep_overrides_the_fast_path():
    """The UI's "deep mode" toggle must beat greeting detection."""
    orch, engine, life, gov = _build("roomy")
    orch._force_deep = True
    res = orch.run("你好")
    assert not res.stats.get("fast_path")
    assert res.traces, "force_deep must run the full investigation"


def test_fast_path_emits_the_quick_phase_event():
    """The UI distinguishes a quick reply from a stalled investigation."""
    seen = []
    orch, engine, life, gov = _build("roomy")
    orch.on_event = lambda kind, payload: seen.append((kind, payload))
    orch.run("你好")
    assert ("phase", {"text": "quick"}) in seen


def test_full_run_emits_ordered_phase_events():
    """planning -> step_i_n -> finalizing, so progress can only move forward."""
    seen = []
    orch, engine, life, gov = _build("roomy")
    orch.on_event = lambda kind, payload: seen.append((kind, payload))
    orch.run("investigate the repo")
    phases = [p["text"] for k, p in seen if k == "phase"]
    assert phases[0] == "planning"
    assert phases[-1] == "finalizing"
    assert "quick" not in phases
    steps = [p for p in phases if p.startswith("step_")]
    assert steps == ["step_1_2", "step_2_2"], f"unexpected step phases: {steps}"


def test_fast_path_still_records_the_turn_in_memory():
    """A quick reply is still part of the conversation.

    If the fast path skipped memory, the next turn's history would show the
    user's greeting with no answer, and the model would see a broken transcript.
    """
    orch, engine, life, gov = _build("roomy")
    turns = []
    orch.memory.add_turn = lambda role, content, **kw: turns.append((role, content))
    orch.run("你好")
    assert [r for r, _ in turns] == ["user", "assistant"]


def test_orchestrator_passes_run_id_to_engine():
    """Every LLM request a UI session makes (plan/react/final/quick) must carry
    a run_id so the observ panel can tag it [UI] instead of [opencode].

    Without this, the relay sees no X-Run-Id header, tags the request as 'api',
    and the panel mislabels it [opencode] -- making it impossible to tell which
    frontend sent what. This is the regression for the 2026-08-04 production
    mislabel (UI requests showing up as [opencode]).
    """
    orch, engine, life, gov = _build("roomy")
    assert orch.run_id, "orchestrator must generate a run_id"
    orch.run("investigate the repo")
    # every plan/react/final call must have forwarded the same session run_id
    assert engine.last_run_id == orch.run_id, (
        f"engine.chat was called with run_id={engine.last_run_id!r}, "
        f"expected the orchestrator's session run_id {orch.run_id!r}")
