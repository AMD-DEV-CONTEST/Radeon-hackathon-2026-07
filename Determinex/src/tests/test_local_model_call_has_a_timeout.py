"""A local model call must carry a timeout, or the build session hangs forever.

WHY THIS EXISTS
---------------
Found 2026-07-30 by watching a `run-session` sit on step 2 for 30+ minutes: **0% CPU** and two
ESTABLISHED sockets to `127.0.0.1:11434`, having written its builder output and then stopped. It was
blocked on an Ollama read that never returned, with nothing to interrupt it.

`api_client.ApiRateLimiter.call` has an OOM guard whose comment says exactly what must not happen --
*"Local Ollama calls can stall forever ... Without a timeout the step hangs forever."* But the
condition was:

    _model = kwargs.get("model", "")
    if isinstance(_model, str) and _model.startswith("ollama/"):

and `kwargs["model"]` holds the **configured alias**, not the resolved provider name.
`builder_model` comes straight from `model_assignments["builder"]`, i.e. `determinex/engineer`, which
does not start with `ollama/`. So no timeout reached the builder, monitor, oracle or architect calls
and the documented failure was the actual behaviour.

THE SAME BUG, THREE TIMES
-------------------------
`budget.is_local_model` exists *because* the pricing path had this identical defect, fixed
2026-07-29: the check was `startswith("ollama/") or startswith("determinex/")`, and the default role
assignments are BARE tags (`determinex-engineer-v11-dsl` starts with `determinex-`, not
`determinex/`), so every local call was billed at the cloud fallback rate and eventually tripped
`budget_exhausted` on a session that had never left the machine. That docstring even notes the same
defect remained in api_client.

So the rule this file enforces is not "check these prefixes" but **"use the one canonical locality
helper"** -- a fourth hand-rolled prefix test is how this recurs.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT, ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from hive.budget import is_local_model  # noqa: E402

API_CLIENT = ROOT / "scripts" / "hive" / "api_client.py"


def test_the_timeout_guard_uses_the_canonical_locality_helper():
    """THE regression. A bare `startswith("ollama/")` here cannot see an alias."""
    src = API_CLIENT.read_text(encoding="utf-8")
    guard_at = src.index("OOM guard")
    window = src[guard_at : guard_at + 2200]
    assert "is_local_model(" in window, (
        "the OOM timeout guard no longer uses budget.is_local_model, so it cannot recognise a "
        "configured alias like 'determinex/engineer' and local calls will hang with no timeout"
    )
    # A hand-rolled prefix test in the guard is what broke it; a comment quoting the old code is fine.
    live = [
        line
        for line in window.splitlines()
        if not line.lstrip().startswith("#") and re.search(r'startswith\(\s*["\']ollama/', line)
    ]
    assert not live, f"the guard has gone back to a hand-rolled prefix check: {live}"


def test_every_role_alias_this_project_assigns_is_recognised_as_local():
    """These are the exact strings that reach the guard as `kwargs["model"]`.

    `determinex/engineer` was the live failure. The bare `determinex-*` tags are the ctx_config
    defaults, and are what broke the pricing path in the same way.
    """
    for alias in (
        "determinex/engineer",
        "determinex/observer",
        "determinex/sentinel",
        "determinex/qwen7b",
        "determinex-engineer-v11-dsl",
        "determinex-observer-v6-dsl",
        "determinex-sentinel-v5-dsl",
        "ollama/determinex-engineer-v11-dsl",
        "ollama_chat/qwen2.5-coder",
        "local/fast",
    ):
        assert is_local_model(alias), (
            f"{alias!r} is served locally but is_local_model says otherwise, so it would get no "
            f"timeout and could hang the session indefinitely"
        )


def test_cloud_models_are_not_treated_as_local():
    """The opposite failure: forcing the local ceiling onto a cloud call would cut off legitimate
    long completions, and would also mis-price them as free."""
    for model in (
        "anthropic/claude-opus-4-8",
        "openrouter/deepseek/deepseek-chat",
        "gpt-5.5-pro",
    ):
        assert not is_local_model(model), f"{model!r} is a cloud model but reads as local"


def test_the_builder_timeout_ceiling_is_finite_and_documented():
    """A guard that sets `timeout=None` would be no guard at all."""
    from hive.api_client import BUILDER_TIMEOUT_SECONDS  # noqa: PLC0415

    assert isinstance(BUILDER_TIMEOUT_SECONDS, int) and 0 < BUILDER_TIMEOUT_SECONDS <= 1800, (
        f"BUILDER_TIMEOUT_SECONDS={BUILDER_TIMEOUT_SECONDS!r} is not a sane finite ceiling"
    )


def test_an_explicit_caller_timeout_still_wins():
    """The DSL pre-processor passes `timeout=45` deliberately ("if it hasn't responded in 45s the
    model is looping"). The guard must not overwrite a caller's tighter budget with 300."""
    src = API_CLIENT.read_text(encoding="utf-8")
    guard_at = src.index("OOM guard")
    window = src[guard_at : guard_at + 2200]
    assert 'kwargs.get("timeout"' in window, (
        "the guard no longer defers to an explicit caller timeout, so a deliberate 45s cap would be "
        "replaced by the 300s ceiling"
    )


# ── The same locality question, in the safety gate ───────────────────────────────────────────────


def test_a_local_model_is_not_blocked_as_a_cloud_call_on_a_fresh_install():
    """This blocked EVERY local call on a fresh install (found 2026-07-30).

    `safety_gate._is_cloud_model` tested `not m.startswith("ollama/")`, but callers pass the
    configured alias (`api_client._effective_model = kwargs.get("model", model)` -> `determinex/
    engineer`). So a model on the user's own machine read as cloud, and with the documented default
    `DETERMINEX_REQUIRE_CLOAK=1` plus Cloak inactive, `pre_api_gate` raised:

        [SAFETY GATE] Cloud API call to 'determinex/engineer' blocked ...

    Invisible on the development box, because `.env` there sets `DETERMINEX_REQUIRE_CLOAK=0` -- and
    `.env` is not shipped in the installer. Same shape as the agent-chat default model: works only
    where it was written.

    This test clears the environment so it asserts the FRESH-INSTALL behaviour, not this machine's.
    """
    import importlib
    import os

    saved = {k: os.environ.get(k) for k in ("DETERMINEX_REQUIRE_CLOAK", "DETERMINEX_CLOAK")}
    try:
        os.environ["DETERMINEX_REQUIRE_CLOAK"] = "1"
        os.environ.pop("DETERMINEX_CLOAK", None)
        sg = importlib.reload(importlib.import_module("hive.safety_gate"))
        messages = [{"role": "user", "content": "write a rust function"}]
        for model in (
            "determinex/engineer",
            "determinex-engineer-v11-dsl",
            "ollama/determinex-engineer-v11-dsl",
            "ollama_chat/qwen2.5-coder",
            "local/fast",
        ):
            assert not sg._is_cloud_model(model), f"{model!r} is local but reads as cloud"
            sg.pre_api_gate(messages, model, cloak_active=False)  # must not raise
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        importlib.reload(importlib.import_module("hive.safety_gate"))


def test_a_cloud_model_is_still_blocked_without_cloak():
    """The opposite failure would be far worse: skipping Cloak on a real cloud call. An unrecognised
    provider must still err toward "cloud, therefore require Cloak"."""
    import importlib
    import os

    saved = {k: os.environ.get(k) for k in ("DETERMINEX_REQUIRE_CLOAK", "DETERMINEX_CLOAK")}
    try:
        os.environ["DETERMINEX_REQUIRE_CLOAK"] = "1"
        os.environ.pop("DETERMINEX_CLOAK", None)
        sg = importlib.reload(importlib.import_module("hive.safety_gate"))
        messages = [{"role": "user", "content": "hello"}]
        for model in (
            "anthropic/claude-opus-4-8",
            "openrouter/deepseek/deepseek-chat",
            "gpt-5.5-pro",
            "groq/llama3",  # not in _CLOUD_PROVIDERS -- must still be treated as cloud
        ):
            assert sg._is_cloud_model(model), f"{model!r} is a cloud model but reads as local"
            try:
                sg.pre_api_gate(messages, model, cloak_active=False)
            except Exception:
                continue
            raise AssertionError(f"{model!r} was allowed with Cloak inactive and REQUIRE_CLOAK=1")
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        importlib.reload(importlib.import_module("hive.safety_gate"))
