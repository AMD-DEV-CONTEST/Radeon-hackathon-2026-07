"""
scripts/hive/api_client.py — Rate limiter, role assignments, API call wrapper, DAG generation
==============================================================================================
Moved from determinex_hive.py (lines ~133-366, ~1611-1819).
"""

from __future__ import annotations

import json
import logging
import re
import sys
import time as _time
import uuid
from pathlib import Path

from hive.budget import is_local_model, record_api_call_cost
from hive.concurrent_guard import (
    api_backpressure,  # #27 per-role concurrency semaphore
    drop_session_state,  # #34 cleanup on session end
)
from hive.hardware import get_hw_profile
from hive.manifest import (
    ManifestSession,
    StepRecord,
    load_manifest,
    resolve_repo_root,
    save_manifest,
)
from hive.workspace import (
    scaffold_go_module,
    scaffold_python_project,
    scaffold_rust_project,
)

try:
    from hive._log import bind_session as _bind_session
    from hive._log import get_logger as _get_logger  # noqa: F401

    log = _get_logger("hive.api_client")
except ImportError:
    log = logging.getLogger("hive")

# ── CRITICAL: Zero-Egress Guarantee ─────────────────────────────────────────────
# LiteLLM ships with telemetry=True by default, pinging BerriAI servers on every
# completion call with model name, latency, and token counts. This violates the
# Determinex Enterprise "zero data egress" and "air-gapped" architecture claims.
# Both environment variable (subprocess-safe) and attribute (in-process) must be
# set before any litellm import in downstream code executes the telemetry path.
import os as _os_env

_os_env.environ["LITELLM_TELEMETRY"] = "False"
try:
    import litellm as _litellm_init

    _litellm_init.telemetry = False
    _litellm_init.suppress_debug_info = True
except Exception:  # litellm not yet installed (e.g. test env) — skip silently
    pass

# ── #29 KV Cache UUID Namespace ──────────────────────────────────────────────
# Ollama caches KV state keyed by prompt hash. Two concurrent sessions using
# the same model with similar prompts will collide in the KV cache, causing
# context bleed: the builder in session A sees tokens generated for session B.
# Injecting a per-session UUID as a system prompt prefix guarantees a unique
# cache key.  Cost: ~3 tokens per call.  Benefit: eliminates cross-session
# hallucination.
_SESSION_KV_NAMESPACE: dict[str, str] = {}
_KV_NAMESPACE_LOCK = __import__("threading").Lock()


def _kv_namespace(session_id: str) -> str:
    """Return a stable per-session UUID for KV cache isolation."""
    with _KV_NAMESPACE_LOCK:
        if session_id not in _SESSION_KV_NAMESPACE:
            _SESSION_KV_NAMESPACE[session_id] = str(uuid.uuid4())
        return _SESSION_KV_NAMESPACE[session_id]


def inject_kv_namespace(messages: list[dict], session_id: str) -> list[dict]:
    """#29: Prepend a per-session UUID to the system message for KV cache isolation.

    This is invisible to the model (it's a comment-like metadata prefix) but
    changes the prompt hash, forcing Ollama to allocate a separate KV cache slot.

    Only modifies messages if a system message exists and session_id is provided.
    """
    if not session_id or not messages:
        return messages

    ns = _kv_namespace(session_id)
    messages = list(messages)  # shallow copy to avoid mutation

    for i, msg in enumerate(messages):
        if msg.get("role") == "system":
            messages[i] = dict(msg)
            messages[i]["content"] = f"[session:{ns}]\n{msg['content']}"
            break

    return messages


def cleanup_session(session_id: str) -> None:
    """G19: Purge all in-memory session state to prevent unbounded memory growth.

    Removes the per-session KV-cache UUID from _SESSION_KV_NAMESPACE and drops
    the epoch-tagged state from concurrent_guard.  Call at session teardown.
    """
    with _KV_NAMESPACE_LOCK:
        _SESSION_KV_NAMESPACE.pop(session_id, None)
    drop_session_state(session_id)


def _ollama_extra(model: str, role: str, hw_profile=None) -> dict:
    """Return extra_body dict for Ollama calls, empty dict for API models."""
    if not model.startswith("ollama/"):
        return {}
    keep_hot = hw_profile.lifecycle.keep_hot if hw_profile else ["builder"]
    max_loaded = hw_profile.lifecycle.max_loaded if hw_profile else 2

    # The monitor eviction is decided from CAPACITY, before keep_hot is consulted.
    #
    # It used to be an `elif` after `role in keep_hot`, and tier 0 -- the ~6GB rig this whole
    # branch was written about -- lists "monitor" in keep_hot. So on the one machine whose
    # arithmetic is spelled out below, the monitor took keep_alive=-1 and this branch never ran.
    # Measured 2026-07-31 on a 6.0 GB GTX: with the observer pinned, a hive session stalled in
    # step 2's Monitor call for 19 minutes with zero CPU movement and no error, because the
    # observer was sharing VRAM with the pinned engineer and running its prefill on CPU. The
    # same call with keep_alive=0 returned in 39s -- Ollama evicts the engineer and runs the
    # observer at 100% GPU instead of co-loading both onto the CPU path.
    #
    # The arithmetic, unchanged and now actually reachable: observer (3.3GB) + engineer (1.6GB)
    # + step-N KV cache (430MB) = 5.4GB > 5.2GB available -> CPU offload -> 400-500s prefill
    # -> builder timeout. Keying on `max_loaded <= 1` rather than on tier means a profile that
    # says "one model at a time" gets that honoured no matter which roles someone later adds to
    # keep_hot -- the contradiction cannot come back by list edit.
    if role == "monitor" and max_loaded <= 1:
        keep_alive = 0
    elif role in keep_hot:
        keep_alive = -1  # builder: never evict — stays hot between steps
    elif role == "monitor":
        keep_alive = 0  # evict observer immediately after verdict
    else:
        keep_alive = 300  # default 5min (oracle, architect, unknown roles); keeps qwen7b
        # alive across the oracle→architect handoff inside generate_dag.
    return {"keep_alive": keep_alive}


def _provider_extra_body(
    model_alias: str,
    role: str,
    hw_profile=None,
    *,
    force_evict: bool = False,
) -> dict:
    """Return provider-specific LiteLLM extra_body for a configured model alias."""
    real_model, _ = _resolve_model(model_alias)
    if not real_model.startswith("ollama/"):
        return {}
    body = _ollama_extra(real_model, role, hw_profile)
    if force_evict:
        body = {**body, "keep_alive": 0}
    return body


# ── Paths ─────────────────────────────────────────────────────────────────────
# ONE resolver, in hive.manifest (already imported above, and lower-level -- it does
# not import this module, so there is no cycle). A second copy here is exactly the
# divergence that let two argv builders and two audit docs drift apart earlier in
# this campaign: same fact, two implementations, one of them eventually stale.
#
# Why it needs to validate rather than just honour the variable: DETERMINEX_ROOT
# pointed at C:\Dev\Citadel -- the pre-rename checkout, present on disk but with no
# litellm_config.yaml. load_role_assignments() therefore reported "config not found"
# and silently returned its local-only fallbacks, so every hive session ran with
# architect=local/fast instead of the configured determinex/qwen7b. The config's own
# comment warns the small model "produces empty plans as architect", and nothing
# surfaced that the canon was not in effect. Found live 2026-07-28.
_ROOT = resolve_repo_root()

# ── API rate limit defaults ──────────────────────────────────────────────────────
_DEFAULT_RATE_LIMIT_PROFILE = {
    "backoff_seconds": [5, 15, 30, 60, 120],
    "inter_call_pause": 1.0,
    "max_retries": 5,
}

# Timeout (seconds) for all local Ollama calls (Builder, Monitor, Oracle, Architect).
# If llama.cpp runs out of VRAM mid-generation, the process silently stalls and
# the HTTP response never arrives. Without a timeout the step hangs forever.
# 300 s: model cold-load from disk (3B = ~30s) + generation (3B at 5 tok/s, 800 tok = 160s)
# leaves ~110s margin for VRAM eviction + swap overhead on a 6GB rig.
BUILDER_TIMEOUT_SECONDS: int = 300


class RateLimitExhausted(Exception):
    """Raised when 429 retries are exhausted — caller pauses the build and notifies user."""


class ApiRateLimiter:
    """
    Rate limiter for all Hive Mind API calls across all providers and roles.

    Three concerns, in order of importance:
      1. Proactive TPM tracking
      2. Inter-call pacing
      3. Reactive backoff
    """

    def __init__(self, profile: dict | None = None) -> None:
        p = profile or _DEFAULT_RATE_LIMIT_PROFILE
        self._backoff_seconds: list[int] = p["backoff_seconds"]
        self._inter_call_pause: float = p["inter_call_pause"]
        self._max_retries: int = p["max_retries"]
        self._tpm_limit: int = p.get("tpm_limit", 40_000)
        self._last_call_time: float = 0.0
        self._token_window: list[tuple[float, int]] = []
        # G18: protect _token_window and _last_call_time from concurrent mutations
        self._rate_lock = __import__("threading").Lock()

    def reconfigure(self, profile: dict) -> None:
        """Hot-reload rate limit profile."""
        self._backoff_seconds = profile["backoff_seconds"]
        self._inter_call_pause = profile["inter_call_pause"]
        self._max_retries = profile["max_retries"]
        self._tpm_limit = profile.get("tpm_limit", self._tpm_limit)
        log.info(
            "Rate limiter reconfigured: pause=%.2fs, tpm=%d, max_retries=%d",
            self._inter_call_pause,
            self._tpm_limit,
            self._max_retries,
        )

    def _tokens_in_window(self, now: float) -> int:
        """Sum tokens used in the last 60 seconds. Caller must hold _rate_lock."""
        cutoff = now - 60.0
        self._token_window = [(t, n) for t, n in self._token_window if t > cutoff]
        return sum(n for _, n in self._token_window)

    def _proactive_tpm_wait(self, estimated_tokens: int) -> None:
        """If sending estimated_tokens would exceed the TPM limit, sleep."""
        with self._rate_lock:  # G18: lock window reads/mutations
            now = _time.monotonic()
            used = self._tokens_in_window(now)
            if used + estimated_tokens <= self._tpm_limit:
                return
            if not self._token_window:
                return
            oldest_ts = self._token_window[0][0]
            sleep_until = oldest_ts + 60.0
            wait = max(0.0, sleep_until - now)
        if wait > 0:
            log.info(
                "Proactive TPM wait: %.1fs (window used %d/%d tokens)", wait, used, self._tpm_limit
            )
            _time.sleep(wait)

    def record_tokens(self, tokens: int) -> None:
        """Call after a successful API response to record tokens used in window."""
        with self._rate_lock:  # G18
            self._token_window.append((_time.monotonic(), tokens))

    def call(self, fn, *args, estimated_tokens: int = 2000, **kwargs):
        """
        Call fn(*args, **kwargs) with proactive TPM pacing and reactive 429 backoff.
        """
        self._proactive_tpm_wait(estimated_tokens)

        with self._rate_lock:  # G18: read + update _last_call_time atomically
            elapsed = _time.monotonic() - self._last_call_time
            gap = self._inter_call_pause - elapsed
        if gap > 0:
            _time.sleep(gap)

        attempt = 0
        while True:
            try:
                with self._rate_lock:  # G18
                    self._last_call_time = _time.monotonic()
                # ── OOM guard ─────────────────────────────────────────────────────────
                # Local Ollama calls can stall forever if the model runs out of
                # VRAM. Pass a ceiling timeout so the executor loop gets a
                # TimeoutError it can surface to the user instead of a silent hang.
                #
                # THE GUARD DID NOT FIRE (found 2026-07-30). The condition was
                # `_model.startswith("ollama/")`, but `kwargs["model"]` holds the CONFIGURED
                # ALIAS, not the resolved provider name -- `builder_model` comes straight from
                # `model_assignments["builder"]`, i.e. `determinex/engineer`. That does not start
                # with "ollama/", so no timeout was set on the builder, monitor, oracle or
                # architect calls, and the comment above described exactly what then happened:
                # the step hung forever.
                #
                # Observed directly: a run-session sat 30+ minutes on step 2 with 0% CPU and two
                # ESTABLISHED sockets to 127.0.0.1:11434, having written its builder output and
                # then stopped. It is also the most likely cause of the repeated hive limits-test
                # stalls the same day.
                #
                # This is the THIRD appearance of one locality-detection bug. `budget.is_local_model`
                # exists because the pricing path had it (fixed 2026-07-29: bare tags like
                # `determinex-engineer-v11-dsl` start with "determinex-", not "determinex/"), and its
                # docstring already notes the same defect sits in api_client. So use that canonical
                # helper rather than a fourth hand-rolled prefix test -- it knows about ollama/,
                # ollama_chat/, hosted_vllm/, text-completion-openai/, determinex/, local/ and the
                # bare `determinex-` family.
                _model = kwargs.get("model", "")
                if isinstance(_model, str) and _model and is_local_model(_model):
                    kwargs = {**kwargs, "timeout": kwargs.get("timeout", BUILDER_TIMEOUT_SECONDS)}
                result = fn(*args, **kwargs)
                usage = getattr(result, "usage", None)
                if usage:
                    actual = getattr(usage, "input_tokens", 0) + getattr(usage, "output_tokens", 0)
                    self.record_tokens(actual)
                else:
                    self.record_tokens(estimated_tokens)
                return result
            except Exception as exc:
                is_rate_limit = (
                    "RateLimitError" in type(exc).__name__
                    or getattr(exc, "status_code", None) == 429
                    or getattr(exc, "code", None) == 429
                    or "rate_limit" in str(exc).lower()
                    or "quota" in str(exc).lower()
                    or "429" in str(exc)
                )
                if not is_rate_limit:
                    raise

                attempt += 1
                if attempt > self._max_retries:
                    raise RateLimitExhausted(
                        f"Rate limit not cleared after {self._max_retries} retries. "
                        "Build paused — resume when rate limit window resets (~60s). "
                        "Raise inter_call_pause or lower tpm_limit in litellm_config.yaml "
                        "under determinex.rate_limits: to match your API tier."
                    ) from exc

                retry_after = getattr(getattr(exc, "response", None), "headers", {}).get(
                    "retry-after"
                )
                wait = (
                    int(retry_after)
                    if retry_after
                    else self._backoff_seconds[min(attempt - 1, len(self._backoff_seconds) - 1)]
                )
                log.warning(
                    "Rate limit (attempt %d/%d) — backing off %ds", attempt, self._max_retries, wait
                )
                _time.sleep(wait)


def load_rate_limit_profile(config_path: Path | None = None) -> dict:
    """Load rate limit profile from litellm_config.yaml."""
    if config_path is None:
        config_path = _ROOT / "litellm_config.yaml"

    if not config_path.exists():
        return _DEFAULT_RATE_LIMIT_PROFILE

    try:
        import yaml

        with open(config_path) as f:
            config = yaml.safe_load(f) or {}
        rl = (config.get("determinex") or {}).get("rate_limits") or {}
        return {
            "backoff_seconds": rl.get(
                "backoff_seconds", _DEFAULT_RATE_LIMIT_PROFILE["backoff_seconds"]
            ),
            "inter_call_pause": rl.get(
                "inter_call_pause", _DEFAULT_RATE_LIMIT_PROFILE["inter_call_pause"]
            ),
            "max_retries": rl.get("max_retries", _DEFAULT_RATE_LIMIT_PROFILE["max_retries"]),
        }
    except Exception as e:
        log.warning("Could not load rate_limits from litellm_config.yaml (%s) — using defaults", e)
        return _DEFAULT_RATE_LIMIT_PROFILE


def load_role_assignments(config_path: Path | None = None) -> dict:
    """Load role-to-model assignments from litellm_config.yaml.

    Defaults are fully-local (Ollama) models — NOT cloud/* aliases.
    If the config file is missing or unreadable, the system runs in local-only
    mode using the generic Qwen base models rather than silently calling a
    cloud API that requires an API key.
    """
    if config_path is None:
        config_path = _ROOT / "litellm_config.yaml"

    # ── Local-only defaults — no cloud API required ───────────────────────
    # These are the generic base models used only as a last resort when the
    # config is genuinely missing. Under normal operation litellm_config.yaml
    # overrides these with the DSL-fine-tuned determinex/* models.
    defaults = {
        "oracle": "local/fast",  # Qwen2.5-3B (local Ollama)
        "architect": "local/fast",  # Qwen2.5-3B (local Ollama)
        "builder": "local/coder",  # Qwen2.5-Coder-1.5B (local Ollama)
        "monitor": "local/fast",  # Qwen2.5-3B (local Ollama)
    }

    if not config_path.exists():
        log.warning(
            "litellm_config.yaml not found — using local-only defaults. "
            "Models: oracle/architect=local/fast, builder=local/coder, monitor=local/fast. "
            "To enable cloud models, set DETERMINEX_ALLOW_CLOUD_FALLBACK=1 in your environment "
            "and add API keys to .env."
        )
        return defaults

    try:
        import yaml

        with open(config_path) as f:
            config = yaml.safe_load(f) or {}
        roles = (config.get("determinex") or {}).get("roles") or {}
        return _apply_role_overrides({**defaults, **roles})
    except Exception as e:
        log.warning(
            "Could not load role assignments from litellm_config.yaml (%s) — using local-only defaults",
            e,
        )
        return _apply_role_overrides(defaults)


def _apply_role_overrides(roles: dict) -> dict:
    """Let one run pin a role without editing the shared config file.

        DETERMINEX_ROLE_BUILDER=determinex/qwen7b

    Added for the router A/B, which has to run the SAME specs with the builder
    pinned to a single model (the always-frontier arm) and then with a ladder (the
    routed arm). Doing that by rewriting litellm_config.yaml between arms would
    mutate shared state mid-experiment and leave the repo dirty if a run died
    partway. It is generally useful too: overriding a role for one invocation is
    ordinary, and the neighbouring DETERMINEX_BUILDER_FALLBACK_MODEL already
    establishes the env-override precedent.

    Only the four known roles are honoured, so a typo cannot silently invent one.
    """
    out = dict(roles)
    for role in ("oracle", "architect", "builder", "monitor"):
        val = _os_env.environ.get(f"DETERMINEX_ROLE_{role.upper()}", "").strip()
        if val:
            out[role] = val
            # Plain format string, not structlog kwargs: this runs during config
            # load, which is exactly when the structlog binding may not be in
            # place, and a TypeError here would take out role resolution itself.
            log.info("role override: %s -> %s (DETERMINEX_ROLE_%s)", role, val, role.upper())
    return out


# ── Lightweight model alias resolver ─────────────────────────────────────────
# Translates friendly names (cloud/claude-best, determinex/engineer) to real
# litellm params (model string, api_key, api_base).  No Router — no health
# checks, no cost-based probing, no startup failures on missing local models.

_alias_map: dict | None = None  # lazy-loaded on first api_call


def _alias_config_candidates() -> list[Path]:
    """Every plausible location of litellm_config.yaml, most specific first.

    WHY MORE THAN ONE. `_ROOT` is `resolve_repo_root()`, which in a PyInstaller sidecar is a temp
    extraction directory rather than a checkout -- so `_ROOT / "litellm_config.yaml"` was the ONLY
    place looked at, and in a shipped build nothing was there. The file was bundled by neither path:
    not in `bundle.resources` (Tauri) and not in the sidecar's PyInstaller data.

    The consequence was not a degraded feature. With no alias map, `determinex/engineer` resolves to
    ITSELF, and `determinex/` is not a provider litellm knows -- so on a fresh install the hive build
    loop could not call any model at all. Measured 2026-07-30 by pointing `_ROOT` at an empty dir:
    0 alias entries, and every role alias resolved to an unusable string.

    Searching candidates rather than picking one avoids trading that bug for a guess about
    PyInstaller's layout: whichever packaging path delivers the file, this finds it.
    """
    candidates: list[Path] = [_ROOT / "litellm_config.yaml"]
    # PyInstaller one-file extraction root.
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        candidates.append(Path(meipass) / "litellm_config.yaml")
    # Beside the running executable, and the `../../` resource layout Tauri preserves
    # (bundle.resources declared as "../../x" land in <install>/_up_/_up_/x).
    exe_dir = Path(sys.executable).resolve().parent
    candidates.extend(
        [
            exe_dir / "litellm_config.yaml",
            exe_dir / "_up_" / "_up_" / "litellm_config.yaml",
        ]
    )
    # Deduplicate, preserving order.
    seen: set[str] = set()
    unique: list[Path] = []
    for candidate in candidates:
        key = str(candidate).lower()
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def _load_alias_map() -> dict:
    """
    Parse litellm_config.yaml and build alias → litellm_params mapping.
    Returns {} if config is missing or unparseable.
    """
    global _alias_map
    if _alias_map is not None:
        return _alias_map

    _alias_map = {}
    searched = _alias_config_candidates()
    config_path = next((c for c in searched if c.exists()), None)
    if config_path is None:
        log.warning(
            "litellm_config.yaml not found in any of %s — no alias resolution, so role aliases "
            "like 'determinex/engineer' will not resolve to an Ollama tag and model calls will fail",
            [str(p) for p in searched],
        )
        return _alias_map

    try:
        import yaml

        with open(config_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        for entry in cfg.get("model_list", []):
            name = entry.get("model_name", "")
            params = entry.get("litellm_params", {})
            if name and params.get("model"):
                _alias_map[name] = params
        log.info("Alias map loaded: %d entries from litellm_config.yaml", len(_alias_map))
    except Exception as e:
        log.warning("Could not parse litellm_config.yaml (%s) — alias resolution disabled", e)

    return _alias_map


def _expand_env_refs(params: dict, *, require: bool = True) -> dict:
    """Resolve `os.environ/VAR_NAME` values in litellm_params against the environment.

    This is LiteLLM's own indirection syntax, but it is implemented by the litellm PROXY.
    The hive calls `litellm.completion` directly with params read straight out of the YAML,
    so before this the string was passed through verbatim and surfaced as:

        InternalServerError: Hosted_vllmException - Request URL is missing an
        'http://' or 'https://' protocol.

    -- an error that says nothing about the actual cause. Found 2026-08-02 wiring a live
    Radeon GPU in as the builder.

    It matters because `litellm_config.yaml` is committed and published. An endpoint URL for
    a cloud GPU instance is ephemeral (it changes every time the tunnel restarts) and an API
    key is a credential; neither belongs in the repo. Without this, the only way to point a
    role at a private endpoint is to write the endpoint into a tracked file.

    An unset variable RAISES rather than silently dropping the key: dropping `api_base`
    would send the request to whatever default the client picks -- most likely localhost --
    and a request that quietly goes somewhere else is worse than one that fails.
    """
    import os

    out: dict = {}
    for key, value in params.items():
        if isinstance(value, str) and value.startswith("os.environ/"):
            var = value[len("os.environ/"):]
            resolved = os.environ.get(var)
            if not resolved:
                if not require:
                    # INSPECTION, not a call. Callers like `_required_ollama_models` only
                    # want to know whether an alias resolves to an Ollama model; demanding a
                    # cloud API key to answer that would make an offline, local-only run fail
                    # on credentials it never intended to use. Drop the unresolved key --
                    # the call path re-resolves with require=True and raises there.
                    continue
                raise RuntimeError(
                    f"litellm_config.yaml sets {key}={value}, but ${var} is unset or empty. "
                    f"Export it (e.g. {var}=... ) before using this alias."
                )
            out[key] = resolved
        else:
            out[key] = value
    return out


def _resolve_model(alias: str, *, require_env: bool = False) -> tuple[str, dict]:
    """
    Resolve alias → (real_model_string, extra_kwargs).
    Returns (alias, {}) if the alias is not in the map (treat as a native litellm model).

    CLOUD GUARD: If the resolved model is a cloud/* alias (i.e. not an Ollama model)
    and DETERMINEX_ALLOW_CLOUD_FALLBACK is not set to '1', raises a RuntimeError with a
    clear user-facing message rather than silently burning API credits or requiring
    an API key the user did not know was needed.

    To enable cloud models, add to your .env or shell:
        DETERMINEX_ALLOW_CLOUD_FALLBACK=1
    """
    import os

    amap = _load_alias_map()
    if alias not in amap:
        return alias, {}

    params = _expand_env_refs(amap[alias], require=require_env)
    real_model = params["model"]

    # ── Cloud guard ────────────────────────────────────────────────────────
    # If the resolved model is not an Ollama model (i.e. it is a cloud API),
    # block the call unless the user has explicitly opted in.
    _is_cloud = not real_model.startswith("ollama/")
    if _is_cloud:
        _allow = os.environ.get("DETERMINEX_ALLOW_CLOUD_FALLBACK", "").strip() == "1"
        if not _allow:
            raise RuntimeError(
                f"[DETERMINEX] Cloud model blocked: '{alias}' → '{real_model}'.\n"
                "  The system attempted to call a cloud API model, but "
                "DETERMINEX_ALLOW_CLOUD_FALLBACK is not set.\n"
                "  To run fully local: check your litellm_config.yaml — "
                "all roles should point to determinex/* or local/* models.\n"
                "  To allow cloud fallback: add DETERMINEX_ALLOW_CLOUD_FALLBACK=1 "
                "to your .env file or shell environment."
            )

    extra: dict = {}

    # api_base (for Ollama / custom providers)
    if params.get("api_base"):
        extra["api_base"] = params["api_base"]

    # api_key: expand os.environ/KEY_NAME references
    api_key = params.get("api_key", "")
    if api_key.startswith("os.environ/"):
        import os

        env_name = api_key.split("os.environ/", 1)[1]
        api_key = os.environ.get(env_name, "")
    if api_key:
        extra["api_key"] = api_key

    return real_model, extra


# Module-level singleton
_api_rate_limiter = ApiRateLimiter(load_rate_limit_profile())


def api_call(
    fn,
    *args,
    model: str = "",
    role: str = "",
    session_id: str = "",
    cloak_active: bool = False,
    **kwargs,
):
    """
    Wrapper for all Hive Mind API calls.

    Resolves friendly model aliases from litellm_config.yaml, injects api_key /
    api_base, then calls through the global rate limiter to litellm.completion.

    #27: Acquires per-role backpressure semaphore before the call to cap
    in-flight concurrency (prevents OOM on VRAM-constrained Tier 0 rigs when
    multiple DAG steps run in parallel).

    #29: If session_id is provided and kwargs contains 'messages', injects a
    per-session UUID prefix into the system message to prevent KV cache
    collisions between concurrent Ollama sessions.

    SAFETY: Runs pre_api_gate (L2 egress filter + Cloak enforcement) before
    every cloud-tier API call. Raises SafetyDenied / RuntimeError on violation.

    The fn argument is kept for back-compat; it is always overridden to
    litellm.completion so callers don't need to import litellm themselves.
    """
    import litellm

    if model:
        # require_env=True: this is the ONLY caller that consumes `extra` (api_base /
        # api_key), so it is the only one for which an unresolved os.environ/ reference is
        # fatal. Every other caller discards the extras with `_`.
        real_model, extra = _resolve_model(model, require_env=True)
        kwargs = {**kwargs, "model": real_model, **extra}
        fn = litellm.completion

    # ── SAFETY: L2 egress filter + Cloak enforcement ─────────────────────────
    # Run before KV injection so the safety scan sees the raw prompt content,
    # not the UUID-prefixed version.
    _effective_model = kwargs.get("model", model)
    _messages = kwargs.get("messages", [])
    try:
        from hive.safety_gate import pre_api_gate

        pre_api_gate(_messages, _effective_model, cloak_active=cloak_active)
    except Exception as _safety_err:
        log.error("[api_call] Safety gate rejected call to '%s': %s", _effective_model, _safety_err)
        raise

    # #29: Inject per-session KV namespace for Ollama cache isolation.
    # Skip oracle/architect: the DSL-fine-tuned observer pattern-matches the
    # [session:UUID] prefix as a Determinex session context and generates wrong output.
    _kv_skip_roles = {"oracle", "architect"}
    if session_id and "messages" in kwargs and role not in _kv_skip_roles:
        kwargs["messages"] = inject_kv_namespace(kwargs["messages"], session_id)

    _role = role or "builder"  # default backpressure bucket
    with api_backpressure(_role):  # #27
        return _api_rate_limiter.call(fn, *args, **kwargs)


# ── MD spec dependency parser ────────────────────────────────────────────────

# Known Rust crates → Cargo.toml value string.
# Entries with features use inline table syntax so serde derive works out of the box.
_RUST_KNOWN_CRATES: dict[str, str] = {
    "serde": '{ version = "1", features = ["derive"] }',
    "serde_json": '"1"',
    "serde_yaml": '"0.9"',
    "tokio": '{ version = "1", features = ["full"] }',
    "clap": '{ version = "4", features = ["derive"] }',
    "anyhow": '"1"',
    "thiserror": '"1"',
    "reqwest": '{ version = "0.11", features = ["json", "blocking"] }',
    "rand": '"0.8"',
    "chrono": '"0.4"',
    "regex": '"1"',
    "uuid": '{ version = "1", features = ["v4"] }',
    "log": '"0.4"',
    "env_logger": '"0.10"',
    "actix-web": '"4"',
    "lazy_static": '"1"',
    "once_cell": '"1"',
    "itertools": '"0.12"',
    "indexmap": '"2"',
    "tracing": '"0.1"',
    "tracing-subscriber": '"0.3"',
    "axum": '"0.7"',
}


def _parse_md_dependencies(spec_text: str, lang: str) -> dict[str, str]:
    """
    Extract the ## Dependencies section from an MD spec and return a dict
    of { crate_name: cargo_toml_value } for Rust, or { pkg: version } for Go/Python.
    Lines must match:  - <name> [—|-] <description>
    """
    deps: dict[str, str] = {}
    in_deps = False
    for line in spec_text.splitlines():
        stripped = line.strip()
        if re.match(r"^##\s+[Dd]ependencies", stripped):
            in_deps = True
            continue
        if in_deps:
            if stripped.startswith("## "):
                break  # end of section
            # Match: - cratename — description   or   - cratename: description
            m = re.match(r"^-\s+([\w\-]+)", stripped)
            if not m:
                continue
            name = m.group(1).lower()
            # Skip sentinel "no dependency" values the model emits
            if name in {
                "none",
                "n/a",
                "na",
                "nil",
                "null",
                "stdlib",
                "standard",
                "builtin",
                "built-in",
                "no",
                "nothing",
            }:
                continue
            if lang == "rust":
                deps[name] = _RUST_KNOWN_CRATES.get(name, '"*"')
            elif lang == "go":
                deps[name] = "latest"
            else:
                deps[name] = "*"
    return deps


# ── Architect DAG generation ──────────────────────────────────────────────────

_ARCHITECT_SYSTEM = """You are the Architect for the Determinex build system.
Output ONLY a raw JSON array. No prose, no markdown fences, no explanation.
First character must be [, last character must be ].

Each element:
{"id": 1, "instruction": "...", "depends_on": [], "target_file": "src/main.rs", "write_mode": "new_file", "target_region": null}

CRITICAL RULE — COMPILABILITY:
Every step must leave the whole project in a state that compiles.
After step 1, the compiler must pass. After step 2, the compiler must pass. Always.
This means: NEVER create a partial file that is missing required syntax (e.g. fn main for a Rust binary).

RULE — SMALL PROJECTS (single source file, under 100 lines):
Use ONE step with write_mode=new_file that writes the COMPLETE, working implementation.
Do NOT split one small file into skeleton + body + logic. That breaks compilation at every intermediate step.

RULE — RUST BINARIES:
The step that creates src/main.rs MUST include a complete fn main() entry point.
A src/main.rs without fn main() will not compile and every subsequent step will fail.

RULE — DATA FILES:
Text data files (e.g. counter.txt, data.json) do NOT need their own step.
Include them in the instruction of the step that creates the source file that reads them,
or create them as the LAST step after all source code compiles.

RULE — write_mode:
- new_file: first time a file is created
- replace_file: rewrite the whole file (use for all edits to existing files)
- append_to_file: add a NEW top-level function that does not modify any existing code
- replace_function: Rust only — replace ONE EXISTING named function by AST. ONLY use this if a function with that exact name already exists in the file from a prior step.

CRITICAL RULE — replace_function:
NEVER use replace_function for a function that does not already exist in the file.
If you want to ADD a new function, use append_to_file.
If you want to REPLACE an existing function that a prior step created, use replace_function.
Using replace_function on a non-existent function silently appends broken code.

RULE — single-file projects:
If the ## Files section lists only ONE source file (e.g., only src/main.rs), output EXACTLY ONE step with write_mode=new_file that writes the COMPLETE, working implementation. Do NOT split into stub + helpers.

RULE — depends_on:
Every step that modifies a file MUST depend on all prior steps that created or modified that file.
A step with no depends_on runs immediately — only use [] if the step truly has no prerequisites.

GOOD example for a small Rust CLI with serde_json persistence:
[{"id":1,"instruction":"Write complete src/main.rs: fn main() reads argv subcommand (add N / reset / show). Read counter.json with serde_json (default 0 if missing). Update and write back for add/reset. Print value for show. Use std::env, std::fs, serde, serde_json. No Arc, no Mutex, no threads.","depends_on":[],"target_file":"src/main.rs","write_mode":"new_file","target_region":null}]

GOOD example for a Rust CLI grocery list (multiple subcommands, struct with fields):
[{"id":1,"instruction":"Write complete src/main.rs: struct GroceryItem {name:String, qty:u32, done:bool} with #[derive(Serialize,Deserialize,Debug,Clone,PartialEq)]. fn main() reads argv, loads groceries.json with serde_json (default [] if missing). Subcommands: add <name> <qty> pushes new item; check <name> sets done=true on matching item; list prints undone items; clear retains only undone items. Writes back to groceries.json. No Arc, no Mutex, no threads.","depends_on":[],"target_file":"src/main.rs","write_mode":"new_file","target_region":null}]

BAD example (DO NOT DO THIS — breaks compilation at every step):
[{"id":1,"instruction":"Create src/main.rs stub"},{"id":2,"instruction":"Add fn read_counter"},{"id":3,"instruction":"Add fn write_counter"},{"id":4,"instruction":"Implement main"}]
"""


# ── DSL Pre-processor ────────────────────────────────────────────────────────
# Tier 0 gap fix: at Tier 0 the Oracle/Architect run via cloud API (no hidden
# states exposed — Rosetta Layer 2 cannot bridge them).  But we can use the
# local Builder (free, zero API cost) to compress the user's freeform spec into
# a dense DSL packet BEFORE the Oracle call.  The API Oracle receives structured
# input, not prose:
#
#   User freeform text
#       ↓  (local Builder, zero cost)
#   INTENT:implement LANG:rust PATTERN:arc-mutex
#   CONSTRAINT:thread-safe CONSTRAINT:no-unsafe
#   FILES:src/lib.rs src/main.rs
#       ↓  (API Oracle receives dense structured spec)
#   fewer tokens · zero ambiguity · Architect DAG is tighter
#       ↓  (DSL enters Builder↔Monitor boundary)
#   Rosetta Layer 2 eligible (both local)
#
# The pre-processor is skipped if:
#   - builder_model is an API model (no savings — API pre-processing costs more)
#   - spec_text is already short (<400 chars — no prose to compress)
#   - the local call fails (soft fallback — original spec used unchanged)

_DSL_PREPROCESSOR_SYSTEM = """\
You are a spec compressor for the Determinex Hive Mind.
Your job: convert a Markdown software specification into a compact DSL packet.

Output ONLY the DSL packet — no prose, no explanation, no markdown fences.
Use this exact format:

INTENT:<verb> <object>         # e.g. implement thread-safe counter
LANG:<language>                # rust | go | python | typescript
PATTERN:<pattern>              # e.g. arc-mutex | goroutine-channel | async-await
CONSTRAINT:<constraint>        # one per line, repeat tag for multiple
CONSTRAINT:<constraint>
FILES:<file1> <file2>          # space-separated relative paths

Rules:
- INTENT must be a single imperative phrase (verb + object), max 8 words.
- LANG must be exactly one of: rust, go, python, typescript, c, cpp, java, other.
- PATTERN is the dominant algorithmic pattern — one phrase, no spaces within it.
- CONSTRAINT lines: one hard requirement per line. Include thread-safety, error handling,
  performance, API surface, and security constraints if mentioned. Omit vague wishes.
- FILES: relative paths only. Guess based on language conventions if not stated.
- If the spec is already a DSL packet, output it unchanged.
- If a field cannot be determined, omit it rather than guessing wrongly.
"""


def _preprocess_spec_to_dsl(
    spec_text: str,
    builder_model: str,
    session_id: str = "",
    hw_profile=None,
) -> str:
    """
    Run spec_text through the local Builder to produce a compact DSL packet.

    Returns the DSL packet string on success, or the original spec_text if
    the builder model is remote, the spec is already compact, or the call fails.

    This is a best-effort optimisation — it MUST NOT block the main pipeline.
    """
    # _resolve_model is the single source of truth for model locality.
    # The previous two-check approach incorrectly skipped bare model names
    # (e.g. "determinex-engineer") because they have no slash — but they ARE
    # local Ollama models. Resolving first handles all cases correctly.
    if not builder_model:
        log.debug("DSL pre-processor skipped: no builder model assigned")
        return spec_text
    real_model, _ = _resolve_model(builder_model)
    if not real_model.startswith("ollama/"):
        log.debug(
            "DSL pre-processor skipped: resolved model is not local (%s → %s)",
            builder_model,
            real_model,
        )
        return spec_text
    # Skip if spec is already short enough to not benefit from compression
    if len(spec_text.strip()) < 400:
        log.debug("DSL pre-processor skipped: spec already compact (%d chars)", len(spec_text))
        return spec_text

    import litellm

    messages = [
        {"role": "system", "content": _DSL_PREPROCESSOR_SYSTEM},
        {"role": "user", "content": f"SPECIFICATION:\n\n{spec_text}"},
    ]
    try:
        log.info(
            "DSL pre-processor: compressing spec (%d chars) via %s", len(spec_text), builder_model
        )
        # keep_alive=0: evict immediately after preprocessing so the larger Oracle
        # model (3B) can load without VRAM contention from the hot engineer (1.5B).
        # The engineer gets keep_alive=-1 during actual build steps; pre-processing
        # is a one-shot warmup that shouldn't hold VRAM through the Oracle call.
        resp = api_call(
            litellm.completion,
            model=builder_model,
            messages=messages,
            session_id=session_id,
            role="builder",
            estimated_tokens=300,
            # 45s cap: 1.5B at 5 tok/s = ~300 tokens in 60s. If it hasn't responded
            # in 45s the model is looping or stuck — fail fast and use the raw spec.
            timeout=45,
            extra_body=_provider_extra_body(
                builder_model,
                "builder",
                hw_profile,
                force_evict=True,
            ),
        )
        dsl_packet = (resp.choices[0].message.content or "").strip()
        if not dsl_packet or len(dsl_packet) < 20:
            log.warning("DSL pre-processor returned empty/trivial output — using original spec")
            return spec_text
        log.info(
            "DSL pre-processor: compressed %d → %d chars\n%s",
            len(spec_text),
            len(dsl_packet),
            dsl_packet[:300],
        )
        return dsl_packet
    except Exception as exc:
        # Soft fallback — never block the pipeline
        log.warning("DSL pre-processor failed (non-fatal, using original spec): %s", exc)
        return spec_text


def _build_oracle_messages(spec_text: str) -> list[dict]:
    return [
        {
            "role": "system",
            "content": (
                "You are the Oracle for the Determinex build system. "
                "Read the specification and write a plain English summary (3-5 sentences). "
                "Cover: what the software does, the programming language, "
                "the key data structures or types needed, and the critical constraints. "
                "Output plain prose only — no JSON, no DSL tags, no bullet points, no markdown."
            ),
        },
        {"role": "user", "content": f"SPECIFICATION:\n\n{spec_text}"},
    ]


def _extract_spec_constraints(spec_text: str) -> str:
    """Extract ## Constraints section from MD spec for explicit injection."""
    m = re.search(r"## Constraints\s*\n(.*?)(?:\n##|\Z)", spec_text, re.DOTALL)
    if not m:
        return ""
    return m.group(1).strip()


def _count_spec_source_files(spec_text: str) -> int:
    """Count distinct source files listed in the ## Files section.

    Returns the number of source files found (e.g. .rs/.go/.py entries).
    Returns 0 if no ## Files section exists.
    """
    m = re.search(r"## Files\s*\n(.*?)(?:\n##|\Z)", spec_text, re.DOTALL)
    if not m:
        return 0
    block = m.group(1)
    # Match lines like: - `src/main.rs` — ...  or  - src/main.rs
    file_lines = re.findall(
        r"^\s*-\s+`?([^\s`\n]+\.[a-zA-Z0-9]+)`?",
        block,
        re.MULTILINE,
    )
    # Filter to actual source files (exclude config files like Cargo.toml, go.mod)
    _config_files = {
        "cargo.toml",
        "go.mod",
        "go.sum",
        "pyproject.toml",
        "setup.py",
        "requirements.txt",
        "makefile",
        ".gitignore",
    }
    source_files = [f for f in file_lines if Path(f).name.lower() not in _config_files]
    return len(set(source_files))


def _build_architect_messages(
    spec_text: str, oracle_summary: str, lang: str, error_note: str = ""
) -> list[dict]:
    note = f"\n\nIMPORTANT: {error_note}" if error_note else ""

    # Inject spec constraints as hard requirements in the user message.
    # The 3B model ignores system prompt rules but does obey inline user-turn directives.
    constraint_text = _extract_spec_constraints(spec_text)
    constraint_block = ""
    if constraint_text:
        constraint_block = (
            f"\n\nHARD REQUIREMENTS FROM SPEC — violating these makes the build wrong:\n"
            f"{constraint_text}\n"
            "These constraints override any default patterns. "
            "Do NOT add concurrency, threads, or external crates not listed in ## Dependencies.\n"
        )

    # Detect single-file spec and add an explicit one-step directive.
    single_file_directive = ""
    spec_lower = spec_text.lower()
    _is_single_file = (
        any(
            x in spec_lower
            for x in (
                "single source file",
                "single file",
                "one file",
                ".rs only",
                ".go only",
                ".py only",
            )
        )
        or _count_spec_source_files(spec_text) == 1
    )
    if _is_single_file:
        single_file_directive = (
            "\n\nSINGLE FILE DIRECTIVE: The spec targets ONE source file. "
            "Output EXACTLY ONE step with write_mode=new_file. "
            "Do NOT split into multiple append_to_file steps. "
            "The one step must write the COMPLETE, compilable implementation.\n"
        )

    return [
        {"role": "system", "content": _ARCHITECT_SYSTEM},
        {
            "role": "user",
            "content": (
                f"LANGUAGE: {lang}\n\n"
                f"ORACLE SUMMARY:\n{oracle_summary}\n\n"
                f"MD SPECIFICATION:\n{spec_text}"
                f"{constraint_block}"
                f"{single_file_directive}"
                f"{note}\n\n"
                "Generate the step manifest JSON array now:"
            ),
        },
    ]


def _repair_json(text: str) -> str:
    """
    Fix common LLM JSON output issues before parsing.

    1. Invalid escape sequences: LLMs embed Windows paths (C:\\...) or words like
       '\\escape' literally. JSON only allows \\", \\\\, \\/, \\b, \\f, \\n, \\r,
       \\t, \\uXXXX — anything else is invalid. Replace bare backslashes with \\\\.
    2. Trailing commas before ] or } (strict JSON doesn't allow them).
    """
    # Fix invalid escape sequences: \X where X is not a valid JSON escape char
    repaired = re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", text)
    # Strip trailing commas before closing brackets/braces
    repaired = re.sub(r",\s*([}\]])", r"\1", repaired)
    return repaired


def _try_loads(text: str) -> list:
    """Try json.loads with automatic repair on failure."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return json.loads(_repair_json(text))


def _extract_json_array(text: str) -> list:
    """Extract first JSON array from LLM response, robust to markdown fences."""
    m = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
    if m:
        return _try_loads(m.group(1))
    m = re.search(r"(\[.*\])", text, re.DOTALL)
    if m:
        return _try_loads(m.group(1))
    # Model may have wrapped array in an object: {"steps": [...]}
    m = re.search(r'"steps"\s*:\s*(\[.*?\])', text, re.DOTALL)
    if m:
        return _try_loads(m.group(1))
    raise ValueError("No JSON array found in response")


_VALID_WRITE_MODES = {"new_file", "replace_file", "append_to_file", "replace_function"}


def _parse_step_records(raw: list, lang: str) -> list[StepRecord]:
    """Parse raw JSON list into StepRecord objects with field validation."""
    steps = []
    seen_ids: set[int] = set()
    for item in raw:
        sid = int(item["id"])
        if sid in seen_ids:
            continue
        seen_ids.add(sid)

        wm = item.get("write_mode", "append_to_file")
        if wm not in _VALID_WRITE_MODES:
            wm = "append_to_file"
        if wm == "replace_function" and lang != "rust":
            wm = "replace_file"

        steps.append(
            StepRecord(
                id=sid,
                instruction=str(item.get("instruction", "")).strip(),
                depends_on=[int(d) for d in item.get("depends_on", []) if int(d) < sid],
                target_file=str(item.get("target_file", "")).strip(),
                write_mode=wm,
                target_region=item.get("target_region") or None,
            )
        )
    steps.sort(key=lambda s: s.id)
    return steps


def generate_dag(
    session: ManifestSession,
    model_assignments: dict | None = None,
) -> ManifestSession:
    """
    Call Oracle + Architect to generate the DAG step manifest.
    """
    import litellm

    if model_assignments is None:
        model_assignments = load_role_assignments()

    spec_path = Path(session.md_spec_path)
    if not spec_path.exists():
        raise FileNotFoundError(f"MD spec not found: {spec_path}")
    spec_text = spec_path.read_text(encoding="utf-8")
    workspace = Path(session.project_root)
    hw = get_hw_profile()

    # ── DSL Pre-processor: compress freeform spec before cloud API call ───────
    # Tier 0 fix: local Builder runs free, converts user prose → dense DSL packet.
    # API Oracle receives structured input → fewer tokens, tighter Architect DAG.
    # Skipped automatically if builder is an API model or spec is already compact.
    builder_model = model_assignments.get("builder", "")
    spec_text_for_api = _preprocess_spec_to_dsl(
        spec_text,
        builder_model=builder_model,
        session_id=session.session_id,
        hw_profile=hw,
    )
    if spec_text_for_api is not spec_text:
        log.info(
            "DSL pre-processor active: Oracle will receive compressed spec (%d → %d chars)",
            len(spec_text),
            len(spec_text_for_api),
        )

    # ── Oracle: encode spec intent ────────────────────────────────────────────
    oracle_model = model_assignments.get("oracle") or model_assignments.get("architect")
    log.info("Oracle: encoding spec (%d chars) via %s", len(spec_text_for_api), oracle_model)
    print(
        f"[DETERMINEX] Oracle ({oracle_model}) encoding spec — may take 30-90s on first load...",
        flush=True,
    )
    try:
        oracle_resp = api_call(
            litellm.completion,
            model=oracle_model,
            messages=_build_oracle_messages(spec_text_for_api),
            session_id=session.session_id,
            role="oracle",
            estimated_tokens=800,
            max_tokens=400,
            extra_body=_provider_extra_body(oracle_model, "oracle", hw),
        )
        o_usage = getattr(oracle_resp, "usage", None)
        record_api_call_cost(
            session,
            getattr(o_usage, "total_tokens", 800) if o_usage else 800,
            model=oracle_model or "",
            prompt_tokens=getattr(o_usage, "prompt_tokens", None) if o_usage else None,
            completion_tokens=getattr(o_usage, "completion_tokens", None) if o_usage else None,
        )
        oracle_summary = oracle_resp.choices[0].message.content or ""
        log.info("Oracle summary: %s...", oracle_summary[:120])
    except RateLimitExhausted as e:
        log.error("Rate limit exhausted during Oracle call: %s", e)
        raise

    # ── Architect: generate step manifest ────────────────────────────────────
    arch_model = model_assignments.get("architect") or oracle_model
    log.info("Architect: generating DAG via %s", arch_model)
    print(
        f"[DETERMINEX] Architect ({arch_model}) planning DAG — may take 30-90s on first load...",
        flush=True,
    )

    error_note = ""
    steps: list[StepRecord] = []
    for attempt in range(2):
        try:
            arch_resp = api_call(
                litellm.completion,
                model=arch_model,
                messages=_build_architect_messages(
                    spec_text, oracle_summary, session.lang, error_note
                ),
                session_id=session.session_id,
                role="architect",
                estimated_tokens=4000,
                max_tokens=2048,
                extra_body=_provider_extra_body(arch_model, "architect", hw),
            )
            a_usage = getattr(arch_resp, "usage", None)
            record_api_call_cost(
                session,
                getattr(a_usage, "total_tokens", 3000) if a_usage else 3000,
                model=arch_model or "",
                prompt_tokens=getattr(a_usage, "prompt_tokens", None) if a_usage else None,
                completion_tokens=getattr(a_usage, "completion_tokens", None) if a_usage else None,
            )
            arch_text = arch_resp.choices[0].message.content or ""

            raw_steps = _extract_json_array(arch_text)
            if not raw_steps:
                raise ValueError("Architect returned empty step list")
            steps = _parse_step_records(raw_steps, session.lang)
            if not steps:
                raise ValueError("Step parse produced zero StepRecords")
            log.info("Architect produced %d steps", len(steps))
            break

        except (ValueError, json.JSONDecodeError, KeyError) as e:
            log.warning("Architect attempt %d failed: %s", attempt + 1, e)
            # L10-A: Explicit schema reminder on retry — the first attempt's system
            # prompt wasn't enough; repeat the exact required format with a concrete
            # example so the model has no ambiguity about what to output.
            error_note = (
                f"Your previous response could not be parsed as a valid JSON array: {e}. "
                "You MUST output ONLY a raw JSON array — no prose, no markdown fences, "
                "no explanation before or after. "
                "First character: '['. Last character: ']'. "
                "Each element MUST match this exact schema: "
                '{"id": 1, "instruction": "...", "depends_on": [], '
                '"target_file": "src/main.rs", "write_mode": "new_file", "target_region": null}'
            )
            if attempt == 1:
                raise RuntimeError(
                    f"Architect failed to produce a valid DAG after 2 attempts: {e}"
                ) from e

    # ── DAG safety: collapse multi-step single-file plans ────────────────────
    # The 3B Architect sometimes generates append_to_file chains for specs that
    # list only one source file. Collapse to a single new_file step.
    spec_lower = spec_text.lower()
    _single_file_spec = (
        any(
            x in spec_lower
            for x in ("single source file", "single file", ".rs only", ".go only", ".py only")
        )
        or _count_spec_source_files(spec_text) == 1
    )
    _SOURCE_EXTS = {".rs", ".go", ".py", ".ts", ".js", ".c", ".cpp", ".java"}
    if len(steps) > 1 and _single_file_spec:
        # Only count source-code files — data/json/txt steps don't block collapse
        src_target_files = {
            s.target_file
            for s in steps
            if s.target_file and Path(s.target_file).suffix in _SOURCE_EXTS
        }
        if len(src_target_files) == 1:
            target_file = list(src_target_files)[0]
            # Collect instructions from source steps only
            combined = " ".join(
                s.instruction
                for s in steps
                if s.target_file and Path(s.target_file).suffix in _SOURCE_EXTS
            )
            steps = [
                StepRecord(
                    id=1,
                    instruction=(
                        f"Write the COMPLETE, compilable {session.lang} implementation for "
                        f"{target_file}. Include all functions. {combined}"
                    )[:800],
                    depends_on=[],
                    target_file=target_file,
                    write_mode="new_file",
                    target_region=None,
                    status="pending",
                )
            ]
            log.info(
                "DAG collapse: multi-step → 1 (single source file %s, data-file steps dropped)",
                target_file,
            )

    session.steps = steps

    # ── Generate project scaffolding ──────────────────────────────────────────
    pkg_name = workspace.name.replace("-", "_").replace(" ", "_")
    md_deps = _parse_md_dependencies(spec_text, session.lang)
    if md_deps:
        log.info("Parsed %d dependencies from MD spec: %s", len(md_deps), list(md_deps.keys()))
    if session.lang == "rust":
        cargo_content = scaffold_rust_project(
            workspace, package_name=pkg_name, dependencies=md_deps or None
        )
        session.cargo_toml = cargo_content
        log.info("Scaffolded Rust project: %s/Cargo.toml", workspace)
    elif session.lang == "go":
        scaffold_go_module(workspace, module_name=f"determinex/{pkg_name}")
        log.info("Scaffolded Go module: %s/go.mod", workspace)
    elif session.lang == "python":
        scaffold_python_project(workspace, package_name=pkg_name)
        log.info("Scaffolded Python project: %s/pyproject.toml", workspace)

    save_manifest(session)
    log.info("DAG manifest saved — %d steps, session=%s", len(steps), session.session_id)
    return session


def cmd_generate_dag(args) -> None:
    """CLI handler for 'generate-dag': call Oracle+Architect to populate step manifest."""
    try:
        session = load_manifest(args.session)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        log.error("Session not found or corrupted: %s", e)
        sys.exit(1)

    if session.steps and not getattr(args, "force", False):
        print(f"Session already has {len(session.steps)} steps.")
        print(
            f"Use --force to regenerate.  Run: python determinex_hive.py run-session --session {args.session}"
        )
        sys.exit(0)

    try:
        model_assignments = load_role_assignments()
        session = generate_dag(session, model_assignments)
    except (RuntimeError, FileNotFoundError, RateLimitExhausted) as e:
        log.error("DAG generation failed: %s", e)
        sys.exit(1)

    print(f"\nDAG generated: {len(session.steps)} steps")
    print(f"  Session: {session.session_id}")
    print(f"  API cost so far: ${session.api_cost_usd:.4f}")
    print("\nStep manifest:")
    for s in session.steps:
        deps = f"  [deps: {s.depends_on}]" if s.depends_on else ""
        print(f"  [{s.id:03d}] {s.write_mode:<18} {s.target_file:<25} {s.instruction[:55]}{deps}")
    print(f"\nNext: python determinex_hive.py validate-scaffolding --session {args.session}")
    print(f"Then: python determinex_hive.py run-session --session {args.session}")
