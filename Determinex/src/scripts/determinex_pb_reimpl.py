#!/usr/bin/env python3
"""
determinex_pb_reimpl.py -- the LEGITIMATE ProgramBench loop: reverse-engineer -> reimplement
=========================================================================================
Composes the engine end-to-end for the HONEST task (no upstream source, no wrappers):

  task image -> observe the reference binary (determinex_observe) -> SOUND local oracle
       -> VerifiedSearch amplifies a from-scratch reimplementation (qwen2.5-coder:7b)
       -> first candidate that reproduces observed behavior wins -> package submission

This is NOT build-from-source. The candidate is NEW code (Python) that reproduces the
binary's observable I/O. Correctness is bounded by the oracle (observed behavior), so the
model is the swappable part. Final OFFICIAL scoring still runs the PB harness in
task_cleanroom_v6; this proves the engine and gives an honest local pass-rate.

Usage:
  python scripts/determinex_pb_reimpl.py <slug> [--k 8] [--rounds 3] [--model ollama/qwen2.5-coder:7b-instruct]
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import determinex_observe as OBS
import determinex_reimpl_corpus as CORPUS
from determinex_case_memory import CaseMemory
from determinex_contract import guard as contract_guard
from determinex_contract import native_code_contract, py_contract, trap_guard
from determinex_router import ModelEntry, ModelRouter

PLAYBOOK = ROOT / "corpus" / "programbench" / "REIMPLEMENTATION_PLAYBOOK.md"


def _api_key(name: str) -> str:
    """Read an API key from the ENVIRONMENT, with a local .env fallback for dev. NEVER
    hardcoded -- on release, users supply their OWN key via env, Determinex ships keyless."""
    import os

    v = os.getenv(name)
    if v:
        return v.strip()
    envf = ROOT / ".env"
    if envf.exists():
        for ln in envf.read_text(encoding="utf-8").splitlines():
            if ln.startswith(name + "="):
                return ln.split("=", 1)[1].strip()
    return ""


def _rate_limit_wait_s(
    retry_after_header: str | None, body_text: str, default: float, cap: float = 30.0
) -> float:
    """How long to sleep before retrying a 429. Prefers the server's own answer
    (Retry-After header, or retry_after_seconds in the error body -- OpenRouter's
    free :free models return this for a temporarily-saturated shared upstream pool)
    over a generic guess. Capped so a single retry loop can't stall on an
    absurd suggested wait -- fail fast and let the router escalate instead."""
    import json as _json

    if retry_after_header:
        try:
            return min(float(retry_after_header) + 1, cap)
        except ValueError:
            pass
    try:
        meta = _json.loads(body_text).get("error", {}).get("metadata", {})
        secs = meta.get("retry_after_seconds")
        if secs is not None:
            return min(float(secs) + 1, cap)
    except Exception:
        pass
    return default


def _post_json_hard(
    url: str, headers: dict, data: bytes, *, deadline: int = 120, attempts: int = 3
):
    """POST + parse JSON with a HARD total wall-clock per attempt, and retry.

    Why not just urlopen(timeout=): a stalled-but-ESTABLISHED connection (server accepted the
    request then went silent / trickles bytes) does NOT reliably trip urlopen's per-recv timeout
    -- we observed a generate() call frozen 338s with timeout=180 never firing, hanging the whole
    run. A daemon thread + join(deadline) gives a TRUE wall-clock: if the call hasn't returned by
    `deadline`, we abandon that (daemon) thread and retry on a fresh connection. Essential for an
    unattended batch march -- one dead socket must never stall the campaign.

    429-AWARE: a 429 is "come back in N seconds", not "broken" -- the generic backoff
    below (max 8s) was shorter than OpenRouter's observed ~19s suggested wait for its
    free :free models (a shared, temporarily-saturated upstream pool), so it burned
    every retry against a still-saturated pool and never got through. Honor the
    server's own Retry-After / retry_after_seconds instead."""
    import json as _json
    import threading
    import time as _time
    import urllib.error
    import urllib.request

    last = "no attempt made"
    for i in range(attempts):
        box: dict = {}

        def _do(_box=box):
            try:
                req = urllib.request.Request(url, data=data, headers=headers)
                _box["r"] = _json.loads(urllib.request.urlopen(req, timeout=deadline).read())
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", errors="replace")
                _box["e"] = f"HTTP {e.code}: {body[:500]}"
                _box["status"] = e.code
                _box["retry_after"] = e.headers.get("Retry-After")
                _box["body"] = body
            except Exception as e:  # noqa: BLE001 -- surfaced via box["e"]
                _box["e"] = str(e)

        t = threading.Thread(target=_do, daemon=True)
        t.start()
        t.join(deadline)
        if "r" in box:
            return box["r"]
        last = (
            f"hard-deadline {deadline}s exceeded (attempt {i + 1}/{attempts})"
            if t.is_alive()
            else box.get("e", "unknown error")
        )
        wait = min(2 * (i + 1), 8)
        if box.get("status") == 429:
            wait = _rate_limit_wait_s(box.get("retry_after"), box.get("body", ""), default=wait)
        _time.sleep(wait)
    raise RuntimeError(last)


def deepseek_generator(
    model: str = "deepseek-chat", host: str | None = None, num_predict: int = 8192
):
    """Cheap fast cloud generator (OpenAI-compatible). Key from env/.env, never hardcoded.

    DETERMINEX_DEEPSEEK_HOST overrides the endpoint -- used by the on-box engine to target a
    local key-proxy over an SSH reverse tunnel (so the API key never leaves the operator box).
    When pointed at the proxy, the proxy injects Authorization; no key is needed on the box."""
    import json as _json
    import os as _os
    import urllib.request  # noqa: F401

    host = host or _os.environ.get("DETERMINEX_DEEPSEEK_HOST", "https://api.deepseek.com")
    proxied = "api.deepseek.com" not in host
    key = _api_key("DEEPSEEK_API_KEY")

    def _gen(prompt: str, temperature: float) -> str:
        if not key and not proxied:
            return "__generation_error__: DEEPSEEK_API_KEY not set (export it; never hardcode)"
        body = _json.dumps(
            {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature,
                "max_tokens": num_predict,
            }
        ).encode()
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        try:
            r = _post_json_hard(host + "/chat/completions", headers, body, deadline=120, attempts=3)
            return r["choices"][0]["message"]["content"] or ""
        except Exception as e:
            return f"__generation_error__: {e}"

    return _gen


def anthropic_generator(model: str = "claude-opus-4-8", num_predict: int = 8192):
    """Frontier escalation tier (Claude). Key from env/.env, never hardcoded. Used by the
    router as a high-tier model: the cheap model clears the bulk, Claude clears the hard tail
    -> cheap-model-bulk + frontier-tail can EXCEED a single top model, oracle-bounded."""
    import json as _json

    key = _api_key("ANTHROPIC_API_KEY")

    def _gen(prompt: str, temperature: float) -> str:
        if not key:
            return "__generation_error__: ANTHROPIC_API_KEY not set (export it; never hardcode)"
        body = _json.dumps(
            {
                "model": model,
                "max_tokens": num_predict,
                "temperature": min(temperature, 1.0),
                "messages": [{"role": "user", "content": prompt}],
            }
        ).encode()
        try:
            r = _post_json_hard(
                "https://api.anthropic.com/v1/messages",
                {
                    "content-type": "application/json",
                    "x-api-key": key,
                    "anthropic-version": "2023-06-01",
                },
                body,
                deadline=300,
                attempts=3,
            )
            return "".join(b.get("text", "") for b in r.get("content", []))
        except Exception as e:
            return f"__generation_error__: {e}"

    return _gen


def uses_raw_gemini_api(model: str) -> bool:
    m = (model or "").strip().lower()
    if m.startswith(("local/", "ollama/", "tiny/")):
        return False
    return m.startswith("gemini-") or m.startswith("gemini/")


def _is_generation_error_text(text: str | None) -> bool:
    return bool(str(text or "").lstrip().startswith("__generation_error__"))


def gemini_generator(model: str = "gemini-3.1-flash-lite", num_predict: int = 4096):
    """Google Gemini Developer API generator.

    This is intentionally key-gated. Free-tier Gemini calls still require the
    operator's API key; Determinex never ships or invents one.
    """
    import json as _json

    key = _api_key("GEMINI_API_KEY") or _api_key("GOOGLE_API_KEY")
    try:
        max_tokens = int(os.environ.get("DETERMINEX_REIMPL_GEMINI_OUT_CAP", str(num_predict)))
    except ValueError:
        max_tokens = num_predict
    try:
        deadline = int(os.environ.get("DETERMINEX_REIMPL_GEMINI_DEADLINE", "90"))
    except ValueError:
        deadline = 90
    try:
        attempts = int(os.environ.get("DETERMINEX_REIMPL_GEMINI_ATTEMPTS", "1"))
    except ValueError:
        attempts = 1
    model_name = model.split("/", 1)[1] if model.startswith("gemini/") else model

    def _gen(prompt: str, temperature: float) -> str:
        if not key:
            return "__generation_error__: GEMINI_API_KEY not set (free tier still requires an operator API key)"
        body = _json.dumps(
            {
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": temperature,
                    "maxOutputTokens": max_tokens,
                },
            }
        ).encode()
        try:
            url = (
                "https://generativelanguage.googleapis.com/v1beta/"
                f"models/{model_name}:generateContent?key={quote(key)}"
            )
            r = _post_json_hard(
                url,
                {"Content-Type": "application/json"},
                body,
                deadline=max(15, deadline),
                attempts=max(1, attempts),
            )
            parts = ((r.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
            return "".join(str(part.get("text") or "") for part in parts)
        except Exception as e:
            return f"__generation_error__: {e}"

    return _gen


def uses_raw_openrouter_api(model: str) -> bool:
    m = (model or "").strip().lower()
    if m.startswith(("local/", "ollama/", "tiny/")):
        return False
    return m.startswith("openrouter/")


def openrouter_generator(model: str = "openrouter/qwen/qwen3-coder:free", num_predict: int = 8192):
    """OpenRouter generator (OpenAI-compatible), for genuinely free coding-capable models
    (e.g. qwen/qwen3-coder:free -- 480B/35B-active MoE, 1M ctx, free tier good for real
    k=8/rounds=3 amplification: 20 req/min, 50-1000 req/day, no context-truncation risk).

    2026-07-02: wired in as the DeepSeek/Gemini/Claude keys on this box were all out of
    quota -- this is the only remaining zero-cost cloud lane. Key from env/.env, never
    hardcoded; get a free key (no credit card) at https://openrouter.ai/keys.
    """
    import json as _json

    key = _api_key("OPENROUTER_API_KEY")
    model_name = model.split("/", 1)[1] if model.startswith("openrouter/") else model

    def _gen(prompt: str, temperature: float) -> str:
        if not key:
            return (
                "__generation_error__: OPENROUTER_API_KEY not set -- get a free key "
                "(no credit card) at https://openrouter.ai/keys and add it to .env"
            )
        body = _json.dumps(
            {
                "model": model_name,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature,
                "max_tokens": num_predict,
            }
        ).encode()
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
            # OpenRouter asks for these to attribute free-tier traffic; harmless if ignored.
            "HTTP-Referer": "https://github.com/determinex-dev/determinex",
            "X-Title": "Determinex ProgramBench reimpl",
        }
        try:
            # attempts=5: the free :free pool's observed 429 backoff (~19s) needs more
            # headroom than the other raw generators' default of 3 to actually clear.
            r = _post_json_hard(
                "https://openrouter.ai/api/v1/chat/completions",
                headers,
                body,
                deadline=180,
                attempts=5,
            )
            return r["choices"][0]["message"]["content"] or ""
        except Exception as e:
            return f"__generation_error__: {e}"

    return _gen


def _register_raw_factories() -> None:
    """CONVERGE onto determinex_providers (the universal registry) instead of duplicating it,
    BUT keep our proven raw-API generators: providers defaults to LiteLLM, which degraded
    DeepSeek output (7/10 syntax errors) -> register our raw factories so the WHOLE system
    (router/build-from-idea/repair) uses the working path and we inherit to_router_entries()
    + rate-limit rotation for free."""
    try:
        import determinex_providers as PROV

        PROV.register_provider(
            "deepseek",
            tier=3,
            env_key="DEEPSEEK_API_KEY",
            default_model="deepseek-chat",
            factory=lambda m: deepseek_generator(m),
        )
        PROV.register_provider(
            "claude",
            tier=4,
            env_key="ANTHROPIC_API_KEY",
            default_model="claude-opus-4-8",
            aliases=("anthropic",),
            factory=lambda m: anthropic_generator(m),
        )
        PROV.register_provider(
            "gemini",
            tier=2,
            env_key="GEMINI_API_KEY",
            default_model="gemini-3.1-flash-lite",
            aliases=("google",),
            factory=lambda m: gemini_generator(m),
        )
        PROV.register_provider(
            "openrouter",
            tier=2,
            env_key="OPENROUTER_API_KEY",
            default_model="openrouter/qwen/qwen3-coder:free",
            aliases=("qwen3-coder-free",),
            factory=lambda m: openrouter_generator(m),
        )

        def _local_model_name(m: str) -> str:
            for prefix in ("local/", "ollama/", "tiny/"):
                if m.startswith(prefix):
                    return m.split("/", 1)[1]
            return m

        # PREFIXED, like the canonical registration it replaces. This factory strips the
        # prefix itself (`_local_model_name`), so a bare tag happened to work HERE -- but
        # registering it bare overwrites the `local` provider process-wide for anyone who
        # imports this module, and `determinex_providers` guarantees that provider's default
        # names its backend. An unprefixed default does not route anywhere but this factory.
        #
        # It was caught as test pollution: `test_the_local_default_model_is_still_prefixed_in
        # _config` passed alone and failed whenever a PB test had imported this module first,
        # which is the signature of global state being rewritten at import rather than a
        # flaky test. Importing a module must not change which model the rest of the system
        # runs.
        PROV.register_provider(
            "local",
            tier=1,
            env_key="",
            aliases=("ollama",),
            default_model="ollama/qwen2.5-coder:7b-instruct",
            factory=lambda m: ollama_generator(_local_model_name(m)),
        )
    except Exception:
        pass


def uses_raw_deepseek_api(model: str) -> bool:
    """Return True only for cloud DeepSeek API model names.

    Local Ollama model tags can start with ``deepseek-`` too. Those must stay
    local/free when they are prefixed with local/ollama/tiny or are coder model
    tags, otherwise an overnight run silently leaves the free lane.
    """
    m = (model or "").strip().lower()
    if m.startswith(("local/", "ollama/", "tiny/")):
        return False
    return m in {"deepseek-chat", "deepseek-reasoner"} or m.startswith("deepseek/")


def make_generator(model: str):
    """One universal contract for ANY model. deepseek*/claude* use our proven raw-API path;
    everything else routes through determinex_providers (the registry: GPT/Gemini/Groq/local/…)."""
    if uses_raw_deepseek_api(model):
        return deepseek_generator(model)
    if uses_raw_gemini_api(model):
        return gemini_generator(model)
    if uses_raw_openrouter_api(model):
        return openrouter_generator(model)
    if model.startswith("claude"):
        return anthropic_generator(model)
    try:
        import determinex_providers as PROV

        if model.split("/")[0].split(":")[0].lower() in PROV._PROVIDERS:  # a known provider name
            return PROV.get_generator(model.split("/")[0].split(":")[0], model)
    except Exception:
        pass
    return ollama_generator(model)


_register_raw_factories()


def parse_model_ladder(spec: str) -> list[tuple[str, int, float]]:
    """Parse ``--models`` entries without breaking Ollama tags.

    Historical syntax is ``name:tier:cost``. Ollama model names also contain
    colons (``qwen2.5-coder:7b-instruct``), so only treat the last two fields as
    tier/cost when they are numeric. Otherwise the entire entry is the model.
    """
    ladder: list[tuple[str, int, float]] = []
    for raw in (spec or "").split(","):
        item = raw.strip()
        if not item:
            continue
        name, tier, cost = item, 1, 1.0
        parts = item.rsplit(":", 2)
        if len(parts) == 3:
            maybe_name, maybe_tier, maybe_cost = parts
            try:
                tier = int(maybe_tier)
                cost = float(maybe_cost)
                name = maybe_name
            except ValueError:
                name, tier, cost = item, 1, 1.0
        ladder.append((name, tier, cost))
    return ladder


def preflight_ladder(ladder_names: list[str], host: str = "http://localhost:11434") -> list[str]:
    """Verify every model in a --models ladder is ACTUALLY reachable before a drive spends
    any real compute -- observe/decompose can run for hours, and a broken escalation tier
    was previously indistinguishable from 'the model tried hard and failed' (see
    _is_generation_error_text: the error text just became the failing candidate, silently,
    for every single sample at that tier, for the whole run).

    Found live 2026-07-18: the reimpl drive's default ladder named
    'ollama/qwen2.5-coder:14b-instruct' as its escalation tier, but that model was never
    pulled -- every escalation attempt across 6+ stations silently produced a generation
    error masquerading as a wrong-code sample, and nobody could tell without querying
    Ollama by hand. Mirrors the equivalent check already in scripts/hive/executor.py
    ('Ollama model pre-flight') -- this is the same class of gap in a sibling subsystem.

    Returns a list of human-readable problems (empty = every model in the ladder is ready
    to actually generate). Never raises -- a network hiccup here shouldn't crash a caller
    that hasn't decided how to react yet; the CALLER decides whether to abort."""
    import json as _json
    import urllib.request

    problems: list[str] = []

    installed_ollama: set[str] | None = None

    def _ollama_installed() -> set[str]:
        nonlocal installed_ollama
        if installed_ollama is None:
            try:
                req = urllib.request.urlopen(host + "/api/tags", timeout=5)
                data = _json.loads(req.read())
                installed_ollama = {
                    m.get("name") or m.get("model") or "" for m in data.get("models", [])
                }
                installed_ollama.discard("")
            except Exception as e:
                problems.append(
                    f"could not reach Ollama at {host} ({e}) -- "
                    f"any ollama/* ladder entry cannot be verified"
                )
                installed_ollama = set()
        return installed_ollama

    for raw in ladder_names:
        name = raw.strip()
        if not name:
            continue
        low = name.lower()
        if low.startswith(("local/", "ollama/", "tiny/")):
            bare = name.split("/", 1)[1]
            tags = _ollama_installed()
            if tags and bare not in tags and not any(t.startswith(bare + ":") for t in tags):
                problems.append(
                    f"'{name}' -> Ollama has no model '{bare}' registered "
                    f"(run `ollama pull {bare}` or fix the --models spec; "
                    f"`ollama list` for what's actually available)"
                )
        elif uses_raw_deepseek_api(name):
            if not _api_key("DEEPSEEK_API_KEY"):
                problems.append(f"'{name}' needs DEEPSEEK_API_KEY, not set")
        elif uses_raw_gemini_api(name):
            if not (_api_key("GEMINI_API_KEY") or _api_key("GOOGLE_API_KEY")):
                problems.append(f"'{name}' needs GEMINI_API_KEY, not set")
        elif low.startswith("claude"):
            if not _api_key("ANTHROPIC_API_KEY"):
                problems.append(f"'{name}' needs ANTHROPIC_API_KEY, not set")
    return problems


def _model_ctx_len(model: str, host: str, default: int = 32768) -> int:
    """Query the model's native context length via /api/show (rotating cap, not a fixed
    guess). Different models differ wildly (qwen2.5-coder 32k, qwen3moe 256k)."""
    import json as _json
    import urllib.request

    try:
        req = urllib.request.Request(
            host + "/api/show",
            data=_json.dumps({"model": model}).encode(),
            headers={"Content-Type": "application/json"},
        )
        info = _json.loads(urllib.request.urlopen(req, timeout=30).read()).get("model_info", {})
        for k, v in info.items():
            if k.endswith(".context_length") or k == "context_length":
                return int(v)
    except Exception:
        pass
    return default


def ollama_generator(
    model: str,
    host: str = "http://localhost:11434",
    num_predict: int | None = None,
    num_ctx: int | None = None,
    out_cap: int = 8192,
    ctx_cap: int = 16384,
    keep_alive: str | None = None,
):
    """Raw Ollama /api/generate generate(prompt,temp)->str. Bypasses litellm (degraded
    output). ROTATING CAP: derive num_ctx/num_predict from the model's real context length
    (/api/show), capped for CPU sanity. A fixed cap silently truncated longer reimpls
    (the MoE wrote 203 lines > 1536 tokens -> broken). Generous output cap so a complete
    reimplementation never gets cut; num_ctx = min(model_ctx, ctx_cap) fits prompt+output."""
    import json as _json
    import os as _os
    import urllib.request

    env_ctx_cap = int(_os.environ.get("DETERMINEX_REIMPL_OLLAMA_CTX_CAP", str(ctx_cap)))
    env_out_cap = int(_os.environ.get("DETERMINEX_REIMPL_OLLAMA_OUT_CAP", str(out_cap)))
    mctx = _model_ctx_len(model, host)
    _num_ctx = num_ctx if num_ctx is not None else min(mctx, env_ctx_cap)
    _num_predict = (
        num_predict if num_predict is not None else min(max(2048, mctx // 8), env_out_cap)
    )
    _keep_alive = (
        keep_alive
        if keep_alive is not None
        else _os.environ.get("DETERMINEX_REIMPL_OLLAMA_KEEP_ALIVE", "0")
    )
    _keep_alive = str(_keep_alive).strip() or "0"

    def _gen(prompt: str, temperature: float) -> str:
        body = _json.dumps(
            {
                "model": model,
                "prompt": prompt,
                "stream": False,
                # Churn runs on a RAM-constrained CPU host. Keeping every escalated
                # model warm leaves multiple GGUFs resident and drives the box into
                # swap. Interactive runs can opt back in with DETERMINEX_REIMPL_OLLAMA_KEEP_ALIVE.
                "keep_alive": _keep_alive,
                "options": {
                    "temperature": temperature,
                    "num_predict": _num_predict,
                    "num_ctx": _num_ctx,
                },
            }
        ).encode()
        req = urllib.request.Request(
            host + "/api/generate", data=body, headers={"Content-Type": "application/json"}
        )
        try:
            resp = _json.loads(
                urllib.request.urlopen(req, timeout=700).read()
            )  # 1st call cold-loads 18GB
            return resp.get("response", "") or ""
        except Exception as e:
            return f"__generation_error__: {e}"

    return _gen


# Representative INPUT probes per tool (the playbook: generating these is part of the
# challenge; we seed a few to start the discovery loop, the oracle does the rest).
def _gron_probes() -> list[OBS.Probe]:
    """Rich, edge-case-covering battery so the LOCAL oracle (observed reference behavior)
    faithfully approximates the official hidden tests -- forcing the candidate to handle
    arrays, deep nesting, every scalar type, empty containers, special/numeric keys,
    unicode, exact number reprs, AND every output mode. A thin battery let a buggy
    candidate (array-as-object, duplicated output) pass locally yet fail official."""
    inputs = {
        "obj_arr": '{"a":1,"b":[true,"x"]}',
        "top_array": "[1,2,3]",
        "arr_objs": '[{"a":1},{"b":2}]',
        "deep": '{"a":{"b":{"c":[1,[2,3]]}}}',
        "types": '{"s":"hi","i":42,"neg":-7,"f":1.5,"sci":1.2e10,"t":true,"ff":false,"n":null}',
        "empty": '{"o":{},"a":[]}',
        "spec_keys": '{"a-b":1,"a.b":2,"a b":3,"123":4}',
        "unicode": '{"e":"caf\\u00e9","k":"\\u4f60\\u597d"}',
        # control-char escaping in STRING values: gron emits \t \n \" \\ escaped, never raw
        "escapes": '{"s":"a\\tb\\nc\\"d\\\\e"}',
        # reserved-word keys (true/false/null) -> gron BRACKET-quotes them: json["null"]
        "reserved": '{"true":1,"false":2,"null":3,"normal":4}',
        # empty-string key sort placement
        "empty_key": '{"":"e","a":1}',
    }
    probes: list[OBS.Probe] = []
    # core flatten via THREE channels per input: bare stdin (no flags -- the most common case,
    # MUST be pinned or the search can regress it), -m stdin, and -m file arg. Pinning bare
    # stdin stops a URL/file-centric candidate from winning the oracle while breaking stdin.
    for name, body in inputs.items():
        probes.append(OBS.Probe(f"bare_{name}", [], stdin=body))  # bare stdin (core invariant)
        probes.append(OBS.Probe(f"m_{name}", ["-m", f"{name}.json"], files={f"{name}.json": body}))
        probes.append(OBS.Probe(f"stdin_{name}", ["-m"], stdin=body))
    # bare --json / --stream / --no-sort via stdin too (official tests use these without -m or file)
    for mode, flag in [("bjson", "--json"), ("bstream", "--stream"), ("bnosort", "--no-sort")]:
        probes.append(OBS.Probe(f"{mode}_obj", [flag], stdin=inputs["obj_arr"]))
    # output modes on representative inputs
    for mode, flag in [("json", "--json"), ("stream", "--stream"), ("nosort", "--no-sort")]:
        for name in ("obj_arr", "deep", "types"):
            probes.append(
                OBS.Probe(
                    f"{mode}_{name}",
                    [flag, "-m", f"{name}.json"],
                    files={f"{name}.json": inputs[name]},
                )
            )
    # values + ungron round-trip (feed gron's own output shape)
    probes.append(
        OBS.Probe("values_obj", ["-v"], stdin='json.a = 1;\njson.b = "hi";\njson.c = true;')
    )
    probes.append(OBS.Probe("ungron_obj", ["-u"], stdin='json = {};\njson.a = 1;\njson.b = "x";'))
    probes.append(OBS.Probe("ungron_arr", ["-u"], stdin="json = [];\njson[0] = 1;\njson[1] = 2;"))
    return probes


_TASK_INPUTS: dict[str, list[OBS.Probe]] = {
    "gron": _gron_probes(),
}

# DETERMINEX RULE: native submissions. Set by main() from --lang; the prompt builders inject the
# language directive so the model rebuilds the tool in ITS language, compiler-verified.
_LANG: str = "python"
_LANG_RUN = {
    "python": "python3 main.py",
    "go": "the compiled Go binary",
    "rust": "the compiled Rust binary",
    "c": "the compiled C binary",
    "cpp": "the compiled C++ binary",
    "haskell": "the compiled Haskell binary",
}
# Single shared source for the output filename per language -- build_prompt() and
# build_incremental_prompt() both need this; a second hand-copied dict is exactly how
# build_prompt()'s "Your task" trailer silently stayed hardcoded to Python long after
# _lang_directive() was fixed to support native languages (found + fixed 2026-07-16).
_FNAME_BY_LANG = {
    "python": "main.py",
    "rust": "main.rs",
    "go": "main.go",
    "c": "main.c",
    "cpp": "main.cpp",
    "haskell": "main.hs",
}

_LANG_REF_DIR = ROOT / "corpus" / "programbench" / "language_reference"
_LANG_REF_FILE = {"rust": "rust.md", "go": "go.md", "c": "c.md", "cpp": "cpp.md"}
_SYSTEMS_REF_FILE = _LANG_REF_DIR / "systems.md"

# Non-language tool-CATEGORY families (file_renamers, search_grep, json_yaml_toml, ...) from
# corpus/programbench/families/ -- real, hand-written convention knowledge (help/error/flag
# shape per tool archetype) that predates the native-only rule and was orphaned: nothing in
# the CURRENT native reimplementation driver read it (audited 2026-07-16, confirmed by Ryan's
# "it might be orphaned"). The *_cli language families (rust_cli/go_cli/python_cli/node_cli)
# are excluded here -- rust_cli/go_cli's genuinely useful convention content is already
# absorbed into language_reference/{rust,go}.md; python_cli/node_cli aren't native-reimpl
# targets. This wires the REMAINING, still-unused, still-accurate family knowledge back in
# without duplicating anything -- zero new content-authoring cost.
_EXCLUDED_LANGUAGE_FAMILIES = {"rust_cli", "go_cli", "python_cli", "node_cli"}


def _language_reference_block(lang: str, max_chars: int = 8000) -> str:
    """Curated, project-independent language grounding (grammar/stdlib/idioms for THIS
    language) -- never the upstream project's own source, never another real benchmark
    target's code (that's determinex_code_rag's job, and it's explicitly technique-only).
    Empty for python (needs no native-build grounding) and for languages without a
    reference file yet (haskell) -- absent, not fabricated."""
    fname = _LANG_REF_FILE.get(lang)
    if not fname:
        return ""
    path = _LANG_REF_DIR / fname
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")[:max_chars]


def _systems_reference_block(max_chars: int = 8000) -> str:
    """OS/runtime-environment grounding (exit codes, TTY/signal/locale/Docker-root
    conventions) that applies regardless of implementation language -- distinct from
    CROSS_TOOL_PITFALLS (observable OUTPUT conventions) and from per-language stdlib grounding
    (language SYNTAX/API). Included for every language, not just native ones."""
    if not _SYSTEMS_REF_FILE.exists():
        return ""
    return _SYSTEMS_REF_FILE.read_text(encoding="utf-8")[:max_chars]


def _family_conventions_block(short: str, max_chars: int = 1800) -> str:
    """Tool-CATEGORY convention knowledge (this tool's archetype -- file renamer, search/grep,
    formatter, json/yaml tool, ...) mined from corpus/programbench/families/*/FAMILY.md.
    Distinct axis from language grounding: this is 'what do file-renaming CLIs conventionally
    do', not 'how does Rust work'. Best-effort: returns "" if the tool doesn't match a known
    family, or the family has no FAMILY.md yet (several wave3 entries are still TODO stubs)."""
    try:
        import programbench_classify_family as CLASSIFY
    except Exception:
        return ""
    try:
        families = [
            f for f in CLASSIFY._classify_by_name(short) if f not in _EXCLUDED_LANGUAGE_FAMILIES
        ]
    except Exception:
        return ""
    if not families:
        return ""
    family = families[0]
    matches = sorted(
        (ROOT / "corpus" / "programbench" / "families").glob(f"wave*/{family}/FAMILY.md")
    )
    if not matches:
        return ""
    try:
        content = matches[0].read_text(encoding="utf-8")
    except Exception:
        return ""
    return content[:max_chars]


def _lang_directive() -> str:
    if _LANG == "python":
        return "Write a single self-contained `main.py` (Python 3, stdlib only)."
    names = {"go": "Go", "rust": "Rust", "c": "C", "cpp": "C++", "haskell": "Haskell"}
    L = names.get(_LANG, _LANG)
    return (
        f"Write a single self-contained {L} program (standard library only, no external "
        f"packages — there is NO internet at build). It MUST COMPILE and run as a native "
        f"binary. Output ONLY one ```{_LANG}``` code block."
    )


def _image_for(slug: str) -> str | None:
    short = slug.split("__")[-1].split(".")[0]
    out = subprocess.run(
        ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"], capture_output=True, text=True
    ).stdout
    lines = [l for l in out.splitlines() if short in l.lower()]
    # prefer the plain :task image; fall back to task_cleanroom_v6 (also has /workspace/executable
    # -- it's the inference image -- so observe works there too; many tools are cleanroom-only).
    cands = [l for l in lines if l.endswith(":task") and "cleanroom" not in l]
    if not cands:
        cands = [l for l in lines if l.endswith("task_cleanroom_v6")]
    return cands[0] if cands else None


def _decode_output(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _docs_and_help(image: str, exe: str = "/workspace/executable") -> tuple[str, str]:
    """Pull README docs + the binary's --help text from the task image."""
    docs_proc = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--entrypoint",
            "sh",
            image,
            "-c",
            "cat /workspace/*.mkd /workspace/*.md /workspace/README* 2>/dev/null | head -c 6000",
        ],
        capture_output=True,
        text=False,
    )
    help_proc = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--entrypoint",
            "sh",
            image,
            "-c",
            f"{exe} --help 2>&1 | head -c 4000",
        ],
        capture_output=True,
        text=False,
    )
    return _decode_output(docs_proc.stdout), _decode_output(help_proc.stdout)


_CODE_RE = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.DOTALL)


def extract_code(text: str) -> str:
    """Pull the python from a model reply. Handles balanced ```python``` fences AND the
    UNBALANCED case (closing fence truncated by num_predict) -- strip a leading ```lang line
    and any trailing ```, so a long generation that ran out of tokens still yields code."""
    blocks = _CODE_RE.findall(text or "")
    if blocks:
        return str(max(blocks, key=len)).strip()
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""  # drop the ```lang opener line
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip()


def build_prompt(slug: str, docs: str, helptext: str, observations: list[OBS.Observation]) -> str:
    playbook = PLAYBOOK.read_text(encoding="utf-8")[:3000] if PLAYBOOK.exists() else ""
    examples = OBS.observations_to_examples(observations)
    short = slug.split("__")[-1].split(".")[0]
    corpus = CORPUS.render_prompt_block(
        short, observations=observations
    )  # pitfalls + technique recipes + what Determinex knows
    lang_ref = _language_reference_block(_LANG)
    lang_ref_block = (
        (f"## Language reference for `{_LANG}` (grounding, NOT this tool's source)\n{lang_ref}\n\n")
        if lang_ref
        else ""
    )
    systems_ref = _systems_reference_block()
    systems_ref_block = (
        (f"## Systems/runtime conventions (apply regardless of language)\n{systems_ref}\n\n")
        if systems_ref
        else ""
    )
    family_conv = _family_conventions_block(short)
    family_conv_block = (
        (
            f"## Tool-category conventions (this tool's archetype, not its own source)\n"
            f"{family_conv}\n\n"
        )
        if family_conv
        else ""
    )
    # CODE-RAG: idiomatic example code from OTHER real tools (NEVER this tool's own source -- excluded
    # by `short`). Technique reference for the builder. Best-effort -- skipped if not indexed yet.
    rag_block = ""
    try:
        import determinex_code_rag as RAG

        hits = RAG.retrieve(f"{short} {docs[:400]} {helptext[:200]}", k=3, exclude=short)
        if hits:
            blocks = [f"### {h['file']}\n```\n{h['snippet'][:700]}\n```" for h in hits]
            rag_block = (
                "## Example TECHNIQUE from other tools (study the APPROACH; this is NOT the "
                "tool you are building -- do not copy its logic):\n" + "\n".join(blocks) + "\n\n"
            )
    except Exception:
        rag_block = ""
    # DETERMINEX RULE: this trailer MUST stay _LANG-conditional. It previously hardcoded
    # "Write a single self-contained Python 3 program" unconditionally for every language --
    # a live contradiction with _lang_directive() above it (which correctly said "write Rust"
    # etc.) on every native task. Found + fixed 2026-07-16; build_incremental_prompt() (the
    # iterative fix-loop prompt) already got this right via fname/runcmd -- reuse the same
    # _FNAME_BY_LANG source of truth so the two can't drift apart again.
    fname = _FNAME_BY_LANG.get(_LANG, f"main.{_LANG}")
    if _LANG == "python":
        task_instruction = (
            f"Write a single self-contained Python 3 program (`{fname}`) that, invoked as\n"
            f"`python3 {fname} <args>` with the same stdin, reproduces the EXACT stdout and exit "
            f"code\nshown above for EVERY case. Output ONLY the Python code in one ```python``` "
            f"block, no prose."
        )
    else:
        names = {"go": "Go", "rust": "Rust", "c": "C", "cpp": "C++", "haskell": "Haskell"}
        L = names.get(_LANG, _LANG)
        task_instruction = (
            f"Write a single self-contained {L} program (`{fname}`, standard library only) that, "
            f"once compiled and run as the native binary with the same args/stdin, reproduces the "
            f"EXACT stdout and exit code shown above for EVERY case. Output ONLY the {L} code in "
            f"one ```{_LANG}``` code block, no prose."
        )
    return f"""You are reverse-engineering the CLI tool `{short}` to REIMPLEMENT it from scratch.
{_lang_directive()}
You may NOT use the original source, clone any repo, or wrap any binary. Write NEW code
that reproduces the tool's EXACT observable behavior (stdout and exit code) for the runs below.

## Knowledge (ProgramBench reimplementation playbook, excerpt)
{playbook}

{corpus}

{lang_ref_block}{systems_ref_block}{family_conv_block}{rag_block}## Tool docs (README)
{docs[:2200]}

## Tool --help
{helptext[:1500]}

## Observed reference behavior (your code MUST reproduce stdout + exit code EXACTLY)
{examples}

## Your task
{task_instruction}

CRITICAL rules derived from the observations — follow them exactly, even if counterintuitive:
- INPUT SOURCE: if a non-flag ARGUMENT (e.g. a filename) is present, read THAT FILE as the
  input. Only if there is no such argument do you read STDIN. Many cases above pass the
  input as a file argument, NOT stdin — handle both.
- Match stdout BYTE-FOR-BYTE: exact text, exact whitespace, exact trailing newlines, and
  exact escape/ANSI codes (e.g. \\x1b[...] sequences) shown in EXPECTED output.
- Match the EXIT CODE exactly (e.g. some flags exit 0 with empty output; some inputs exit
  2 or 3; a short flag like -V may differ from --version — do what the observation shows,
  not what you assume the flag conventionally means).
- Implement the tool's CORE transform exactly as the EXPECTED outputs demonstrate
  (study the input->output mapping carefully and reproduce its precise format/recursion).
- Send usage/error text to the stream the observation shows (note empty STDOUT with a
  non-zero exit usually means the message went to stderr)."""


def build_incremental_prompt(current, new_obs, accepted, helptext, short):
    """One assembly-line station: add ONE behavior to the current program. The model only
    holds ONE new constraint at a time; the SYSTEM holds the program (scratchpad) and the
    existing behaviors. This sidesteps the small-model 'too many constraints at once' wall."""
    o = new_obs
    argv = " ".join(o.probe.argv) or "(no args)"
    inp = ""
    for fn, content in o.probe.files.items():
        inp += f"\n  file {fn}: {content}"
    if o.probe.stdin:
        inp += f"\n  stdin: {o.probe.stdin}"
    keep = []
    for a in accepted[:-1][-8:]:
        stderr_note = " [+exact stderr]" if a.returncode != 0 and a.stderr.strip() else ""
        keep.append(
            f"  - executable {' '.join(a.probe.argv) or '(no args)'} -> exit {a.returncode}, "
            f"{(a.stdout.splitlines()[:1] or [''])[0][:60]}{stderr_note}"
        )
    keep_block = "\n".join(keep) if keep else "  (none yet)"
    seeded = bool(current.strip()) and current.strip() != "import sys"
    helphint = f"\n## Tool --help (reference)\n{helptext[:800]}\n" if not seeded else ""
    # 2026-07-02: pass observations= so the corpus can auto-detect domain (TUI/json/table)
    # from what's ACTUALLY been observed for this tool -- without it, recipes_for() sees an
    # empty blob and the TUI recipe (e.g.) never fires even when a pty-snapshot IS present
    # among `accepted`. Found via cmatrix scoring 0.00 on 48/48 samples across both ladder
    # tiers with zero relevant guidance in the prompt.
    coach = CORPUS.render_prompt_block(short, max_chars=900, observations=accepted)
    fname = _FNAME_BY_LANG.get(_LANG, f"main.{_LANG}")
    runcmd = "python3 main.py <args>" if _LANG == "python" else "the COMPILED binary <args>"
    # STDERR (2026-07-02): make_verify requires an EXACT stderr match whenever the exit is
    # non-zero and stderr is non-empty (e.g. ncurses' "Error opening terminal: unknown." with
    # no TTY -- the exact case that made every cmatrix station score 0.00: the model was
    # scored against stderr content it was never shown). Surface it explicitly when it's
    # part of the pass criteria.
    stderr_block = ""
    if o.returncode != 0 and o.stderr.strip():
        stderr_block = (
            f"  EXPECTED stderr (MUST MATCH EXACTLY -- part of the pass criteria):\n"
            f"{o.stderr if len(o.stderr) <= 800 else o.stderr[:800] + '…'}\n"
        )
    # SIBLING ERROR EXAMPLES (2026-07-19, found live on gron's --ungron stations): when a
    # behavior's pass criterion is an exact, non-obvious error-formatting rule (e.g. gron's
    # "ungron failed for `<truncated-token>`: invalid statement" -- the shown token length
    # varies per input in a way that encodes the tool's own tokenizer logic), keep_block's
    # one-line "[+exact stderr]" flag tells the model a sibling case exists but not what it
    # says. A model given exactly one such example per station has no way to infer the
    # underlying rule; three isolated single-shot guesses is not the same signal as three
    # examples seen together. Surface the FULL stderr for up to 3 prior siblings that share
    # this behavior's first argv token (same flag) and also have an exact-stderr pass
    # criterion, so the model can pattern-match the rule instead of memorizing one instance.
    sibling_block = ""
    if argv.split()[:1] and o.returncode != 0 and o.stderr.strip():
        flag = argv.split()[0]
        siblings = [
            a
            for a in accepted[:-1]
            if a.probe.argv[:1]
            and a.probe.argv[0] == flag
            and a.returncode != 0
            and a.stderr.strip()
        ][-3:]
        if siblings:
            lines = "\n".join(
                f"  - executable {' '.join(s.probe.argv)}{''.join(f' (file {fn}: {c})' for fn, c in s.probe.files.items())}"
                f" -> exit {s.returncode}, stderr: {s.stderr.strip()[:200]}"
                for s in siblings
            )
            sibling_block = (
                f"\n## RELATED {flag} EXAMPLES ALREADY OBSERVED (same flag, different input --\n"
                f"## study these together with the target above to find the SHARED formatting rule,\n"
                f"## not just this one instance):\n{lines}\n"
            )
    return f"""You are incrementally building a {_LANG} program `{fname}` that reimplements `{short}`,
run as `{runcmd}`. Add ONE new behavior to the CURRENT program below.
{coach}
{helphint}
## CURRENT PROGRAM (already handles the prior behaviors — keep them working)
```{_LANG}
{current}
```

## ADD THIS NEW BEHAVIOR (reproduce its stdout byte-for-byte and its exit code)
  invocation: executable {argv}{inp}
  EXPECTED exit={o.returncode}, stdout:
{o.stdout if len(o.stdout) <= 1200 else o.stdout[:1200] + "…"}
{stderr_block}{sibling_block}
## MUST ALSO STILL SATISFY (do not regress these)
{keep_block}

Rules: read a file argument if present else stdin; match output bytes exactly (newlines,
quoting like JSON `"x"`/`true`/`null`, `[i]` for array indices, and any declaration lines).
If EXPECTED stderr is shown above, your program MUST write that exact text to stderr too —
it is checked, not optional.
{_lang_directive()}
Output the COMPLETE updated program in one code block, nothing else."""


# --------------------------------------------------------------------------- caches (2026-07-02)
# Observation cache + station checkpoint: the two fixes that make kills/restarts CHEAP.
# Before these, every relaunch re-paid the full observe phase (minutes + model calls --
# paid 4x for cmatrix in one day) and decompose restarted from station 0, discarding all
# accepted stations (a 1.5h run's progress vanished on every config correction).


def _obs_cache_path(slug: str) -> Path:
    return ROOT / "logs" / "reimpl" / "obs_cache" / f"{slug}.json"


def _corpus_probes_sig(learned: list) -> str:
    """Signature of the corpus-learned probe set. LOAD-BEARING for cache correctness:
    determinex_reimpl_drive's self-feed loop ADDS probes between iterations (fuzz-diagnose
    divergences) -- a cache that ignored them would silently freeze the oracle and break
    the compounding-corpus mechanism. Corpus growth = cache miss = rebuild (correct:
    the new probes need real reference runs anyway)."""
    import hashlib as _h
    import json as _json

    return _h.sha256(
        _json.dumps(learned or [], sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:16]


def _save_obs_cache(slug: str, image: str, corpus_sig: str, observations: list) -> None:
    import dataclasses as _dc
    import json as _json
    import time as _t

    p = _obs_cache_path(slug)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "image": image,
        "corpus_sig": corpus_sig,
        "saved": _t.strftime("%Y-%m-%dT%H:%M:%S"),
        "observations": [
            {
                "probe": _dc.asdict(o.probe),
                "stdout": o.stdout,
                "stderr": o.stderr,
                "returncode": o.returncode,
            }
            for o in observations
        ],
    }
    tmp = p.with_suffix(".tmp")
    tmp.write_text(_json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def _load_obs_cache(slug: str, image: str, corpus_sig: str) -> list | None:
    import json as _json

    p = _obs_cache_path(slug)
    if not p.exists():
        return None
    try:
        data = _json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    if data.get("image") != image:  # image changed -> observations are stale
        return None
    if data.get("corpus_sig") != corpus_sig:  # corpus grew -> oracle must re-observe
        return None
    out = []
    try:
        for row in data.get("observations", []):
            out.append(
                OBS.Observation(
                    OBS.Probe(**row["probe"]),
                    row.get("stdout", ""),
                    row.get("stderr", ""),
                    int(row.get("returncode", 0)),
                )
            )
    except Exception:
        return None
    return out or None


def _stations_sig(ordered: list) -> str:
    import hashlib as _h

    return _h.sha256("|".join(o.probe.name for o in ordered).encode()).hexdigest()[:16]


def _save_ckpt(path: Path, sig: str, current: str, done: set[str], stations: int) -> None:
    import json as _json

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        _json.dumps(
            {"obs_sig": sig, "current": current, "done": sorted(done), "stations": stations},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    tmp.replace(path)


def _behavior_key(o) -> tuple:
    """Behavior-class key: probes whose observed (rc, stdout, stderr) are identical
    exercise the same output behavior (usually the same code path) even when their
    argv differ."""
    return (o.returncode, o.stdout, o.stderr)


def _dedup_reps(accepted: list, focus) -> list:
    """ORACLE DEDUP (2026-07-02): one representative probe per behavior class, for the
    SEARCH oracle only. cmatrix audit: 48 probes collapse to 6 classes (30x the same
    'Error opening terminal' stderr), so every candidate verify was paying 8x redundant
    probe-runs. SOUNDNESS: acceptance in incremental_solve still uses the FULL accepted
    set -- a candidate that games the representatives is never admitted on their word.
    `focus` (the station's own probe) is always included: it is the behavior being
    solved, even when an earlier probe of the same class is the class representative."""
    seen: set = set()
    reps = []
    for x in accepted:
        key = _behavior_key(x)
        if key in seen:
            continue
        seen.add(key)
        reps.append(x)
    if all(x is not focus for x in reps):
        reps.append(focus)
    return reps


def incremental_solve(
    observations,
    ladder,
    helptext,
    short,
    k=4,
    rounds=2,
    case_mem=None,
    runner=None,
    checkpoint_path: Path | None = None,
):
    """Assembly-line / scratchpad solve composing the amplifier pieces for the SINGLE-PROGRAM
    case: decompose (#2) into one behavior-station at a time, each verified against ALL behaviors
    accepted so far (no regression); per station the ROUTER (#7) escalates cheap->strong on a
    miss, CASE MEMORY (#3) injects a verified worked example, and the ladder's generators are
    already CONTRACT-guarded (#6). The model only ever holds ONE new constraint; the system
    holds the growing program + the sub-oracle. Returns (best_code, n_stations)."""
    ordered = sorted(observations, key=lambda o: (len(o.stdout), o.probe.name))
    # DETERMINEX RULE: native decompose -> compile each station as a real binary. Python is dev-only.
    if runner is None:
        # NOTE: main() always passes an image-aware runner (same-platform grading). This
        # fallback only fires for a direct call, and a host-built binary must not be graded
        # against in-image ground truth -- pass runner=make_native_runner(lang, image=...).
        runner = OBS._run_candidate_py if _LANG == "python" else OBS.make_native_runner(_LANG)
    current = "import sys\n" if _LANG == "python" else ""  # lang-appropriate empty seed
    stations = 0
    escalated = 0
    # CHECKPOINT RESUME: accepted stations persist as they land, so a kill/timeout/restart
    # resumes at station N instead of discarding everything. Keyed to the exact ordered
    # probe-name signature -- a changed observation set invalidates the checkpoint.
    sig = _stations_sig(ordered)
    done: set[str] = set()
    if checkpoint_path is not None and checkpoint_path.exists():
        import json as _json

        try:
            ck = _json.loads(checkpoint_path.read_text(encoding="utf-8"))
            if ck.get("obs_sig") == sig:
                current = ck.get("current", current)
                done = set(ck.get("done", []))
                stations = int(ck.get("stations", 0))
                print(
                    f"  [decompose] RESUMED from checkpoint: {len(done)}/{len(ordered)} "
                    f"behaviors done, {stations} stations worked",
                    flush=True,
                )
            else:
                print("  [decompose] checkpoint ignored (observation set changed)", flush=True)
        except Exception:
            pass
    # VERIFY MEMO (2026-07-02): `current` only changes when a station is accepted, yet the
    # per-station skip-check re-ran the WHOLE accepted set every time -- O(n^2) probe-runs
    # across a run (~1,176 for cmatrix's 48 probes, most confirming what the last full
    # verify already proved). Remember the last full verify's per-probe outcome for the
    # current code digest; while the code is unchanged and every prior probe passed, the
    # skip-check only needs to run the ONE new probe.
    import hashlib as _hl

    memo_dg: str | None = None
    memo_failed: set[str] = set()
    memo_cover: set[str] = set()

    def _remember(code_dg: str, probes: list, res) -> None:
        nonlocal memo_dg, memo_failed, memo_cover
        memo_dg = code_dg
        memo_failed = {getattr(f, "name", "") for f in (res.failures or [])}
        memo_cover = {x.probe.name for x in probes}

    # ANOMALY GUARD (2026-07-18, found live on gron): a run of consecutive stations that
    # ALL land at score 0.00 even after full ladder escalation is a distinct pattern from
    # genuine incremental difficulty (which shows gradual partial credit). It usually means
    # the PROBES feeding this station are malformed, not that the model is failing N
    # equally hard problems in a row -- and each escalated attempt burns real compute (the
    # gron case: 9 stations, ~10-15 min each on the biggest model in the ladder) before
    # anyone notices. This is independent of _warn_if_probe_pool_poisoned (which catches
    # the specific "identical reference stderr" signature up front) -- this one fires on
    # ANY consecutive-zero run regardless of cause, and can re-fire per threshold crossing
    # since a long autonomous run shouldn't go silent on a stuck pattern.
    _consec_zero_stations = 0
    _ZERO_STREAK_WARN_EVERY = 5

    for idx, o in enumerate(ordered):
        if o.probe.name in done:
            continue  # already handled in a prior (checkpointed) pass
        accepted = ordered[: idx + 1]
        sub_verify = OBS.make_verify(accepted, runner=runner)
        dg = _hl.sha256(current.encode("utf-8", "replace")).hexdigest()[:16]
        prior_names = {x.probe.name for x in accepted[:-1]}
        if dg == memo_dg and memo_cover >= prior_names and not (memo_failed & prior_names):
            # code unchanged + all prior probes known-passing -> only the new probe matters
            solo = OBS.make_verify([o], runner=runner)(current)
            if solo.passed:
                memo_cover.add(o.probe.name)  # memo stays valid: o now known-passing
                done.add(o.probe.name)
                if checkpoint_path is not None:
                    _save_ckpt(checkpoint_path, sig, current, done, stations)
                continue
        cur_res = sub_verify(current)
        _remember(dg, accepted, cur_res)
        if cur_res.passed:
            done.add(o.probe.name)
            if checkpoint_path is not None:
                _save_ckpt(checkpoint_path, sig, current, done, stations)
            continue  # current program already handles this behavior — shelf it, move on
        stations += 1
        prompt = build_incremental_prompt(current, o, accepted, helptext, short)
        if case_mem is not None:
            cases = case_mem.retrieve(f"{o.probe.name} {o.stdout[:120]}", k=1)
            if cases:
                prompt += (
                    "\n\n## VERIFIED snippet for a similar behavior (adapt the technique):\n"
                    f"```{_LANG}\n{cases[0].solution[:1500]}\n```"
                )
        # ROUTER: this station climbs the ladder (cheapest first, escalate on a verified miss).
        # The SEARCH oracle is COMPOSITE (2026-07-02, fixed same-day): rep-check first (one
        # probe per behavior class, see _dedup_reps), and only a rep-PASS pays for the full
        # accepted set. Most candidates fail the cheap reps outright; but a candidate that
        # overfits the representatives (passes reps, regresses a same-class sibling with
        # different argv -- observed live: cmatrix station 5 returned "solved" off the reps,
        # never escalated, and left the behavior unsolved) now full-fails INSIDE the search,
        # so feedback rounds and the ladder keep working the station instead of moving on.
        reps = _dedup_reps(accepted, o)
        if len(reps) < len(accepted):
            print(
                f"  [station {stations}] oracle dedup: {len(accepted)} probes -> "
                f"{len(reps)} behavior classes for search (full set on rep-pass)",
                flush=True,
            )
            _rep_verify = OBS.make_verify(reps, runner=runner)

            def search_verify(code, _rv=_rep_verify, _fv=sub_verify):
                r = _rv(code)
                return _fv(code) if r.passed else r
        else:
            search_verify = sub_verify
        router = ModelRouter(ladder, k=k, rounds=rounds)
        rr = router.solve_leaf(verify=search_verify, prompt=prompt, start_tier=ladder[0].tier)
        if rr.escalations:
            escalated += 1
        cand = rr.search.best if rr.search else None
        if cand:
            new_res = sub_verify(cand.text)
            # MONOTONE ACCEPTANCE (2026-07-02, found live): `n_pass >= cur` admitted
            # behavior SWAPS -- cmatrix station 7's candidate added -s but dropped the
            # already-solved -n (both 4/5), so accepted progress silently regressed a
            # done probe and poisoned the checkpoint's done-set. Accept only strict
            # improvement: the candidate's failing set must be a proper subset of the
            # current one (never fail anything current passes), or identical with a
            # better line-score (gradient step on genuine outputs).
            cur_failed = {getattr(f, "name", "") for f in (cur_res.failures or [])}
            new_failed = {getattr(f, "name", "") for f in (new_res.failures or [])}
            if new_failed < cur_failed or (
                new_failed == cur_failed and new_res.score > cur_res.score + 1e-9
            ):
                current = cand.text
                # admit only a FAITHFUL station (enough accumulated genuine probes) -- a 1-probe
                # station pass is too cheap to trust into shared case memory (poisoning guard).
                if case_mem is not None and new_res.passed and new_res.n_genuine >= 8:
                    case_mem.add(
                        signature=f"{o.probe.name} {o.stdout[:120]}",
                        solution=cand.text,
                        oracle_passed=True,
                        tool=short,
                    )
        fin = sub_verify(current)
        _remember(
            _hl.sha256(current.encode("utf-8", "replace")).hexdigest()[:16], accepted, fin
        )  # keep the memo current for the next station's skip-check
        via = f"ESCALATED->{rr.model_used}" if rr.escalations else rr.model_used
        o_solved = o.probe.name not in {getattr(f, "name", "") for f in (fin.failures or [])}
        print(
            f"  [station {stations}] +{o.probe.name}: {fin.n_pass}/{len(accepted)} "
            f"(score {fin.score:.2f}) via {via}"
            f"{'' if o_solved else '  [UNSOLVED -- retried on next run]'}",
            flush=True,
        )
        if o_solved or fin.score > 1e-9:
            _consec_zero_stations = 0
        else:
            _consec_zero_stations += 1
            if _consec_zero_stations % _ZERO_STREAK_WARN_EVERY == 0:
                print(
                    f"  [decompose] ⚠ {_consec_zero_stations} CONSECUTIVE stations scored "
                    f"0.00 even after full escalation (last: {o.probe.name}). This pattern "
                    f"usually means the probes are malformed upstream, not that the model "
                    f"is genuinely failing this many equally hard behaviors in a row -- "
                    f"check the observation cache before spending more compute here.",
                    flush=True,
                )
        # Only a station whose OWN behavior actually passes is checkpointed as done.
        # An unsolved one stays out of `done` so a restart retries it (this pass keeps
        # moving -- later stations often add code that incidentally fixes it).
        if o_solved:
            done.add(o.probe.name)
        if checkpoint_path is not None:
            _save_ckpt(checkpoint_path, sig, current, done, stations)
    print(f"  [decompose] {stations} stations, {escalated} needed escalation")
    return current, stations


def _warn_if_probe_pool_poisoned(proposed: list, observations: list) -> bool:
    """Sanity-check model-proposed exploration probes against their OBSERVED reference
    behavior, before decompose ever spends a single station on them.

    Found live 2026-07-18 driving gron: propose_probes() explicitly instructs the model to
    return "flags only, after the program name", but the model echoed the program name
    anyway ("gron -u" instead of "-u"). The parser only checked that the line contained a
    flag token, so the whole ['gron', '-u'] survived into Probe.argv (which must exclude
    the program name -- see Probe's own docstring). The reference binary then treated
    'gron' as a bogus positional filename and errored identically ("open gron: no such
    file or directory") on EVERY one of the 11 exploration probes. Nine consecutive
    decompose stations then escalated all the way to the biggest model in the ladder
    trying to byte-match that nonsense -- roughly two hours of real compute -- before a
    human caught it by hand inspecting the raw observation cache.

    That argv-echo bug is now fixed at the source (determinex_observe.propose_probes), but
    this is a distinct, generalizable check: DIFFERENT invocations producing an IDENTICAL
    reference error is itself a strong, cheap, automatable signal that something upstream
    is malformed -- whatever the specific cause turns out to be next time. Prints a loud,
    actionable warning and returns True if triggered; never raises, never blocks the run
    (an autonomous loop should flag anomalies, not silently halt on them)."""
    if len(proposed) < 5:
        return False
    proposed_names = {p.name for p in proposed}
    by_name = {o.probe.name: o for o in observations if o.probe.name in proposed_names}
    stderrs = [by_name[p.name].stderr.strip() for p in proposed if p.name in by_name]
    if not stderrs:
        return False
    from collections import Counter

    counts = Counter(s for s in stderrs if s)
    if not counts:
        return False
    common_err, n = counts.most_common(1)[0]
    if n >= max(3, int(len(stderrs) * 0.6)):
        print(
            f"[observe] ⚠ SUSPECT PROBE POOL: {n}/{len(stderrs)} exploration probes "
            f"produced the IDENTICAL reference stderr {common_err[:120]!r}. Distinct flag "
            f"combinations genuinely erroring identically this often is unlikely -- this "
            f"usually means the probes themselves are malformed upstream (e.g. a leaked "
            f"token in argv), not that decompose is facing {n} equally hard behaviors. "
            f"Inspect the observation cache before trusting these stations' results.",
            flush=True,
        )
        return True
    return False


def _load_spec_assertion_observations(short: str, slug: str, image: str) -> list:
    """OFFICIAL-test examples as assertion-carrying Observations. Runs the reference to get
    its real output (so CONTAINS checks the correct stream), then attaches the test's actual
    criteria (expect_in / expect_rc / expect_stdout). The oracle then grades what the OFFICIAL
    eval grades -- not exact reproduction of clap banners the test only substring-matches."""
    import json as _json

    specs_dir = ROOT / "corpus" / "programbench" / "specs"
    spec_path = None
    for cand in (specs_dir / f"{slug}.json", specs_dir / f"{short}.json"):
        if cand.exists():
            spec_path = cand
            break
    if spec_path is None:
        matches = sorted(specs_dir.glob(f"{slug.split('.')[0]}*.json"))
        spec_path = matches[0] if matches else None
    if spec_path is None:
        return []
    spec = _json.loads(spec_path.read_text(encoding="utf-8"))
    _drop = {"executable", "./executable", short, f"./{short}"}
    pairs = []
    for i, e in enumerate(spec.get("examples", []) or []):
        a = {
            "expect_in": list(e.get("expect_in") or []),
            "expect_rc": e.get("expect_rc"),
            "expect_stdout": e.get("expect_stdout"),
        }
        if not (a["expect_in"] or a["expect_rc"] is not None or a["expect_stdout"]):
            continue  # nothing the test actually asserts -> skip
        argv = list(e.get("argv") or [])
        if argv and argv[0] in _drop:  # some extracted argvs include the program name
            argv = argv[1:]
        p = OBS.Probe(
            name=f"spec::{e.get('test') or i}",
            argv=argv,
            stdin=e.get("stdin"),
            files=e.get("files") or {},
            serve={},
            env=e.get("env") or {},
        )
        pairs.append((p, a))
    if not pairs:
        return []
    ref = OBS.observe_in_image(image, "/workspace/executable", [p for p, _ in pairs])
    by_name = {o.probe.name: o for o in ref}
    out = []
    for p, a in pairs:
        o = by_name.get(p.name)
        if o is None:
            continue
        o.assertion = a
        out.append(o)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("slug")
    ap.add_argument("--k", type=int, default=8)
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--model", default="qwen2.5-coder:7b-instruct")
    ap.add_argument(
        "--models",
        default="",
        help="capability ladder 'name:tier:cost,...' (router escalates cheap->strong "
        "on a miss). Overrides --model. e.g. deepseek-chat:1:1,deepseek-reasoner:3:3",
    )
    ap.add_argument("--check-stderr", action="store_true")
    ap.add_argument(
        "--lang",
        default="python",
        help="DETERMINEX RULE: native submissions. Set the tool's real language "
        "(go/rust/c/cpp/haskell) -> candidate is COMPILED (compiler oracle) + "
        "run as a real binary. 'python' is dev-only/non-submission.",
    )
    ap.add_argument(
        "--decompose",
        action="store_true",
        help="assembly-line: accumulate behaviors one station at a time",
    )
    ap.add_argument(
        "--fresh",
        action="store_true",
        help="ignore + clear the observation cache and station checkpoint "
        "(default: reuse both -- relaunches resume instead of restarting)",
    )
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    global _LANG
    _LANG = args.lang  # DETERMINEX RULE: prompt builders rebuild in the tool's native language
    image = _image_for(args.slug)
    if not image:
        print(f"no :task image for {args.slug}")
        return 2
    short = args.slug.split("__")[-1].split(".")[0]
    ckpt_path = ROOT / "logs" / "reimpl" / f"{short}_stations.ckpt.json"
    if args.fresh:
        _obs_cache_path(args.slug).unlink(missing_ok=True)
        ckpt_path.unlink(missing_ok=True)
    print(f"[observe] image={image}")
    docs, helptext = _docs_and_help(image)
    # corpus-learned probes load FIRST: they are part of the cache key (the drive's
    # self-feed loop grows them between iterations; growth must invalidate the cache).
    learned = CORPUS.load_probes(short)
    corpus_sig = _corpus_probes_sig(learned)
    cached = None if args.fresh else _load_obs_cache(args.slug, image, corpus_sig)
    if cached is not None:
        # OBSERVATION CACHE (2026-07-02): the observe phase is deterministic per tool+image
        # but was re-paid on every relaunch (minutes of docker execs + model-proposed-probe
        # calls -- paid 4x for cmatrix in one day). Reuse it; --fresh rebuilds.
        observations = cached
        print(
            f"[observe] loaded {len(observations)} CACHED observations "
            f"({_obs_cache_path(args.slug)}; --fresh to rebuild)"
        )
    else:
        task_inputs = _TASK_INPUTS.get(short)
        if not task_inputs:
            # SELF-BUILD the oracle: discover the tool's input format from the binary (the
            # scale unlock -- no hand-crafted probes needed per tool).
            print("[observe] auto-generating input battery from the reference binary...")
            task_inputs = OBS.auto_inputs(image, "/workspace/executable")
            print(f"[observe] auto-discovered {len(task_inputs)} input probes")
        task_inputs = list(task_inputs or [])
        # CORPUS-OWNED auto-grown oracle: add probes fuzz_diagnose discovered on prior drive cycles
        # (the corpus literally holds the behavioral coverage it has learned -> the oracle compounds).
        if learned:
            for d in learned:
                task_inputs.append(
                    OBS.Probe(
                        d.get("name", "learned"),
                        d.get("argv", []),
                        d.get("stdin"),
                        d.get("files", {}) or {},
                        d.get("serve", {}) or {},
                    )
                )
            print(f"[observe] +{len(learned)} corpus-learned probes (auto-grown oracle)")
        probes = OBS.build_probes(helptext, task_inputs)
        # COMPREHENSIVE EXPLORATION (the frontier-agent half): ask the cheap model to propose diverse
        # invocations from --help/docs -- FLAG VALUES (--style rounded) + combinations a fixed battery
        # misses. Cheap now that observe is exec-fast. This is what makes us coverage-comparable to a
        # bare agent, then the compiler oracle verifies (the half they lack).
        proposed: list = []
        try:
            parsed_models = parse_model_ladder(args.models)
            primary_model = parsed_models[0][0] if parsed_models else args.model
            proposed = OBS.propose_probes(
                helptext, docs, task_inputs, make_generator(primary_model), n=40
            )
            if proposed:
                probes += proposed
                print(
                    f"[observe] +{len(proposed)} model-proposed exploration probes (flag-values/combos)"
                )
        except Exception as e:
            print(f"[observe] propose_probes skipped: {e}")
        print(f"[observe] {len(probes)} probes; running reference binary...")
        observations = OBS.observe_in_image(image, "/workspace/executable", probes)
        # keep only deterministic, non-empty-or-meaningful observations
        print(f"[observe] captured {len(observations)} observations")
        _warn_if_probe_pool_poisoned(proposed, observations)
        # TUI GAP (found 2026-07-02 hand-driving tty-clock): observe_in_image's plain docker-exec
        # probes have no pty and never set TERM, so an ncurses/curses tool's reference behavior is
        # NEVER actually seen (every probe reads "Error opening terminal: unknown") -- the model
        # builds blind. If the binary links a terminal-UI library, add real pty-captured frames.
        try:
            if OBS.is_tui_binary(image, "/workspace/executable"):
                tui_obs = OBS.observe_tui_snapshot(image, "/workspace/executable", [[]])
                observations += tui_obs
                print(
                    f"[observe] +{len(tui_obs)} pty-captured TUI snapshot(s) "
                    f"(ncurses/curses linkage detected)"
                )
        except Exception as e:
            print(f"[observe] TUI snapshot skipped: {e}")
        _save_obs_cache(args.slug, image, corpus_sig, observations)
        print(f"[observe] cached {len(observations)} observations -> {_obs_cache_path(args.slug)}")
    # ASSERTION-AWARE ORACLE (2026-07-03): overlay the OFFICIAL test criteria. For every input
    # that has an official test, grade what the TEST grades (CONTAINS / rc), not exact reference
    # bytes -- and REPLACE the exact observation for the same argv. Fuzz-only probes keep exact
    # match (extra coverage, no looser criterion defined). This is what unblocks the ~15 hardest
    # error-formatting stations per tool (clap banners the test only substring-matches), which
    # were making every tool plateau and look like a model ceiling.
    try:
        spec_obs = _load_spec_assertion_observations(short, args.slug, image)
        if spec_obs:
            spec_argvs = {tuple(o.probe.argv) for o in spec_obs}
            observations = [
                o for o in observations if tuple(o.probe.argv) not in spec_argvs
            ] + spec_obs
            print(
                f"[observe] +{len(spec_obs)} official-test assertion probes "
                f"(CONTAINS/rc-aware; replaced exact-match for those inputs)"
            )
    except Exception as e:
        print(f"[observe] spec-assertion overlay skipped: {e}")
    # ORACLE FAITHFULNESS: how well does this local oracle reject trivially-wrong programs?
    # ratio<1.0 = a do-nothing/echo candidate could slip through -> local-pass would not mean
    # official-pass. This is the number for the local<->official gap (the correctness BOUND).
    disc = OBS.discrimination_estimate(observations)
    print(
        f"[oracle] discrimination {disc['rejected']}/{disc['total']} "
        f"(ratio {disc['ratio']:.2f}) -- trivial-mutant rejection; 1.00 = no free pass"
    )

    # DETERMINEX RULE: native submissions. lang!=python => the candidate is COMPILED (compiler
    # oracle) and run as a real binary; python is dev-only and never a real submission.
    # SAME-PLATFORM GRADING (2026-07-31): the reference was observed inside `image`, so the
    # candidate is built and run there too. Grading a host binary against in-image ground truth
    # produced 0/234 for a known-good reimplementation that scores 84% built in-image -- a false
    # zero indistinguishable from model incapacity. The preflight refuses the mismatch outright.
    OBS.assert_same_platform_as_reference(image, runner_is_containerized=True)
    runner = (
        OBS._run_candidate_py
        if args.lang == "python"
        else OBS.make_native_runner(args.lang, image=image)
    )
    if args.lang != "python":
        print(
            f"[native] {args.lang}: candidates COMPILED + run as real binaries "
            f"IN {image.split('/')[-1][:44]} (same platform as the reference)"
        )
    # BATCHED ORACLE: make_verify has no early exit, so per-probe container + bind-mount
    # overhead dominated (1310 ms/probe = 5.1 min per candidate, for a tool that runs in ~5 ms).
    # One container for the whole battery: 239 ms/probe, ~50 s per candidate, same accuracy.
    _batch = (args.lang, image) if (args.lang != "python" and image) else None
    if _batch:
        print(
            f"[oracle] batched: whole {len(observations)}-probe battery in ONE container "
            f"(~5x faster than per-probe)"
        )
    verify = OBS.make_verify(
        observations, check_stderr=args.check_stderr, runner=runner, batch=_batch
    )

    # CASE MEMORY (amplifier #3): inject a VERIFIED past solution for a similar tool as a worked
    # example -- the corpus "houses all of it", carrying proven technique from tool to tool.
    CASE_MEM = CaseMemory(
        ROOT / "corpus" / "programbench" / "training_corpus" / "reimpl_cases.jsonl"
    )
    obs_sig = f"{short} :: " + " | ".join(
        sorted(set((o.stdout.splitlines()[:1] or [""])[0][:40] for o in observations))[:8]
    )
    prior_cases = CASE_MEM.retrieve(obs_sig, k=1)

    # MODEL-AGNOSTIC ROUTER (amplifier #7) + OUTPUT CONTRACT (amplifier #6):
    # any model plugs in; each is contract-guarded (malformed candidates resampled, never
    # wasting an oracle slot); the router runs the cheapest tier first and ESCALATES to a
    # stronger model only when verified search misses -> cheap bulk, strong tail, oracle-bounded.
    # 2026-07-02: py_contract runs ast.parse() -- PYTHON syntax -- and was being applied
    # UNCONDITIONALLY, including to native (--lang c/rust/go/...) candidates. Real C/Rust/Go
    # source essentially never parses as Python, so every native candidate was failing its
    # own contract check and burning resample budget on a check that could never pass.
    _candidate_contract = py_contract if args.lang == "python" else native_code_contract

    def _entry(name: str, tier: int, cost: float) -> ModelEntry:
        raw = make_generator(name)
        gen = contract_guard(lambda p, t, _raw=raw: extract_code(_raw(p, t)), _candidate_contract)
        # KNOWN-TRAPS TWO-STRIKE GATE (2026-07-16): a first occurrence of a documented
        # language pitfall (see corpus/programbench/language_reference/*.md) passes through
        # untouched -- the real oracle is still the only judge of a first attempt. Only if
        # this SAME model-ladder entry repeats the SAME trap in a LATER candidate (meaning it
        # was warned and ignored it) does this gate before the candidate reaches the
        # compiler. Fresh instance per entry -> a router escalation to a stronger model tier
        # starts with a clean slate, never inheriting a weaker model's warnings.
        if args.lang != "python":
            gen = trap_guard(gen, args.lang)
        return ModelEntry(name, tier=tier, cost=cost, generate=gen)

    ladder_specs = (
        parse_model_ladder(args.models) if args.models.strip() else [(args.model, 1, 1.0)]
    )
    _pf_problems = preflight_ladder([n for n, _t, _c in ladder_specs])
    if _pf_problems:
        print(
            "\n[MODEL PREFLIGHT] FAIL -- the run has NOT started (would have silently "
            "burned real compute treating these as 'the model tried and failed'):"
        )
        for p in _pf_problems:
            print(f"  ✗ {p}")
        print("Fix the --models spec (or the missing key/model) and re-run.\n")
        return 1
    print(f"[MODEL PREFLIGHT] OK -- {len(ladder_specs)} ladder tier(s) all reachable")
    ladder = [_entry(name, tier, cost) for name, tier, cost in ladder_specs]
    primary_name = ladder[0].name

    if args.decompose:
        print(
            f"[decompose] assembly-line over {len(observations)} behaviors, "
            f"k={args.k} rounds={args.rounds} model={primary_name}"
        )
        best, n_stations = incremental_solve(
            observations,
            ladder,
            helptext,
            short,
            k=args.k,
            rounds=args.rounds,
            case_mem=CASE_MEM,
            runner=runner,
            checkpoint_path=ckpt_path,
        )
        res_solved = verify(best).passed
        print(f"[decompose] done: {n_stations} stations worked")
    else:
        prompt = build_prompt(args.slug, docs, helptext, observations)
        if prior_cases:
            # inject the most similar VERIFIED prior solution as a worked example
            prompt += (
                "\n\n## A VERIFIED solution to a SIMILAR tool (study its techniques, adapt):\n"
                f"```python\n{prior_cases[0].solution[:3500]}\n```"
            )
            print(f"[case-memory] injected verified prior case: {prior_cases[0].tool}")
        print(
            f"[amplify] router ladder={[m.name + '(t' + str(m.tier) + ')' for m in ladder]} "
            f"k={args.k} rounds={args.rounds} (contract-guarded)"
        )
        router = ModelRouter(ladder, k=args.k, rounds=args.rounds)
        rr = router.solve_leaf(verify=verify, prompt=prompt, start_tier=ladder[0].tier)
        res = rr.search
        best = res.best.text if res and res.best else None
        res_solved = rr.solved
        print(
            f"[router] solved={rr.solved} model_used={rr.model_used} "
            f"tier={rr.tier_used} escalations={rr.escalations}"
        )

    # report -- HONEST metric: genuine (non-empty-output) probes reproduced, not the
    # inflated total (which trivial empty/error probes pad). Plus the line-closeness score.
    mode = "decompose" if args.decompose else "monolithic"
    print(f"\n=== RESULT {short} [{mode}] models={[m.name for m in ladder]} ===")
    if _is_generation_error_text(best):
        print((best or "").strip())
        print("[generation] no candidate written because the model provider returned an error")
        return 2
    if best:
        r = verify(best)
        print(f"solved(all probes)={res_solved}")
        print(
            f"GENUINE behavior reproduced: {r.n_genuine_pass}/{r.n_genuine}  "
            f"(the honest reverse-engineering score)"
        )
        print(
            f"line-closeness score: {r.score:.3f}   |   all-probes(incl trivial): {r.n_pass}/{r.n_total}"
        )
        if r.failures:
            print("\n-- remaining failures (name | first line of diff) --")
            for f in r.failures[:6]:
                print(f"  {f.name}: {f.text.splitlines()[0] if f.text else ''}")
        out = args.out or str(ROOT / "logs" / "reimpl" / f"{short}_candidate.py")
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(best, encoding="utf-8")
        print(f"wrote best candidate -> {out}")
        # LEARN: the corpus records this run (hard behaviors + local score). Official score
        # + verified-skill lock are recorded by determinex_pb_official_eval.py.
        CORPUS.record_run(
            short,
            observations=observations,
            failed_probe_names=[f.name for f in r.failures],
            best_local=f"{r.n_genuine_pass}/{r.n_genuine} genuine, score {r.score:.3f}",
            candidate_path=out,
        )
        print(f"[corpus] recorded run for {short} (hard behaviors + local score)")
        # ADMIT to case memory ONLY on a FAITHFUL pass -- not merely a local pass. A thin oracle
        # (few genuine probes) makes "passed" meaningless (elfcat 8/8-local was 9.75% official):
        # admitting it POISONS retrieval, propagating wrong patterns to similar tools. Gate on
        # faithfulness: enough genuine probes AND full discrimination. In the wild, thin oracles
        # are common -> this guard is what keeps the corpus from learning garbage unsupervised.
        _MIN_GENUINE_FOR_CASE = 8
        faithful = (
            r.passed and r.n_genuine >= _MIN_GENUINE_FOR_CASE and disc.get("ratio", 0.0) >= 1.0
        )
        if faithful:
            CASE_MEM.add(signature=obs_sig, solution=best, oracle_passed=True, tool=short)
            print(f"[case-memory] admitted (faithful: {r.n_genuine} genuine probes, disc 1.0)")
        elif r.passed:
            print(
                f"[case-memory] WITHHELD: passed but oracle too thin ({r.n_genuine} genuine "
                f"probes < {_MIN_GENUINE_FOR_CASE}) -> would poison retrieval; not admitted"
            )
        # CONSTANT ANALYSIS: every run self-reports whether the loop worked as designed --
        # did the model APPLY the corpus's injected recipes, is the oracle sound, is capability
        # accumulating? (corpus<->LLM design-invariant audit, no extra docker.)
        try:
            import determinex_reimpl_analyze as ANALYZE

            print("\n[analyze] corpus<->LLM design-invariant check:")
            for ln in ANALYZE.check_recipe_adherence(short, best, observations):
                print(ln)
            print(
                ANALYZE._line(
                    ANALYZE.OK,
                    "oracle-discrimination",
                    f"{disc['rejected']}/{disc['total']} (ratio {disc['ratio']:.2f})"
                    if disc["ratio"] >= 1.0
                    else f"ratio {disc['ratio']:.2f} -- trivial candidate can slip through!",
                )
            )
        except Exception as e:
            print(f"[analyze] skipped: {e}")
    else:
        print("no candidate produced")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
