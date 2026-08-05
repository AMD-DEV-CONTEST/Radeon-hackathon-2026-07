"""User-added models must actually be reachable by the engine.

Ryan, live: "users should be able to add future llms that dont have access at the
moment, we should make sure we are compatable with EVERYTHING."

The IDE has always been able to write a custom model into
`models_registry.json` (frontend/src-tauri/src/registry.rs), and nothing on the
Python side ever read that file. So a model added through the UI was filed into a
catalogue the engine never consulted: it showed up in a dropdown and could not be
used. Worse, the persisted entry had no field for an endpoint, so even a reader
could not have known where to send the request.

These tests pin the three things that make "add any future model" real:

  * an entry with a `base_url` becomes a resolvable provider, with no code change
    and no knowledge of the vendor;
  * `api_key_env` is treated as the NAME of an env var, never a secret, because
    the registry is plain JSON in the app data directory;
  * a custom endpoint does not become a hole in the network policy -- offline mode
    still allows a local server and still refuses a remote one.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"
for p in (str(REPO_ROOT), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)


def _registry(tmp_path: Path, models: list[dict]) -> Path:
    path = tmp_path / "models_registry.json"
    path.write_text(
        json.dumps({"tiers": [{"tier_id": "custom", "models": models}], "tandem_presets": []}),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def providers(monkeypatch):
    """A freshly imported providers module, so registrations don't leak between
    tests through the module-level _PROVIDERS dict."""

    def _load(registry_path: Path | None = None, policy: str = "online"):
        monkeypatch.setenv("DETERMINEX_NETWORK_POLICY", policy)
        if registry_path is not None:
            monkeypatch.setenv("DETERMINEX_MODELS_REGISTRY", str(registry_path))
        else:
            monkeypatch.delenv("DETERMINEX_MODELS_REGISTRY", raising=False)
        sys.modules.pop("determinex_providers", None)
        return importlib.import_module("determinex_providers")

    return _load


FUTURE_MODEL = {
    "id": "some-model-from-2027",
    "provider": "future-vendor",
    "name": "Future Vendor 9000",
    "desc": "A provider this build has never heard of",
    "elo_rating": 1500,
    "context_window": 200_000,
    "custom": True,
    "base_url": "https://api.future-vendor.example/v1",
    "api_key_env": "FUTURE_VENDOR_KEY",
}


def test_a_model_this_build_has_never_heard_of_becomes_usable(providers, tmp_path):
    P = providers(_registry(tmp_path, [FUTURE_MODEL]))

    assert "some-model-from-2027" in P.register_custom_providers()
    # The real assertion: it resolves to the universal generate() contract.
    gen = P.get_generator("some-model-from-2027")
    assert callable(gen)
    assert "some-model-from-2027" in P.available()


def test_registration_happens_at_import_not_only_when_asked(providers, tmp_path):
    """Every entry point (hive, amplifier, autofix, IDE bridge) has to see these
    without each remembering to call the loader."""
    P = providers(_registry(tmp_path, [FUTURE_MODEL]))
    assert "some-model-from-2027" in P._PROVIDERS


def test_entry_without_a_base_url_is_routed_on_its_id(providers, tmp_path):
    """Naming a new model from a provider LiteLLM already understands should not
    require inventing an endpoint for it."""
    P = providers(
        _registry(tmp_path, [{"id": "anthropic/claude-next", "api_key_env": "ANTHROPIC_API_KEY"}])
    )
    assert "anthropic/claude-next" in P._PROVIDERS
    assert callable(P.get_generator("anthropic/claude-next"))


def test_api_key_env_is_a_variable_name_and_the_secret_is_never_persisted(providers, tmp_path):
    path = _registry(tmp_path, [FUTURE_MODEL])
    P = providers(path)
    P.register_custom_providers()

    raw = path.read_text(encoding="utf-8")
    assert "FUTURE_VENDOR_KEY" in raw, "the env var NAME belongs in the registry"
    # Nothing that looks like a credential may be written to this file: it is
    # plain JSON in the app data directory and ends up in every backup of it.
    assert "sk-" not in raw
    assert "api_key" not in json.loads(raw)["tiers"][0]["models"][0]


def test_offline_policy_still_refuses_a_remote_custom_endpoint(providers, tmp_path):
    """A user-supplied base_url must not become a way around the network policy."""
    P = providers(_registry(tmp_path, [FUTURE_MODEL]), policy="offline")
    gen = P.get_generator("some-model-from-2027")
    with pytest.raises(P.NetworkPolicyViolation, match="offline"):
        gen("hello", 0.0)


def test_offline_policy_still_allows_a_local_custom_endpoint(providers, tmp_path):
    """The common case for a not-yet-supported model is a local server (vLLM,
    llama.cpp, LM Studio). Offline must not block loopback, or the whole
    local-first premise breaks."""
    local = {**FUTURE_MODEL, "id": "local-future", "base_url": "http://localhost:9999/v1"}
    P = providers(_registry(tmp_path, [local]), policy="offline")
    gen = P.get_generator("local-future")
    # It must get PAST the policy gate. The request itself then fails because
    # nothing is listening on 9999, which is a connection error, not a policy one.
    with pytest.raises(Exception) as excinfo:
        gen("hello", 0.0)
    assert not isinstance(excinfo.value, P.NetworkPolicyViolation)


def test_loopback_detection(providers):
    P = providers()
    for url in ("http://localhost:8000/v1", "http://127.0.0.1:1234/v1", "http://[::1]:8080/v1"):
        assert P._is_loopback(url), url
    for url in ("https://api.openai.com/v1", "http://192.168.1.50:8000/v1", "https://evil.example"):
        assert not P._is_loopback(url), url


def test_a_malformed_registry_does_not_take_the_engine_down(providers, tmp_path):
    bad = tmp_path / "models_registry.json"
    bad.write_text("{ this is not json", encoding="utf-8")
    P = providers(bad)
    assert P.register_custom_providers() == []
    # Built-ins must still be intact.
    assert "claude" in P._PROVIDERS and "local" in P._PROVIDERS


def test_no_registry_file_is_not_an_error(providers, tmp_path):
    P = providers(tmp_path / "nope" / "models_registry.json")
    assert P.register_custom_providers() == []
    assert "claude" in P._PROVIDERS


# ── credential aliasing ──────────────────────────────────────────────────────
#
# Found live 2026-07-28: the repo's .env carried HF_TOKEN (HuggingFace's own
# name for it), this module checked HUGGINGFACE_API_KEY, and passport.rs stores
# HUGGINGFACE_TOKEN. Three names for one token, and the failure is silent -- the
# provider just reports itself unavailable and the model is skipped, with nothing
# explaining why a configured credential did nothing.


def test_hf_token_alias_populates_the_canonical_key(providers, monkeypatch):
    monkeypatch.delenv("HUGGINGFACE_API_KEY", raising=False)
    monkeypatch.setenv("HF_TOKEN", "unit-test-value")
    P = providers()
    P._apply_env_aliases()
    import os

    assert os.environ["HUGGINGFACE_API_KEY"] == "unit-test-value"
    assert P.available()["huggingface"] is True


def test_passport_style_name_also_works(providers, monkeypatch):
    monkeypatch.delenv("HUGGINGFACE_API_KEY", raising=False)
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.setenv("HUGGINGFACE_TOKEN", "unit-test-value")
    P = providers()
    P._apply_env_aliases()
    import os

    assert os.environ["HUGGINGFACE_API_KEY"] == "unit-test-value"


def test_an_explicit_canonical_key_is_never_overwritten_by_an_alias(providers, monkeypatch):
    """Aliasing must not clobber a deliberate setting."""
    monkeypatch.setenv("HUGGINGFACE_API_KEY", "explicit")
    monkeypatch.setenv("HF_TOKEN", "alias")
    P = providers()
    P._apply_env_aliases()
    import os

    assert os.environ["HUGGINGFACE_API_KEY"] == "explicit"


def test_aliasing_is_idempotent(providers, monkeypatch):
    monkeypatch.delenv("HUGGINGFACE_API_KEY", raising=False)
    monkeypatch.setenv("HF_TOKEN", "v")
    P = providers()
    for _ in range(3):
        P._apply_env_aliases()
    import os

    assert os.environ["HUGGINGFACE_API_KEY"] == "v"
