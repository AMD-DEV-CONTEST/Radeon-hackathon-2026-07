#!/usr/bin/env python3
"""
determinex_providers.py -- the universal provider registry (bring in any AI)
=========================================================================
Determinex's amplifier defined ONE contract: generate(prompt, temperature) -> str.
This registry exposes EVERY model -- Claude, Codex/GPT, Gemini, DeepSeek, local
Ollama, and anything added later -- behind that single contract, so any of them
plugs straight into verified search / build-from-idea / repair / the router.
Bringing in a new AI is one entry; that is what makes Determinex a host, not a
wrapper.

The whole point: correctness is bounded by the ORACLE, not the model, so it does
not matter which provider you bolt on -- weak or frontier, local or cloud,
present or not-yet-invented. Use one, or ensemble several (the router escalates
tiny->frontier and the amplifier samples them for diversity).

    from determinex_providers import get_generator, available, register_provider
    gen = get_generator("claude")            # generate(prompt, temp) -> str
    build_from_idea(idea, gen)               # ...feeds straight into the engine

    # an addon registers itself:
    register_provider("myllm", lambda model: my_generate_fn, tier=2, models=["myllm/x"])

CLI
---
    python scripts/determinex_providers.py            # show what's available here
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse


class NetworkPolicyViolation(Exception):
    """Raised when an external network request is blocked by the active DETERMINEX_NETWORK_POLICY."""

    pass


GenerateFn = Callable[[str, float], str]
VALID_NETWORK_POLICIES = {"offline", "cloaked", "online"}


def _load_env_once() -> None:
    """Load repo .env into os.environ so provider keys are detected (idempotent)."""
    if os.environ.get("_DETERMINEX_ENV_LOADED"):
        return
    env = Path(__file__).resolve().parent.parent / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and v and not os.environ.get(k):
                os.environ[k] = v
    os.environ["_DETERMINEX_ENV_LOADED"] = "1"
    _apply_env_aliases()


# The same credential goes by different names in different places, and a
# mismatch is silent: the provider simply reports itself unavailable and the
# model is skipped, with nothing saying why.
#
# Found live 2026-07-28: `.env` carried HF_TOKEN (the name HuggingFace's own CLI
# and docs use), this module's huggingface provider checked
# HUGGINGFACE_API_KEY, and passport.rs stores its row as HUGGINGFACE_TOKEN.
# Three names, one token, and the configured token reached nothing.
#
# Canonical name first, accepted aliases after. Aliasing is one-directional and
# never overwrites a value that is already set, so an explicit
# HUGGINGFACE_API_KEY always wins over an inferred one.
_ENV_ALIASES: dict[str, tuple[str, ...]] = {
    "HUGGINGFACE_API_KEY": ("HF_TOKEN", "HUGGINGFACE_TOKEN", "HUGGING_FACE_HUB_TOKEN"),
    "OPENAI_API_KEY": ("OPENAI_KEY",),
    "ANTHROPIC_API_KEY": ("CLAUDE_API_KEY",),
    "GEMINI_API_KEY": ("GOOGLE_API_KEY", "GOOGLE_GENAI_API_KEY"),
    "GITHUB_TOKEN": ("GH_TOKEN",),
}


def _apply_env_aliases() -> None:
    """Fill a canonical key from any accepted alias. Idempotent."""
    for canonical, aliases in _ENV_ALIASES.items():
        if os.environ.get(canonical):
            continue
        for alias in aliases:
            value = os.environ.get(alias)
            if value:
                os.environ[canonical] = value
                break


_load_env_once()


@dataclass
class Provider:
    name: str
    tier: int  # 1 tiny/local ... 4 frontier
    env_key: str  # required API key env var ("" = local/none)
    default_model: str  # litellm-style model string
    aliases: tuple[str, ...] = ()
    factory: Callable[[str], GenerateFn] | None = None  # custom (addons); else litellm
    models: list[str] = field(default_factory=list)

    def available(self) -> bool:
        if self.factory is not None and not self.env_key:
            return True
        if not self.env_key:  # local
            return _ollama_up() if "ollama" in self.default_model else True
        return bool(os.environ.get(self.env_key))


# ---------------------------------------------------------------------------
# The universal LiteLLM-backed generator (handles claude/gpt/gemini/deepseek/ollama)
# ---------------------------------------------------------------------------
def _network_policy() -> str:
    policy = os.environ.get("DETERMINEX_NETWORK_POLICY", "cloaked").strip().lower()
    if policy not in VALID_NETWORK_POLICIES:
        raise NetworkPolicyViolation(
            f"Invalid DETERMINEX_NETWORK_POLICY={policy!r}; expected one of {sorted(VALID_NETWORK_POLICIES)}."
        )
    return policy


def _is_local_litellm_model(model: str) -> bool:
    """Is this model served locally?

    Delegates to budget_guard.is_local_model, the canonical rule shared with the cloud
    spend cap and the session pricer. This function's own list was missing `local/` and
    `determinex/`, and the bare `determinex-*` tags that hive/ctx_config.py assigns by
    default -- so genuinely local models were treated as cloud in two places that
    matter: the usage ledger billed them, and DETERMINEX_NETWORK_POLICY=offline
    REFUSED them as if they were about to leave the machine.

    Falls back to the original prefix list if budget_guard cannot be imported, because
    an offline-policy check must never fail open.
    """
    try:
        from budget_guard import is_local_model

        return is_local_model(model)
    except Exception:  # noqa: BLE001 — never let accounting/policy break on an import
        normalized = (model or "").strip().lower()
        return normalized.startswith(
            (
                "ollama/",
                "ollama_chat/",
                "hosted_vllm/",
                "text-completion-openai/",
                "determinex/",
                "local/",
                "determinex-",
            )
        )


_OLLAMA_CTX: dict[str, int] = {}


def _ollama_model_ctx(model: str, host: str = "http://localhost:11434") -> int:
    """The model's REAL trained context length, from /api/show. 0 if unknown."""
    tag = model.split("/", 1)[-1]
    if tag in _OLLAMA_CTX:
        return _OLLAMA_CTX[tag]
    import json as _json
    import urllib.request

    n = 0
    try:
        req = urllib.request.Request(
            f"{host}/api/show",
            data=_json.dumps({"name": tag}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            info = _json.loads(r.read()).get("model_info") or {}
        n = max(
            (
                int(v)
                for k, v in info.items()
                if k.endswith("context_length") and isinstance(v, int)
            ),
            default=0,
        )
    except Exception:
        n = 0
    _OLLAMA_CTX[tag] = n
    return n


def _ollama_ctx_kwargs(model: str, prompt: str) -> dict:
    """num_ctx big enough for this prompt, for Ollama-served models. {} for everyone else.

    Ollama defaults num_ctx to 2048 and, unlike vLLM, does NOT reject an over-long prompt --
    it silently drops the overflow, keeps the tail, and returns HTTP 200. Measured: a
    20,747-token prompt with a marker on line 1 came back prompt_eval_count=2050 and the
    model answered from the padding, because the actual instruction had been discarded.
    Every local repair prompt is ~3,800 tokens, so the model was being graded on a prompt
    whose task statement had been cut off, and the oracle recorded that as the model
    failing. Same class as the fenced-candidate bug: a harness defect wearing a model
    verdict, except silent -- there is no error to notice.

    The ROTATING CAP in determinex_pb_reimpl already solved this, but only inside that one
    module's private raw-HTTP lane, so every caller on the shared LiteLLM path kept the
    broken default. Deriving it here is what makes the fix reach them.
    """
    if not (model or "").split("/", 1)[0].startswith("ollama"):
        return {}
    mctx = _ollama_model_ctx(model)
    if mctx <= 0:
        return {}
    cap = int(os.environ.get("DETERMINEX_OLLAMA_CTX_CAP", "16384"))
    # chars//3 over-estimates tokens for code, which is the safe direction here.
    need = (len(prompt) // 3) + 1024
    return {"num_ctx": max(2048, min(mctx, cap, max(need, 8192)))}


def _assert_prompt_not_truncated(model: str, prompt: str, resp) -> None:
    """Refuse to return an answer the model formed from a clipped prompt.

    One-sided and deliberately slack: it fires only when the server reports evaluating
    fewer tokens than the prompt could possibly have compressed to. Even the most
    compressible text does not reach 8 chars/token, so a prompt below that bound was
    demonstrably cut. Silence here is indistinguishable from success, which is precisely
    how this went unnoticed -- an explicit failure is worth more than a plausible answer.
    """
    try:
        used = int(getattr(getattr(resp, "usage", None), "prompt_tokens", 0) or 0)
    except Exception:
        return
    floor = len(prompt) // 8
    if used and floor and used < floor:
        raise RuntimeError(
            f"PROMPT TRUNCATED by the server: {model} evaluated {used} prompt tokens for a "
            f"{len(prompt)}-char prompt (>= ~{floor} tokens). The task statement was cut off, "
            f"so any answer is about a prompt nobody wrote. Raise the context window "
            f"(DETERMINEX_OLLAMA_CTX_CAP, or OLLAMA_CONTEXT_LENGTH on the server) or shorten "
            f"the prompt. This is NOT a model-capability result."
        )


def _litellm_generator(model: str) -> GenerateFn:
    def _gen(prompt: str, temperature: float) -> str:
        policy = _network_policy()
        if policy == "offline" and not _is_local_litellm_model(model):
            raise NetworkPolicyViolation(
                f"Cannot use cloud model '{model}' because DETERMINEX_NETWORK_POLICY is set to 'offline'."
            )

        import litellm

        extra = _ollama_ctx_kwargs(model, prompt)
        resp = litellm.completion(
            # 8192: a full corrected compile.sh (the amplifier's task) runs 200-400 lines
            # >> 1024 tokens -> 1024 TRUNCATED every candidate to a malformed script that
            # fast-failed the eval (~0s). Code generation needs the headroom.
            model=model,
            temperature=float(temperature),
            messages=[{"role": "user", "content": prompt}],
            max_tokens=8192,
            **extra,
        )
        _ledger_append(model, resp)
        _assert_prompt_not_truncated(model, prompt, resp)
        return resp.choices[0].message.content or ""

    return _gen


# USD per 1M tokens (in, out) for cloud lanes with no BudgetGuard PRICING row.
#
# This SUPPLEMENTS budget_guard.PRICING, which is what the comment here always claimed
# and the code never did: the lookup below used to consult only this dict -- one entry --
# and fall back to a flat $1/$1 for everything else. So every model was billed at a
# fictional flat rate: free local calls appeared as spend in the "gas gauge", and a real
# claude-sonnet call (3.00/15.00) was under-reported by roughly 10x. A gauge that
# under-reports the expensive model is worse than no gauge.
#
# Canonical table first, this dict second, conservative default last.
_LEDGER_PRICING_DEFAULT = (1.0, 1.0)
_LEDGER_PRICING = {
    "huggingface/qwen/qwen2.5-coder-32b-instruct": (0.9, 0.9),
}


def _ledger_rate(model: str) -> tuple[float, float]:
    """(in, out) $/1M for the ledger. Local models are free and never reach here."""
    try:
        from budget_guard import price_per_1m

        rate = price_per_1m(model)
        if rate is not None:
            return rate
    except Exception:  # noqa: BLE001 — accounting must never break generation
        pass
    return _LEDGER_PRICING.get(model.lower(), _LEDGER_PRICING_DEFAULT)


def _ledger_append(model: str, resp) -> None:
    """Append real token usage to logs/api_ledger/providers.jsonl. NEVER raises —
    accounting must not break generation. Every cloud call through the litellm
    lane lands here so credit burn is observable (was previously untracked)."""
    try:
        import datetime as _dt
        import json as _json

        usage = getattr(resp, "usage", None)
        tin = int(getattr(usage, "prompt_tokens", 0) or 0)
        tout = int(getattr(usage, "completion_tokens", 0) or 0)
        # A locally-served model costs nothing. Billing it invented spend in the gauge
        # that the user then had to reconcile against a real credit balance.
        pin, pout = (0.0, 0.0) if _is_local_litellm_model(model) else _ledger_rate(model)
        ledger_dir = Path(__file__).resolve().parent.parent / "logs" / "api_ledger"
        ledger_dir.mkdir(parents=True, exist_ok=True)
        with open(ledger_dir / "providers.jsonl", "a", encoding="utf-8") as f:
            f.write(
                _json.dumps(
                    {
                        "ts": _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds"),
                        "model": model,
                        "tokens_in": tin,
                        "tokens_out": tout,
                        "est_usd": round(tin / 1e6 * pin + tout / 1e6 * pout, 6),
                    }
                )
                + "\n"
            )
    except Exception:
        pass


def _ollama_up(host: str = "http://localhost:11434") -> bool:
    import urllib.request

    try:
        urllib.request.urlopen(host + "/api/tags", timeout=2)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Registry -- the built-in providers + the extension point
# ---------------------------------------------------------------------------
_PROVIDERS: dict[str, Provider] = {}


def register_provider(
    name: str,
    *,
    tier: int = 3,
    env_key: str = "",
    default_model: str = "",
    aliases: tuple[str, ...] = (),
    factory: Callable[[str], GenerateFn] | None = None,
    models: list[str] | None = None,
) -> None:
    """Register an AI provider/addon. With no factory it routes through LiteLLM
    (model string decides the backend). With a factory it can be anything that
    yields generate(prompt, temperature) -> str -- a local agent, a remote API,
    an ensemble, a future model."""
    p = Provider(
        name=name,
        tier=tier,
        env_key=env_key,
        default_model=default_model or name,
        aliases=aliases,
        factory=factory,
        models=models or [],
    )
    for key in (name, *aliases):
        _PROVIDERS[key.lower()] = p


# Built-ins. Codex == OpenAI; "claude" == Anthropic; etc. All via LiteLLM.
register_provider(
    "claude",
    tier=4,
    env_key="ANTHROPIC_API_KEY",
    default_model="anthropic/claude-sonnet-4-6",
    aliases=("anthropic", "claude-code"),
)
register_provider(
    "codex",
    tier=4,
    env_key="OPENAI_API_KEY",
    default_model="openai/gpt-5.5-pro",
    aliases=("openai", "gpt"),
)
def _gemini_qualify(model: str) -> str:
    """Route a Google model to AI Studio (`gemini/`), never accidentally to Vertex.

    THE BUG (2026-08-03). The registry's DEFAULT is correctly `gemini/gemini-3-flash-preview`,
    but a caller-supplied name arrives bare -- `get_generator("google", "gemini-2.0-flash")` --
    and LiteLLM then resolves it to **vertex_ai**, which needs the Google Cloud SDK and
    Application Default Credentials. The user sees:

        ImportError: Google Cloud SDK not found. Install it with: pip install 'litellm[google]'

    about an API key that is perfectly valid, for a service that does not need the SDK at all.
    Two different diagnoses for one working credential.

    This is the same bare-name footgun as `_vllm_qualify`, in a second provider, found the
    same day -- which is why the fix is a named function here too rather than an inline
    prefix: the next provider that grows a caller-supplied model needs the same treatment.

    An explicit `vertex_ai/` prefix is honoured untouched, because choosing Vertex on purpose
    is legitimate; only bare and `gemini/`-prefixed names are normalised.
    """
    if not model:
        return model
    if model.startswith(("vertex_ai/", "vertex_ai_beta/")):
        return model
    name = model
    while name.startswith("gemini/"):
        name = name[len("gemini/"):]
    return f"gemini/{name}" if name else model


#: Google's 429 has two completely different causes and one of them is not a rate limit at
#: all. Mapping them apart is the difference between "wait and retry" (which never succeeds)
#: and "top up billing" (which fixes it in a minute).
_GEMINI_ERROR_HINTS = (
    ("prepayment credits are depleted",
     "Google AI Studio prepay credits are exhausted. This is billing, not a rate limit -- "
     "retrying will not help. Top up at https://ai.studio/projects (billing), or set "
     "DETERMINEX_ROLE_* to another provider; Determinex will keep working on whichever "
     "providers are funded."),
    ("RESOURCE_EXHAUSTED",
     "Google returned RESOURCE_EXHAUSTED. If this is quota-per-minute it will clear; if the "
     "body mentions credits it is billing. Check https://ai.studio/projects."),
    ("IneligibleTier",
     "The Gemini CLI's stored OAuth login is on a tier Google no longer serves. Determinex "
     "does not need the CLI -- it calls the AI Studio API directly with GEMINI_API_KEY."),
    ("Google Cloud SDK not found",
     "A Google model was routed to Vertex AI. Determinex normalises Google models to the AI "
     "Studio endpoint (see _gemini_qualify); an explicit vertex_ai/ prefix requires the SDK "
     "and Application Default Credentials."),
)


def explain_google_failure(err: object) -> str:
    """Turn a Google/LiteLLM exception into one sentence a human can act on."""
    text = str(err)
    for needle, hint in _GEMINI_ERROR_HINTS:
        if needle.lower() in text.lower():
            return hint
    return ""


def _gemini_factory(model: str) -> GenerateFn:
    """Google via AI Studio, with the real cause surfaced when it refuses."""
    qualified = _gemini_qualify(model)

    def _gen(prompt: str, temperature: float) -> str:
        import litellm

        try:
            resp = litellm.completion(
                model=qualified,
                temperature=float(temperature),
                messages=[{"role": "user", "content": prompt}],
                api_key=os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"),
            )
        except Exception as exc:
            hint = explain_google_failure(exc)
            # Raise, never return "" -- an empty string from a provider is indistinguishable
            # from a model with nothing to say, which is how a dead provider once looked like
            # a weak one for an entire evaluation.
            raise RuntimeError(f"{type(exc).__name__} from {qualified}. {hint}".strip()) from exc
        return (resp.choices[0].message.content or "") if resp.choices else ""

    return _gen


register_provider(
    "gemini",
    tier=4,
    env_key="GEMINI_API_KEY",
    default_model="gemini/gemini-3-flash-preview",
    aliases=("google",),
    factory=_gemini_factory,
)
register_provider(
    "deepseek", tier=3, env_key="DEEPSEEK_API_KEY", default_model="deepseek/deepseek-chat"
)
register_provider(
    "groq", tier=3, env_key="GROQ_API_KEY", default_model="groq/llama-3.3-70b-versatile"
)
register_provider(
    "huggingface",
    tier=3,
    env_key="HUGGINGFACE_API_KEY",
    default_model="huggingface/Qwen/Qwen2.5-Coder-32B-Instruct",
    aliases=("hf",),
)
# ── Added 2026-07-31 ────────────────────────────────────────────────────────────────────────────
# Ryan: "kimi, hf, vars ai, etc etc etc should all be configured in this". hf was already here
# (aliased below); these were not, and their absence was not a capability gap -- every one of them
# routes through the same LiteLLM call the existing rows use, so what was missing was the row. An
# unregistered provider cannot be selected by name anywhere in the system: not as a hive role, not as
# a chat participant's model, not by the amplifier's router.
#
# No key is written by this. `env_key` names the variable the operator sets; a provider whose key is
# absent stays unavailable and says which variable to set, rather than failing at call time with a
# provider error that does not name the fix.
register_provider(
    "moonshot",
    tier=3,
    env_key="MOONSHOT_API_KEY",
    default_model="moonshot/kimi-k2-0711-preview",
    aliases=("kimi", "moonshot-ai"),
)
# Vertex is Google's OTHER surface, and the distinction is load-bearing rather than pedantic: the
# `gemini` row above uses an AI Studio key (GEMINI_API_KEY), while Vertex authenticates with GCP
# service-account credentials and a project/location. Google ended Code Assist for individual
# accounts on 2026-07-31 -- measured on this machine, gemini-cli refused with IneligibleTierError --
# so having both surfaces registered separately is what lets a Google model be reached at all when
# one of the two paths is closed to an account.
register_provider(
    "vertex_ai",
    tier=4,
    env_key="GOOGLE_APPLICATION_CREDENTIALS",
    default_model="vertex_ai/gemini-2.5-pro",
    aliases=("vertex", "vertexai", "gcp"),
)
register_provider(
    "xai", tier=3, env_key="XAI_API_KEY", default_model="xai/grok-4", aliases=("grok",)
)
register_provider(
    "mistral",
    tier=3,
    env_key="MISTRAL_API_KEY",
    default_model="mistral/codestral-latest",
    aliases=("codestral",),
)
register_provider(
    "together_ai",
    tier=3,
    env_key="TOGETHERAI_API_KEY",
    default_model="together_ai/Qwen/Qwen2.5-Coder-32B-Instruct",
    aliases=("together",),
)
register_provider(
    "cerebras", tier=3, env_key="CEREBRAS_API_KEY", default_model="cerebras/qwen-3-coder-480b"
)
# OpenRouter had no row despite OPENROUTER_API_KEY being the key the SWE-bench ablation's DeepSeek
# builder runs on (see CLAUDE.md's config table). A bare `openrouter/...` model string always worked
# because the prefix passes through untouched, but with no registered row the NAME resolved to
# nothing -- so the one provider that fronts hundreds of models could not be picked by name, only by
# knowing a full model path.
register_provider(
    "openrouter",
    tier=3,
    env_key="OPENROUTER_API_KEY",
    default_model="openrouter/deepseek/deepseek-chat",
    aliases=("or",),
)
register_provider(
    "fireworks_ai",
    tier=3,
    env_key="FIREWORKS_AI_API_KEY",
    default_model="fireworks_ai/accounts/fireworks/models/qwen3-coder-480b-a35b-instruct",
    aliases=("fireworks",),
)

register_provider(
    "local",
    tier=1,
    env_key="",
    default_model="ollama/determinex-coder-base-tiny:latest",
    aliases=("ollama", "tiny"),
)
register_provider(
    "bonsai",
    tier=1,
    env_key="",
    default_model="ollama/bonsai-27b",
    aliases=("bonsai-27b", "prism-ml/bonsai"),
)

# ── vLLM provider (1C — audit 2026-07-19) ────────────────────────────────────
# vLLM serves an OpenAI-compatible API. For the PB churn loop the verified-search
# amplifier benefits from vLLM's continuous batching: K=8 requests served in
# parallel instead of sequentially, cutting per-tool wall-clock time ~6x.
#
# Setup (Linux; CUDA or ROCm -- AMD Radeon is verified, see below):
#   pip install vllm>=0.5.0
#   vllm serve Qwen/Qwen2.5-Coder-32B-Instruct --port 8000 --dtype bfloat16
#
# Then set in .env:
#   DETERMINEX_VLLM_BASE_URL=http://localhost:8000
#   DETERMINEX_VLLM_MODEL=Qwen/Qwen2.5-Coder-32B-Instruct
#
# Remote/hosted vLLM (e.g. an AMD Radeon Cloud instance) works through this same
# provider -- set DETERMINEX_VLLM_BASE_URL to the instance's /v1 URL and supply
# DETERMINEX_VLLM_API_KEY (or AMD_API_KEY). Measured on a Radeon GPU 2026-07-31:
# 30.0 tok/s single-stream vs 166.9 tok/s aggregate at K=6 concurrent -- i.e. K=6
# verified-search sampling cost 1.08x the wall clock of a single sample.
#
# _is_local_litellm_model() already recognizes "hosted_vllm/" prefix as local.
# A REMOTE vLLM (e.g. an AMD Radeon Cloud instance) is the same protocol but adds
# two things a localhost server does not have: a bearer token, and a base URL that
# already ends in /v1. Both are handled here so the AMD path needs no separate
# provider. AMD_BASE_URL/AMD_API_KEY are honored as a fallback so a Radeon Cloud
# instance's credentials live in exactly one place in .env rather than two.
_VLLM_BASE_URL = (
    os.environ.get("DETERMINEX_VLLM_BASE_URL")
    or os.environ.get("AMD_BASE_URL")
    or "http://localhost:8000"
).rstrip("/")
_VLLM_API_KEY = os.environ.get("DETERMINEX_VLLM_API_KEY") or os.environ.get("AMD_API_KEY") or ""
_VLLM_DEFAULT_MODEL = os.environ.get(
    "DETERMINEX_VLLM_MODEL", "hosted_vllm/Qwen/Qwen2.5-Coder-32B-Instruct"
)
# Prefix with hosted_vllm/ if the user gave a plain HF model name
if not _VLLM_DEFAULT_MODEL.startswith("hosted_vllm/"):
    _VLLM_DEFAULT_MODEL = f"hosted_vllm/{_VLLM_DEFAULT_MODEL}"


_VLLM_MODEL_EXPLICIT = bool(os.environ.get("DETERMINEX_VLLM_MODEL"))
_VLLM_DISCOVERED: list[str] = []  # one-element cache; [] = not yet probed


_VLLM_MAXLEN: list[int] = []  # one-element cache; [] = not yet probed


def _vllm_max_tokens(default: int = 8192, prompt: str = "") -> int:
    """Clamp max_tokens to what the server will actually accept.

    vLLM rejects outright: "max_tokens=8192 cannot be greater than
    max_model_len=max_total_tokens=4096". The provider hard-coded 8192, so EVERY request
    failed against any server started with a smaller context -- and lowering max_model_len
    is exactly what you do to raise concurrency (94,784 KV tokens / 4,096 = 23x vs
    /32,768 = 2.88x). So tuning the server for throughput broke generation entirely, and
    the failure surfaced as an opaque LiteLLM error rather than a config mismatch.

    /v1/models reports max_model_len, so ask instead of assuming. A reserve is kept for the
    prompt, which shares the same budget.
    """
    if not _VLLM_MAXLEN:
        import json as _json
        import urllib.request

        headers = {"Authorization": f"Bearer {_VLLM_API_KEY}"} if _VLLM_API_KEY else {}
        n = 0
        try:
            req = urllib.request.Request(f"{_VLLM_BASE_URL}/models", headers=headers)
            with urllib.request.urlopen(req, timeout=10) as r:
                n = int((_json.loads(r.read())["data"][0] or {}).get("max_model_len") or 0)
        except Exception:
            n = 0
        _VLLM_MAXLEN.append(n)
    limit = _VLLM_MAXLEN[0]
    if limit <= 0:
        return default
    # The reserve must cover the ACTUAL prompt, and a character heuristic cannot deliver
    # that: a fixed 1024 produced "You passed 1025 input tokens and requested 3072 output
    # tokens ... maximum context length is 4096", and replacing it with len//3+64 produced
    # "passed 3841 ... requested 256 ... is 4096" -- off by one AGAIN, on a real repair, so
    # all six samples died and the run read as the model failing. Any divisor is a guess
    # about someone else's tokenizer. Ask the server for the true count; only estimate when
    # it does not offer /tokenize.
    n_prompt = _vllm_prompt_tokens(prompt) if prompt else 0
    if n_prompt <= 0:
        n_prompt = (len(prompt) // 3) + 64 if prompt else 1024
        n_prompt += 128  # unverified estimate -> keep the old safety margin
    return max(64, min(default, limit - n_prompt - 1))


_VLLM_TOKENIZE_OK: list[bool] = []  # one-element cache; [] = not yet probed


def _vllm_prompt_tokens(prompt: str) -> int:
    """Exact prompt length, from the server's own tokenizer. 0 if it cannot say.

    vLLM serves /tokenize at the ROOT, not under /v1, so the OpenAI-style base URL has to
    have its suffix stripped. One failed probe disables it for the process -- a server
    without the endpoint must not pay a round trip per sample.
    """
    if _VLLM_TOKENIZE_OK and not _VLLM_TOKENIZE_OK[0]:
        return 0
    import json as _json
    import urllib.request

    root = _VLLM_BASE_URL.rstrip("/")
    if root.endswith("/v1"):
        root = root[: -len("/v1")]
    headers = {"Content-Type": "application/json"}
    if _VLLM_API_KEY:
        headers["Authorization"] = f"Bearer {_VLLM_API_KEY}"
    served = (
        _VLLM_DISCOVERED[0] if (_VLLM_DISCOVERED and _VLLM_DISCOVERED[0]) else _VLLM_DEFAULT_MODEL
    )
    body = _json.dumps(
        {
            "model": served.split("/", 1)[-1] if served.startswith("hosted_vllm/") else served,
            "prompt": prompt,
        }
    ).encode("utf-8")
    try:
        req = urllib.request.Request(f"{root}/tokenize", data=body, headers=headers)
        with urllib.request.urlopen(req, timeout=20) as r:
            n = int(_json.loads(r.read()).get("count") or 0)
    except Exception:
        n = 0
    if not _VLLM_TOKENIZE_OK:
        _VLLM_TOKENIZE_OK.append(n > 0)
    return n


_CTX_PASSED = re.compile(r"passed\s+(\d+)\s+input tokens", re.I)
_CTX_LIMIT = re.compile(r"maximum context length is\s+(\d+)", re.I)


def _vllm_retry_budget(err: str) -> int:
    """Output budget the server itself says is left, parsed from its rejection. 0 if none.

    Belt and braces behind /tokenize: a server that does not expose the endpoint, or a
    chat template that adds tokens the raw /tokenize call does not see, still lands here.
    The server names both numbers in the error, so the second attempt does not have to
    guess -- it uses the server's own arithmetic.
    """
    m_p, m_l = _CTX_PASSED.search(err), _CTX_LIMIT.search(err)
    if not (m_p and m_l):
        return 0
    return max(0, int(m_l.group(1)) - int(m_p.group(1)) - 1)


def _vllm_discover_model() -> str:
    """Ask the server which model it actually serves.

    Without this, pointing DETERMINEX_VLLM_BASE_URL (or AMD_BASE_URL) at a working
    server still 404s whenever that server happens not to be serving the hard-coded
    default -- a hosted instance serves exactly ONE model, chosen at launch, and the
    operator has no reason to expect a client-side constant to match it. Measured
    2026-07-31: a Radeon Cloud instance serving Qwen2.5-Coder-7B-Instruct resolved to
    the 32B default and would have failed every call.

    Only consulted when the operator did NOT pin DETERMINEX_VLLM_MODEL; an explicit
    pin always wins. Cached, so this costs one request per process.
    """
    if _VLLM_DISCOVERED:
        return _VLLM_DISCOVERED[0]
    import json as _json
    import urllib.request

    headers = {"Authorization": f"Bearer {_VLLM_API_KEY}"} if _VLLM_API_KEY else {}
    name = ""
    try:
        req = urllib.request.Request(f"{_VLLM_BASE_URL}/models", headers=headers)
        with urllib.request.urlopen(req, timeout=10) as r:
            data = _json.loads(r.read()).get("data") or []
        if data:
            name = f"hosted_vllm/{data[0]['id']}"
    except Exception:
        name = ""
    _VLLM_DISCOVERED.append(name)
    return name


def _vllm_qualify(model: str) -> str:
    """Ensure exactly one `hosted_vllm/` prefix on a vLLM model name.

    THE BUG (measured 2026-08-02, live AMD Radeon MI GPU). The `hosted_vllm/` prefix was
    applied in exactly two places -- to `_VLLM_DEFAULT_MODEL` at import, and inside
    `_vllm_discover_model()`. A caller supplying the model EXPLICITLY got neither:

        get_generator("vllm", "Qwen/Qwen2.5-Coder-7B-Instruct")
        -> litellm.BadRequestError: LLM Provider NOT provided ... you passed
           model=Qwen/Qwen2.5-Coder-7B-Instruct

    on every single call. That is the same bare-name footgun `_qualify_local_model` was
    written for, and this file already documents three prior recurrences -- but its rule is
    `if "/" in model: leave it alone`, and EVERY Hugging Face id contains a slash
    (`Qwen/Qwen2.5-Coder-7B-Instruct`). The existing guard structurally cannot catch this
    case, so it is a fourth occurrence rather than a regression of the third.

    Why it survived: the default path prefixes itself, and `/v1/models` is what a UI or a
    router reads to offer a choice -- and it returns BARE ids. So Determinex worked when it
    picked the model and failed when the USER did, on the AMD path specifically.

    Unconditional re-prefixing is right here, not a guess: for this provider the model name
    is by definition whatever the vLLM endpoint serves, so `hosted_vllm/` is the only
    correct LiteLLM route. A caller passing some other provider's prefix has made a category
    error, and the endpoint rejecting `hosted_vllm/openai/gpt-4` by name is a better outcome
    than silently routing away from the endpoint they asked for.
    """
    if not model:
        return model
    name = model
    while name.startswith("hosted_vllm/"):
        name = name[len("hosted_vllm/"):]
    return f"hosted_vllm/{name}" if name else model


def _vllm_factory(model: str) -> GenerateFn:
    """Factory for vLLM provider: routes through LiteLLM's hosted_vllm backend."""
    if model == _VLLM_DEFAULT_MODEL and not _VLLM_MODEL_EXPLICIT:
        model = _vllm_discover_model() or model
    model = _vllm_qualify(model)

    def _gen(prompt: str, temperature: float) -> str:
        import litellm

        kwargs = {}
        if _VLLM_API_KEY:
            kwargs["api_key"] = _VLLM_API_KEY
        # LiteLLM's default request timeout kills long generations from a big model over a
        # remote tunnel: a 32B rewriting a whole module took >60s and every sample past the
        # first died as "Timeout", which reads as the model failing rather than the client
        # giving up. Generous by default, overridable.
        kwargs["timeout"] = float(os.environ.get("DETERMINEX_VLLM_TIMEOUT", "600"))

        def _call(budget: int):
            return litellm.completion(
                model=model,
                temperature=float(temperature),
                messages=[{"role": "user", "content": prompt}],
                max_tokens=budget,
                api_base=_VLLM_BASE_URL,
                **kwargs,
            )

        try:
            resp = _call(_vllm_max_tokens(prompt=prompt))
        except Exception as exc:
            # The server rejects prompt+output over its context and names both numbers.
            # Failing here is indistinguishable from the model being unable to answer, and
            # that is exactly how it presented: six identical samples, all "GENERATION
            # ERROR", on a repair the model was never actually asked to attempt. The chat
            # template adds tokens /tokenize does not see, so an exact prompt count is
            # still not a guarantee -- take the server's own arithmetic and retry once.
            budget = _vllm_retry_budget(str(exc))
            if budget < 16:
                raise
            resp = _call(budget)
        _ledger_append(model, resp)
        return resp.choices[0].message.content or ""

    return _gen


def _vllm_available() -> bool:
    """vLLM is available if its OpenAI-compatible API answers.

    /models is probed before /health because it is the one endpoint both a bare
    localhost server and a hosted instance expose at the documented base URL. A
    hosted base URL already ends in /v1, where /health does not exist -- probing
    only /health would report a perfectly working remote endpoint as unavailable.
    """
    import urllib.request

    headers = {"Authorization": f"Bearer {_VLLM_API_KEY}"} if _VLLM_API_KEY else {}
    for path in ("/models", "/health"):
        try:
            req = urllib.request.Request(f"{_VLLM_BASE_URL}{path}", headers=headers)
            with urllib.request.urlopen(req, timeout=5):
                return True
        except Exception:
            continue
    return False


register_provider(
    "vllm",
    tier=1,
    env_key="",  # No API key — local endpoint
    default_model=_VLLM_DEFAULT_MODEL,
    aliases=("vllm-local",),
    factory=_vllm_factory,
)


# ---------------------------------------------------------------------------
# AMD Radeon Token Factory -- models served on AMD GPUs, free tier
# ---------------------------------------------------------------------------
# CLAUDE.md and the hackathon submission both recorded this endpoint as "wired and
# labelled unverified -- its portal needs a China-registered account". That was true
# when written and is NOT true now: verified live 2026-08-02 from an ordinary account,
# GET /models returned 200 with five models served on AMD hardware, and MiniCPM5-1B
# (described by the portal as running on four Radeon PRO W7900 workers) completed a
# 200-token generation in 2.0 s.
#
# The free tier is budget- and rate-limited rather than KV-cache-limited, which makes it
# a third distinct shape for determinex_calibrate.py: the ceiling here is requests per
# minute, not GPU memory. Measured budget at time of writing: $10/day, 30 RPM.
_AMD_TF_BASE = os.environ.get(
    "AMD_TOKEN_FACTORY_BASE", "https://radeon.anruicloud.com/api/v1"
)
_AMD_TF_DEFAULT_MODEL = os.environ.get("AMD_TOKEN_FACTORY_MODEL", "MiniCPM5-1B")

register_provider(
    "amd-token-factory",
    tier=2,
    env_key="AMD_TOKEN_FACTORY_KEY",
    default_model=_AMD_TF_DEFAULT_MODEL,
    aliases=("amd", "radeon", "token-factory"),
    factory=lambda m: _openai_compatible_factory(
        m, _AMD_TF_BASE, "AMD_TOKEN_FACTORY_KEY"
    ),
)


# ---------------------------------------------------------------------------
# User-registered models -- "compatible with EVERYTHING"
# ---------------------------------------------------------------------------
# Ryan, live: "users should be able to add future llms that dont have access at
# the moment, we should make sure we are compatable with EVERYTHING."
#
# The IDE writes user-added models into `models_registry.json` in the Tauri app
# data directory (see frontend/src-tauri/src/registry.rs). Nothing read that file
# on this side, so a model added in the UI was registered into a catalogue the
# engine never consulted -- it appeared in a dropdown and could not be used.
#
# An entry carrying `base_url` is routed as `openai/<id>` with that api_base.
# That covers effectively every current and future provider without a code change,
# because vendors and local servers alike (vLLM, llama.cpp, LM Studio, Ollama,
# OpenRouter, Together, Fireworks, and whatever launches next month) all expose an
# OpenAI-compatible /v1 surface. An entry without one is assumed to name a model a
# built-in provider already understands and is routed by LiteLLM on its id alone.
#
# `api_key_env` holds the NAME of an environment variable, never a secret: this
# file is plain JSON on disk, and a key written into it would end up in every
# backup of the app data directory.

_CUSTOM_REGISTRY_ENV = "DETERMINEX_MODELS_REGISTRY"


def _app_data_registry_paths() -> list[Path]:
    """Where models_registry.json can live, most explicit first."""
    paths: list[Path] = []
    override = os.environ.get(_CUSTOM_REGISTRY_ENV, "").strip()
    if override:
        paths.append(Path(override))
    # Tauri's app data dir. The identifier is set in tauri.conf.json; on Windows
    # this is %APPDATA%\<identifier>, on macOS ~/Library/Application Support, and
    # on Linux ~/.local/share.
    ident = "com.determinex.ide"
    appdata = os.environ.get("APPDATA")
    if appdata:
        paths.append(Path(appdata) / ident / "models_registry.json")
    home = Path.home()
    paths.append(home / "Library" / "Application Support" / ident / "models_registry.json")
    paths.append(home / ".local" / "share" / ident / "models_registry.json")
    return paths


def _custom_model_entries() -> list[dict]:
    for path in _app_data_registry_paths():
        try:
            if not path.is_file():
                continue
            data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, json.JSONDecodeError):
            # A malformed or unreadable registry must not take the engine down;
            # the built-in providers still work.
            continue
        out: list[dict] = []
        for tier in data.get("tiers") or []:
            for model in tier.get("models") or []:
                if isinstance(model, dict) and model.get("id"):
                    out.append(model)
        if out:
            return out
    return []


#: Reasoning models hide their output in two different places, and a consumer that knows
#: about neither records a MODEL failure for a HARNESS defect -- the same shape as the
#: fence-stripping bug this repository already fixed once. Both were observed live on
#: 2026-08-02 against AMD's Radeon Token Factory:
#:
#:   Qwen3.6-35B-A3B   separate `reasoning` field, `content` null. Handled by asking for
#:                     chat_template_kwargs.enable_thinking=false, and by raising a named
#:                     error rather than returning "" when that is ignored.
#:   MiniCPM5-1B       `<think> ... </think>` INLINE in content. Handled here.
#:
#: Stripping is deliberately conservative: only a well-formed, closed block at the start is
#: removed. A response that merely mentions the word "think", or an unterminated tag from a
#: truncated completion, is left exactly as it arrived -- silently deleting part of a model's
#: answer would be a worse bug than the one being fixed.
_THINK_BLOCK = re.compile(r"\A\s*<(think|thinking|reasoning)>.*?</\1>\s*", re.DOTALL | re.IGNORECASE)


def _strip_reasoning_tags(text: str) -> str:
    stripped = _THINK_BLOCK.sub("", text, count=1)
    return stripped if stripped.strip() else text


def _openai_compatible_factory(model_id: str, base_url: str, api_key_env: str) -> GenerateFn:
    """Generate against any OpenAI-compatible endpoint."""

    def _gen(prompt: str, temperature: float) -> str:
        policy = _network_policy()
        # A user-supplied endpoint may well be a local server, which offline mode
        # must still allow -- but anything not demonstrably loopback is treated as
        # network egress and refused, rather than assumed safe.
        if policy == "offline" and not _is_loopback(base_url):
            raise NetworkPolicyViolation(
                f"Cannot reach custom endpoint '{base_url}' because "
                f"DETERMINEX_NETWORK_POLICY is set to 'offline'."
            )
        import litellm

        kwargs = {
            "model": f"openai/{model_id}",
            "temperature": float(temperature),
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 8192,
            "api_base": base_url,
            # REASONING MODELS RETURN NOTHING WITHOUT THIS (found live 2026-08-02 against
            # AMD's Radeon Token Factory). Qwen3.6-35B-A3B spends its whole completion budget
            # on a separate `reasoning` field and returns `content: null`: measured 199 of 200
            # reasoning tokens at max_tokens=200, and 1110 of 1200 at max_tokens=1200 -- more
            # budget does not help, it just buys more thinking. `enable_thinking: false` gives
            # real code in 2.3s with reasoning_tokens=0.
            #
            # Sent via extra_body because it is a vLLM chat-template extension, not an OpenAI
            # parameter; endpoints that do not know it ignore it, and the one that rejects it
            # is retried without below.
            "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
        }
        key = os.environ.get(api_key_env, "") if api_key_env else ""
        # Many local servers require no key but LiteLLM's openai backend still
        # wants the parameter present, so send a placeholder rather than failing.
        kwargs["api_key"] = key or "not-needed"
        try:
            resp = litellm.completion(**kwargs)
        except Exception:
            kwargs.pop("extra_body", None)
            resp = litellm.completion(**kwargs)
        _ledger_append(f"openai/{model_id}", resp)

        msg = resp.choices[0].message
        text = getattr(msg, "content", None) or ""
        if text.strip():
            return _strip_reasoning_tags(text)
        # Empty content is NOT an empty answer. Returning "" here made a reasoning model that
        # had spent its entire budget thinking look like a model that had nothing to say --
        # a verdict about the MODEL for a defect in the HARNESS, which is the same failure
        # this project already fixed once in its fence-stripping path. Say what happened.
        reasoning = getattr(msg, "reasoning", None) or getattr(msg, "reasoning_content", None) or ""
        rtok = 0
        details = getattr(getattr(resp, "usage", None), "completion_tokens_details", None)
        if details is not None:
            getter = getattr(details, "get", None)
            rtok = (getter("reasoning_tokens", 0) if callable(getter)
                    else getattr(details, "reasoning_tokens", 0)) or 0
        if reasoning or rtok:
            raise RuntimeError(
                f"{model_id} returned no content: the completion budget went to reasoning "
                f"({rtok} reasoning tokens). This endpoint ignored "
                f"chat_template_kwargs.enable_thinking=false; raise max_tokens or route this "
                f"model through a provider that separates reasoning from output."
            )
        return text

    return _gen


def _is_loopback(url: str) -> bool:
    host = urlparse(url).hostname or ""
    return host in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def register_custom_providers() -> list[str]:
    """Register every user-added model from the IDE's registry. Returns the names
    registered, so a caller (and the test suite) can assert it actually happened."""
    registered: list[str] = []
    for entry in _custom_model_entries():
        model_id = str(entry["id"]).strip()
        if not model_id:
            continue
        base_url = str(entry.get("base_url") or "").strip()
        api_key_env = str(entry.get("api_key_env") or "").strip()
        # Name it by id so a user picks the same string they typed in.
        name = model_id.lower()
        if base_url:
            register_provider(
                name,
                tier=int(entry.get("tier") or 3),
                env_key="",  # availability is the endpoint's, not a key's
                default_model=model_id,
                factory=lambda m, _u=base_url, _k=api_key_env: _openai_compatible_factory(
                    m, _u, _k
                ),
            )
        else:
            register_provider(name, tier=3, env_key=api_key_env, default_model=model_id)
        registered.append(name)
    return registered


# Registered at import so every entry point (hive, amplifier, autofix, the IDE
# bridge) sees user-added models without each having to remember to ask.
try:
    register_custom_providers()
except Exception as exc:  # pragma: no cover - defensive
    print(f"[providers] could not load user-added models: {exc}", file=sys.stderr)


#: Providers that are served by a local Ollama, so a model name with no provider prefix can
#: only mean an Ollama tag. Kept as a set rather than a `name == "local"` test so an addon that
#: registers another Ollama-backed provider gets the same treatment by adding itself here.
_OLLAMA_BACKED_PROVIDERS = frozenset({"local"})


def _qualify_local_model(provider: Provider, model: str) -> str:
    """Give a bare Ollama tag the `ollama/` prefix the LiteLLM lane requires.

    THE BUG (measured 2026-07-31). `--provider local --model determinex-engineer-v11-dsl:latest`
    -- the tag exactly as `ollama list` prints it -- reached `_litellm_generator` unprefixed, and
    LiteLLM raised `BadRequestError: LLM Provider NOT provided` on EVERY call. Downstream that
    surfaced as `build_from_idea` reporting "not solved, 12 samples", i.e. a verdict on a model
    that was never once reached.

    This is the third place the bare-tag footgun has bitten; `budget.is_local_model` and
    `api_client._resolve_model` both carry comments about it.

    NOT the same as guessing locality from a name, which `budget.is_local_model` deliberately
    refuses to do (Bedrock ships `anthropic.claude-v2:1` -- colon, no slash -- and treating that
    as local would price a real cloud call at $0). Here the caller has ALREADY declared
    `provider="local"`. Honouring that declaration is not inference.

    A name that already carries a prefix is left alone, so `ollama/x`, `openrouter/y` and a
    deliberate override all still pass through untouched.
    """
    if provider.name not in _OLLAMA_BACKED_PROVIDERS:
        return model
    if not model or "/" in model:
        return model
    return f"ollama/{model}"


def get_generator(provider: str, model: str | None = None) -> GenerateFn:
    """Return the universal generate(prompt, temperature) for a provider."""
    p = _PROVIDERS.get(provider.lower())
    if p is None:
        raise KeyError(f"unknown provider '{provider}'. Known: {sorted(set(_PROVIDERS))}")
    m = model or p.default_model
    m = _qualify_local_model(p, m)
    if p.factory is not None:
        return p.factory(m)
    return _litellm_generator(m)


def available() -> dict[str, bool]:
    seen = {}
    for p in _PROVIDERS.values():
        seen[p.name] = p.available()
    return dict(sorted(seen.items()))


def get_rotating_generator(names: list[str] | None = None, persist: bool = True):
    """A generate(prompt, temperature) that auto-throttles per model and ROTATES
    across providers on a 429 -- so a rate limit on one AI transparently falls over
    to the next. Defaults to all available providers. Returns the universal contract."""
    from determinex_ratelimit import AdaptiveLimiter, RotatingGenerator

    names = names or [n for n, ok in available().items() if ok]
    if not names:
        raise RuntimeError("no providers available for a rotating generator")
    providers = [(n, get_generator(n)) for n in names]
    pp = (
        (Path(__file__).resolve().parent.parent / ".determinex_ratelimits.json")
        if persist
        else None
    )
    return RotatingGenerator(providers, limiter=AdaptiveLimiter(persist_path=pp)).generate


def to_router_entries(only_available: bool = True):
    """Build determinex_router.ModelEntry list from the registry -- so the router can
    escalate across providers (e.g. local tiny -> Claude -> a frontier fallback)."""
    sys.path.insert(0, os.path.dirname(__file__))
    from determinex_router import ModelEntry

    entries, seen = [], set()
    for p in _PROVIDERS.values():
        if p.name in seen:
            continue
        seen.add(p.name)
        if only_available and not p.available():
            continue
        entries.append(
            ModelEntry(
                name=p.name,
                tier=p.tier,
                cost=float(p.tier),
                generate=get_generator(p.name),
                capability_hint=p.default_model,
            )
        )
    return entries


def registry_json() -> list[dict]:
    """The provider roster as data, so the IDE can show and assign it.

    There was only the human-readable report below, so the seventeen providers this module knows
    about were invisible to the app: nothing could list them, so nothing could offer them for a hive
    role or a chat participant's model, and adding a provider row changed nothing a user could see.
    Each row names the env var it needs, because "unavailable" without "set MOONSHOT_API_KEY" is the
    same unhelpful shape as a bare `logged_in: false`.
    """
    out: list[dict] = []
    for name, ok in available().items():
        p = _PROVIDERS[name]
        out.append(
            {
                "name": name,
                "tier": p.tier,
                "available": ok,
                "env_key": p.env_key,
                "default_model": p.default_model,
                "aliases": list(p.aliases),
                "needs": "" if ok else (p.env_key or "a reachable local endpoint"),
            }
        )
    return out


def main() -> int:
    if "--json" in sys.argv:
        import json as _json

        print(_json.dumps(registry_json()))
        return 0
    print("=== Determinex providers (universal generate contract) ===")
    for name, ok in available().items():
        p = _PROVIDERS[name]
        mark = "READY" if ok else "----"
        print(
            f"  {mark}  {name:10} tier {p.tier}  {p.default_model}"
            + ("" if ok else f"   (needs {p.env_key or 'ollama'})")
        )
    rdy = [n for n, ok in available().items() if ok]
    print(f"\n  {len(rdy)} provider(s) ready here: {rdy}")
    print("  Any of them plugs into build-from-idea / repair / router unchanged.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
