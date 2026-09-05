"""Offline unit tests for the llama.cpp MoL backend (path D).

No GPU / no real server required. We spin up a local http.server that mimics
the two endpoints the backend talks to:

    POST /lora-adapters      -> records the last scale array, returns {"ok":true}
    GET  /lora-adapters      -> returns the preloaded adapter list
    POST /v1/chat/completions -> echoes back which adapter id was requested

We assert:
  1. activate() posts the correct [{id, scale}] body
  2. activate(None) posts scale 0 for every preloaded adapter (native fallback)
  3. chat() forwards messages WITHOUT a per-request lora override (Phase 0 P0 fix)
  4. MoLLlamaCpp exposes the same 5-method surface as MoLEngine (signature parity)
  5. SkillRouter maps planning query -> teichai_plan (or None after fallback)
"""
from __future__ import annotations

import inspect
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from screwshell.core.mol_engine_llamacpp import MoLLlamaCpp
from screwshell.core.mol_types import SwitchRecord, GenStats
from screwshell.core.router import SkillRouter, DEFAULT_SKILL_MAP, is_forbidden, EXPERT_NAME_ALIASES
from screwshell.core.lora_scan import discover_adapters

# The peft backend (mol_engine.MoLEngine) imports torch at module load.
# Torch is only present on the GPU instance, not on a plain dev box, so we
# import it lazily and skip the parity test when it is unavailable.
try:
    from screwshell.core.mol_engine import MoLEngine  # type: ignore
    _HAS_TORCH = True
except ModuleNotFoundError:
    _HAS_TORCH = False


# ---- mock server ----

class _Handler(BaseHTTPRequestHandler):
    received = []          # list of (method, path, body)
    fail_next = False      # one-shot: next POST answers 500 (HTTP failure path)
    preloaded = [
        {"id": 0, "path": "btl3", "scale": 0.0},
        {"id": 1, "path": "teichai_plan", "scale": 0.0},
        {"id": 2, "path": "cybersec", "scale": 0.0},
        {"id": 3, "path": "rag_n7", "scale": 0.0},
    ]

    def log_message(self, *a):  # silence
        pass

    def do_GET(self):
        if self.path == "/lora-adapters":
            self._send(200, json.dumps(self.preloaded).encode())
        else:
            self._send(404, b"{}")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        self.received.append((self.command, self.path, body))
        if _Handler.fail_next:
            _Handler.fail_next = False
            self._send(500, b'{"error":"simulated server failure"}')
            return
        if self.path == "/lora-adapters":
            self._send(200, b'{"ok":true}')
        elif self.path == "/v1/chat/completions":
            lora = body.get("lora")
            self._send(200, json.dumps({
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 2},
                "echo_lora": lora,
            }).encode())
        else:
            self._send(404, b"{}")

    def _send(self, code, data: bytes):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture
def server():
    _Handler.received.clear()
    _Handler.fail_next = False
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}"
    srv.shutdown()


def test_load_base_resolves_preloaded_ids(server):
    eng = MoLLlamaCpp("Qwen3.6-27B", server_url=server).load_base()
    assert eng.adapters["btl3"]["id"] == 0
    assert eng.adapters["teichai_plan"]["id"] == 1
    assert eng.adapters["cybersec"]["id"] == 2
    assert eng.adapters["rag_n7"]["id"] == 3


def test_activate_posts_correct_scale(server):
    eng = MoLLlamaCpp("Qwen3.6-27B", server_url=server).load_base()
    rec = eng.activate("btl3")
    assert isinstance(rec, SwitchRecord)
    assert rec.mode == "set_adapter"
    posted = _Handler.received[-1][2]
    # Roomy mode must send an EXHAUSTIVE scale vector: target 1.0 and every
    # other preloaded adapter explicitly 0.0. Posting only the target
    # ([{"id":0,"scale":1.0}]) leaves whatever was previously enabled still
    # enabled, so several LoRAs blend into one another and the "active expert"
    # in the report is a lie.
    assert posted == [{"id": 0, "scale": 1.0},
                      {"id": 1, "scale": 0.0},
                      {"id": 2, "scale": 0.0},
                      {"id": 3, "scale": 0.0}]
    assert eng.active_adapter == "btl3"


def test_activate_unpreloaded_adapter_fails_loudly(server):
    """An adapter with no server-side id must NOT report a successful mount.

    load_adapter() registers unknown adapters with id=-1. The roomy-mode
    "target 1.0, others 0.0" vector then matches nothing and zeroes every
    adapter -- the server accepts it, so without this guard the engine would
    claim active_adapter == the expert while actually running the bare base.
    Silent quality loss with a green log; the mount must be reported as failed.
    """
    eng = MoLLlamaCpp("Qwen3.6-27B", server_url=server).load_base()
    eng.load_adapter("ghost_expert", "/nowhere/ghost/adapter.gguf")
    rec = eng.activate("ghost_expert")
    assert rec.mode == "mount_failed_base"
    assert rec.to_adapter is None
    assert eng.active_adapter is None, "must not claim an expert it never mounted"
    posted = _Handler.received[-1][2]
    assert all(e["scale"] == 0.0 for e in posted), "unmountable expert -> pure base"


def test_load_base_skips_forbidden_preloaded_expert(server):
    """A forbidden LoRA preloaded server-side must never be registered.

    The ban has to hold at every registration layer (TRUTH section 6), not just
    routing -- otherwise launching the server with a stale --lora quietly makes
    the expert mountable again.
    """
    original = _Handler.preloaded
    _Handler.preloaded = original + [{"id": 4, "path": "/loras/fable5/adapter.gguf",
                                      "scale": 0.0}]
    try:
        eng = MoLLlamaCpp("Qwen3.6-27B", server_url=server).load_base()
        assert "fable5" not in eng.adapters
        assert "btl3" in eng.adapters, "legitimate experts must still register"
    finally:
        _Handler.preloaded = original


def test_load_base_names_adapters_by_parent_dir_and_logical_name(server):
    """Adapter keys come from the parent DIRECTORY, mapped to the logical name.

    Two failure modes this locks down:
      1. naming by the .gguf filename collapses every expert into one
         "adapter" key (they are all called adapter.gguf on disk);
      2. naming by the raw disk folder bypasses EXPERT_NAME_ALIASES, so the
         planning expert registers as `teichai_fable5_plan` while the router
         asks for `teichai_plan` -- lookup misses, expert silently degrades.
    Must agree with discover_adapters(), which uses the same authority.
    """
    original = _Handler.preloaded
    _Handler.preloaded = [
        {"id": 0, "path": "/persistent/loras/btl3/adapter.gguf", "scale": 0.0},
        {"id": 1, "path": "/persistent/loras/teichai_fable5_plan/adapter.gguf",
         "scale": 0.0},
    ]
    try:
        eng = MoLLlamaCpp("Qwen3.6-27B", server_url=server).load_base()
        assert set(eng.adapters) == {"btl3", "teichai_plan"}
        assert eng.adapters["teichai_plan"]["id"] == 1
        # the key the router will ask for must be exactly this one
        assert DEFAULT_SKILL_MAP["agent"] in eng.adapters
    finally:
        _Handler.preloaded = original


def test_activate_none_disables_all(server):
    eng = MoLLlamaCpp("Qwen3.6-27B", server_url=server).load_base()
    eng.activate("btl3")
    rec = eng.activate(None)
    assert rec.mode == "disable"
    posted = _Handler.received[-1][2]
    # all preloaded adapters forced to scale 0
    assert posted == [{"id": 0, "scale": 0.0},
                      {"id": 1, "scale": 0.0},
                      {"id": 2, "scale": 0.0},
                      {"id": 3, "scale": 0.0}]
    assert eng.active_adapter is None


def test_activate_http_failure_fails_loudly(server):
    """P0: a failed POST /lora-adapters must NOT record a successful switch.

    The pre-fix code caught the HTTP error, logged it, and still recorded
    active_adapter=<name> plus a green SwitchRecord -- so callers like
    InferenceCoordinator advanced _current_expert, and every status()/event
    claimed the expert was mounted while the server actually ran the previous
    state (possibly the bare base). That is the silent-fallback P0 resurrected
    on the HTTP-failure path. Now: raise, record switch_failed_base, and leave
    active_adapter None so the rest of the stack cannot believe a lie.
    """
    eng = MoLLlamaCpp("Qwen3.6-27B", server_url=server).load_base()
    _Handler.fail_next = True  # next POST answers 500
    with pytest.raises(RuntimeError):
        eng.activate("btl3")
    assert eng.active_adapter is None, \
        "must not claim an expert the server never mounted"
    assert eng.switch_log[-1].mode == "switch_failed_base"
    assert eng.switch_log[-1].to_adapter is None


def test_chat_forwards_messages_without_lora_override(server):
    """Phase 0 P0 fix: chat() must NEVER inject a per-request "lora" override.

    The LoRA switch is owned exclusively by activate() (global POST
    /lora-adapters) in direct mode, and by the relay/coordinator in relay_mode.
    Mixing a per-request "lora" with the global switch is the silent
    base-fallback bug (kv_reprefill_report P0). So chat() forwards the messages
    and lets the server's already-applied global adapter serve the request.
    """
    eng = MoLLlamaCpp("Qwen3.6-27B", server_url=server).load_base()
    eng.activate("rag_n7")
    msgs = [{"role": "user", "content": "read this py file"}]
    text, stats = eng.chat(msgs)
    assert text == "ok"
    assert isinstance(stats, GenStats)
    # chat must POST to /v1/chat/completions
    chat_post = [r for r in _Handler.received if r[1] == "/v1/chat/completions"][-1]
    assert chat_post[2]["messages"] == msgs
    # P0: no per-request lora override in the forwarded payload
    assert "lora" not in chat_post[2]


def test_interface_parity_with_peft():
    """MoLLlamaCpp must expose the same 5-method contract as MoLEngine."""
    if not _HAS_TORCH:
        pytest.skip("torch not installed locally; parity check runs on GPU instance")
    methods = ["load_base", "load_adapter", "activate", "chat", "status"]
    for m in methods:
        a = inspect.signature(getattr(MoLLlamaCpp, m))
        b = inspect.signature(getattr(MoLEngine, m))
        # drop 'self' for comparison
        pa = [p for p in a.parameters.values() if p.name != "self"]
        pb = [p for p in b.parameters.values() if p.name != "self"]
        assert [p.name for p in pa] == [p.name for p in pb], f"arg mismatch on {m}"
        assert [p.default for p in pa] == [p.default for p in pb], f"default mismatch on {m}"


def test_skill_map_routing():
    router = SkillRouter()
    # planning query -> agent -> teichai_plan (stage-5 acceptance default)
    d = router.route("调查这份 ROCm 迁移计划的主要风险，先给出分步调查方案")
    assert d.skill == "agent"
    assert d.adapter == "teichai_plan"
    # code query -> code -> btl3
    d2 = router.route("读这个 py 文件，解释为什么 benchmark 慢")
    assert d2.skill == "code"
    assert d2.adapter == "btl3"
    # security-intent query -> security -> cybersec (new pipeline step)
    d3 = router.route("audit this auth module for CVE and SQL injection vulnerabilities")
    assert d3.skill == "security"
    assert d3.adapter == "cybersec"
    # doc/summary query -> doc -> rag_n7
    d4 = router.route("summarize the incident report and write the risk memo")
    assert d4.skill == "doc"
    assert d4.adapter == "rag_n7"


def test_skill_map_doc_fallback_to_none():
    """n7 fallback: if rag_n7 fails acceptance, set doc->None.
    Router then degrades to activate(None) = base native thinking."""
    router = SkillRouter(skill_map={**DEFAULT_SKILL_MAP, "doc": None})
    d = router.route("summarize the incident report", task_tag="doc")
    assert d.adapter is None


def test_skill_map_planning_fallback_to_none():
    """B+ fallback: if TeichAI fails acceptance, set agent->None.
    Router then degrades to activate(None) = base native thinking."""
    router = SkillRouter(skill_map={**DEFAULT_SKILL_MAP, "agent": None})
    d = router.route("调查这份 ROCm 迁移计划的主要风险", task_tag="agent")
    assert d.adapter is None


# ---- G5 doc-sync gate: config/docs must not resurrect removed experts ----
# Catches the doc-drift class of bug where a silently-mismatched base (hermes_s2)
# or a never-downloaded repo (fable5) creeps back into bench config / skill map
# even though they were removed from the live lineup. Static artifacts must stay
# in lock-step with the verified runtime.
import json as _json
from pathlib import Path as _Path

_REPO_ROOT = _Path(__file__).resolve().parents[1]
_BENCH_JSON = _REPO_ROOT / "bench" / "benchmark_pathd.json"
_FORBIDDEN = {"hermes_s2", "fable5"}
_NEW_LINEUP = {"btl3", "teichai_plan", "cybersec", "rag_n7"}


def test_bench_config_has_no_removed_experts():
    """bench/benchmark_pathd.json must reflect the finalized lineup, NOT the
    pre-cleanup hermes_s2/fable5 snapshot."""
    assert _BENCH_JSON.exists(), f"missing {_BENCH_JSON}"
    data = _json.loads(_BENCH_JSON.read_text(encoding="utf-8"))
    server_args = data.get("meta", {}).get("server_args", "")
    # server_args mounts adapters as <name>/adapter.gguf; extract basenames
    mounted = {p for p in server_args.replace(",", " ").split()
               if p.endswith("/adapter.gguf")}
    mounted = {m.split("/")[0] for m in mounted}
    # server_args names the on-disk folder (teichai_fable5_plan); resolve to the
    # logical name (teichai_plan) so the lineup check uses the code-facing name.
    _ondisk_to_logical = {v: k for k, v in EXPERT_NAME_ALIASES.items()}
    mounted = {_ondisk_to_logical.get(m, m) for m in mounted}
    for bad in _FORBIDDEN:
        assert bad not in mounted, \
            f"bench server_args still mounts removed {bad}: {server_args}"
    assert _NEW_LINEUP.issubset(mounted), \
        f"bench server_args missing finalized experts: {_NEW_LINEUP - mounted}"
    adapters = data.get("adapters", {})
    assert not (set(adapters) & _FORBIDDEN), \
        f"bench adapters still list removed experts: {set(adapters) & _FORBIDDEN}"
    assert _NEW_LINEUP.issubset(set(adapters)), \
        f"bench adapters missing finalized experts: {_NEW_LINEUP - set(adapters)}"


def test_skill_map_excludes_removed_experts():
    """DEFAULT_SKILL_MAP must never resurrect hermes_s2/fable5."""
    router = SkillRouter()
    active = {v for v in router.skill_map.values() if v is not None}
    assert not (active & _FORBIDDEN), \
        f"skill_map still references removed experts: {active & _FORBIDDEN}"
    assert _NEW_LINEUP.issubset(active), \
        f"skill_map missing finalized experts: {_NEW_LINEUP - active}"


def test_scan_skips_forbidden_experts(tmp_path):
    """Adapter discovery must never register forbidden experts (hermes_s2/fable5).

    Closes the gap where the ban lived only in DEFAULT_SKILL_MAP but a stale
    on-disk copy would still be loaded by the scan layer (see TRUTH §6). A real
    folder on disk must be ignored, and legitimate experts must still resolve.
    """
    (tmp_path / "hermes_s2" / "adapter.gguf").mkdir(parents=True)
    (tmp_path / "fable5" / "adapter.gguf").mkdir(parents=True)
    (tmp_path / "btl3" / "adapter.gguf").mkdir(parents=True)
    found = discover_adapters(str(tmp_path), "llamacpp")
    assert "hermes_s2" not in found, "forbidden hermes_s2 was discovered"
    assert "fable5" not in found, "forbidden fable5 was discovered"
    assert found.get("btl3", "").endswith("adapter.gguf")


def test_scan_anchored_forbidden_no_substring(tmp_path):
    """The forbidden ban is an ANCHORED exact match, not substring.

    A folder like 'xfable5y' or 'my_hermes_s2' must NOT be skipped — only the
    exact names hermes_s2 / fable5 are banned, so a renamed expert that merely
    *resembles* a forbidden name (the old teichai_fable5_plan collision) is safe.
    """
    (tmp_path / "xfable5y" / "adapter.gguf").mkdir(parents=True)
    (tmp_path / "my_hermes_s2" / "adapter.gguf").mkdir(parents=True)
    (tmp_path / "teichai_plan" / "adapter.gguf").mkdir(parents=True)
    found = discover_adapters(str(tmp_path), "llamacpp")
    assert "xfable5y" in found, "anchored ban must not skip non-exact names"
    assert "my_hermes_s2" in found, "anchored ban must not skip non-exact names"
    assert "teichai_plan" in found, "renamed expert must resolve normally"


def test_is_forbidden_is_anchored():
    """router.is_forbidden uses an anchored regex, never substring."""
    assert is_forbidden("fable5")
    assert is_forbidden("hermes_s2")
    assert not is_forbidden("teichai_plan")       # renamed expert, no collision
    assert not is_forbidden("xfable5y")           # substring must NOT match
    assert not is_forbidden("my_hermes_s2_extra")


def test_is_forbidden_accepts_none():
    """None is the pure-base route (the documented doc->None fallback).

    The guard now runs on every routing decision, and "no adapter" is a
    legitimate outcome. Raising TypeError here would break the base path.
    """
    assert is_forbidden(None) is False


# ---- the forbidden guard must cover EVERY route() exit ---------------------
#
# The guard originally sat on the last `return` of route() only. That branch is
# unreachable on the main path: the Orchestrator always calls
# `route(desc, task_tag=step["skill"])`, which returns from the very first
# branch. The ban existed, read correctly, and protected nothing.
#
# Covering every entry style is the point here — a future branch added to
# route() that skips the guard has to fail one of these.

@pytest.mark.parametrize("poisoned_skill,query,task_tag", [
    ("agent",    "调查这份计划的风险，先给出分步调查方案", None),  # planning keywords
    ("agent",    "just chatting about nothing",           None),  # default branch
    ("agent",    "anything",                              "agent"),  # explicit tag
    ("code",     "读这个 py 文件，解释为什么 benchmark 慢",  None),
    ("code",     "anything",                              "code"),
    ("security", "audit this auth module for CVE and SQL injection", None),
    ("security", "anything",                              "security"),
    ("doc",      "summarize the incident report and write the risk memo", None),
    ("doc",      "anything",                              "doc"),
    ("tool",     "anything",                              "tool"),
])
def test_forbidden_expert_is_blocked_on_every_route_path(
        poisoned_skill, query, task_tag):
    """A poisoned skill_map must never yield a forbidden adapter.

    Simulates the realistic failure: a SkillPack scan (or a hand-edited config)
    resurrects `fable5` for one skill. Routing must degrade to base rather than
    mount a banned LoRA, whichever branch happens to fire.
    """
    router = SkillRouter()
    router.skill_map[poisoned_skill] = "fable5"

    d = router.route(query, task_tag=task_tag)

    if d.skill == poisoned_skill:
        assert d.adapter is None, (
            f"route({query!r}, task_tag={task_tag!r}) returned the FORBIDDEN "
            f"adapter {d.adapter!r} — the guard was bypassed on this branch"
        )
        assert "FORBIDDEN" in d.reason, (
            "a silent downgrade is how this class of bug hides; the reason "
            "string must record the block"
        )


def test_forbidden_guard_leaves_legitimate_routes_untouched():
    """The guard blocks only banned experts; everything else routes normally."""
    router = SkillRouter()
    router.skill_map["agent"] = "fable5"

    assert router.route("anything", task_tag="agent").adapter is None

    for tag, expected in [("code", "btl3"), ("security", "cybersec"),
                          ("doc", "rag_n7"), ("tool", "btl3")]:
        d = router.route("anything", task_tag=tag)
        assert d.adapter == expected, f"{tag} must still route to {expected}"
        assert "FORBIDDEN" not in d.reason


def test_route_to_base_is_not_treated_as_forbidden():
    """skill_map entries that are legitimately None must route cleanly."""
    router = SkillRouter()
    router.skill_map["doc"] = None          # the documented n7 fallback

    d = router.route("summarize the incident report and write the risk memo")

    assert d.skill == "doc"
    assert d.adapter is None
    assert "FORBIDDEN" not in d.reason, "base is a valid route, not a blocked one"


def test_every_route_return_goes_through_the_guard():
    """Structural check: no `return RouteDecision(...)` may bypass _decide().

    The behavioural tests above can only cover branches that exist today. This
    one fails the moment someone adds a branch to route() that constructs a
    RouteDecision directly — which is exactly how the guard became dead code.
    """
    import inspect
    src = inspect.getsource(SkillRouter.route)
    assert "RouteDecision(" not in src, (
        "route() must build every decision via self._decide() so the "
        "forbidden-expert guard cannot be bypassed"
    )


def test_importing_the_app_does_not_pull_in_torch():
    """The llama.cpp/HTTP deployment must run on a box with no torch installed.

    `MoLEngine` (peft backend) imports torch at module load, so a single
    top-level `from screwshell.core.mol_engine import MoLEngine` in app.py makes
    torch a hard dependency of the local UI — which then fails to start with an
    ImportError on any machine that never needed it. The import is deliberately
    lazy inside the peft branch; this test is the tripwire that keeps it there.

    Runs in a subprocess: another test in this session may already have imported
    torch, and an in-process `sys.modules` check would then pass or fail for
    reasons unrelated to app.py.
    """
    import subprocess
    import sys
    import os

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    probe = (
        "import sys; import screwshell.app; "
        "print('TORCH' if 'torch' in sys.modules else 'CLEAN')"
    )
    env = dict(os.environ, PYTHONPATH=root)
    out = subprocess.run([sys.executable, "-c", probe], cwd=root, env=env,
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, f"importing screwshell.app failed:\n{out.stderr}"
    assert out.stdout.strip() == "CLEAN", (
        "importing screwshell.app pulled in torch — the peft-only import "
        "escaped back to module level and the torch-free deployment is broken"
    )
