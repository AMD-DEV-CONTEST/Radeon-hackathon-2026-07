from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_setup_and_config_vault_expose_all_advertised_cloud_key_providers():
    setup = (ROOT / "frontend/src/components/SetupWizard.tsx").read_text(encoding="utf-8")
    settings_context = (ROOT / "frontend/src/contexts/SettingsContext.tsx").read_text(
        encoding="utf-8"
    )
    settings_modal = (ROOT / "frontend/src/components/modals/SettingsModal.tsx").read_text(
        encoding="utf-8"
    )
    api = (ROOT / "frontend/src/lib/api.ts").read_text(encoding="utf-8")
    api_keys = (ROOT / "frontend/src-tauri/src/api_keys.rs").read_text(encoding="utf-8")

    for key in [
        "openai_key",
        "anthropic_key",
        "gemini_key",
        "groq_key",
        "deepseek_key",
        "mistral_key",
    ]:
        assert key in setup
        assert key in settings_context
        assert key in api
        assert key in api_keys

    for provider in ["openai", "anthropic", "gemini", "groq", "deepseek", "mistral"]:
        assert provider in settings_modal
        assert provider in api_keys


def test_role_assignment_cloud_options_match_litellm_model_names():
    # 2026-07 refactor moved the cloud route catalog out of RoleAssignmentPanel.tsx's own
    # body into a shared frontend/src/lib/aiRouting.ts module (CLOUD_ROUTE_OPTIONS /
    # FREE_CLOUD_ROUTE_OPTIONS), imported rather than inlined -- the test previously only
    # checked the panel file directly and went stale the moment that refactor landed
    # (every model name legitimately moved, none were dropped). Check both: aiRouting.ts
    # for the actual IDs, RoleAssignmentPanel.tsx for genuinely importing that module
    # (not just that some unrelated string happens to match).
    roles = (ROOT / "frontend/src/components/RoleAssignmentPanel.tsx").read_text(encoding="utf-8")
    routing = (ROOT / "frontend/src/lib/aiRouting.ts").read_text(encoding="utf-8")
    config = (ROOT / "litellm_config.yaml").read_text(encoding="utf-8")

    assert "CLOUD_ROUTE_OPTIONS" in roles and "aiRouting" in roles

    for model_name in [
        "cloud/claude-best",
        "cloud/claude-fast",
        "cloud/deepseek-chat",
        "cloud/deepseek-coder",
        "cloud/gemini-flash",
        "cloud/gpt4o",
        "cloud/mistral-large",
        "cloud/groq-llama",
    ]:
        assert model_name in routing
        assert f"model_name: {model_name}" in config


def test_tauri_pipeline_resolves_cloud_routes_instead_of_falling_back_to_ollama():
    pipeline = (ROOT / "frontend/src-tauri/src/orchestrator/pipeline_models.rs").read_text(
        encoding="utf-8"
    )
    transport = (ROOT / "frontend/src-tauri/src/orchestrator/transport.rs").read_text(
        encoding="utf-8"
    )
    orchestrator = (ROOT / "frontend/src-tauri/src/orchestrator/mod.rs").read_text(encoding="utf-8")

    assert "pub enum ModelRoute" in pipeline
    assert "ModelRoute::DeepSeek" in pipeline
    assert "ModelRoute::Mistral" in pipeline
    assert "ModelRoute::Groq" in pipeline
    assert "pub async fn call_model" in transport
    assert "cloud_route_blocked_by_offline_policy" in transport
    assert "call_model(" in orchestrator
    assert "call_ollama(" not in orchestrator


# ── the vLLM bare-name defect (found live on an AMD Radeon MI GPU, 2026-08-02) ──────────


def test_an_explicit_vllm_model_gets_the_hosted_vllm_prefix():
    """THE BUG. `hosted_vllm/` was applied to the DEFAULT model at import and inside
    `_vllm_discover_model()`, and nowhere else. A caller naming the model explicitly --
    which is what a UI dropdown or a router does, populated from `/v1/models`, which returns
    BARE ids -- reached LiteLLM unprefixed and got

        BadRequestError: LLM Provider NOT provided ... model=Qwen/Qwen2.5-Coder-7B-Instruct

    on every call. Determinex worked when it chose the model and failed when the user did,
    on the AMD path specifically.
    """
    from determinex_providers import _vllm_qualify

    assert _vllm_qualify("Qwen/Qwen2.5-Coder-7B-Instruct") == (
        "hosted_vllm/Qwen/Qwen2.5-Coder-7B-Instruct"
    )


def test_the_existing_slash_guard_could_not_have_caught_it():
    """Why this is a fourth occurrence and not a regression of the third.

    `_qualify_local_model` fixes the same class of footgun with the rule "a name that
    already carries a prefix is left alone", implemented as `if "/" in model: return model`.
    Every Hugging Face id contains a slash, so that rule declines to touch exactly the names
    that break. Pinning this so nobody 'simplifies' the vLLM path by reusing it.
    """
    from determinex_providers import _PROVIDERS, _qualify_local_model

    hf_id = "Qwen/Qwen2.5-Coder-7B-Instruct"
    vllm = _PROVIDERS["vllm"]
    assert _qualify_local_model(vllm, hf_id) == hf_id, (
        "the local-model guard passes HF ids through untouched -- which is correct for it, "
        "and precisely why the vLLM path needs its own"
    )


def test_prefixing_is_idempotent_and_collapses_doubles():
    """`_vllm_discover_model()` already returns a prefixed name and the default is prefixed
    at import, so this function is reached with names that are sometimes already qualified.
    Prefixing those again would produce `hosted_vllm/hosted_vllm/...` and fail just as hard,
    in a way that looks like the fix working."""
    from determinex_providers import _vllm_qualify

    once = _vllm_qualify("Qwen/Qwen2.5-Coder-7B-Instruct")
    assert _vllm_qualify(once) == once
    assert _vllm_qualify("hosted_vllm/hosted_vllm/x") == "hosted_vllm/x"


def test_an_empty_model_is_not_turned_into_a_prefix():
    """`hosted_vllm/` alone is a valid-looking string that names no model. Returning it
    would convert 'nothing was configured' into 'this specific model 404s'."""
    from determinex_providers import _vllm_qualify

    assert _vllm_qualify("") == ""


# ── the Google path (found 2026-08-03 while making the multi-agent room work) ────────────


def test_a_bare_google_model_routes_to_ai_studio_not_vertex():
    """THE BUG. The registry default is correctly `gemini/gemini-3-flash-preview`, but a
    caller-supplied name arrives BARE -- get_generator("google", "gemini-2.0-flash") -- and
    LiteLLM resolves a bare Google name to **vertex_ai**, which needs the Google Cloud SDK
    and Application Default Credentials. The user is told

        ImportError: Google Cloud SDK not found

    about an API key that is perfectly valid, for a service that does not need the SDK.
    Same bare-name footgun as _vllm_qualify, in a second provider, found the same week.
    """
    from determinex_providers import _gemini_qualify

    assert _gemini_qualify("gemini-2.0-flash") == "gemini/gemini-2.0-flash"


def test_choosing_vertex_on_purpose_is_left_alone():
    """Normalisation must not override an explicit decision -- Vertex is a legitimate
    target for someone who has ADC configured."""
    from determinex_providers import _gemini_qualify

    assert _gemini_qualify("vertex_ai/gemini-2.5-pro") == "vertex_ai/gemini-2.5-pro"


def test_google_prefixing_is_idempotent_and_survives_an_empty_model():
    from determinex_providers import _gemini_qualify

    once = _gemini_qualify("gemini-3-flash-preview")
    assert _gemini_qualify(once) == once
    assert _gemini_qualify("") == ""


def test_depleted_credits_are_not_reported_as_a_rate_limit():
    """Google returns HTTP 429 for two unrelated conditions. One clears if you wait; the
    other never does. Telling a user to retry when their balance is zero wastes their
    afternoon, so the two are separated by the message body, not the status code."""
    from determinex_providers import explain_google_failure

    hint = explain_google_failure(
        'RateLimitError: {"error": {"code": 429, "message": "Your prepayment credits are '
        'depleted. Please go to AI Studio", "status": "RESOURCE_EXHAUSTED"}}'
    )
    assert "billing" in hint.lower()
    assert "retrying will not help" in hint.lower()
    assert "ai.studio" in hint.lower()


def test_the_dead_cli_tier_points_at_the_api_instead():
    """The Gemini CLI's stored OAuth login is on a tier Google no longer serves. Determinex
    does not need the CLI at all, and the hint should say so rather than sending the user to
    re-authenticate something that cannot work."""
    from determinex_providers import explain_google_failure

    hint = explain_google_failure("Error authenticating: IneligibleTierError: no longer supported")
    assert "does not need the CLI" in hint
    assert "GEMINI_API_KEY" in hint


def test_a_google_failure_raises_rather_than_returning_empty_text():
    """An empty string from a provider is indistinguishable from a model with nothing to
    say -- which is how a dead provider once looked like a weak one for a whole evaluation."""
    import inspect

    from determinex_providers import _gemini_factory

    src = inspect.getsource(_gemini_factory)
    assert "raise RuntimeError" in src


# ── first-run setup: the screen a non-technical user meets ──────────────────────────────


def test_a_present_key_is_not_reported_as_working():
    """Proven on this repo: a valid GEMINI_API_KEY whose account had zero prepay credits.
    Reporting that as "set up" sends someone away believing they are done, to fail on their
    first real request. `ready` must mean a live call succeeded."""
    import determinex_provider_setup as S

    rep = S.build_report()
    for opt in rep.options:
        if opt["readiness"] == "credentials_unverified":
            assert opt["ready"] is False, f"{opt['id']} claims ready on an unverified credential"


def test_a_finished_setup_stops_asking_for_more():
    """A setup screen's job is to end. The first version always returned the cheapest
    unfinished option, so a machine with Claude, ChatGPT and 38 local models still led with
    "Get a key" -- turning a finished setup into a chore list."""
    import determinex_provider_setup as S

    rep = S.build_report()
    if rep.ready_count > 0:
        assert rep.recommended is None
        assert "nothing else is required" in rep.headline.lower()


def test_options_are_ranked_by_what_the_user_must_understand():
    """Not by model quality and not alphabetically. Local ranks above paste-a-key because it
    needs no account, no card, and cannot run out of credit."""
    import determinex_provider_setup as S

    rep = S.build_report()
    unready = [o for o in rep.options if not o["ready"]]
    efforts = [o["effort"] for o in unready]
    assert efforts == sorted(efforts), f"unready options are out of effort order: {efforts}"


def test_every_provider_offers_the_same_three_shapes():
    """Claude has 3 current models, Google 4, OpenAI several. One vocabulary -- fast /
    balanced / deep -- means the user learns it once and it transfers."""
    import determinex_provider_setup as S

    for pid in S.MODEL_CHOICES:
        tiers = [c["tier"] for c in S.model_choices(pid)]
        assert tiers == [S.FAST, S.BALANCED, S.DEEP], f"{pid} offers {tiers}"
        assert sum(1 for c in S.model_choices(pid) if c["default"]) == 1, f"{pid} needs exactly one default"


def test_every_choice_explains_itself_without_a_model_name():
    """A raw identifier like `claude-sonnet-4-6` is not a decision. Every choice carries a
    plain-language label and help string; the id is for the runtime, not the reader."""
    import determinex_provider_setup as S

    for pid in S.MODEL_CHOICES:
        for c in S.model_choices(pid):
            assert c["label"] and c["help"], f"{pid}/{c['tier']} has no human-readable text"
            assert not c["label"].startswith(("gemini/", "openrouter/", "claude-", "gpt-")), (
                f"{pid}/{c['tier']} shows a raw model id as its label"
            )


def test_could_not_ask_never_renders_as_the_answer_is_none():
    """A 4-second timeout on a slow Ollama daemon returned [], the screen concluded "you have
    no models", and it told a user with 38 installed to download another gigabyte."""
    import determinex_provider_setup as S

    models, reachable = S._ollama_models()
    if not reachable:
        assert models == []
    assert isinstance(reachable, bool), "reachability must be reported separately from the count"


def test_there_is_always_a_way_in_that_needs_no_api_key():
    """Ryan, 2026-08-03: "if you download antigravity you hit the button you're in ... I want
    the same for all of it, not where a user has to go and set up a whole other part (api's)
    that sometimes requires higher pricing and different pricing."

    An API key must never be the price of entry. The start_here group is the guarantee: local
    models need no account at all, and the CLI providers sign in to a subscription the user
    already has."""
    import determinex_provider_setup as S

    start = [o for o in S.build_report().options if o["group"] == "start_here"]
    assert start, "there must always be a keyless path"
    assert any(o["id"] == "local" for o in start), "local needs no account and must be offered"
    assert all(o["signin"] or o["id"] == "local" for o in start), (
        "start_here may only contain sign-in or no-auth options"
    )


def test_a_key_option_says_when_you_are_already_signed_in_to_that_vendor():
    """Otherwise the screen shows "Sign in with Claude" and "Anthropic - get a key" as two
    separate things the user apparently needs, which is the confusion the grouping exists to
    remove."""
    import determinex_provider_setup as S

    rep = S.build_report()
    signed = {o["id"] for o in rep.options if o["signin"] and o["ready"]}
    for opt in rep.options:
        if opt["covered_by"]:
            assert opt["covered_by"] in signed
            assert "already signed in" in opt["what_it_means"].lower()
