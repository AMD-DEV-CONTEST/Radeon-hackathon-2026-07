"""Agent tools: schemas, dispatch, and guardrails.

Least-privilege by construction: the agent acts only through this
whitelist, every argument is bounds-checked, and rejections return an
explanatory error string the model can read and adapt to.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Callable

BOUNDS = {
    "max_num_seqs": (1, 512),
    "concurrency": (1, 64),
    "power_cap_w": (100, 241),  # gfx1100 cloud SKU: board cap 241 W read from amdsmi power_limit
}

# Backends present in this vLLM 0.16.1 ROCm build (registry.py, verified on the
# instance). FLASH_ATTN on RDNA requires FLASH_ATTENTION_TRITON_AMD_ENABLE=TRUE,
# which the restart script sets. Which ones actually load is a measurement.
ROCM_ATTENTION_BACKENDS = ("TRITON_ATTN", "ROCM_ATTN", "FLASH_ATTN", "ROCM_AITER_UNIFIED_ATTN")

_STATE_PATH = os.environ.get("VLLM_STATE", "/workspace/vllm_state.json")
_RESTART_SCRIPT = os.environ.get("RESTART_SCRIPT", "/root/rocm-autopilot/scripts/restart_vllm.sh")


def _read_state() -> dict:
    try:
        with open(_STATE_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def _relaunch(backend=None, max_num_seqs=None, enable_prefix_caching=None) -> bool:
    """Relaunch the deployment, filling unspecified knobs from the live state."""
    import subprocess
    st = _read_state()
    b = backend or st.get("attention_backend", "TRITON_ATTN")
    m = max_num_seqs if max_num_seqs is not None else st.get("max_num_seqs", 256)
    p = enable_prefix_caching if enable_prefix_caching is not None \
        else st.get("enable_prefix_caching", True)
    r = subprocess.run(["bash", _RESTART_SCRIPT, str(b), str(int(m)), "true" if p else "false"],
                       capture_output=True, text=True, timeout=900)
    return r.returncode == 0

TOOL_SCHEMAS = [
    {"type": "function", "function": {
        "name": "run_benchmark",
        "description": "Benchmark the live deployment with a serving configuration. Returns tokens/s, TTFT, ITL and energy per token.",
        "parameters": {"type": "object", "properties": {
            "max_num_seqs": {"type": "integer", "description": "vLLM max concurrent sequences (batch pressure)"},
            "enable_prefix_caching": {"type": "boolean"},
            "concurrency": {"type": "integer", "description": "client-side concurrent requests"},
        }, "required": ["max_num_seqs", "enable_prefix_caching", "concurrency"]}}},
    {"type": "function", "function": {
        "name": "set_power_cap",
        "description": "Set the GPU power limit in watts (takes effect for subsequent benchmarks).",
        "parameters": {"type": "object", "properties": {
            "watts": {"type": "integer"}}, "required": ["watts"]}}},
    {"type": "function", "function": {
        "name": "search_web",
        "description": "Search the web for framework knowledge (known issues, tuning guides). Use when metrics are surprising.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "search_papers",
        "description": "Search open-science literature (OpenAIRE) for optimization techniques.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "restart_server",
        "description": "Restart the deployment with a different attention backend (takes ~1-2 min). If the new backend fails to load, the previous configuration is restored and the failure is reported.",
        "parameters": {"type": "object", "properties": {
            "attention_backend": {"type": "string", "enum": list(ROCM_ATTENTION_BACKENDS)}},
            "required": ["attention_backend"]}}},
    {"type": "function", "function": {
        "name": "report_done",
        "description": "Stop optimizing. Call when further gains look below ~3%.",
        "parameters": {"type": "object", "properties": {
            "summary": {"type": "string"}}, "required": ["summary"]}}},
]


@dataclass
class Ctx:
    base_url: str = "http://localhost:8000"
    journal: object = None
    pending_power_cap: int | None = None
    bench_fn: Callable | None = None          # injectable for tests
    power_fn: Callable | None = None
    http_get: Callable | None = None
    extra: dict = field(default_factory=dict)

    @classmethod
    def for_tests(cls):
        return cls(bench_fn=lambda cfg, base_url: {"ok": True, "cfg": cfg},
                   power_fn=lambda w: True,
                   http_get=lambda url, params: {"stub": True})


def _reject(name: str, value, lo, hi) -> str:
    return json.dumps({"error": "rejected", "reason":
                       f"{name}={value} out of allowed range [{lo}, {hi}]. "
                       f"Guardrail: pick a value inside the range."})


def dispatch(name: str, args: dict, ctx: Ctx) -> str:
    try:
        if name == "run_benchmark":
            for key in ("max_num_seqs", "concurrency"):
                lo, hi = BOUNDS[key]
                if not (lo <= int(args[key]) <= hi):
                    return _reject(key, args[key], lo, hi)
            cfg = {"max_num_seqs": int(args["max_num_seqs"]),
                   "enable_prefix_caching": bool(args["enable_prefix_caching"]),
                   "concurrency": int(args["concurrency"]),
                   "power_cap_w": ctx.pending_power_cap}
            # max_num_seqs and prefix caching are server-side: they only take
            # effect through a relaunch. Restart when the request differs from
            # the live state (state file is written by restart_vllm.sh).
            st = _read_state()
            if st and (st.get("max_num_seqs") != cfg["max_num_seqs"]
                       or st.get("enable_prefix_caching") != cfg["enable_prefix_caching"]):
                relaunch = ctx.extra.get("relaunch_fn", _relaunch)
                if not relaunch(max_num_seqs=cfg["max_num_seqs"],
                                enable_prefix_caching=cfg["enable_prefix_caching"]):
                    return json.dumps({"error": "server relaunch with requested "
                                       "max_num_seqs/prefix_caching failed; previous config kept"})
            fn = ctx.bench_fn
            if fn is None:
                from autopilot.bench_runner import run_benchmark as fn
            result = fn(cfg, base_url=ctx.base_url)
            return json.dumps(result)

        if name == "set_power_cap":
            lo, hi = BOUNDS["power_cap_w"]
            watts = int(args["watts"])
            if not (lo <= watts <= hi):
                return _reject("power_cap_w", watts, lo, hi)
            fn = ctx.power_fn
            if fn is None:
                from autopilot.power import set_power_cap as fn
            ok = fn(watts)
            if ok:
                ctx.pending_power_cap = watts
            return json.dumps({"power_cap_w": watts, "applied": ok})

        if name == "search_web":
            key = os.environ.get("SERPAPI_API_KEY", "")
            if not key:
                return json.dumps({"error": "search unavailable (no key)"})
            get = ctx.http_get or _serpapi_get
            data = get("https://serpapi.com/search.json",
                       {"engine": "google_light", "q": args["query"], "api_key": key})
            hits = [{"title": r.get("title"), "snippet": r.get("snippet")}
                    for r in data.get("organic_results", [])[:3]]
            return json.dumps({"results": hits} if hits else data)

        if name == "search_papers":
            get = ctx.http_get or _openaire_get
            data = get("https://api.openaire.eu/search/publications",
                       {"keywords": args["query"], "format": "json", "size": 3})
            return json.dumps({"results": _openaire_trim(data)})

        if name == "restart_server":
            backend = str(args["attention_backend"])
            if backend not in ROCM_ATTENTION_BACKENDS:
                return json.dumps({"error": "rejected", "reason": f"backend {backend} not in whitelist"})
            fn = ctx.extra.get("restart_fn")
            ok = fn(backend) if fn is not None else _relaunch(backend=backend)
            return json.dumps({"attention_backend": backend, "restarted": ok})

        if name == "report_done":
            return json.dumps({"done": True, "summary": args.get("summary", "")})

        return json.dumps({"error": f"unknown tool {name}"})
    except Exception as e:  # a tool error must never kill the loop
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def _serpapi_get(url, params):
    import requests
    return requests.get(url, params=params, timeout=20).json()


def _openaire_get(url, params):
    import requests
    return requests.get(url, params=params, timeout=20).json()


def _openaire_trim(data) -> list[dict]:
    try:
        results = data["response"]["results"]["result"]
        out = []
        for r in results[:3]:
            md = r["metadata"]["oaf:entity"]["oaf:result"]
            title = md.get("title")
            if isinstance(title, list):
                title = title[0]
            out.append({"title": (title or {}).get("$", "untitled")})
        return out
    except Exception:
        return []
